<script setup>
import { reactive, watch } from 'vue'
import { RouterLink } from 'vue-router'
import AppIcon from '../AppIcon.vue'

const props = defineProps({
  parts: { type: Array, default: () => [] },
  currentSlug: { type: String, default: '' },
  completed: { type: Object, default: () => new Set() },
  compact: { type: Boolean, default: false },
})

// 默认全部展开；切换章节时确保当前章节所在部分可见。
const openParts = reactive(new Set(props.parts.map((part) => part.id)))

watch(
  () => [props.parts, props.currentSlug],
  () => {
    const currentPart = props.parts.find((part) => part.chapters.some((chapter) => chapter.slug === props.currentSlug))
    if (currentPart && !openParts.has(currentPart.id)) openParts.add(currentPart.id)
  },
  { deep: false },
)

function toggle(partId) {
  if (openParts.has(partId)) openParts.delete(partId)
  else openParts.add(partId)
}

function isOpen(partId) {
  return openParts.has(partId)
}
</script>

<template>
  <nav class="chapter-nav" :class="{ 'chapter-nav--compact': compact }" aria-label="章节导航">
    <div v-for="part in parts" :key="part.id" class="chapter-nav__part">
      <button
        type="button"
        class="chapter-nav__toggle"
        :aria-expanded="isOpen(part.id)"
        @click="toggle(part.id)"
      >
        <AppIcon name="chevron-down" :size="14" class="chapter-nav__chevron" :class="{ 'is-closed': !isOpen(part.id) }" />
        <span class="chapter-nav__part-title">{{ part.title }}</span>
        <span class="chapter-nav__count">{{ part.chapters.length }}</span>
      </button>

      <ul v-show="isOpen(part.id)" class="chapter-nav__list">
        <li v-for="chapter in part.chapters" :key="chapter.slug">
          <RouterLink
            :to="`/learn/${chapter.slug}`"
            class="chapter-nav__link"
            :class="{ 'is-active': chapter.slug === currentSlug }"
            :aria-current="chapter.slug === currentSlug ? 'page' : undefined"
          >
            <span class="chapter-nav__order">{{ String(chapter.order).padStart(2, '0') }}</span>
            <span class="chapter-nav__title">{{ chapter.title }}</span>
            <AppIcon
              v-if="completed.has(chapter.slug)"
              name="check-circle"
              :size="14"
              class="chapter-nav__done"
            />
          </RouterLink>
        </li>
      </ul>
    </div>
  </nav>
</template>

<style scoped>
.chapter-nav { display: flex; flex-direction: column; gap: 6px; }
.chapter-nav__part { border-radius: 10px; }
.chapter-nav__toggle {
  display: flex;
  align-items: center;
  gap: 7px;
  width: 100%;
  padding: 8px 8px;
  border: 0;
  border-radius: 8px;
  background: transparent;
  color: var(--text-2);
  font-size: 12.5px;
  font-weight: 650;
  text-align: left;
  line-height: 1.5;
  transition: background-color 0.15s ease, color 0.15s ease;
}
.chapter-nav__toggle:hover { background: var(--surface-3); color: var(--text); }
.chapter-nav__chevron { flex: none; color: var(--text-4); transition: transform 0.18s ease; }
.chapter-nav__chevron.is-closed { transform: rotate(-90deg); }
.chapter-nav__part-title { flex: 1; min-width: 0; }
.chapter-nav__count {
  font-family: var(--font-mono);
  font-size: 10.5px;
  font-weight: 600;
  color: var(--text-4);
  background: var(--surface-3);
  border-radius: 5px;
  padding: 0 5px;
  line-height: 1.6;
}
.chapter-nav__list {
  list-style: none;
  margin: 2px 0 6px;
  padding: 0 0 0 6px;
  display: flex;
  flex-direction: column;
  gap: 1px;
}
.chapter-nav__link {
  position: relative;
  display: flex;
  align-items: flex-start;
  gap: 7px;
  padding: 6px 8px 6px 10px;
  border-radius: 8px;
  color: var(--text-3);
  font-size: 13px;
  line-height: 1.55;
  text-decoration: none;
  border-left: 2px solid transparent;
  transition: background-color 0.15s ease, color 0.15s ease, border-color 0.15s ease;
}
.chapter-nav__link:hover { background: var(--surface-3); color: var(--text); }
.chapter-nav__link.is-active {
  background: var(--brand-50);
  color: var(--brand-700);
  border-left-color: var(--brand);
  font-weight: 600;
}
.chapter-nav__order {
  flex: none;
  font-family: var(--font-mono);
  font-size: 10.5px;
  line-height: 1.9;
  color: var(--text-4);
}
.chapter-nav__link.is-active .chapter-nav__order { color: var(--brand); }
.chapter-nav__title { flex: 1; min-width: 0; }
.chapter-nav__done { flex: none; margin-top: 3px; color: var(--success); }
.chapter-nav--compact .chapter-nav__title { font-size: 13.5px; }
</style>
