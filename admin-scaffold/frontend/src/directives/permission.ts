import type { App, Directive } from 'vue'
import { useUserStore } from '@/stores/user'

const permission: Directive<HTMLElement, string> = {
  mounted(el, binding) {
    const store = useUserStore()
    if (!store.hasPerm(binding.value)) {
      el.parentNode?.removeChild(el)
    }
  },
}

export function setupPermissionDirective(app: App) {
  app.directive('permission', permission)
}
