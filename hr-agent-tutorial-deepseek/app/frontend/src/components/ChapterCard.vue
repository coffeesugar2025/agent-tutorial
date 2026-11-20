<script setup>
import { computed } from 'vue'
import { RouterLink } from 'vue-router'
import AppIcon from './AppIcon.vue'

const props = defineProps({
  chapter: { type: Object, required: true },
  completed: { type: Boolean, default: false },
})

defineEmits(['toggle'])

const orderLabel = computed(() => String(props.chapter.order).padStart(2, '0'))
const difficultyClass = computed(() => {
  const map = { 入门: 'starter', 进阶: 'advanced', 高阶: 'expert', 项目: 'project' }
  return `difficulty--${map[props.chapter.difficulty] || 'starter'}`
})
</script>

<template>
  <RouterLink
    :to="`/learn/${chapter.slug}`"
    class="chapter-card"
    :class="{ 'is-done': completed }"
    :aria-label="`第 ${orderLabel} 章 ${chapter.title}${completed ? '（已完成）' : ''}`"
  >
    <div class="chapter-card__head">
      <span class="chapter-card__index">{{ orderLabel }}</span>
      <span class="chapter-card__tags">
        <span v-if="completed" class="chapter-card__done-tag">
          <AppIcon name="check-circle" :size="13" />
          已完成
        </span>
        <span class="difficulty" :class="difficultyClass">{{ chapter.difficulty }}</span>
      </span>
    </div>

    <h3 class="chapter-card__title">{{ chapter.title }}</h3>
    <p class="chapter-card__summary">{{ chapter.summary }}</p>

    <div class="chapter-card__foot">
      <span class="chapter-card__meta">
        <AppIcon name="clock" :size="14" />
        {{ chapter.minutes }} 分钟
      </span>
      <span class="chapter-card__actions">
        <button
          type="button"
          class="chapter-card__toggle"
          :class="{ 'is-done': completed }"
          :title="completed ? '取消完成标记' : '标记为已完成'"
          @click.prevent.stop="$emit('toggle', chapter.slug)"
        >
          <AppIcon :name="completed ? 'check-circle' : 'check'" :size="14" />
          <span>{{ completed ? '已学完' : '标记完成' }}</span>
        </button>
        <AppIcon name="arrow-right" :size="16" class="chapter-card__arrow" />
      </span>
    </div>
  </RouterLink>
</template>

<style scoped>
.chapter-card {
  position: relative;
  display: flex;
  flex-direction: column;
  min-height: 208px;
  padding: 18px 18px 14px;
  border: 1px solid var(--border);
  border-radius: var(--radius);
  background: var(--surface);
  color: inherit;
  text-decoration: none;
  box-shadow: var(--shadow-sm);
  transition: transform 0.18s ease, border-color 0.18s ease, box-shadow 0.18s ease;
}
.chapter-card:hover {
  transform: translateY(-2px);
  border-color: var(--brand-200);
  box-shadow: var(--shadow-md);
}
.chapter-card:focus-visible { outline-offset: 3px; }
.chapter-card.is-done {
  border-color: #d6e4ff;
  background: linear-gradient(180deg, #fbfcff, #fff);
}
.chapter-card.is-done::before {
  content: "";
  position: absolute;
  left: 0;
  top: 14px;
  bottom: 14px;
  width: 3px;
  border-radius: 0 3px 3px 0;
  background: linear-gradient(180deg, #34d399, #10b981);
}
.chapter-card__head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
}
.chapter-card__index {
  display: inline-grid;
  place-items: center;
  min-width: 30px;
  height: 24px;
  padding: 0 7px;
  border-radius: 7px;
  background: var(--brand-50);
  color: var(--brand-700);
  font-family: var(--font-mono);
  font-size: 12px;
  font-weight: 700;
  letter-spacing: 0.04em;
}
.is-done .chapter-card__index { background: #ecfdf3; color: var(--success); }
.chapter-card__tags {
  display: inline-flex;
  align-items: center;
  gap: 6px;
}
.chapter-card__done-tag {
  display: inline-flex;
  align-items: center;
  gap: 3px;
  font-size: 11.5px;
  font-weight: 600;
  color: var(--success);
}
.difficulty {
  padding: 1px 8px;
  border-radius: 999px;
  font-size: 11.5px;
  font-weight: 600;
  border: 1px solid transparent;
}
.difficulty--starter { color: #027a48; background: #ecfdf3; border-color: #d1fadf; }
.difficulty--advanced { color: #175cd3; background: #eff8ff; border-color: #d1e9ff; }
.difficulty--expert { color: #5925dc; background: #f4f3ff; border-color: #ebe9fe; }
.difficulty--project { color: #be185d; background: #fdf2f8; border-color: #fce7f3; }

.chapter-card__title {
  margin: 13px 0 0;
  font-size: 16.5px;
  line-height: 1.5;
  letter-spacing: -0.01em;
  color: var(--text);
  transition: color 0.16s ease;
}
.chapter-card:hover .chapter-card__title { color: var(--brand-700); }
.chapter-card__summary {
  margin: 8px 0 0;
  flex: 1;
  color: var(--text-3);
  font-size: 13.5px;
  line-height: 1.72;
  display: -webkit-box;
  -webkit-line-clamp: 3;
  -webkit-box-orient: vertical;
  overflow: hidden;
}
.chapter-card__foot {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
  margin-top: 14px;
  padding-top: 11px;
  border-top: 1px solid var(--border);
}
.chapter-card__meta {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  color: var(--text-3);
  font-size: 12.5px;
}
.chapter-card__actions {
  display: inline-flex;
  align-items: center;
  gap: 6px;
}
.chapter-card__toggle {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  padding: 3px 7px;
  border: 1px solid transparent;
  border-radius: 7px;
  background: transparent;
  color: var(--text-4);
  font-size: 11.5px;
  font-weight: 600;
  transition: color 0.15s ease, background-color 0.15s ease, border-color 0.15s ease;
}
.chapter-card__toggle:hover { color: var(--brand-700); background: var(--brand-50); border-color: var(--brand-100); }
.chapter-card__toggle.is-done { color: var(--success); }
.chapter-card__toggle.is-done:hover { background: var(--success-soft); border-color: var(--success-border); color: var(--success); }
.chapter-card__arrow {
  color: var(--text-4);
  opacity: 0;
  transform: translateX(-3px);
  transition: opacity 0.16s ease, transform 0.16s ease, color 0.16s ease;
}
.chapter-card:hover .chapter-card__arrow { opacity: 1; transform: translateX(0); color: var(--brand); }
</style>
