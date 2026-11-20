import { defineStore } from 'pinia'
import { getMe, getMenus, logoutApi, type Menu, type Profile } from '@/api'

export const useUserStore = defineStore('user', {
  state: () => ({
    token: localStorage.getItem('access_token') || '',
    profile: null as Profile | null,
    menus: [] as Menu[],
    loaded: false,
  }),
  getters: {
    permissions: (state) => state.profile?.permissions ?? [],
  },
  actions: {
    setToken(token: string) {
      this.token = token
      localStorage.setItem('access_token', token)
    },
    hasPerm(code: string): boolean {
      if (!this.profile) return false
      return this.profile.is_superuser || this.permissions.includes(code)
    },
    async fetchProfile() {
      const [profile, menus] = await Promise.all([getMe(), getMenus()])
      this.profile = profile
      this.menus = menus
      this.loaded = true
    },
    async logout() {
      try {
        await logoutApi()
      } catch {
        // 忽略网络异常，本地凭证照常清除
      }
      this.token = ''
      this.profile = null
      this.menus = []
      this.loaded = false
      localStorage.removeItem('access_token')
    },
  },
})
