<script setup>
import { RouterLink } from 'vue-router'
import AppIcon from '../components/AppIcon.vue'
</script>

<template>
  <div class="page not-found">
    <div class="container not-found__inner">
      <div class="not-found__code" aria-hidden="true">404</div>
      <div class="not-found__panel">
        <span class="eyebrow">
          <AppIcon name="search" :size="14" />
          Page not found
        </span>
        <h1 class="not-found__title">这个页面不在课程地图里</h1>
        <p class="not-found__desc">
          链接可能拼错了，或者章节 slug 发生了变化。你可以回到课程首页继续学习，或直接打开工作台试一次对话。
        </p>
        <div class="not-found__actions">
          <RouterLink to="/" class="btn btn--primary">
            <AppIcon name="home" :size="16" />
            回到课程首页
          </RouterLink>
          <RouterLink to="/playground" class="btn btn--secondary">
            <AppIcon name="terminal" :size="16" />
            打开工作台
          </RouterLink>
          <RouterLink to="/eval" class="btn btn--ghost">
            <AppIcon name="chart" :size="16" />
            评测看板
          </RouterLink>
        </div>
        <p class="not-found__hint">
          课程路径形如 <code>/learn/agent-loop</code>；完整章节列表见首页学习路径。
        </p>
      </div>
    </div>
  </div>
</template>

<style scoped>
.not-found { padding: 72px 0 48px; }
.not-found__inner {
  display: grid;
  grid-template-columns: minmax(0, 0.9fr) minmax(0, 1.1fr);
  gap: 40px;
  align-items: center;
  max-width: 1040px;
}
.not-found__code {
  font-size: clamp(120px, 18vw, 220px);
  font-weight: 800;
  line-height: 1;
  letter-spacing: -0.08em;
  text-align: center;
  background: linear-gradient(140deg, #c7d2fe 10%, #6366f1 55%, #4338ca 100%);
  -webkit-background-clip: text;
  background-clip: text;
  color: transparent;
  user-select: none;
}
.not-found__panel {
  padding: 30px;
  border: 1px solid var(--border);
  border-radius: var(--radius);
  background: #fff;
  box-shadow: var(--shadow-md);
}
.not-found__title { margin: 8px 0 0; font-size: 26px; letter-spacing: -0.03em; }
.not-found__desc { margin: 10px 0 0; color: var(--text-3); font-size: 13.5px; line-height: 1.8; }
.not-found__actions { display: flex; flex-wrap: wrap; gap: 9px; margin-top: 20px; }
.not-found__hint { margin: 16px 0 0; color: var(--text-4); font-size: 11.5px; }
.not-found__hint code {
  font-family: var(--font-mono);
  font-size: 11px;
  padding: 1px 5px;
  border-radius: 4px;
  background: var(--surface-3);
  color: var(--text-2);
}
@media (max-width: 820px) {
  .not-found { padding: 40px 0 24px; }
  .not-found__inner { grid-template-columns: 1fr; gap: 20px; }
  .not-found__code { font-size: 120px; }
  .not-found__panel { padding: 22px; }
  .not-found__actions .btn { flex: 1 1 auto; }
}
</style>
