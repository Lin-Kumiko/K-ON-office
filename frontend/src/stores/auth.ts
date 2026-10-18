import { defineStore } from 'pinia'
import { api, getToken, setToken } from '@/api/http'

export interface Me {
  id: number
  username: string
  display_name: string
  email: string | null
  must_change_password: boolean
  roles: string[]
  role_names: string[]
  permissions: string[]
  data_scope: string
  menus: { key: string; title: string; perm: string }[]
  employee: {
    id: number
    employee_no: string
    name: string
    department_id: number
    department_name: string | null
    position_name: string | null
    manager_id: number | null
    status: string
  } | null
}

export const useAuth = defineStore('auth', {
  state: () => ({ me: null as Me | null, token: getToken() as string | null }),
  getters: {
    loggedIn: (s) => !!s.token,
    isAdmin: (s) => !!s.me?.roles.includes('admin'),
  },
  actions: {
    can(perm: string): boolean {
      if (!this.me) return false
      return this.me.roles.includes('admin') || this.me.permissions.includes(perm)
    },
    async login(username: string, password: string) {
      const res = await api.post<{ token: string; user: Me }>('/api/auth/login', { username, password })
      this.token = res.token
      setToken(res.token)
      this.me = res.user
      return res.user
    },
    async fetchMe() {
      this.me = await api.get<Me>('/api/auth/me')
      return this.me
    },
    async logout(remote = true) {
      if (remote && this.token) {
        try {
          await api.post('/api/auth/logout')
        } catch {
          /* already invalid */
        }
      }
      this.token = null
      this.me = null
      setToken(null)
    },
  },
})
