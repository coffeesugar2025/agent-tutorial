// 阅读进度：localStorage 持久化 + 模块级响应式状态，首页与章节页共享。
import { computed, reactive } from 'vue'

const STORAGE_KEY = 'hr-agent-progress-v1'
const LAST_KEY = 'hr-agent-last-chapter'

function readCompleted() {
  try {
    const raw = localStorage.getItem(STORAGE_KEY)
    if (!raw) return new Set()
    const parsed = JSON.parse(raw)
    return new Set(Array.isArray(parsed) ? parsed.filter((item) => typeof item === 'string') : [])
  } catch {
    return new Set()
  }
}

function readLast() {
  try {
    return localStorage.getItem(LAST_KEY) || ''
  } catch {
    return ''
  }
}

const state = reactive({
  completed: readCompleted(),
  lastSlug: readLast(),
})

function persist() {
  try {
    localStorage.setItem(STORAGE_KEY, JSON.stringify([...state.completed]))
  } catch {
    // 隐私模式下写入失败不影响阅读
  }
}

export function useProgress() {
  const completedCount = computed(() => state.completed.size)

  function isCompleted(slug) {
    return state.completed.has(slug)
  }

  function markCompleted(slug) {
    if (!slug) return
    state.completed.add(slug)
    persist()
  }

  function unmarkCompleted(slug) {
    state.completed.delete(slug)
    persist()
  }

  function toggleCompleted(slug) {
    if (isCompleted(slug)) unmarkCompleted(slug)
    else markCompleted(slug)
  }

  function setLastVisited(slug) {
    if (!slug) return
    state.lastSlug = slug
    try {
      localStorage.setItem(LAST_KEY, slug)
    } catch {
      // 忽略存储失败
    }
  }

  return {
    completed: state.completed,
    lastSlug: computed(() => state.lastSlug),
    completedCount,
    isCompleted,
    markCompleted,
    unmarkCompleted,
    toggleCompleted,
    setLastVisited,
  }
}
