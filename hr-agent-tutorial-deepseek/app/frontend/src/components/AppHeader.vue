<script setup>
import { computed } from 'vue'
import { RouterLink, useRoute } from 'vue-router'
import AppIcon from './AppIcon.vue'

const route = useRoute()

const navItems = [
  { label: '首页', to: '/', icon: 'home' },
  { label: '工作台', to: '/playground', icon: 'terminal' },
  { label: '评测看板', to: '/eval', icon: 'chart' },
]

function isActive(item) {
  if (item.to === '/') return route.path === '/'
  return route.path === item.to || route.path.startsWith(`${item.to}/`)
}

const isLearn = computed(() => route.path.startsWith('/learn'))
</script>

<template>
  <header class="site-header">
    <div class="site-header__inner">
      <RouterLink to="/" class="brand" aria-label="HR Agent 学堂首页">
        <span class="brand__mark" aria-hidden="true">
          <svg viewBox="0 0 32 32" width="22" height="22" fill="none" aria-hidden="true">
            <path d="M6 11l10-5 10 5-10 5-10-5Z" fill="currentColor" opacity=".95" />
            <path d="M10 14v6.5c0 1.8 2.7 3.3 6 3.3s6-1.5 6-3.3V14" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" />
            <path d="M26 11v6" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" />
          </svg>
        </span>
        <span class="brand__text">
          <span class="brand__name">HR Agent 学堂</span>
          <span class="brand__tagline">从 HR 痛点到可交付的 Agent</span>
        </span>
      </RouterLink>

      <nav class="site-nav" aria-label="主导航">
        <RouterLink
          v-for="item in navItems"
          :key="item.to"
          :to="item.to"
          class="site-nav__link"
          :class="{ 'is-active': isActive(item) }"
          :aria-current="isActive(item) ? 'page' : undefined"
        >
          <AppIcon :name="item.icon" :size="16" />
          <span>{{ item.label }}</span>
        </RouterLink>
      </nav>

      <div class="site-header__aside">
        <span class="env-pill" title="演示环境默认使用离线 MockLLM，不调用外部模型">
          <span class="env-pill__dot" aria-hidden="true"></span>
          离线演示
        </span>
        <RouterLink v-if="!isLearn" to="/playground" class="btn btn--primary btn--sm header-cta">
          打开工作台
          <AppIcon name="arrow-right" :size="15" />
        </RouterLink>
      </div>
    </div>
  </header>
</template>

<style scoped>
.site-header {
  position: sticky;
  top: 0;
  z-index: 40;
  background: rgba(255, 255, 255, 0.86);
  backdrop-filter: saturate(160%) blur(14px);
  border-bottom: 1px solid var(--border);
}
.site-header__inner {
  max-width: 1240px;
  margin: 0 auto;
  padding: 0 24px;
  height: 64px;
  display: flex;
  align-items: center;
  gap: 20px;
}
.brand {
  display: flex;
  align-items: center;
  gap: 10px;
  color: var(--text);
  text-decoration: none;
  min-width: 0;
  border-radius: 10px;
  padding: 4px;
  margin-left: -4px;
}
.brand:hover .brand__mark { transform: translateY(-1px); }
.brand__mark {
  display: grid;
  place-items: center;
  flex: none;
  width: 34px;
  height: 34px;
  border-radius: 10px;
  color: #fff;
  background: linear-gradient(140deg, #6366f1, #4f46e5 55%, #4338ca);
  box-shadow: 0 6px 14px -8px rgba(79, 70, 229, 0.9);
  transition: transform 0.18s ease;
}
.brand__text {
  display: flex;
  flex-direction: column;
  line-height: 1.25;
  min-width: 0;
}
.brand__name {
  font-size: 15.5px;
  font-weight: 700;
  letter-spacing: 0.01em;
  white-space: nowrap;
}
.brand__tagline {
  font-size: 11.5px;
  color: var(--text-3);
  white-space: nowrap;
}
.site-nav {
  display: flex;
  align-items: center;
  gap: 2px;
  margin-left: 8px;
}
.site-nav__link {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 7px 12px;
  border-radius: 9px;
  font-size: 14px;
  color: var(--text-2);
  text-decoration: none;
  transition: background 0.16s ease, color 0.16s ease;
}
.site-nav__link:hover { background: var(--surface-3); color: var(--text); }
.site-nav__link.is-active {
  color: var(--brand-700);
  background: var(--brand-50);
  font-weight: 600;
}
.site-header__aside {
  margin-left: auto;
  display: flex;
  align-items: center;
  gap: 12px;
}
.env-pill {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  font-size: 12px;
  color: var(--text-3);
  padding: 4px 10px;
  border-radius: 999px;
  border: 1px solid var(--border);
  background: #fff;
  white-space: nowrap;
}
.env-pill__dot {
  width: 6px;
  height: 6px;
  border-radius: 50%;
  background: #12b76a;
  box-shadow: 0 0 0 3px rgba(18, 183, 106, 0.12);
}
.header-cta { white-space: nowrap; }

@media (max-width: 900px) {
  .site-header__inner { padding: 0 16px; gap: 12px; }
  .brand__tagline, .env-pill { display: none; }
  .site-nav { margin-left: 0; }
}
@media (max-width: 680px) {
  .site-nav__link span { display: none; }
  .site-nav__link { padding: 8px; }
  .header-cta { display: none; }
  .site-header__inner { height: 58px; }
}
</style>
