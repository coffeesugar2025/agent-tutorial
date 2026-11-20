<script setup>
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { RouterLink, useRoute } from 'vue-router'
import { api, errorMessage } from '../api'
import { splitFrontmatter } from '../lib/markdown'
import { useCourse } from '../composables/useCourse'
import { useProgress } from '../composables/useProgress'
import AppIcon from '../components/AppIcon.vue'
import ErrorState from '../components/ui/ErrorState.vue'
import MarkdownView from '../components/learn/MarkdownView.vue'
import ChapterNav from '../components/learn/ChapterNav.vue'
import TocList from '../components/learn/TocList.vue'

const route = useRoute()
const slug = computed(() => String(route.params.slug || ''))

const { state: courseState, parts, chapters, load: loadCourse, findChapter, neighbors } = useCourse()
const { completed, isCompleted, toggleCompleted, setLastVisited } = useProgress()

const doc = ref(null)
const frontmatter = ref({})
const loading = ref(true)
const error = ref('')
const headings = ref([])
const progress = ref(0)
const activeId = ref('')
const drawerOpen = ref(false)

const chapter = computed(() => findChapter(slug.value))
const done = computed(() => isCompleted(slug.value))
const links = computed(() => neighbors(slug.value))
const tocHeadings = computed(() => headings.value.filter((heading) => heading.level === 2 || heading.level === 3))

const meta = computed(() => {
  const fromApi = doc.value?.meta || {}
  const fromFile = frontmatter.value || {}
  const fallback = chapter.value || {}
  return {
    order: fromApi.order ?? fromFile.order ?? fallback.order ?? 0,
    minutes: fromApi.minutes ?? fromFile.minutes ?? fallback.minutes ?? 30,
    difficulty: fromApi.difficulty ?? fromFile.difficulty ?? fallback.difficulty ?? '入门',
    part: fromApi.part ?? fromFile.part ?? fallback.part ?? '',
  }
})

const title = computed(
  () => doc.value?.title || frontmatter.value.title || chapter.value?.title || '章节内容',
)

const orderLabel = computed(() => String(meta.value.order ?? 0).padStart(2, '0'))

const difficultyClass = computed(() => {
  const map = { 入门: 'starter', 进阶: 'advanced', 高阶: 'expert', 项目: 'project' }
  return `difficulty--${map[meta.value.difficulty] || 'starter'}`
})

const prevLink = computed(() => links.value.prev)
const nextLink = computed(() => links.value.next)

const catalogError = computed(() => Boolean(courseState.error) && !courseState.data)

async function load() {
  loading.value = true
  error.value = ''
  doc.value = null
  headings.value = []
  progress.value = 0
  frontmatter.value = {}

  const catalogPromise = courseState.data ? Promise.resolve() : loadCourse().catch(() => null)
  try {
    const [payload] = await Promise.all([api.getDoc(slug.value), catalogPromise])
    if (!payload || typeof payload.markdown !== 'string') {
      throw new Error('接口返回的章节内容为空，请检查后端 /api/docs 实现。')
    }
    doc.value = payload
    frontmatter.value = splitFrontmatter(payload.markdown).frontmatter
    setLastVisited(slug.value)
    document.title = `${title.value} · HR Agent 学堂`
    await nextTick()
    updateReadingProgress()
    updateActiveHeading()
  } catch (err) {
    error.value = errorMessage(err)
  } finally {
    loading.value = false
  }
}

function retry() {
  load()
}

function retryCatalog() {
  loadCourse({ force: true }).catch(() => {})
}

function toggleComplete() {
  toggleCompleted(slug.value)
}

/* ---------- 阅读进度与当前小节 ---------- */
let ticking = false

function onScroll() {
  if (ticking) return
  ticking = true
  requestAnimationFrame(() => {
    ticking = false
    updateReadingProgress()
    updateActiveHeading()
  })
}

function updateReadingProgress() {
  const article = document.querySelector('.learn-article')
  if (!article) return
  const top = window.scrollY + article.getBoundingClientRect().top - 96
  const scrollable = Math.max(article.offsetHeight - window.innerHeight + 96, 1)
  const ratio = (window.scrollY - top) / scrollable
  progress.value = Math.min(100, Math.max(0, Math.round(ratio * 100)))
}

function updateActiveHeading() {
  if (!tocHeadings.value.length) return
  let current = tocHeadings.value[0].id
  for (const heading of tocHeadings.value) {
    const element = document.getElementById(heading.id)
    if (!element) continue
    if (element.getBoundingClientRect().top <= 132) current = heading.id
    else break
  }
  activeId.value = current
}

function onHeadingsReady(list) {
  headings.value = list
  nextTick(() => {
    updateReadingProgress()
    updateActiveHeading()
  })
}

/* ---------- 移动端抽屉 ---------- */
function openDrawer() {
  drawerOpen.value = true
}
function closeDrawer() {
  drawerOpen.value = false
}
function onDrawerClick(event) {
  if (event.target.closest?.('a')) closeDrawer()
}
function onKeydown(event) {
  if (event.key === 'Escape') closeDrawer()
}

watch(drawerOpen, (open) => {
  document.body.style.overflow = open ? 'hidden' : ''
})

onMounted(() => {
  load()
  window.addEventListener('scroll', onScroll, { passive: true })
  window.addEventListener('resize', onScroll, { passive: true })
  window.addEventListener('keydown', onKeydown)
})

onBeforeUnmount(() => {
  window.removeEventListener('scroll', onScroll)
  window.removeEventListener('resize', onScroll)
  window.removeEventListener('keydown', onKeydown)
  document.body.style.overflow = ''
})
</script>

<template>
  <div class="learn-page">
    <!-- 顶部阅读进度 -->
    <div class="reading-progress" aria-hidden="true">
      <span :style="{ width: `${progress}%` }"></span>
    </div>

    <div class="container learn-shell">
      <!-- 左侧目录 -->
      <aside class="learn-sidebar" aria-label="课程目录">
        <div class="sidebar-head">
          <div class="sidebar-head__title">
            <AppIcon name="book" :size="16" />
            <span>课程目录</span>
          </div>
          <span class="sidebar-head__count">{{ completed.size }} / {{ chapters.length || 18 }}</span>
        </div>

        <template v-if="parts.length">
          <ChapterNav
            :parts="parts"
            :current-slug="slug"
            :completed="completed"
            class="sidebar-nav"
          />
        </template>
        <div v-else-if="catalogError" class="sidebar-error">
          <p>目录加载失败</p>
          <button type="button" class="btn btn--secondary btn--sm" :disabled="courseState.loading" @click="retryCatalog">
            <AppIcon name="refresh" :size="14" />
            重试目录
          </button>
        </div>
        <div v-else class="sidebar-skeleton" aria-hidden="true">
          <div v-for="i in 8" :key="i" class="skeleton" style="height: 26px; margin-bottom: 6px"></div>
        </div>
      </aside>

      <!-- 正文 -->
      <main class="learn-main">
        <!-- 移动端目录栏 -->
        <div class="learn-mobilebar">
          <button type="button" class="btn btn--secondary btn--sm" @click="openDrawer" aria-label="打开章节目录">
            <AppIcon name="menu" :size="16" />
            目录
          </button>
          <span class="learn-mobilebar__title">{{ title }}</span>
          <button
            type="button"
            class="mobilebar-done"
            :class="{ 'is-done': done }"
            :aria-pressed="done"
            :title="done ? '取消完成标记' : '标记完成'"
            @click="toggleComplete"
          >
            <AppIcon :name="done ? 'check-circle' : 'check'" :size="16" />
          </button>
        </div>

        <div v-if="loading" class="learn-skeleton" aria-busy="true" aria-live="polite">
          <span class="sr-only">正在加载章节…</span>
          <div class="skeleton" style="height: 18px; width: 130px"></div>
          <div class="skeleton" style="height: 38px; width: 78%; margin-top: 18px"></div>
          <div class="skeleton" style="height: 16px; width: 58%; margin-top: 14px"></div>
          <div class="learn-skeleton__body">
            <div v-for="i in 9" :key="i" class="skeleton" style="height: 15px; margin-bottom: 12px"></div>
          </div>
        </div>

        <div v-else-if="error" class="learn-error">
          <ErrorState
            title="章节加载失败"
            :message="error"
            retry-label="重新加载章节"
            :loading="loading"
            @retry="retry"
          >
            <template #actions>
              <RouterLink to="/" class="btn btn--secondary btn--sm">返回课程首页</RouterLink>
            </template>
          </ErrorState>
          <p class="learn-error__slug">
            当前 slug：<code>{{ slug }}</code>
            <span v-if="chapter"> · 目录中的章节标题为「{{ chapter.title }}」</span>
          </p>
        </div>

        <template v-else>
          <article class="learn-article">
            <header class="article-head">
              <RouterLink to="/" class="article-back">
                <AppIcon name="arrow-left" :size="15" />
                返回课程首页
              </RouterLink>

              <div class="article-labels">
                <span v-if="meta.part" class="article-part">{{ meta.part }}</span>
                <span class="article-chapter">第 {{ orderLabel }} 章</span>
              </div>

              <h1 class="article-title">{{ title }}</h1>

              <div class="article-meta">
                <span class="chip">
                  <AppIcon name="clock" :size="14" />
                  预计 {{ meta.minutes }} 分钟
                </span>
                <span class="chip" :class="difficultyClass">{{ meta.difficulty }}</span>
                <span v-if="doc?.title && frontmatter.title && doc.title !== frontmatter.title" class="chip chip--neutral">
                  正文标题：{{ frontmatter.title }}
                </span>
              </div>

              <div class="article-actions">
                <button
                  type="button"
                  class="btn btn--sm"
                  :class="done ? 'btn--success' : 'btn--primary'"
                  :aria-pressed="done"
                  @click="toggleComplete"
                >
                  <AppIcon :name="done ? 'check-circle' : 'check'" :size="15" />
                  {{ done ? '已完成' : '标记完成' }}
                </button>
                <span class="article-actions__hint">
                  {{ done ? '已记录到本机进度，点击可取消' : '进度保存在本机浏览器，不会上传' }}
                </span>
              </div>
            </header>

            <MarkdownView :markdown="doc.markdown" @ready="onHeadingsReady" />

            <footer class="article-foot">
              <div class="complete-panel">
                <div class="complete-panel__text">
                  <span class="complete-panel__icon">
                    <AppIcon :name="done ? 'check-circle' : 'graduation'" :size="20" />
                  </span>
                  <div>
                    <b>{{ done ? '这一章已完成' : '学完这一章了吗？' }}</b>
                    <p>
                      {{ done ? '你可以继续下一章，或取消标记重新复习。' : '标记完成会更新首页的学习进度与已投入时长。' }}
                    </p>
                  </div>
                </div>
                <button
                  type="button"
                  class="btn btn--sm"
                  :class="done ? 'btn--secondary' : 'btn--primary'"
                  :aria-pressed="done"
                  @click="toggleComplete"
                >
                  <AppIcon :name="done ? 'minus' : 'check'" :size="15" />
                  {{ done ? '取消完成' : '标记为已完成' }}
                </button>
              </div>

              <nav class="chapter-pager" aria-label="章节翻页">
                <RouterLink
                  v-if="prevLink"
                  :to="`/learn/${prevLink.slug}`"
                  class="pager-card pager-card--prev"
                >
                  <AppIcon name="arrow-left" :size="18" class="pager-card__arrow" />
                  <span class="pager-card__body">
                    <small>上一章 · {{ String(prevLink.order).padStart(2, '0') }}</small>
                    <b>{{ prevLink.title }}</b>
                  </span>
                </RouterLink>
                <RouterLink v-else to="/" class="pager-card pager-card--prev">
                  <AppIcon name="arrow-left" :size="18" class="pager-card__arrow" />
                  <span class="pager-card__body">
                    <small>回到</small>
                    <b>课程首页</b>
                  </span>
                </RouterLink>

                <RouterLink
                  v-if="nextLink"
                  :to="`/learn/${nextLink.slug}`"
                  class="pager-card pager-card--next"
                >
                  <span class="pager-card__body">
                    <small>下一章 · {{ String(nextLink.order).padStart(2, '0') }}</small>
                    <b>{{ nextLink.title }}</b>
                  </span>
                  <AppIcon name="arrow-right" :size="18" class="pager-card__arrow" />
                </RouterLink>
                <RouterLink v-else to="/eval" class="pager-card pager-card--next">
                  <span class="pager-card__body">
                    <small>全部章节已读完</small>
                    <b>去评测看板看 20 条 Golden Case</b>
                  </span>
                  <AppIcon name="arrow-right" :size="18" class="pager-card__arrow" />
                </RouterLink>
              </nav>
            </footer>
          </article>
        </template>
      </main>

      <!-- 右侧本页 TOC -->
      <aside class="learn-toc" aria-label="本页目录">
        <div class="learn-toc__inner">
          <TocList :headings="tocHeadings" :active-id="activeId" />
        </div>
      </aside>
    </div>

    <!-- 移动端抽屉 -->
    <Teleport to="body">
      <Transition name="drawer">
        <div v-if="drawerOpen" class="drawer-root">
          <div class="drawer-overlay" @click="closeDrawer"></div>
          <aside class="drawer" role="dialog" aria-modal="true" aria-label="章节目录">
            <header class="drawer__head">
              <div>
                <span class="drawer__eyebrow">课程目录</span>
                <p class="drawer__progress">{{ completed.size }} / {{ chapters.length || 18 }} 章已完成</p>
              </div>
              <button type="button" class="btn btn--ghost btn--icon" aria-label="关闭目录" @click="closeDrawer">
                <AppIcon name="close" :size="18" />
              </button>
            </header>
            <div class="drawer__body" @click="onDrawerClick">
              <ChapterNav
                v-if="parts.length"
                :parts="parts"
                :current-slug="slug"
                :completed="completed"
                compact
              />
              <div v-else class="drawer__error">
                目录暂不可用
                <button type="button" class="btn btn--secondary btn--sm" @click="retryCatalog">
                  <AppIcon name="refresh" :size="14" /> 重试
                </button>
              </div>

              <div class="drawer__toc">
                <TocList :headings="tocHeadings" :active-id="activeId" />
              </div>
            </div>
            <footer class="drawer__foot">
              <button
                type="button"
                class="btn btn--block"
                :class="done ? 'btn--success' : 'btn--primary'"
                @click="toggleComplete"
              >
                <AppIcon :name="done ? 'check-circle' : 'check'" :size="15" />
                {{ done ? '已完成本章' : '标记本章完成' }}
              </button>
            </footer>
          </aside>
        </div>
      </Transition>
    </Teleport>
  </div>
</template>

<style scoped>
.learn-page { position: relative; }
.reading-progress {
  position: fixed;
  top: var(--header-height);
  left: 0;
  right: 0;
  height: 3px;
  z-index: 35;
  background: rgba(79, 70, 229, 0.08);
  pointer-events: none;
}
.reading-progress span {
  display: block;
  height: 100%;
  width: 0;
  background: linear-gradient(90deg, #6366f1, #8b5cf6);
  border-radius: 0 2px 2px 0;
  transition: width 0.12s linear;
}
.learn-shell {
  display: grid;
  grid-template-columns: 252px minmax(0, 1fr) 208px;
  gap: 32px;
  align-items: start;
  padding-top: 26px;
  padding-bottom: 40px;
}

/* ---------- 左侧目录 ---------- */
.learn-sidebar {
  position: sticky;
  top: calc(var(--header-height) + 20px);
  max-height: calc(100vh - var(--header-height) - 40px);
  overflow-y: auto;
  padding: 12px 10px 14px;
  border: 1px solid var(--border);
  border-radius: var(--radius);
  background: rgba(255, 255, 255, 0.72);
  backdrop-filter: blur(8px);
  box-shadow: var(--shadow-sm);
}
.sidebar-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 2px 8px 10px;
  margin-bottom: 6px;
  border-bottom: 1px solid var(--border);
}
.sidebar-head__title {
  display: flex;
  align-items: center;
  gap: 6px;
  font-size: 12.5px;
  font-weight: 700;
  color: var(--text);
}
.sidebar-head__title svg { color: var(--brand); }
.sidebar-head__count {
  font-family: var(--font-mono);
  font-size: 10.5px;
  color: var(--text-3);
  background: var(--surface-3);
  border-radius: 5px;
  padding: 1px 5px;
}
.sidebar-nav { padding-bottom: 4px; }
.sidebar-error { padding: 12px 8px; text-align: center; }
.sidebar-error p { margin: 0 0 8px; color: var(--text-3); font-size: 12.5px; }
.sidebar-skeleton { padding: 4px 8px; }

/* ---------- 正文 ---------- */
.learn-main { min-width: 0; }
.learn-article {
  padding: 36px 42px 30px;
  border: 1px solid var(--border);
  border-radius: 20px;
  background: var(--surface);
  box-shadow: var(--shadow-sm);
}
.article-back {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  color: var(--text-3);
  font-size: 12.5px;
  text-decoration: none;
  padding: 3px 0;
}
.article-back:hover { color: var(--brand-700); }
.article-labels {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 8px;
  margin-top: 20px;
}
.article-part {
  font-size: 12px;
  font-weight: 600;
  color: var(--brand-700);
  background: var(--brand-50);
  border: 1px solid var(--brand-100);
  border-radius: 6px;
  padding: 2px 8px;
}
.article-chapter {
  font-family: var(--font-mono);
  font-size: 11.5px;
  color: var(--text-4);
  letter-spacing: 0.04em;
}
.article-title {
  margin: 12px 0 0;
  font-size: clamp(26px, 3.2vw, 34px);
  line-height: 1.34;
  letter-spacing: -0.03em;
}
.article-meta {
  display: flex;
  flex-wrap: wrap;
  gap: 7px;
  margin-top: 16px;
}
.difficulty--starter { color: #027a48; background: #ecfdf3; border-color: #d1fadf; }
.difficulty--advanced { color: #175cd3; background: #eff8ff; border-color: #d1e9ff; }
.difficulty--expert { color: #5925dc; background: #f4f3ff; border-color: #ebe9fe; }
.difficulty--project { color: #be185d; background: #fdf2f8; border-color: #fce7f3; }
.article-actions {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 12px;
  margin-top: 20px;
  padding-bottom: 22px;
  border-bottom: 1px solid var(--border);
}
.article-actions__hint { color: var(--text-4); font-size: 12px; }

/* 正文内的第一个标题与 header 的间距 */
.learn-article :deep(.md-body) { margin-top: 28px; }

.article-foot { margin-top: 40px; }
.complete-panel {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
  flex-wrap: wrap;
  padding: 16px 18px;
  border: 1px solid var(--border);
  border-radius: var(--radius-sm);
  background: linear-gradient(120deg, #fbfbff, #f7f6ff);
}
.complete-panel__text { display: flex; align-items: center; gap: 12px; min-width: 0; }
.complete-panel__icon {
  display: grid;
  place-items: center;
  width: 38px;
  height: 38px;
  border-radius: 10px;
  color: var(--brand-700);
  background: #fff;
  border: 1px solid var(--brand-100);
  flex: none;
}
.complete-panel__text b { font-size: 14px; }
.complete-panel__text p { margin: 2px 0 0; color: var(--text-3); font-size: 12.5px; line-height: 1.6; }

.chapter-pager {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 12px;
  margin-top: 16px;
}
.pager-card {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 13px 15px;
  border: 1px solid var(--border);
  border-radius: var(--radius-sm);
  background: #fff;
  color: inherit;
  text-decoration: none;
  transition: border-color 0.16s ease, box-shadow 0.16s ease, transform 0.16s ease;
}
.pager-card:hover { border-color: var(--brand-200); box-shadow: var(--shadow-sm); transform: translateY(-1px); }
.pager-card--next { text-align: right; justify-content: flex-end; }
.pager-card__body { display: flex; flex-direction: column; min-width: 0; line-height: 1.5; }
.pager-card__body small { color: var(--text-4); font-size: 11px; }
.pager-card__body b {
  margin-top: 2px;
  font-size: 13px;
  font-weight: 600;
  color: var(--text-2);
  display: -webkit-box;
  -webkit-line-clamp: 1;
  -webkit-box-orient: vertical;
  overflow: hidden;
}
.pager-card:hover .pager-card__body b { color: var(--brand-700); }
.pager-card__arrow { color: var(--text-4); flex: none; }
.pager-card:hover .pager-card__arrow { color: var(--brand); }

/* ---------- 右侧 TOC ---------- */
.learn-toc {
  position: sticky;
  top: calc(var(--header-height) + 20px);
  max-height: calc(100vh - var(--header-height) - 40px);
  overflow-y: auto;
}
.learn-toc__inner { padding: 4px 0 12px; }

/* ---------- 移动端 ---------- */
.learn-mobilebar {
  display: none;
  position: sticky;
  top: calc(var(--header-height) + 10px);
  z-index: 30;
  align-items: center;
  gap: 10px;
  margin-bottom: 12px;
  padding: 8px 10px;
  border: 1px solid var(--border);
  border-radius: var(--radius-sm);
  background: rgba(255, 255, 255, 0.94);
  backdrop-filter: blur(8px);
  box-shadow: var(--shadow-sm);
}
.learn-mobilebar__title {
  flex: 1;
  min-width: 0;
  font-size: 13px;
  font-weight: 600;
  color: var(--text-2);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}
.mobilebar-done {
  display: grid;
  place-items: center;
  width: 32px;
  height: 32px;
  border: 1px solid var(--border-strong);
  border-radius: 8px;
  background: #fff;
  color: var(--text-3);
  flex: none;
}
.mobilebar-done.is-done { color: var(--success); border-color: var(--success-border); background: var(--success-soft); }

.learn-skeleton {
  padding: 34px 36px;
  border: 1px solid var(--border);
  border-radius: 20px;
  background: #fff;
}
.learn-skeleton__body { margin-top: 30px; }
.learn-error { max-width: 100%; }
.learn-error__slug { margin: 12px 4px 0; color: var(--text-3); font-size: 12.5px; }
.learn-error__slug code {
  padding: 1px 5px;
  border-radius: 4px;
  background: var(--surface-3);
  font-family: var(--font-mono);
}

/* ---------- 抽屉 ---------- */
.drawer-root { position: fixed; inset: 0; z-index: 60; }
.drawer-overlay {
  position: absolute;
  inset: 0;
  background: rgba(22, 27, 38, 0.38);
  backdrop-filter: blur(2px);
}
.drawer {
  position: absolute;
  top: 0;
  left: 0;
  bottom: 0;
  width: min(340px, 88vw);
  display: flex;
  flex-direction: column;
  background: #fff;
  border-right: 1px solid var(--border);
  box-shadow: 24px 0 60px -40px rgba(23, 28, 42, 0.6);
}
.drawer__head {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 12px;
  padding: 16px 16px 12px;
  border-bottom: 1px solid var(--border);
}
.drawer__eyebrow { font-size: 12px; font-weight: 700; letter-spacing: 0.06em; color: var(--brand-700); }
.drawer__progress { margin: 2px 0 0; font-size: 12.5px; color: var(--text-3); }
.drawer__body { flex: 1; overflow-y: auto; padding: 12px; }
.drawer__toc { margin-top: 18px; padding-top: 14px; border-top: 1px solid var(--border); }
.drawer__error { display: flex; flex-direction: column; align-items: flex-start; gap: 8px; color: var(--text-3); font-size: 13px; }
.drawer__foot { padding: 12px 16px 18px; border-top: 1px solid var(--border); }
.drawer-enter-active,
.drawer-leave-active { transition: opacity 0.2s ease; }
.drawer-enter-active .drawer,
.drawer-leave-active .drawer { transition: transform 0.22s cubic-bezier(0.22, 0.8, 0.24, 1); }
.drawer-enter-from,
.drawer-leave-to { opacity: 0; }
.drawer-enter-from .drawer,
.drawer-leave-to .drawer { transform: translateX(-100%); }

/* ---------- 响应式 ---------- */
@media (max-width: 1120px) {
  .learn-shell { grid-template-columns: 236px minmax(0, 1fr); gap: 26px; }
  .learn-toc { display: none; }
}
@media (max-width: 920px) {
  .learn-shell { grid-template-columns: minmax(0, 1fr); padding-top: 16px; }
  .learn-sidebar { display: none; }
  .learn-mobilebar { display: flex; }
  .learn-article { padding: 26px 24px 24px; border-radius: 16px; }
}
@media (max-width: 600px) {
  .learn-article { padding: 20px 18px 20px; }
  .article-title { font-size: 25px; }
  .article-actions__hint { display: none; }
  .chapter-pager { grid-template-columns: 1fr; }
  .pager-card--next { flex-direction: row; }
  .complete-panel { padding: 14px; }
  .complete-panel .btn { width: 100%; }
  .learn-skeleton { padding: 22px 18px; }
  .reading-progress { top: var(--header-height); }
}
</style>
