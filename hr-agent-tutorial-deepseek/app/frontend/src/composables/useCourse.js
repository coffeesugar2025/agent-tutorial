// 课程目录：模块级缓存，首页与章节页共享一次请求；失败可强制重试。
import { computed, reactive } from 'vue'
import { api, errorMessage } from '../api'

const state = reactive({
  data: null,
  loading: false,
  error: '',
})

let inflight = null

function normalizeChapter(chapter, part, index) {
  const order = Number.isFinite(Number(chapter?.order)) ? Number(chapter.order) : index
  return {
    slug: String(chapter?.slug || ''),
    title: chapter?.title || '未命名章节',
    order,
    minutes: Number(chapter?.minutes) || 30,
    difficulty: chapter?.difficulty || '入门',
    summary: chapter?.summary || '',
    part: part.title,
    partId: part.id,
  }
}

function normalizeCourse(payload) {
  const rawParts = Array.isArray(payload?.parts) ? payload.parts : []
  const seen = new Set()
  const parts = rawParts
    .map((rawPart, partIndex) => {
      const part = {
        id: rawPart?.id || `part-${partIndex}`,
        title: rawPart?.title || `第 ${partIndex + 1} 部分`,
      }
      const chapters = (Array.isArray(rawPart?.chapters) ? rawPart.chapters : [])
        .map((chapter, index) => normalizeChapter(chapter, part, index))
        .filter((chapter) => {
          if (!chapter.slug || seen.has(chapter.slug)) return false
          seen.add(chapter.slug)
          return true
        })
        .sort((a, b) => a.order - b.order)
      return { ...part, chapters }
    })
    .filter((part) => part.chapters.length)

  const chapters = parts.flatMap((part) => part.chapters)
  return {
    title: payload?.title || 'HR Agent 实战教程',
    parts,
    chapters,
  }
}

async function load({ force = false } = {}) {
  if (inflight) return inflight
  if (state.data && !force) return state.data

  state.loading = true
  state.error = ''
  inflight = (async () => {
    try {
      const payload = await api.getCourse()
      const data = normalizeCourse(payload)
      if (!data.chapters.length) throw new Error('课程接口返回为空，请检查 docs 目录是否已有章节。')
      state.data = data
      return data
    } catch (error) {
      state.error = errorMessage(error)
      state.data = null
      throw error
    } finally {
      state.loading = false
      inflight = null
    }
  })()
  return inflight
}

export function useCourse() {
  const chapters = computed(() => state.data?.chapters || [])
  const parts = computed(() => state.data?.parts || [])
  const totalMinutes = computed(() => chapters.value.reduce((sum, chapter) => sum + chapter.minutes, 0))

  function findChapter(slug) {
    return chapters.value.find((chapter) => chapter.slug === slug) || null
  }

  function neighbors(slug) {
    const index = chapters.value.findIndex((chapter) => chapter.slug === slug)
    if (index < 0) return { prev: null, next: null, index: -1 }
    return {
      prev: index > 0 ? chapters.value[index - 1] : null,
      next: index < chapters.value.length - 1 ? chapters.value[index + 1] : null,
      index,
    }
  }

  return {
    state,
    chapters,
    parts,
    totalMinutes,
    load,
    findChapter,
    neighbors,
  }
}

export { normalizeCourse }
