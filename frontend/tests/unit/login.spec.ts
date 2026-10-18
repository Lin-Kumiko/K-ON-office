import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { flushPromises, mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { createRouter, createMemoryHistory } from 'vue-router'
import ElementPlus from 'element-plus'
import Login from '@/views/Login.vue'

function setup() {
  const pinia = createPinia()
  setActivePinia(pinia)
  const router = createRouter({ history: createMemoryHistory(), routes: [
    { path: '/login', component: Login }, { path: '/dashboard', component: { template: '<div>dash</div>' } },
    { path: '/profile', component: { template: '<div>profile</div>' } }] })
  return { pinia, router }
}

beforeEach(() => localStorage.clear())
afterEach(() => vi.unstubAllGlobals())

describe('Login view', () => {
  it('validates required fields before calling the API', async () => {
    const fetchMock = vi.fn()
    vi.stubGlobal('fetch', fetchMock)
    const { pinia, router } = setup()
    router.push('/login')
    await router.isReady()
    const w = mount(Login, { global: { plugins: [pinia, router, ElementPlus] } })
    await w.find('form').trigger('submit')
    await flushPromises()
    await new Promise((r) => setTimeout(r, 50))
    await flushPromises()
    expect(fetchMock).not.toHaveBeenCalled()
    expect(w.findAll('.el-form-item.is-error')).toHaveLength(2) // username + password marked invalid
  })

  it('shows the backend error message on failure', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => new Response(JSON.stringify({ error: { code: 'INVALID_CREDENTIALS', message: '用户名或密码错误' } }), { status: 401 })))
    const { pinia, router } = setup()
    router.push('/login')
    await router.isReady()
    const w = mount(Login, { global: { plugins: [pinia, router, ElementPlus] } })
    await w.find('input[placeholder="例如 yui"]').setValue('yui')
    await w.find('input[type="password"]').setValue('wrong-pass-1')
    await w.find('form').trigger('submit')
    await flushPromises()
    await new Promise((r) => setTimeout(r, 20))
    await flushPromises()
    expect(w.text()).toContain('用户名或密码错误')
  })

  it('stores the token and navigates on success', async () => {
    const me = { id: 3, username: 'yui', display_name: '平泽唯', email: null, must_change_password: false, roles: ['employee'],
      role_names: ['普通员工'], permissions: [], data_scope: 'self', menus: [], employee: null }
    vi.stubGlobal('fetch', vi.fn(async () => new Response(JSON.stringify({ token: 'abc', expires_at: '2026-10-19T22:00:00', user: me }), { status: 200 })))
    const { pinia, router } = setup()
    router.push('/login')
    await router.isReady()
    const w = mount(Login, { global: { plugins: [pinia, router, ElementPlus] } })
    await w.find('input[placeholder="例如 yui"]').setValue('yui')
    await w.find('input[type="password"]').setValue('right-pass-1')
    await w.find('form').trigger('submit')
    await flushPromises()
    await new Promise((r) => setTimeout(r, 20))
    await flushPromises()
    expect(localStorage.getItem('doe_token')).toBe('abc')
    expect(router.currentRoute.value.path).toBe('/dashboard')
  })
})
