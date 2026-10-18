import { defineStore } from 'pinia'
import { api } from '@/api/http'

function readTheme(): 'light' | 'dark' {
  try {
    return (localStorage.getItem('doe_theme') as 'light' | 'dark') || 'light'
  } catch {
    return 'light'
  }
}

export const useApp = defineStore('app', {
  state: () => ({ theme: readTheme(), unread: 0, collapsed: false }),
  actions: {
    applyTheme() {
      document.documentElement.classList.toggle('dark', this.theme === 'dark')
    },
    toggleTheme() {
      this.theme = this.theme === 'dark' ? 'light' : 'dark'
      try {
        localStorage.setItem('doe_theme', this.theme)
      } catch {
        /* storage unavailable */
      }
      this.applyTheme()
    },
    async refreshUnread() {
      try {
        this.unread = (await api.get<{ count: number }>('/api/notifications/unread-count')).count
      } catch {
        /* ignore polling errors */
      }
    },
  },
})
