<script setup>
import { RouterLink } from 'vue-router'
import AppIcon from './AppIcon.vue'

const year = new Date().getFullYear()
</script>

<template>
  <footer class="site-footer">
    <div class="site-footer__inner">
      <div class="footer-brand">
        <div class="footer-brand__head">
          <span class="footer-brand__mark" aria-hidden="true">
            <svg viewBox="0 0 32 32" width="18" height="18" fill="none">
              <path d="M6 11l10-5 10 5-10 5-10-5Z" fill="currentColor" />
              <path d="M10 14v6.5c0 1.8 2.7 3.3 6 3.3s6-1.5 6-3.3V14" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" />
            </svg>
          </span>
          <span>HR Agent 学堂</span>
        </div>
        <p>
          一门讲工程取舍的中文教程：从 HR 共享服务中心的真实痛点出发，用 Python 3.12 + FastAPI + Vue 3
          搭建可引用、可审批、可评测的 Agent。
        </p>
        <div class="footer-badges">
          <span class="chip chip--xs">Python 3.12</span>
          <span class="chip chip--xs">FastAPI</span>
          <span class="chip chip--xs">Vue 3</span>
          <span class="chip chip--xs">Mock 离线可跑</span>
        </div>
      </div>

      <nav class="footer-col" aria-label="页脚导航">
        <h2 class="footer-col__title">导航</h2>
        <RouterLink to="/" class="footer-link">课程首页</RouterLink>
        <RouterLink to="/playground" class="footer-link">HR Agent 工作台</RouterLink>
        <RouterLink to="/eval" class="footer-link">评测看板</RouterLink>
      </nav>

      <div class="footer-col">
        <h2 class="footer-col__title">说明</h2>
        <p class="footer-note">
          全部员工、候选人、制度与审批数据均为虚构演示数据，不包含真实个人信息。
        </p>
        <p class="footer-note">
          生产环境需替换为 OIDC/JWT 鉴权、真实审批流与审计存储，详见第 12、16 章。
        </p>
      </div>
    </div>

    <div class="site-footer__bottom">
      <span>© {{ year }} HR Agent 学堂 · 教学演示项目</span>
      <span class="footer-tech">
        <AppIcon name="code" :size="14" />
        Vue 3 · Vite · marked · highlight.js
      </span>
    </div>
  </footer>
</template>

<style scoped>
.site-footer {
  margin-top: 72px;
  border-top: 1px solid var(--border);
  background: linear-gradient(180deg, #fff, #f5f5fc);
}
.site-footer__inner {
  max-width: 1240px;
  margin: 0 auto;
  padding: 44px 24px 28px;
  display: grid;
  grid-template-columns: minmax(0, 1.6fr) minmax(0, 0.7fr) minmax(0, 1fr);
  gap: 40px;
}
.footer-brand__head {
  display: flex;
  align-items: center;
  gap: 8px;
  font-weight: 700;
  font-size: 15px;
  color: var(--text);
}
.footer-brand__mark {
  display: grid;
  place-items: center;
  width: 28px;
  height: 28px;
  border-radius: 8px;
  color: #fff;
  background: var(--brand);
}
.footer-brand p {
  margin: 10px 0 0;
  max-width: 46ch;
  color: var(--text-3);
  font-size: 13.5px;
  line-height: 1.75;
}
.footer-badges {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
  margin-top: 14px;
}
.footer-col__title {
  margin: 2px 0 12px;
  font-size: 12px;
  letter-spacing: 0.08em;
  text-transform: uppercase;
  color: var(--text-3);
  font-weight: 600;
}
.footer-link {
  display: block;
  width: fit-content;
  padding: 4px 0;
  color: var(--text-2);
  text-decoration: none;
  font-size: 14px;
  border-radius: 4px;
}
.footer-link:hover { color: var(--brand-700); text-decoration: underline; text-underline-offset: 3px; }
.footer-note {
  margin: 0 0 10px;
  color: var(--text-3);
  font-size: 13px;
  line-height: 1.75;
}
.site-footer__bottom {
  max-width: 1240px;
  margin: 0 auto;
  padding: 16px 24px 28px;
  border-top: 1px solid var(--border);
  display: flex;
  flex-wrap: wrap;
  gap: 8px 20px;
  justify-content: space-between;
  color: var(--text-3);
  font-size: 12.5px;
}
.footer-tech { display: inline-flex; align-items: center; gap: 6px; }
@media (max-width: 900px) {
  .site-footer__inner {
    grid-template-columns: 1fr 1fr;
    gap: 28px;
    padding: 32px 20px 20px;
  }
  .footer-brand { grid-column: 1 / -1; }
}
@media (max-width: 560px) {
  .site-footer__inner { grid-template-columns: 1fr; }
  .site-footer__bottom { padding: 14px 20px 24px; flex-direction: column; }
  .site-footer { margin-top: 48px; }
}
</style>
