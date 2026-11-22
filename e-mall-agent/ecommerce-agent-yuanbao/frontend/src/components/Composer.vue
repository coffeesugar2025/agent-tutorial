<script setup lang="ts">
import { ref } from 'vue'

defineProps<{ busy: boolean; quickPrompts: Array<{ q: string; hint: string }> }>()
const emit = defineEmits<{ send: [text: string]; stop: [] }>()

const input = ref('')

function submit() {
  const text = input.value.trim()
  if (!text) return
  emit('send', text)
  input.value = ''
}

function onKeydown(event: KeyboardEvent) {
  if (event.key === 'Enter' && !event.shiftKey && !event.isComposing) {
    event.preventDefault()
    submit()
  }
}

function useQuick(text: string) {
  emit('send', text)
}
</script>

<template>
  <div class="composer-zone">
    <div class="composer">
      <textarea
        v-model="input"
        :disabled="busy"
        rows="2"
        placeholder="问问商品、价格、订单或售后… 例如：预算 500 推荐一副降噪耳机"
        @keydown="onKeydown"
      />
      <button v-if="busy" class="stop-btn" @click="emit('stop')">停止</button>
      <button v-else class="send-btn" :disabled="!input.trim()" @click="submit">发送 ↵</button>
    </div>
    <div class="composer-hint">
      Enter 发送 · Shift+Enter 换行 ·
      <button
        v-for="item in quickPrompts.slice(0, 2)"
        :key="item.q"
        class="hint-quick"
        @click="useQuick(item.q)"
      >{{ item.q }}</button>
    </div>
  </div>
</template>

<style scoped>
.hint-quick {
  background: none; border: none; color: #8b9ab5; font-size: 10.5px;
  padding: 0 4px; text-decoration: underline dotted;
}
.hint-quick:hover { color: var(--accent); }
</style>
