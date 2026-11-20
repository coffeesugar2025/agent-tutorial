<script setup>
import { nextTick, onBeforeUnmount, ref, watch } from 'vue'
import { copyText } from '../../lib/clipboard.js'
import { renderMarkdown } from '../../lib/markdown.js'

const props = defineProps({
  markdown: { type: String, default: '' },
})

const emit = defineEmits(['ready'])

const html = ref('')
const articleRef = ref(null)
let copyTimer = null

watch(
  () => props.markdown,
  async (value) => {
    const result = renderMarkdown(value || '')
    html.value = result.html
    await nextTick()
    emit('ready', result.headings)
  },
  { immediate: true },
)

async function copyCode(button) {
  const block = button.closest('.code-block')
  const code = block?.querySelector('pre code')
  if (!code) return
  await copyText(code.textContent)
  const label = button.querySelector('span')
  button.classList.add('is-copied')
  if (label) label.textContent = '已复制'
  clearTimeout(copyTimer)
  copyTimer = setTimeout(() => {
    button.classList.remove('is-copied')
    if (label) label.textContent = '复制'
  }, 1600)
}

function onClick(event) {
  const button = event.target.closest?.('.code-copy')
  if (button) copyCode(button)
}

onBeforeUnmount(() => clearTimeout(copyTimer))
</script>

<template>
  <div ref="articleRef" class="md-body markdown-view" @click="onClick" v-html="html"></div>
</template>

<style scoped>
.markdown-view { min-width: 0; }
</style>
