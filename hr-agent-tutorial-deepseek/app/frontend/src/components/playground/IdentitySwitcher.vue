<script setup>
import AppIcon from '../AppIcon.vue'

defineProps({
  identities: { type: Array, required: true },
  value: { type: String, required: true },
  disabled: { type: Boolean, default: false },
})

const emit = defineEmits(['change'])
</script>

<template>
  <div class="identity-switcher" role="group" aria-label="选择演示身份">
    <span class="identity-switcher__label">
      <AppIcon name="users" :size="15" />
      演示身份
    </span>
    <div class="identity-switcher__options">
      <button
        v-for="identity in identities"
        :key="identity.employeeId"
        type="button"
        class="identity"
        :class="{ 'is-active': identity.employeeId === value }"
        :disabled="disabled"
        :aria-pressed="identity.employeeId === value"
        @click="emit('change', identity.employeeId)"
      >
        <span class="identity__avatar" aria-hidden="true">{{ identity.name.slice(0, 1) }}</span>
        <span class="identity__text">
          <span class="identity__name">
            {{ identity.name }}
            <span class="identity__id">{{ identity.employeeId }}</span>
          </span>
          <span class="identity__role">{{ identity.role }}</span>
        </span>
        <span v-if="identity.employeeId === value" class="identity__check" aria-hidden="true">
          <AppIcon name="check" :size="12" />
        </span>
      </button>
    </div>
  </div>
</template>

<style scoped>
.identity-switcher {
  display: flex;
  align-items: center;
  gap: 16px;
  padding: 12px 14px;
  border: 1px solid var(--border);
  border-radius: var(--radius);
  background: #fff;
  box-shadow: var(--shadow-sm);
}
.identity-switcher__label {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  flex: none;
  color: var(--text-3);
  font-size: 12.5px;
  font-weight: 600;
  white-space: nowrap;
}
.identity-switcher__label svg { color: var(--brand); }
.identity-switcher__options {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 8px;
  flex: 1;
  min-width: 0;
}
.identity {
  position: relative;
  display: flex;
  align-items: center;
  gap: 9px;
  padding: 7px 10px;
  border: 1px solid var(--border);
  border-radius: 11px;
  background: var(--surface-2);
  text-align: left;
  transition: border-color 0.16s ease, background-color 0.16s ease, box-shadow 0.16s ease;
  min-width: 0;
}
.identity:hover:not(:disabled) { border-color: var(--brand-200); background: #fff; }
.identity:disabled { opacity: 0.6; cursor: not-allowed; }
.identity.is-active {
  border-color: var(--brand-200);
  background: linear-gradient(180deg, #fff, #f8f8ff);
  box-shadow: 0 0 0 3px rgba(79, 70, 229, 0.08);
}
.identity__avatar {
  display: grid;
  place-items: center;
  flex: none;
  width: 30px;
  height: 30px;
  border-radius: 9px;
  background: linear-gradient(140deg, #eef2ff, #e0e7ff);
  border: 1px solid var(--brand-100);
  color: var(--brand-700);
  font-size: 13px;
  font-weight: 700;
}
.identity.is-active .identity__avatar { background: var(--brand); border-color: var(--brand); color: #fff; }
.identity__text { display: flex; flex-direction: column; min-width: 0; line-height: 1.4; }
.identity__name { display: flex; align-items: baseline; gap: 5px; font-size: 13px; font-weight: 650; color: var(--text); }
.identity__id { font-family: var(--font-mono); font-size: 9.5px; font-weight: 500; color: var(--text-4); }
.identity__role {
  font-size: 10.5px;
  color: var(--text-3);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}
.identity__check {
  position: absolute;
  top: 5px;
  right: 5px;
  display: grid;
  place-items: center;
  width: 15px;
  height: 15px;
  border-radius: 50%;
  background: var(--brand);
  color: #fff;
}

@media (max-width: 900px) {
  .identity-switcher { flex-direction: column; align-items: stretch; gap: 8px; padding: 10px; }
  .identity-switcher__label { padding-left: 2px; }
}
@media (max-width: 620px) {
  .identity-switcher__options { grid-template-columns: 1fr; }
  .identity { padding: 7px 10px; }
}
</style>
