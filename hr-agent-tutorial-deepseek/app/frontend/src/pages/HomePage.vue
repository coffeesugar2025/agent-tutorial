<script setup>
import { computed, onMounted } from 'vue'
import { RouterLink } from 'vue-router'
import { useCourse } from '../composables/useCourse'
import { useProgress } from '../composables/useProgress'
import AppIcon from '../components/AppIcon.vue'
import ChapterCard from '../components/ChapterCard.vue'
import ErrorState from '../components/ui/ErrorState.vue'

const { state, chapters, parts, totalMinutes, load, findChapter } = useCourse()
const { completedCount, isCompleted, toggleCompleted, lastSlug } = useProgress()

onMounted(() => {
  load().catch(() => {})
})

const loading = computed(() => state.loading && !state.data)
const hasError = computed(() => Boolean(state.error) && !state.data)
const totalChapters = computed(() => chapters.value.length)
const percent = computed(() =>
  totalChapters.value ? Math.round((completedCount.value / totalChapters.value) * 100) : 0,
)
const completedMinutes = computed(() =>
  chapters.value.filter((chapter) => isCompleted(chapter.slug)).reduce((sum, chapter) => sum + chapter.minutes, 0),
)
const firstChapter = computed(() => chapters.value[0] || null)
const continueChapter = computed(() => {
  if (lastSlug.value) {
    const chapter = findChapter(lastSlug.value)
    if (chapter && !isCompleted(chapter.slug)) return chapter
  }
  const next = chapters.value.find((chapter) => !isCompleted(chapter.slug))
  return next || firstChapter.value
})

const ringRadius = 34
const ringCircumference = 2 * Math.PI * ringRadius
const ringOffset = computed(() => ringCircumference * (1 - percent.value / 100))

function partStats(part) {
  const total = part.chapters.length
  const done = part.chapters.filter((chapter) => isCompleted(chapter.slug)).length
  return {
    total,
    done,
    minutes: part.chapters.reduce((sum, chapter) => sum + chapter.minutes, 0),
    percent: total ? Math.round((done / total) * 100) : 0,
  }
}

function retry() {
  load({ force: true }).catch(() => {})
}
</script>

<template>
  <div class="page home">
    <div class="container">
      <!-- Hero -->
      <section class="hero" aria-labelledby="hero-title">
        <div class="hero__copy">
          <span class="hero__eyebrow">
            <AppIcon name="sparkles" :size="15" />
            18 章 · 从 HR 痛点出发的 Agent 工程课
          </span>
          <h1 id="hero-title" class="hero__title">HR Agent 学堂</h1>
          <p class="hero__lead">
            把 HR 共享服务中心的真实痛点，拆成一套能跑、能引用、能审批、能评测的 Agent 系统。
          </p>
          <p class="hero__desc">
            从「年假还剩几天」的第一行代码开始，沿着 5 个部分走到一个可交付的 HR 智能服务台：
            LangChain 1.x + LangGraph 的 Agent、Vue 3 工作台、FastAPI 后端、混合检索、Human-in-the-loop 与 20 条 Golden Case。
          </p>

          <div class="tech-badges" aria-label="技术栈">
            <span class="tech-badge">
              <svg viewBox="0 0 24 24" width="16" height="16" aria-hidden="true">
                <path d="M12 2.5 3.5 7v10L12 21.5 20.5 17V7L12 2.5Z" fill="none" stroke="currentColor" stroke-width="1.6" />
                <path d="M8.5 10.2v3.6M15.5 10.2v3.6" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" />
              </svg>
              Python 3.12
            </span>
            <span class="tech-badge">
              <svg viewBox="0 0 24 24" width="16" height="16" aria-hidden="true">
                <path d="M9.5 14.5 14.5 9.5M8 16l-1.2 1.2a3.2 3.2 0 0 1-4.5-4.5L4.5 10.5M16 8l1.2-1.2a3.2 3.2 0 0 1 4.5 4.5L19.5 13.5" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" />
              </svg>
              LangChain 1.x
            </span>
            <span class="tech-badge">
              <svg viewBox="0 0 24 24" width="16" height="16" aria-hidden="true">
                <path d="M3 4.5h7v7H3zM14 12.5h7v7h-7zM14 4.5h7v5h-7zM6.5 12.5h5v7h-5z" fill="none" stroke="currentColor" stroke-width="1.6" />
              </svg>
              Vue 3
            </span>
            <span class="tech-badge">
              <svg viewBox="0 0 24 24" width="16" height="16" aria-hidden="true">
                <path d="M4 4h16v4H4z" fill="none" stroke="currentColor" stroke-width="1.6" />
                <path d="M6 11h12M6 15h8M6 19h5" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" />
              </svg>
              FastAPI
            </span>
            <span class="tech-badge tech-badge--muted">Mock 离线可跑</span>
          </div>

          <div class="hero__actions">
            <RouterLink
              v-if="continueChapter"
              :to="`/learn/${continueChapter.slug}`"
              class="btn btn--primary btn--lg"
            >
              <AppIcon name="play" :size="17" />
              {{ completedCount ? '继续学习' : '开始第 00 章' }}
            </RouterLink>
            <button v-else-if="loading" type="button" class="btn btn--primary btn--lg" disabled>
              <AppIcon name="play" :size="17" />
              课程加载中
            </button>
            <button v-else-if="hasError" type="button" class="btn btn--primary btn--lg" @click="retry">
              <AppIcon name="refresh" :size="17" />
              重新加载课程
            </button>
            <button v-else type="button" class="btn btn--primary btn--lg" disabled>
              <AppIcon name="book" :size="17" />
              暂无可用章节
            </button>
            <RouterLink to="/playground" class="btn btn--secondary btn--lg">
              <AppIcon name="terminal" :size="17" />
              打开工作台
            </RouterLink>
          </div>

          <dl class="hero__stats">
            <div>
              <dt>学习路径</dt>
              <dd>{{ parts.length || 5 }} 个部分</dd>
            </div>
            <div>
              <dt>章节</dt>
              <dd>{{ totalChapters || 18 }} 章</dd>
            </div>
            <div>
              <dt>预计投入</dt>
              <dd>{{ totalMinutes ? `约 ${totalMinutes} 分钟` : '约 18 小时' }}</dd>
            </div>
            <div>
              <dt>评测集</dt>
              <dd>20 条 Golden Case</dd>
            </div>
          </dl>
        </div>

        <!-- 装饰性工作台预览 -->
        <aside class="hero__visual" aria-hidden="true">
          <div class="trace-card">
            <div class="trace-card__bar">
              <span class="trace-card__dot"></span>
              <span class="trace-card__session">playground · s_8f2c</span>
              <span class="chip chip--success chip--xs">completed</span>
            </div>
            <div class="trace-card__body">
              <div class="mock-bubble">我下个月想休 3 天年假，够不够？需要提前几天申请？</div>
              <ol class="mock-steps">
                <li>
                  <span class="mock-step__icon"><AppIcon name="tool" :size="14" /></span>
                  <span class="mock-step__text"><b>get_leave_balance</b><small>E1001 → 剩余 13 天</small></span>
                  <em>2ms</em>
                </li>
                <li>
                  <span class="mock-step__icon"><AppIcon name="search" :size="14" /></span>
                  <span class="mock-step__text"><b>search_policy</b><small>命中 2025 版 · 2.2 使用与结转</small></span>
                  <em>5ms</em>
                </li>
                <li>
                  <span class="mock-step__icon"><AppIcon name="check" :size="14" /></span>
                  <span class="mock-step__text"><b>生成回答</b><small>余额 + 制度依据 + 下一步</small></span>
                  <em>1ms</em>
                </li>
              </ol>
              <div class="mock-reply">
                <p>你还有 <b>13 天</b>年假，提前 3 天在系统提交即可。</p>
                <span class="mock-cite">
                  <AppIcon name="quote" :size="13" />
                  《年假与休假制度》2025.1 · 2.2 使用与结转
                </span>
              </div>
            </div>
            <div class="trace-card__foot">
              <span><AppIcon name="shield" :size="13" /> 敏感操作需人工审批</span>
              <span>引用 1 · 轨迹 3 步</span>
            </div>
          </div>
          <div class="approval-peek">
            <span class="approval-peek__risk">高风险</span>
            <div>
              <b>adjust_salary 待审批</b>
              <small>张伟 · P5-2 → P6-1</small>
            </div>
          </div>
        </aside>
      </section>

      <!-- 加载骨架 -->
      <div v-if="loading" class="home-skeleton" aria-busy="true" aria-live="polite">
        <span class="sr-only">正在加载课程目录…</span>
        <div class="skeleton skeleton--panel"></div>
        <div class="skeleton-row">
          <div v-for="i in 5" :key="i" class="skeleton skeleton--path"></div>
        </div>
        <div class="skeleton-grid">
          <div v-for="i in 6" :key="i" class="skeleton skeleton--card"></div>
        </div>
      </div>

      <!-- 错误态 -->
      <div v-else-if="hasError" class="home-error">
        <ErrorState
          title="课程目录加载失败"
          :message="state.error"
          retry-label="重新加载课程"
          :loading="state.loading"
          @retry="retry"
        />
        <p class="home-error__hint">
          首页数据来自 <code>GET /api/course</code>。若后端正在启动，请稍等几秒后重试；
          也可以先打开 <RouterLink to="/playground">工作台</RouterLink> 查看交互。
        </p>
      </div>

      <!-- 课程内容 -->
      <template v-else>
        <!-- 进度概览 -->
        <section class="progress-card" aria-labelledby="progress-title">
          <div class="progress-card__ring">
            <svg viewBox="0 0 84 84" width="84" height="84" role="img" :aria-label="`课程完成度 ${percent}%`">
              <defs>
                <linearGradient id="ring-gradient" x1="0" y1="0" x2="1" y2="1">
                  <stop offset="0%" stop-color="#6366f1" />
                  <stop offset="100%" stop-color="#8b5cf6" />
                </linearGradient>
              </defs>
              <circle cx="42" cy="42" :r="ringRadius" fill="none" stroke="#eceef6" stroke-width="7" />
              <circle
                cx="42"
                cy="42"
                :r="ringRadius"
                fill="none"
                stroke="url(#ring-gradient)"
                stroke-width="7"
                stroke-linecap="round"
                :stroke-dasharray="ringCircumference"
                :stroke-dashoffset="ringOffset"
                transform="rotate(-90 42 42)"
                class="progress-card__progress"
              />
            </svg>
            <span class="progress-card__percent">{{ percent }}<small>%</small></span>
          </div>

          <div class="progress-card__main">
            <span class="eyebrow">学习进度</span>
            <h2 id="progress-title" class="progress-card__title">
              {{ percent >= 100 ? '全部章节已完成' : percent > 0 ? '正在学习中，保持节奏' : '从第 00 章开始你的 Agent 之旅' }}
            </h2>
            <p class="progress-card__desc">
              进度保存在本机浏览器（localStorage），不会上传服务器。完成章节后可在章节页随时取消标记。
            </p>
            <div class="progress-card__stats">
              <div class="progress-stat">
                <span class="progress-stat__label">已完成章节</span>
                <span class="progress-stat__value">{{ completedCount }}<small>/ {{ totalChapters }}</small></span>
              </div>
              <div class="progress-stat">
                <span class="progress-stat__label">已投入时长</span>
                <span class="progress-stat__value">{{ completedMinutes }}<small>分钟</small></span>
              </div>
              <div class="progress-stat">
                <span class="progress-stat__label">全课预计</span>
                <span class="progress-stat__value">{{ totalMinutes }}<small>分钟</small></span>
              </div>
            </div>
          </div>

          <div class="progress-card__action">
            <RouterLink
              v-if="continueChapter"
              :to="`/learn/${continueChapter.slug}`"
              class="btn btn--primary"
            >
              <AppIcon name="arrow-right" :size="16" />
              {{ completedCount ? '继续学习' : '开始学习' }}
            </RouterLink>
            <p v-if="continueChapter" class="progress-card__next">
              <span>下一站</span>
              {{ continueChapter.title }}
            </p>
            <p v-else class="progress-card__next">课程目录为空</p>
          </div>
        </section>

        <!-- 学习路径 -->
        <section class="home-section" aria-labelledby="path-title">
          <div class="section-head">
            <div>
              <span class="eyebrow">Learning Path</span>
              <h2 id="path-title" class="section-title">五段式学习路径</h2>
              <p class="section-subtitle">每一部分解决一类工程问题，前后有依赖，建议按顺序推进。</p>
            </div>
            <span class="chip chip--neutral">{{ parts.length }} 个部分 · {{ totalChapters }} 章</span>
          </div>

          <div class="learning-path">
            <a
              v-for="(part, index) in parts"
              :key="part.id"
              :href="`#part-${part.id}`"
              class="path-card"
              :class="{ 'is-complete': partStats(part).percent === 100 }"
            >
              <span class="path-card__step">{{ String(index + 1).padStart(2, '0') }}</span>
              <h3 class="path-card__title">{{ part.title }}</h3>
              <p class="path-card__meta">
                {{ part.chapters.length }} 章 · {{ partStats(part).minutes }} 分钟
              </p>
              <div class="path-card__bar" role="presentation">
                <span :style="{ width: `${partStats(part).percent}%` }"></span>
              </div>
              <p class="path-card__progress">
                <span>{{ partStats(part).done }} / {{ partStats(part).total }} 已完成</span>
                <span v-if="partStats(part).percent === 100" class="path-card__done">
                  <AppIcon name="check-circle" :size="14" /> 通关
                </span>
              </p>
            </a>
          </div>
        </section>

        <!-- 章节卡片 -->
        <section
          v-for="(part, index) in parts"
          :id="`part-${part.id}`"
          :key="part.id"
          class="part-block"
          :aria-labelledby="`part-${part.id}-title`"
        >
          <div class="part-block__head">
            <div class="part-block__label">
              <span class="part-block__index">PART {{ String(index + 1).padStart(2, '0') }}</span>
              <h2 :id="`part-${part.id}-title`" class="part-block__title">{{ part.title }}</h2>
            </div>
            <span class="part-block__meta">
              {{ part.chapters.length }} 章 · {{ partStats(part).minutes }} 分钟
            </span>
          </div>
          <div class="chapter-grid">
            <ChapterCard
              v-for="chapter in part.chapters"
              :key="chapter.slug"
              :chapter="chapter"
              :completed="isCompleted(chapter.slug)"
              @toggle="toggleCompleted"
            />
          </div>
        </section>

        <!-- 结尾入口 -->
        <section class="home-cta" aria-label="继续深入">
          <RouterLink to="/playground" class="cta-card">
            <span class="cta-card__icon"><AppIcon name="terminal" :size="22" /></span>
            <span class="cta-card__body">
              <b>打开 HR Agent 工作台</b>
              <small>切换员工身份，看执行轨迹、引用、记忆与审批</small>
            </span>
            <AppIcon name="arrow-right" :size="18" class="cta-card__arrow" />
          </RouterLink>
          <RouterLink to="/eval" class="cta-card cta-card--alt">
            <span class="cta-card__icon"><AppIcon name="chart" :size="22" /></span>
            <span class="cta-card__body">
              <b>查看评测看板</b>
              <small>20 条 Golden Case 的成功率、引用准确率与 Bad Case</small>
            </span>
            <AppIcon name="arrow-right" :size="18" class="cta-card__arrow" />
          </RouterLink>
        </section>
      </template>
    </div>
  </div>
</template>

<style scoped>
/* ---------- Hero ---------- */
.hero {
  display: grid;
  grid-template-columns: minmax(0, 1.08fr) minmax(0, 0.92fr);
  gap: 48px;
  align-items: center;
  padding: 56px 0 48px;
}
.hero__copy { min-width: 0; }
.hero__eyebrow {
  display: inline-flex;
  align-items: center;
  gap: 7px;
  padding: 5px 12px;
  border-radius: 999px;
  border: 1px solid var(--brand-100);
  background: rgba(238, 242, 255, 0.75);
  color: var(--brand-700);
  font-size: 12.5px;
  font-weight: 600;
}
.hero__title {
  margin: 18px 0 0;
  font-size: clamp(38px, 5vw, 54px);
  line-height: 1.12;
  letter-spacing: -0.045em;
  font-weight: 800;
  background: linear-gradient(120deg, #1f2430 20%, #3f3d9e 80%);
  -webkit-background-clip: text;
  background-clip: text;
  color: transparent;
}
.hero__lead {
  margin: 18px 0 0;
  font-size: 19px;
  line-height: 1.7;
  color: var(--text);
  font-weight: 500;
  max-width: 34em;
}
.hero__desc {
  margin: 12px 0 0;
  font-size: 15px;
  line-height: 1.85;
  color: var(--text-3);
  max-width: 38em;
}
.tech-badges {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  margin-top: 22px;
}
.tech-badge {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  height: 30px;
  padding: 0 11px;
  border: 1px solid var(--border);
  border-radius: 999px;
  background: #fff;
  color: var(--text-2);
  font-size: 12.5px;
  font-weight: 600;
  box-shadow: var(--shadow-sm);
}
.tech-badge svg { color: var(--brand); }
.tech-badge--muted { color: var(--text-3); font-weight: 500; }
.hero__actions {
  display: flex;
  flex-wrap: wrap;
  gap: 12px;
  margin-top: 28px;
}
.hero__stats {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: 12px;
  margin: 34px 0 0;
  padding-top: 22px;
  border-top: 1px solid var(--border);
}
.hero__stats dt {
  color: var(--text-4);
  font-size: 12px;
  letter-spacing: 0.02em;
}
.hero__stats dd {
  margin: 2px 0 0;
  font-size: 14px;
  font-weight: 650;
  color: var(--text-2);
}

/* ---------- Hero 预览卡 ---------- */
.hero__visual {
  position: relative;
  min-width: 0;
}
.trace-card {
  position: relative;
  border: 1px solid var(--border);
  border-radius: 18px;
  background: #fff;
  box-shadow: var(--shadow-lg);
  overflow: hidden;
  transform: rotate(0.6deg);
}
.trace-card__bar {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 10px 14px;
  border-bottom: 1px solid var(--border);
  background: var(--surface-2);
}
.trace-card__dot {
  width: 8px;
  height: 8px;
  border-radius: 50%;
  background: #12b76a;
  box-shadow: 0 0 0 3px rgba(18, 183, 106, 0.14);
}
.trace-card__session {
  font-family: var(--font-mono);
  font-size: 11.5px;
  color: var(--text-3);
  flex: 1;
}
.trace-card__body { padding: 16px; }
.mock-bubble {
  margin-left: auto;
  width: fit-content;
  max-width: 88%;
  padding: 9px 13px;
  border-radius: 13px 13px 4px 13px;
  background: var(--brand);
  color: #fff;
  font-size: 12.5px;
  line-height: 1.65;
  box-shadow: 0 8px 16px -12px rgba(79, 70, 229, 0.9);
}
.mock-steps {
  list-style: none;
  margin: 14px 0 0;
  padding: 0;
  display: flex;
  flex-direction: column;
  gap: 7px;
}
.mock-steps li {
  display: flex;
  align-items: center;
  gap: 9px;
  padding: 7px 9px;
  border: 1px solid var(--border);
  border-radius: 10px;
  background: var(--surface-2);
}
.mock-step__icon {
  display: grid;
  place-items: center;
  width: 24px;
  height: 24px;
  border-radius: 7px;
  color: var(--brand-700);
  background: var(--brand-50);
  border: 1px solid var(--brand-100);
  flex: none;
}
.mock-step__text { display: flex; flex-direction: column; line-height: 1.4; min-width: 0; flex: 1; }
.mock-step__text b { font-family: var(--font-mono); font-size: 11.5px; color: var(--text); font-weight: 600; }
.mock-step__text small { font-size: 10.5px; color: var(--text-3); }
.mock-steps em { font-style: normal; font-family: var(--font-mono); font-size: 10px; color: var(--text-4); }
.mock-reply {
  margin-top: 10px;
  padding: 11px 13px;
  border: 1px solid var(--border);
  border-radius: 12px;
  background: #fff;
}
.mock-reply p { margin: 0; font-size: 12.5px; line-height: 1.7; color: var(--text-2); }
.mock-reply b { color: var(--brand-700); }
.mock-cite {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  margin-top: 7px;
  padding: 3px 8px;
  border-radius: 6px;
  background: var(--brand-50);
  color: var(--brand-700);
  font-size: 10.5px;
  line-height: 1.6;
}
.trace-card__foot {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
  padding: 9px 14px;
  border-top: 1px solid var(--border);
  background: var(--surface-2);
  color: var(--text-3);
  font-size: 10.5px;
}
.trace-card__foot span { display: inline-flex; align-items: center; gap: 4px; }

.approval-peek {
  position: absolute;
  right: -14px;
  bottom: -24px;
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 10px 14px;
  border: 1px solid var(--warning-border);
  border-radius: 13px;
  background: #fff;
  box-shadow: var(--shadow-md);
}
.approval-peek__risk {
  padding: 2px 7px;
  border-radius: 6px;
  background: var(--warning-soft);
  color: var(--warning);
  font-size: 10.5px;
  font-weight: 700;
}
.approval-peek div { display: flex; flex-direction: column; line-height: 1.45; }
.approval-peek b { font-family: var(--font-mono); font-size: 11px; color: var(--text); }
.approval-peek small { font-size: 10.5px; color: var(--text-3); }

/* ---------- 加载 / 错误 ---------- */
.home-skeleton { margin-top: 16px; }
.skeleton--panel { height: 168px; border-radius: var(--radius); }
.skeleton-row {
  display: grid;
  grid-template-columns: repeat(5, 1fr);
  gap: 14px;
  margin-top: 26px;
}
.skeleton--path { height: 148px; border-radius: var(--radius-sm); }
.skeleton-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(280px, 1fr));
  gap: 16px;
  margin-top: 26px;
}
.skeleton--card { height: 208px; border-radius: var(--radius); }
.home-error { margin-top: 12px; }
.home-error__hint {
  margin: 14px 4px 0;
  color: var(--text-3);
  font-size: 13px;
}
.home-error__hint code {
  padding: 1px 5px;
  border-radius: 4px;
  background: var(--surface-3);
  font-family: var(--font-mono);
  font-size: 12px;
}

/* ---------- 进度卡 ---------- */
.progress-card {
  display: grid;
  grid-template-columns: auto minmax(0, 1fr) auto;
  align-items: center;
  gap: 26px;
  padding: 24px 26px;
  border: 1px solid var(--border);
  border-radius: var(--radius);
  background: linear-gradient(120deg, #fff 0%, #fbfaff 58%, #f6f4ff 100%);
  box-shadow: var(--shadow-sm);
}
.progress-card__ring {
  position: relative;
  display: grid;
  place-items: center;
  width: 84px;
  height: 84px;
}
.progress-card__progress { transition: stroke-dashoffset 0.6s cubic-bezier(0.2, 0.8, 0.2, 1); }
.progress-card__percent {
  position: absolute;
  font-size: 21px;
  font-weight: 750;
  letter-spacing: -0.03em;
  color: var(--brand-700);
}
.progress-card__percent small { font-size: 11px; font-weight: 600; margin-left: 1px; }
.progress-card__main { min-width: 0; }
.progress-card__title { margin: 3px 0 0; font-size: 19px; letter-spacing: -0.015em; }
.progress-card__desc { margin: 5px 0 0; color: var(--text-3); font-size: 13px; line-height: 1.7; }
.progress-card__stats {
  display: flex;
  flex-wrap: wrap;
  gap: 10px 28px;
  margin-top: 14px;
  padding-top: 12px;
  border-top: 1px dashed var(--border);
}
.progress-stat { display: flex; flex-direction: column; line-height: 1.4; }
.progress-stat__label { font-size: 11.5px; color: var(--text-4); }
.progress-stat__value { font-size: 18px; font-weight: 700; color: var(--text); letter-spacing: -0.02em; }
.progress-stat__value small { font-size: 11.5px; font-weight: 500; color: var(--text-3); margin-left: 3px; }
.progress-card__action { display: flex; flex-direction: column; align-items: flex-start; gap: 8px; max-width: 240px; }
.progress-card__next {
  margin: 0;
  font-size: 12px;
  color: var(--text-3);
  line-height: 1.6;
  display: -webkit-box;
  -webkit-line-clamp: 2;
  -webkit-box-orient: vertical;
  overflow: hidden;
}
.progress-card__next span { display: block; color: var(--text-4); font-size: 11px; }

/* ---------- 通用 section ---------- */
.home-section { margin-top: 48px; }
.part-block {
  margin-top: 44px;
  scroll-margin-top: 84px;
}
.part-block__head {
  display: flex;
  align-items: flex-end;
  justify-content: space-between;
  gap: 16px;
  flex-wrap: wrap;
  margin-bottom: 16px;
  padding-bottom: 12px;
  border-bottom: 1px solid var(--border);
}
.part-block__label { display: flex; flex-direction: column; gap: 2px; min-width: 0; }
.part-block__index {
  font-family: var(--font-mono);
  font-size: 11px;
  font-weight: 700;
  letter-spacing: 0.14em;
  color: var(--brand);
}
.part-block__title { margin: 0; font-size: 21px; letter-spacing: -0.02em; }
.part-block__meta { color: var(--text-3); font-size: 12.5px; white-space: nowrap; }

/* ---------- 学习路径 ---------- */
.learning-path {
  display: grid;
  grid-template-columns: repeat(5, minmax(0, 1fr));
  gap: 14px;
}
.path-card {
  position: relative;
  display: flex;
  flex-direction: column;
  padding: 16px 16px 14px;
  border: 1px solid var(--border);
  border-radius: var(--radius-sm);
  background: #fff;
  color: inherit;
  text-decoration: none;
  box-shadow: var(--shadow-sm);
  transition: border-color 0.16s ease, transform 0.18s ease, box-shadow 0.18s ease;
}
.path-card:hover {
  transform: translateY(-2px);
  border-color: var(--brand-200);
  box-shadow: var(--shadow-md);
}
.path-card.is-complete { background: linear-gradient(180deg, #fbfefc, #fff); border-color: var(--success-border); }
.path-card__step {
  display: inline-grid;
  place-items: center;
  width: 30px;
  height: 30px;
  border-radius: 9px;
  background: var(--brand-50);
  color: var(--brand-700);
  font-family: var(--font-mono);
  font-size: 12px;
  font-weight: 700;
}
.path-card.is-complete .path-card__step { background: var(--success-soft); color: var(--success); }
.path-card__title {
  margin: 12px 0 0;
  font-size: 14.5px;
  line-height: 1.55;
  letter-spacing: -0.01em;
  min-height: 3.1em;
}
.path-card__meta { margin: 6px 0 0; font-size: 11.5px; color: var(--text-3); }
.path-card__bar {
  height: 4px;
  margin-top: 12px;
  border-radius: 999px;
  background: var(--surface-3);
  overflow: hidden;
}
.path-card__bar span {
  display: block;
  height: 100%;
  border-radius: 999px;
  background: linear-gradient(90deg, #6366f1, #8b5cf6);
  transition: width 0.5s ease;
}
.path-card.is-complete .path-card__bar span { background: linear-gradient(90deg, #34d399, #10b981); }
.path-card__progress {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 4px;
  margin: 7px 0 0;
  font-size: 10.5px;
  color: var(--text-3);
}
.path-card__done { display: inline-flex; align-items: center; gap: 3px; color: var(--success); font-weight: 600; }

/* ---------- 章节网格 ---------- */
.chapter-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(288px, 1fr));
  gap: 16px;
}

/* ---------- 结尾 CTA ---------- */
.home-cta {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 16px;
  margin-top: 52px;
}
.cta-card {
  display: flex;
  align-items: center;
  gap: 14px;
  padding: 18px 20px;
  border: 1px solid var(--border);
  border-radius: var(--radius);
  background: #fff;
  color: inherit;
  text-decoration: none;
  box-shadow: var(--shadow-sm);
  transition: border-color 0.16s ease, box-shadow 0.18s ease, transform 0.18s ease;
}
.cta-card:hover { transform: translateY(-1px); border-color: var(--brand-200); box-shadow: var(--shadow-md); }
.cta-card__icon {
  display: grid;
  place-items: center;
  width: 44px;
  height: 44px;
  border-radius: 12px;
  color: var(--brand-700);
  background: var(--brand-50);
  border: 1px solid var(--brand-100);
  flex: none;
}
.cta-card--alt .cta-card__icon { color: #5925dc; background: #f4f3ff; border-color: #ebe9fe; }
.cta-card__body { display: flex; flex-direction: column; min-width: 0; }
.cta-card__body b { font-size: 14.5px; color: var(--text); }
.cta-card__body small { margin-top: 2px; color: var(--text-3); font-size: 12.5px; line-height: 1.6; }
.cta-card__arrow { margin-left: auto; color: var(--text-4); flex: none; transition: color 0.16s ease, transform 0.16s ease; }
.cta-card:hover .cta-card__arrow { color: var(--brand); transform: translateX(2px); }

/* ---------- 响应式 ---------- */
@media (max-width: 1080px) {
  .hero { gap: 32px; padding: 44px 0 32px; }
  .hero__title { font-size: 44px; }
  .learning-path { grid-template-columns: repeat(3, minmax(0, 1fr)); }
  .path-card__title { min-height: 0; }
  .progress-card { grid-template-columns: auto minmax(0, 1fr); }
  .progress-card__action { grid-column: 1 / -1; flex-direction: row; align-items: center; max-width: none; }
}
@media (max-width: 880px) {
  .hero { grid-template-columns: 1fr; gap: 36px; }
  .hero__visual { max-width: 560px; }
  .approval-peek { right: 8px; }
}
@media (max-width: 720px) {
  .hero { padding-top: 32px; }
  .hero__title { font-size: 38px; }
  .hero__lead { font-size: 17px; }
  .hero__stats { grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 10px 16px; }
  .learning-path { grid-template-columns: repeat(2, minmax(0, 1fr)); }
  .skeleton-row { grid-template-columns: repeat(2, 1fr); }
  .progress-card { grid-template-columns: 1fr; gap: 16px; padding: 20px; }
  .progress-card__ring { width: 72px; height: 72px; }
  .progress-card__ring svg { width: 72px; height: 72px; }
  .progress-card__stats { gap: 12px 22px; }
  .home-cta { grid-template-columns: 1fr; }
  .hero__actions .btn { flex: 1 1 auto; }
  .part-block { margin-top: 34px; }
  .home-section { margin-top: 38px; }
}
@media (max-width: 460px) {
  .learning-path { grid-template-columns: 1fr; }
  .hero__stats { grid-template-columns: 1fr 1fr; }
  .trace-card { transform: none; }
  .approval-peek { display: none; }
}
</style>
