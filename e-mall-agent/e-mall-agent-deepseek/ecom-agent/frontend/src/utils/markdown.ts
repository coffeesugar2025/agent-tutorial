import MarkdownIt from 'markdown-it'

/**
 * markdown 渲染：禁用原始 HTML，链接统一新窗口打开，避免 XSS。
 * 助手消息只信任 markdown-it 的转义输出。
 */
const md = new MarkdownIt({
  html: false,
  linkify: true,
  breaks: true,
  typographer: false,
})

const defaultLinkOpen =
  md.renderer.rules.link_open ??
  ((tokens, index, options, _env, self) => self.renderToken(tokens, index, options))

md.renderer.rules.link_open = (tokens, index, options, env, self) => {
  tokens[index].attrSet('target', '_blank')
  tokens[index].attrSet('rel', 'noopener noreferrer')
  return defaultLinkOpen(tokens, index, options, env, self)
}

// 代码块包一层容器，配合样式做横向滚动
md.renderer.rules.fence = (tokens, index) => {
  const token = tokens[index]
  const lang = md.utils.escapeHtml(token.info.trim().split(/\s+/)[0] ?? '')
  const code = md.utils.escapeHtml(token.content)
  return `<pre class="code-block" data-lang="${lang}"><code>${code}</code></pre>\n`
}

export function renderMarkdown(source?: string): string {
  if (!source) return ''
  return md.render(source)
}

export function renderInlineMarkdown(source?: string): string {
  if (!source) return ''
  return md.renderInline(source)
}

/** 纯文本摘要（用于会话标题、通知等场景） */
export function markdownToPlain(source?: string, maxLength = 120): string {
  if (!source) return ''
  const plain = source
    .replace(/```[\s\S]*?```/g, ' ')
    .replace(/`([^`]*)`/g, '$1')
    .replace(/!\[[^\]]*\]\([^)]*\)/g, ' ')
    .replace(/\[([^\]]*)\]\([^)]*\)/g, '$1')
    .replace(/[#>*_~-]+/g, ' ')
    .replace(/\s+/g, ' ')
    .trim()
  return plain.length > maxLength ? `${plain.slice(0, maxLength)}…` : plain
}
