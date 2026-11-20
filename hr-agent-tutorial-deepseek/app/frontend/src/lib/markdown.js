import { Marked } from 'marked'
import hljs, { resolveLanguage } from './highlight.js'

/**
 * Markdown 渲染管线：
 * 1. 去掉 frontmatter（后端返回的 markdown 含原文 frontmatter）
 * 2. marked 解析（聊天内容额外转义原始 HTML，避免直接渲染用户输入）
 * 3. DOM 白名单清洗（去掉脚本、事件属性、危险链接）
 * 4. 增强：标题锚点、代码高亮 + 复制按钮、callout、表格滚动容器、外链新窗口
 *
 * 所有页面的 Markdown 都必须经过这里，不允许直接 v-html 原始内容。
 */

const LINK_ICON =
  '<svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M10.5 13.5a4 4 0 0 0 5.7 0l2.3-2.3a4 4 0 1 0-5.7-5.7L11.5 6.8"/><path d="M13.5 10.5a4 4 0 0 0-5.7 0l-2.3 2.3a4 4 0 1 0 5.7 5.7l1.3-1.3"/></svg>'
const COPY_ICON =
  '<svg viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M9 9V5.5A1.5 1.5 0 0 1 10.5 4h8A1.5 1.5 0 0 1 20 5.5v8a1.5 1.5 0 0 1-1.5 1.5H15"/><path d="M4 11.5A1.5 1.5 0 0 1 5.5 10h8a1.5 1.5 0 0 1 1.5 1.5v8a1.5 1.5 0 0 1-1.5 1.5h-8A1.5 1.5 0 0 1 4 19.5v-8Z"/></svg>'
const CHECK_ICON =
  '<svg viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M4 12.5 9 17.5 20 6.5"/></svg>'

const CALLOUT_ICONS = {
  tip: '<svg viewBox="0 0 24 24" width="17" height="17" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M9 18h6"/><path d="M10 21h4"/><path d="M12 3a6 6 0 0 0-3.6 10.8c.6.5 1 1.3 1 2.2h5.2c0-.9.4-1.7 1-2.2A6 6 0 0 0 12 3Z"/></svg>',
  warn: '<svg viewBox="0 0 24 24" width="17" height="17" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M12 3 2.8 20h18.4L12 3Z"/><path d="M12 9v5"/><path d="M12 17.6v.1"/></svg>',
  lab: '<svg viewBox="0 0 24 24" width="17" height="17" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M9 3h6"/><path d="M10 3v6.2L4.9 18a2.2 2.2 0 0 0 1.9 3.3h10.4a2.2 2.2 0 0 0 1.9-3.3L14 9.2V3"/><path d="M6.8 15h10.4"/></svg>',
  exam: '<svg viewBox="0 0 24 24" width="17" height="17" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M12 3 5 6v5.5c0 4.3 2.9 7.6 7 9.5 4.1-1.9 7-5.2 7-9.5V6l-7-3Z"/><path d="m9 12 2 2 4-4"/></svg>',
}

// 教程约定的四类提示块：> 💡 **小白提示**：...
const CALLOUTS = [
  { type: 'tip', label: '小白提示', icon: CALLOUT_ICONS.tip },
  { type: 'warn', label: '生产提醒', icon: CALLOUT_ICONS.warn },
  { type: 'lab', label: '动手', icon: CALLOUT_ICONS.lab },
  { type: 'exam', label: '考点', icon: CALLOUT_ICONS.exam },
]
const CALLOUT_BY_LABEL = new Map(CALLOUTS.map((item) => [item.label, item]))

const ALLOWED_TAGS = new Set([
  'A', 'BLOCKQUOTE', 'BR', 'CODE', 'DD', 'DEL', 'DETAILS', 'DIV', 'DL', 'DT', 'EM',
  'H1', 'H2', 'H3', 'H4', 'H5', 'H6', 'HR', 'IMG', 'INPUT', 'KBD', 'LI', 'MARK',
  'OL', 'P', 'PRE', 'S', 'SPAN', 'STRONG', 'SUB', 'SUMMARY', 'SUP', 'TABLE',
  'TBODY', 'TD', 'TH', 'THEAD', 'TR', 'UL',
])
// 这些标签连内容一起删除，其余未知标签只去掉标签、保留文字。
const DANGEROUS_TAGS = new Set([
  'SCRIPT', 'STYLE', 'TEMPLATE', 'IFRAME', 'OBJECT', 'EMBED', 'APP', 'FRAME',
  'FRAMESET', 'NOSCRIPT', 'LINK', 'META', 'BASE', 'FORM', 'TEXTAREA', 'SELECT',
  'BUTTON', 'VIDEO', 'AUDIO', 'CANVAS', 'SVG', 'MATH',
])

const FRONTMATTER_RE = /^\uFEFF?---\r?\n([\s\S]*?)\r?\n---[ \t]*\r?\n?/

/** 去掉并解析章节 frontmatter（只支持教程用到的简单 YAML）。 */
export function splitFrontmatter(markdown) {
  const source = String(markdown ?? '')
  const match = source.match(FRONTMATTER_RE)
  if (!match) return { frontmatter: {}, body: source }
  const frontmatter = {}
  for (const line of match[1].split(/\r?\n/)) {
    const kv = line.match(/^([A-Za-z0-9_-]+):[ \t]*(.*)$/)
    if (!kv) continue
    let value = kv[2].trim()
    if (!value) continue
    if (value.startsWith('"') && value.endsWith('"')) value = value.slice(1, -1)
    else if (value.startsWith("'") && value.endsWith("'")) value = value.slice(1, -1)
    else if (value.startsWith('[') && value.endsWith(']')) {
      value = value
        .slice(1, -1)
        .split(',')
        .map((item) => item.trim().replace(/^["']|["']$/g, ''))
        .filter(Boolean)
    } else if (/^\d+$/.test(value)) value = Number(value)
    frontmatter[kv[1]] = value
  }
  return { frontmatter, body: source.slice(match[0].length) }
}

export function escapeHtml(text) {
  return String(text ?? '')
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#39;')
}

function isSafeUrl(url) {
  const value = String(url || '').trim()
  if (!value) return false
  if (/^(#|\/(?!\/)|\.{1,2}\/)/.test(value)) return true
  return /^(https?:|mailto:)/i.test(value)
}

/** 教程里的 <details> 需要让内部 Markdown 正常解析，先用块级扩展单独处理。 */
const detailsExtension = {
  extensions: [
    {
      name: 'lessonDetails',
      level: 'block',
      start(src) {
        const index = src.indexOf('<details')
        return index < 0 ? undefined : index
      },
      tokenizer(src) {
        const match = /^<details([^>]*)>([\s\S]*?)<\/details>[ \t]*(?:\n|$)/i.exec(src)
        if (!match) return undefined
        return { type: 'lessonDetails', raw: match[0], attrs: match[1], text: match[2] }
      },
      renderer(token) {
        let body = token.text
        let summary = '参考答案'
        const summaryMatch = body.match(/^\s*<summary[^>]*>([\s\S]*?)<\/summary>/i)
        if (summaryMatch) {
          summary = docMarked.parseInline(summaryMatch[1].trim()) || summary
          body = body.slice(summaryMatch[0].length)
        }
        const inner = docMarked.parse(body)
        return `<details${token.attrs}>\n<summary>${summary}</summary>\n<div class="details-body">${inner}</div>\n</details>\n`
      },
    },
  ],
}

const docMarked = new Marked({ gfm: true, breaks: false })
docMarked.use(detailsExtension)

// 聊天内容：marked 会把原始 HTML 当 HTML token，这里统一转义成可见文本。
const chatMarked = new Marked({
  gfm: true,
  breaks: false,
  renderer: {
    html(token) {
      return escapeHtml(token.text)
    },
  },
})

function sanitize(root) {
  for (const el of Array.from(root.querySelectorAll('*'))) {
    const tag = el.tagName.toUpperCase()
    if (DANGEROUS_TAGS.has(tag)) {
      el.remove()
      continue
    }
    if (!ALLOWED_TAGS.has(tag)) {
      el.replaceWith(...Array.from(el.childNodes))
      continue
    }
    for (const attr of Array.from(el.attributes)) {
      const name = attr.name.toLowerCase()
      const value = attr.value
      let keep = false
      if (tag === 'A' && name === 'href') keep = isSafeUrl(value)
      else if (tag === 'A' && name === 'title') keep = true
      else if (tag === 'IMG' && name === 'src') keep = isSafeUrl(value)
      else if (tag === 'IMG' && (name === 'alt' || name === 'title')) keep = true
      else if (tag === 'CODE' && name === 'class') keep = /^language-[a-z0-9+#._-]+$/i.test(value)
      else if (tag === 'OL' && name === 'start') keep = /^\d+$/.test(value)
      else if (tag === 'INPUT' && name === 'type') keep = value.toLowerCase() === 'checkbox'
      else if (tag === 'INPUT' && (name === 'checked' || name === 'disabled')) keep = true
      else if ((tag === 'TH' || tag === 'TD') && name === 'align') keep = /^(left|center|right)$/i.test(value)
      else if ((tag === 'TH' || tag === 'TD') && name === 'colspan') keep = /^\d+$/.test(value)
      else if (tag === 'DIV' && name === 'class') keep = value === 'details-body'
      else if (tag === 'DETAILS' && name === 'open') keep = true
      if (!keep) el.removeAttribute(attr.name)
    }
    if (tag === 'INPUT') el.setAttribute('disabled', '')
    if (tag === 'IMG') el.setAttribute('loading', 'lazy')
    if (tag === 'A') {
      const href = el.getAttribute('href')
      if (href && /^https?:/i.test(href)) {
        el.setAttribute('target', '_blank')
        el.setAttribute('rel', 'noopener noreferrer')
      }
      el.classList.add('md-link')
    }
  }
}

export function slugifyHeading(text) {
  const base = String(text || '')
    .trim()
    .toLowerCase()
    .replace(/[\s\u3000]+/g, '-')
    .replace(/[^\p{L}\p{N}_-]+/gu, '')
    .replace(/^-+|-+$/g, '')
    .slice(0, 60)
  return `h-${base || 'section'}`
}

function addHeadingIds(root) {
  const used = new Map()
  const headings = []
  for (const heading of root.querySelectorAll('h1, h2, h3, h4')) {
    const text = heading.textContent.replace(/\s+/g, ' ').trim()
    if (!text) continue
    let id = slugifyHeading(text)
    if (used.has(id)) {
      let index = used.get(id) + 1
      while (used.has(`${id}-${index}`)) index += 1
      id = `${id}-${index}`
    }
    used.set(id, 1)
    heading.id = id
    const level = Number(heading.tagName.slice(1))
    headings.push({ id, text, level })
    const anchor = document.createElement('a')
    anchor.className = 'heading-anchor'
    anchor.href = `#${id}`
    anchor.setAttribute('aria-label', `复制「${text}」的锚点链接`)
    anchor.setAttribute('title', '锚点链接')
    anchor.innerHTML = LINK_ICON
    heading.appendChild(anchor)
  }
  return headings
}

function highlightCode(code, lang) {
  const resolved = resolveLanguage(lang)
  if (!resolved || resolved === 'plaintext') return
  try {
    const result = hljs.highlight(code.textContent, { language: resolved, ignoreIllegals: true })
    code.innerHTML = result.value
    code.classList.add('hljs')
  } catch {
    code.classList.add('hljs')
  }
}

function enhanceCodeBlocks(root, withCopy) {
  for (const pre of Array.from(root.querySelectorAll('pre'))) {
    if (pre.parentElement?.classList.contains('code-block')) continue
    const code = pre.querySelector('code')
    if (!code) continue
    const langClass = Array.from(code.classList).find((name) => name.startsWith('language-'))
    const lang = langClass ? langClass.slice('language-'.length) : ''
    highlightCode(code, lang)
    code.classList.add('hljs')
    if (lang) code.classList.add(`language-${lang}`)

    const wrapper = document.createElement('div')
    wrapper.className = 'code-block'
    const head = document.createElement('div')
    head.className = 'code-head'
    const label = document.createElement('span')
    label.className = 'code-lang'
    label.textContent = lang || 'code'
    head.appendChild(label)
    if (withCopy) {
      const button = document.createElement('button')
      button.type = 'button'
      button.className = 'code-copy'
      button.setAttribute('data-copy', '')
      button.setAttribute('aria-label', '复制代码')
      button.innerHTML = `${COPY_ICON}<span>复制</span>`
      head.appendChild(button)
    }
    pre.replaceWith(wrapper)
    wrapper.appendChild(head)
    wrapper.appendChild(pre)
  }
}

function enhanceTables(root) {
  for (const table of Array.from(root.querySelectorAll('table'))) {
    if (table.parentElement?.classList.contains('table-wrap')) continue
    const wrap = document.createElement('div')
    wrap.className = 'table-wrap'
    table.replaceWith(wrap)
    wrap.appendChild(table)
    table.classList.add('md-table')
  }
}

function enhanceCallouts(root) {
  for (const quote of Array.from(root.querySelectorAll('blockquote'))) {
    const first = quote.firstElementChild
    if (!first || first.tagName !== 'P') {
      quote.classList.add('md-quote')
      continue
    }
    const strong = Array.from(first.querySelectorAll('strong')).find((el) =>
      CALLOUT_BY_LABEL.has(el.textContent.trim()),
    )
    if (!strong) {
      quote.classList.add('md-quote')
      continue
    }
    const definition = CALLOUT_BY_LABEL.get(strong.textContent.trim())

    // 去掉开头的 emoji（含变体选择符）与「**标签**：」前缀，保留其余说明。
    const leading = first.firstChild
    if (leading && leading.nodeType === Node.TEXT_NODE) {
      leading.textContent = leading.textContent.replace(
        /^[\s\u{1F000}-\u{1FAFF}\u2600-\u27BF\uFE0F]+/u,
        '',
      )
      if (!leading.textContent.trim()) leading.remove()
    }
    const after = strong.nextSibling
    if (after && after.nodeType === Node.TEXT_NODE) {
      after.textContent = after.textContent.replace(/^[\s：:]*/, '')
      if (!after.textContent) after.remove()
    }
    strong.remove()
    if (!first.textContent.trim() && !first.querySelector('code, a, img')) first.remove()

    const callout = document.createElement('div')
    callout.className = `callout callout--${definition.type}`
    const head = document.createElement('div')
    head.className = 'callout__head'
    head.innerHTML = definition.icon
    const label = document.createElement('span')
    label.className = 'callout__label'
    label.textContent = definition.label
    head.appendChild(label)
    const body = document.createElement('div')
    body.className = 'callout__body'
    while (quote.firstChild) body.appendChild(quote.firstChild)
    callout.appendChild(head)
    callout.appendChild(body)
    quote.replaceWith(callout)
  }
  for (const quote of Array.from(root.querySelectorAll('blockquote'))) {
    quote.classList.add('md-quote')
  }
}

function enhanceLinks(root) {
  for (const link of Array.from(root.querySelectorAll('a'))) {
    if (link.classList.contains('heading-anchor')) continue
    const text = link.textContent.trim()
    if (link.getAttribute('href')?.startsWith('#')) {
      link.classList.add('md-anchor-link')
      continue
    }
    if (/^https?:/i.test(link.getAttribute('href') || '')) {
      link.classList.add('md-external')
      if (!text || text === link.getAttribute('href')) link.setAttribute('title', link.href)
    }
  }
}

/**
 * 渲染 Markdown。
 * @param {string} source 原始 markdown（可含 frontmatter）
 * @param {{ escapeRawHtml?: boolean, callouts?: boolean, codeCopy?: boolean }} options
 * @returns {{ html: string, headings: Array<{id:string,text:string,level:number}> }}
 */
export function renderMarkdown(source, options = {}) {
  const { escapeRawHtml = false, callouts = true, codeCopy = true } = options
  const { body } = splitFrontmatter(source)
  const engine = escapeRawHtml ? chatMarked : docMarked
  let rawHtml = ''
  try {
    rawHtml = engine.parse(body)
  } catch (error) {
    rawHtml = `<p>${escapeHtml(body)}</p>`
  }
  if (typeof DOMParser === 'undefined') return { html: rawHtml, headings: [] }

  const documentNode = new DOMParser().parseFromString(
    `<div id="markdown-root">${rawHtml}</div>`,
    'text/html',
  )
  const root = documentNode.getElementById('markdown-root')
  if (!root) return { html: rawHtml, headings: [] }

  sanitize(root)
  const headings = addHeadingIds(root)
  enhanceCodeBlocks(root, codeCopy)
  if (callouts) enhanceCallouts(root)
  enhanceTables(root)
  enhanceLinks(root)

  return { html: root.innerHTML, headings }
}

/** 轻量纯文本预览：用于聊天引用、引用片段等场景。 */
export function stripMarkdown(source, maxLength = 160) {
  const text = String(source ?? '')
    .replace(FRONTMATTER_RE, '')
    .replace(/```[\s\S]*?```/g, ' ')
    .replace(/`([^`]+)`/g, '$1')
    .replace(/!\[[^\]]*\]\([^)]*\)/g, ' ')
    .replace(/\[([^\]]+)\]\([^)]*\)/g, '$1')
    .replace(/[*_~>#|]/g, '')
    .replace(/\s+/g, ' ')
    .trim()
  return text.length > maxLength ? `${text.slice(0, maxLength)}…` : text
}
