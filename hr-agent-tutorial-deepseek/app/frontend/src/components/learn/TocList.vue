<script setup>
defineProps({
  headings: { type: Array, default: () => [] },
  activeId: { type: String, default: '' },
})

function onClick(event, id) {
  // 使用原生锚点跳转，交给浏览器与 router 的 scrollBehavior 处理。
  event.preventDefault()
  const target = document.getElementById(id)
  if (!target) return
  target.scrollIntoView({ behavior: 'smooth', block: 'start' })
  history.replaceState(null, '', `#${id}`)
}
</script>

<template>
  <nav class="toc" aria-label="本页目录">
    <p class="toc__title">本页目录</p>
    <ul v-if="headings.length" class="toc__list">
      <li v-for="heading in headings" :key="heading.id">
        <a
          :href="`#${heading.id}`"
          class="toc__link"
          :class="{ 'is-active': heading.id === activeId, 'toc__link--sub': heading.level === 3 }"
          :aria-current="heading.id === activeId ? 'location' : undefined"
          @click="onClick($event, heading.id)"
        >
          {{ heading.text }}
        </a>
      </li>
    </ul>
    <p v-else class="toc__empty">本章暂无小节标题</p>
  </nav>
</template>

<style scoped>
.toc {
  padding-left: 16px;
  border-left: 1px solid var(--border);
}
.toc__title {
  margin: 0 0 10px;
  font-size: 11.5px;
  font-weight: 650;
  letter-spacing: 0.08em;
  color: var(--text-4);
}
.toc__list { list-style: none; margin: 0; padding: 0; display: flex; flex-direction: column; gap: 1px; }
.toc__link {
  display: block;
  padding: 3px 0 3px 10px;
  border-left: 2px solid transparent;
  margin-left: -17px;
  color: var(--text-3);
  font-size: 12.5px;
  line-height: 1.55;
  text-decoration: none;
  transition: color 0.15s ease, border-color 0.15s ease;
}
.toc__link:hover { color: var(--text); }
.toc__link--sub { padding-left: 22px; font-size: 12px; color: var(--text-4); }
.toc__link.is-active { color: var(--brand-700); border-left-color: var(--brand); font-weight: 600; }
.toc__empty { margin: 0; color: var(--text-4); font-size: 12px; }
</style>
