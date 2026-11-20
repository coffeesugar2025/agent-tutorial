// highlight.js 按需注册语言，避免把整包（约 1MB）打进产物。
import hljs from 'highlight.js/lib/core'
import bash from 'highlight.js/lib/languages/bash'
import css from 'highlight.js/lib/languages/css'
import diff from 'highlight.js/lib/languages/diff'
import ini from 'highlight.js/lib/languages/ini'
import javascript from 'highlight.js/lib/languages/javascript'
import json from 'highlight.js/lib/languages/json'
import markdown from 'highlight.js/lib/languages/markdown'
import plaintext from 'highlight.js/lib/languages/plaintext'
import powershell from 'highlight.js/lib/languages/powershell'
import python from 'highlight.js/lib/languages/python'
import sql from 'highlight.js/lib/languages/sql'
import typescript from 'highlight.js/lib/languages/typescript'
import xml from 'highlight.js/lib/languages/xml'
import yaml from 'highlight.js/lib/languages/yaml'

const languages = {
  bash,
  css,
  diff,
  ini,
  javascript,
  json,
  markdown,
  plaintext,
  powershell,
  python,
  sql,
  typescript,
  xml,
  yaml,
}

for (const [name, definition] of Object.entries(languages)) {
  hljs.registerLanguage(name, definition)
}

// 文档里常见的别名，统一映射到已注册语言。
const aliases = {
  py: 'python',
  python3: 'python',
  js: 'javascript',
  ts: 'typescript',
  sh: 'bash',
  shell: 'bash',
  zsh: 'bash',
  pwsh: 'powershell',
  ps1: 'powershell',
  text: 'plaintext',
  txt: 'plaintext',
  plain: 'plaintext',
  html: 'xml',
  vue: 'xml',
  yml: 'yaml',
  md: 'markdown',
  dockerfile: 'bash',
}

export function resolveLanguage(lang) {
  if (!lang) return ''
  const key = String(lang).toLowerCase()
  return hljs.getLanguage(key) ? key : aliases[key] || ''
}

export default hljs
