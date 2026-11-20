<script setup>
import { RouterView } from 'vue-router'
import AppHeader from './components/AppHeader.vue'
import AppFooter from './components/AppFooter.vue'
</script>

<template>
  <div class="app-shell">
    <a class="skip-link" href="#main-content">跳到主要内容</a>
    <AppHeader />
    <main id="main-content" class="app-main" tabindex="-1">
      <RouterView v-slot="{ Component, route }">
        <Transition name="page-fade" mode="out-in">
          <component :is="Component" :key="route.path" />
        </Transition>
      </RouterView>
    </main>
    <AppFooter />
  </div>
</template>

<style scoped>
.app-main {
  min-height: calc(100vh - 64px - 260px);
  outline: none;
}
.page-fade-enter-active,
.page-fade-leave-active {
  transition: opacity 0.18s ease, transform 0.18s ease;
}
.page-fade-enter-from { opacity: 0; transform: translateY(4px); }
.page-fade-leave-to { opacity: 0; }
@media (prefers-reduced-motion: reduce) {
  .page-fade-enter-active,
  .page-fade-leave-active { transition: none; }
}
</style>
