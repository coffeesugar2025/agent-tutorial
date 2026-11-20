<script setup>
import { computed } from 'vue'

// 全部图标为内联 SVG（stroke 线条），不使用 emoji 作为功能图标。
const props = defineProps({
  name: { type: String, required: true },
  size: { type: [Number, String], default: 20 },
  strokeWidth: { type: [Number, String], default: 1.8 },
})

const ICONS = {
  book: ['M4 5.5A2.5 2.5 0 0 1 6.5 3H20v15.5H6.5A2.5 2.5 0 0 0 4 21V5.5Z', 'M4 18.5A2.5 2.5 0 0 1 6.5 16H20'],
  code: ['m8 6-5 6 5 6', 'm16 6 5 6-5 6'],
  terminal: ['M4 5h16v14H4z', 'm8 9 3 3-3 3', 'M13 15h3'],
  chart: ['M5 20V12', 'M11 20V5', 'M17 20v-9', 'M3 20h18'],
  activity: ['M3 12h4l2.5-7 5 14L17 12h4'],
  sparkles: ['M12 3l1.8 4.7L18.5 9.5l-4.7 1.8L12 16l-1.8-4.7L5.5 9.5l4.7-1.8L12 3Z', 'M18 15l.9 2.3L21 18l-2.1.8L18 21l-.9-2.2L15 18l2.1-.7L18 15Z'],
  'arrow-right': ['M5 12h14', 'm13 6 6 6-6 6'],
  'arrow-left': ['M19 12H5', 'm11 18-6-6 6-6'],
  'arrow-up-right': ['M7 17 17 7', 'M8 7h9v9'],
  'arrow-down-left': ['M17 7 7 17', 'M16 17H7V8'],
  check: ['M4 12.5 9 17.5 20 6.5'],
  'check-circle': ['M22 12a10 10 0 1 1-20 0 10 10 0 0 1 20 0Z', 'm7.5 12.5 3 3 5-6'],
  clock: ['M22 12a10 10 0 1 1-20 0 10 10 0 0 1 20 0Z', 'M12 7v5l3.5 2'],
  layers: ['M12 3 3 8l9 5 9-5-9-5Z', 'm3 13 9 5 9-5', 'm3 17.5 9 5 9-5'],
  play: ['M8 5.5v13l11-6.5-11-6.5Z'],
  refresh: ['M20 11a8 8 0 1 0-1.6 6.4', 'M20 4v7h-7'],
  alert: ['M12 3 2.8 20h18.4L12 3Z', 'M12 9v5', 'M12 17.6v.1'],
  'alert-circle': ['M22 12a10 10 0 1 1-20 0 10 10 0 0 1 20 0Z', 'M12 7.5v5', 'M12 16.4v.1'],
  info: ['M22 12a10 10 0 1 1-20 0 10 10 0 0 1 20 0Z', 'M12 11v6', 'M12 7.5v.1'],
  copy: ['M9 9V5.5A1.5 1.5 0 0 1 10.5 4h8A1.5 1.5 0 0 1 20 5.5v8a1.5 1.5 0 0 1-1.5 1.5H15', 'M4 11.5A1.5 1.5 0 0 1 5.5 10h8a1.5 1.5 0 0 1 1.5 1.5v8a1.5 1.5 0 0 1-1.5 1.5h-8A1.5 1.5 0 0 1 4 19.5v-8Z'],
  link: ['M10.5 13.5a4 4 0 0 0 5.7 0l2.3-2.3a4 4 0 1 0-5.7-5.7L11.5 6.8', 'M13.5 10.5a4 4 0 0 0-5.7 0l-2.3 2.3a4 4 0 1 0 5.7 5.7l1.3-1.3'],
  'chevron-down': ['m6 9 6 6 6-6'],
  'chevron-right': ['m9 6 6 6-6 6'],
  menu: ['M4 7h16', 'M4 12h16', 'M4 17h16'],
  close: ['M6 6l12 12', 'M18 6 6 18'],
  send: ['M21 3 3 13l8 4 4 8 6-22Z', 'M21 3 11 17'],
  user: ['M12 12a4 4 0 1 0 0-8 4 4 0 0 0 0 8Z', 'M4 21a8 8 0 0 1 16 0'],
  users: ['M9 11a3.5 3.5 0 1 0 0-7 3.5 3.5 0 0 0 0 7Z', 'M2.5 21a6.5 6.5 0 0 1 13 0', 'M16 4.5a3.5 3.5 0 0 1 0 6.6', 'M18 14.5a6.5 6.5 0 0 1 3.5 6.5'],
  shield: ['M12 3 5 6v5.5c0 4.3 2.9 7.6 7 9.5 4.1-1.9 7-5.2 7-9.5V6l-7-3Z', 'm9 12 2 2 4-4'],
  'shield-alert': ['M12 3 5 6v5.5c0 4.3 2.9 7.6 7 9.5 4.1-1.9 7-5.2 7-9.5V6l-7-3Z', 'M12 8v4.5', 'M12 15.6v.1'],
  quote: ['M7.5 6C5 6 3 8 3 10.5S5 15 7.5 15c.5 0 1-.1 1.5-.2C8.5 17 7 18.5 5 19', 'M16.5 6C14 6 12 8 12 10.5S14 15 16.5 15c.5 0 1-.1 1.5-.2C17.5 17 16 18.5 14 19'],
  chip: ['M7 7h10v10H7z', 'M10 3v4', 'M14 3v4', 'M10 17v4', 'M14 17v4', 'M3 10h4', 'M3 14h4', 'M17 10h4', 'M17 14h4'],
  'file-text': ['M6 3h8l4 4v14H6V3Z', 'M14 3v4h4', 'M9 12h6', 'M9 16h6'],
  search: ['M21 11a8 8 0 1 1-16 0 8 8 0 0 1 16 0Z', 'm16.5 16.5 4.5 4.5'],
  dollar: ['M12 3v18', 'M16.5 7.5c0-1.9-2-3-4.5-3s-4.5 1.1-4.5 3 2 2.7 4.5 3.4 4.5 1.5 4.5 3.4-2 3-4.5 3-4.5-1.1-4.5-3'],
  timer: ['M22 12a10 10 0 1 1-20 0 10 10 0 0 1 20 0Z', 'M12 8v4l2.5 1.5', 'M9 2h6'],
  target: ['M22 12a10 10 0 1 1-20 0 10 10 0 0 1 20 0Z', 'M18 12a6 6 0 1 1-12 0 6 6 0 0 1 12 0Z', 'M12 12h.01'],
  lock: ['M6 11h12v9H6z', 'M8.5 11V8a3.5 3.5 0 0 1 7 0v3'],
  home: ['M3 10.5 12 3l9 7.5V21h-6v-6H9v6H3V10.5Z'],
  grid: ['M4 4h7v7H4z', 'M13 4h7v7h-7z', 'M4 13h7v7H4z', 'M13 13h7v7h-7z'],
  minus: ['M5 12h14'],
  plus: ['M12 5v14', 'M5 12h16'],
  filter: ['M4 5h16l-6 7.5V20l-4-2v-5.5L4 5Z'],
  tool: ['M14.5 6.5a4 4 0 0 0-5.2 5.2L4 17l3 3 5.3-5.3a4 4 0 0 0 5.2-5.2l-2.5 2.5-2.8-2.8 2.3-2.7Z'],
  spark: ['M12 4l1.5 4.5L18 10l-4.5 1.5L12 16l-1.5-4.5L6 10l4.5-1.5L12 4Z'],
  graduation: ['M2 9l10-5 10 5-10 5L2 9Z', 'M6 11v4.5c0 1.5 2.7 3 6 3s6-1.5 6-3V11', 'M22 9v5'],
}

const paths = computed(() => ICONS[props.name] || ICONS.info)
</script>

<template>
  <svg
    :width="size"
    :height="size"
    viewBox="0 0 24 24"
    fill="none"
    stroke="currentColor"
    :stroke-width="strokeWidth"
    stroke-linecap="round"
    stroke-linejoin="round"
    aria-hidden="true"
    focusable="false"
  >
    <path v-for="(d, index) in paths" :key="index" :d="d" />
  </svg>
</template>
