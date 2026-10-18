import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { flushPromises, mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { createRouter, createMemoryHistory } from 'vue-router'
import ElementPlus from 'element-plus'
import AuthPage from '@/views/AuthPage.vue'

async function setup(path = '/login') {
  const pinia = createPinia()
  setActivePinia(pinia)
  const router = createRouter({ history: createMemoryHistory(), routes: [
    { path: '/login', name: 'login', component: AuthPage }, { path: '/register', name: 'register', component: AuthPage },
    { path: '/dashboard', component: { template: '<div>dash</div>' } },
    { path: '/profile', component: { template: '<div>profile</div>' } }] })
  router.push(path)
  await router.isReady()
  const w = mount(AuthPage, { global: { plugins: [pinia, router, ElementPlus] } })
  return { w, router }
}

const settle = async () => {
  await flushPromises()
  await new Promise((r) => setTimeout(r, 50))
  await flushPromises()
}

const respond = (status: number, body: unknown) =>
  vi.fn(async () => new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } }))

beforeEach(() => localStorage.clear())
afterEach(() => vi.unstubAllGlobals())

describe('AuthPage', () => {
  it('has exactly two fields: username and password', async () => {
    const { w } = await setup('/register')
    expect(w.findAll('input').length).toBe(2)
    expect(w.find('[data-test=auth-submit]').text()).toBe('注册')
  })

  it('validates required fields before calling the API', async () => {
    const fetchMock = vi.fn()
    vi.stubGlobal('fetch', fetchMock)
    const { w } = await setup()
    await w.find('form').trigger('submit')
    await settle()
    expect(fetchMock).not.toHaveBeenCalled()
    expect(w.findAll('.el-form-item.is-error')).toHaveLength(2)
  })

  it('rejects a weak password on the register form without calling the API', async () => {
    const fetchMock = vi.fn()
    vi.stubGlobal('fetch', fetchMock)
    const { w } = await setup('/register')
    await w.find('input[data-test="auth-username"]').setValue('ui_fan')
    await w.find('input[data-test="auth-password"]').setValue('abc')
    await w.find('form').trigger('submit')
    await settle()
    expect(fetchMock).not.toHaveBeenCalled()
  })

  it('shows the backend error message on failed login', async () => {
    vi.stubGlobal('fetch', respond(401, { error: { code: 'INVALID_CREDENTIALS', message: '用户名或密码错误' } }))
    const { w } = await setup()
    await w.find('input[data-test="auth-username"]').setValue('yui')
    await w.find('input[data-test="auth-password"]').setValue('wrong-pass-1')
    await w.find('form').trigger('submit')
    await settle()
    expect(w.find('[data-test=auth-error]').text()).toBe('用户名或密码错误')
  })

  it('registers, then sends the user to the login form with the username filled in', async () => {
    const fetchMock = respond(201, { id: 20, username: 'ui_fan', message: '注册成功，请登录' })
    vi.stubGlobal('fetch', fetchMock)
    const { w, router } = await setup('/register')
    await w.find('input[data-test="auth-username"]').setValue('ui_fan')
    await w.find('input[data-test="auth-password"]').setValue('Cake2026x')
    await w.find('form').trigger('submit')
    await settle()
    expect((fetchMock.mock.calls[0] as unknown as [string])[0]).toBe('/api/auth/register')
    expect(router.currentRoute.value.name).toBe('login')
    expect(router.currentRoute.value.query.username).toBe('ui_fan')
    expect(localStorage.getItem('doe_token')).toBeNull() // registering does not log in
  })

  it('stores the token and navigates on successful login', async () => {
    const me = { id: 3, username: 'yui', display_name: '平泽唯', email: null, must_change_password: false, roles: ['employee'],
      role_names: ['普通员工'], permissions: [], data_scope: 'self', menus: [], employee: null }
    vi.stubGlobal('fetch', respond(200, { token: 'abc', expires_at: '2026-10-19T22:00:00', user: me }))
    const { w, router } = await setup()
    await w.find('input[data-test="auth-username"]').setValue('yui')
    await w.find('input[data-test="auth-password"]').setValue('right-pass-1')
    await w.find('form').trigger('submit')
    await settle()
    expect(localStorage.getItem('doe_token')).toBe('abc')
    expect(router.currentRoute.value.path).toBe('/dashboard')
  })
})
