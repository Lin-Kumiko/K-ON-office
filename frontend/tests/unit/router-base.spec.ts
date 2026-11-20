import { afterEach, describe, expect, it, vi } from 'vitest'

// The router module only needs these for its guards, which are not exercised here.
vi.mock('@/stores/auth', () => ({ useAuth: vi.fn() }))
vi.mock('@/utils/loginPrompt', () => ({ bindLoginPrompt: vi.fn(), promptLogin: vi.fn() }))

afterEach(() => {
  vi.unstubAllEnvs()
  vi.resetModules()
})

describe('router base', () => {
  it('builds links at the site root by default', async () => {
    const { router } = await import('@/router')
    expect(router.resolve('/approvals').href).toBe('/approvals')
  })

  it('builds links under the app base when served from a sub-path', async () => {
    vi.stubEnv('BASE_URL', '/k-on/')
    vi.resetModules()
    const { router } = await import('@/router')
    expect(router.resolve('/approvals').href).toBe('/k-on/approvals')
    expect(router.resolve({ name: 'login' }).href).toBe('/k-on/login')
  })
})
