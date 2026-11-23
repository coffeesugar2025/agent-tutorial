<template>
  <div class="composer">
    <el-input
      v-model="text"
      class="composer__input"
      type="textarea"
      :autosize="{ minRows: 1, maxRows: 5 }"
      :placeholder="placeholder"
      :disabled="disabled"
      resize="none"
      @keydown="onKeydown"
    />
    <div class="composer__footer">
      <span class="composer__hint">Enter 发送 · Shift + Enter 换行</span>
      <span class="composer__count">{{ text.length }}</span>
      <el-button v-if="streaming" type="danger" plain size="small" @click="emit('stop')">
        停止生成
      </el-button>
      <el-button
        v-else
        type="primary"
        size="small"
        :disabled="disabled || !text.trim()"
        @click="submit"
      >
        发送
      </el-button>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref } from 'vue'

const props = withDefaults(
  defineProps<{
    streaming?: boolean
    disabled?: boolean
    placeholder?: string
  }>(),
  { streaming: false, disabled: false, placeholder: '向智能体提问，例如：帮我找 5000 以内的拍照手机' },
)

const emit = defineEmits<{ send: [text: string]; stop: [] }>()

const text = ref('')

function submit(): void {
  const content = text.value.trim()
  if (!content || props.streaming || props.disabled) return
  emit('send', content)
  text.value = ''
}

function onKeydown(event: KeyboardEvent): void {
  if (event.key !== 'Enter' || event.shiftKey) return
  // 中文输入法组合输入中不发送
  if (event.isComposing || event.keyCode === 229) return
  event.preventDefault()
  submit()
}
</script>

<style scoped lang="scss">
.composer {
  padding: 10px 12px;
  background: #fff;
  border: 1px solid var(--ecom-border);
  border-radius: 10px;
  flex-shrink: 0;

  &__input {
    :deep(.el-textarea__inner) {
      padding: 4px 6px;
      font-size: 14px;
      line-height: 1.7;
      box-shadow: none;
      border: 0;
    }
  }

  &__footer {
    display: flex;
    align-items: center;
    gap: 10px;
    margin-top: 6px;
  }

  &__hint {
    font-size: 11px;
    color: var(--ecom-text-placeholder);
  }

  &__count {
    margin-left: auto;
    font-size: 11px;
    color: var(--ecom-text-placeholder);
    font-variant-numeric: tabular-nums;
  }
}
</style>
