import { nextTick } from 'vue'
import { defineStore } from 'pinia'
import { api } from '@/api/http'

type Theme = 'light' | 'dark'

function media(query: string): boolean {
  return typeof window !== 'undefined' && typeof window.matchMedia === 'function' && window.matchMedia(query).matches
}

// A saved choice wins; first-time visitors follow their system setting.
function readTheme(): Theme {
  try {
    const saved = localStorage.getItem('doe_theme')
    if (saved === 'light' || saved === 'dark') return saved
  } catch {
    /* storage unavailable */
  }
  return media('(prefers-color-scheme: dark)') ? 'dark' : 'light'
}

export const useApp = defineStore('app', {
  state: () => ({ theme: readTheme(), unread: 0, collapsed: false, palette: false }),
  actions: {
    applyTheme() {
      document.documentElement.classList.toggle('dark', this.theme === 'dark')
      document.querySelector('meta[name=theme-color]')?.setAttribute('content', this.theme === 'dark' ? '#0f1013' : '#f6f6f8')
    },
    /** Switches theme. When an origin point is given, the new theme spreads out from it as a circle. */
    toggleTheme(origin?: { x: number; y: number }) {
      const swap = () => {
        this.theme = this.theme === 'dark' ? 'light' : 'dark'
        try {
          localStorage.setItem('doe_theme', this.theme)
        } catch {
          /* storage unavailable */
        }
        this.applyTheme()
      }
      const doc = document as Document & { startViewTransition?: (cb: () => unknown) => unknown }
      if (!origin || typeof doc.startViewTransition !== 'function' || media('(prefers-reduced-motion: reduce)')) {
        swap()
        return
      }
      const root = document.documentElement
      const radius = Math.hypot(Math.max(origin.x, window.innerWidth - origin.x), Math.max(origin.y, window.innerHeight - origin.y))
      root.style.setProperty('--vt-x', `${origin.x}px`)
      root.style.setProperty('--vt-y', `${origin.y}px`)
      root.style.setProperty('--vt-r', `${radius}px`)
      doc.startViewTransition(async () => {
        swap()
        await nextTick()
      })
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
