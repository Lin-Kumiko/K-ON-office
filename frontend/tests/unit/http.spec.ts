import { afterEach, describe, expect, it, vi } from 'vitest'
import { ApiError, api, buildUrl, errorText, onAuthProblem, setToken } from '@/api/http'

function mockFetch(status: number, body: unknown) {
  return vi.fn(async () => new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } }))
}

afterEach(() => {
  vi.unstubAllGlobals()
  setToken(null)
})

describe('http client', () => {
  it('builds query strings and skips empty params', () => {
    expect(buildUrl('/api/x', { a: 1, b: '', c: null, d: undefined, e: false })).toBe('/api/x?a=1&e=false')
    expect(buildUrl('/api/x?y=1', { z: 'q w' })).toBe('/api/x?y=1&z=q+w')
  })

  it('sends the bearer token and parses JSON', async () => {
    const f = mockFetch(200, { ok: true })
    vi.stubGlobal('fetch', f)
    setToken('tok-123')
    expect(await api.get('/api/auth/me')).toEqual({ ok: true })
    const [, init] = f.mock.calls[0] as unknown as [string, RequestInit]
    expect((init.headers as Record<string, string>).Authorization).toBe('Bearer tok-123')
  })

  it('turns the unified error body into ApiError', async () => {
    vi.stubGlobal('fetch', mockFetch(409, { error: { code: 'LEAVE_BALANCE_INSUFFICIENT', message: '年假余额不足', details: null } }))
    const err = await api.post('/api/leave/requests', {}).catch((e) => e)
    expect(err).toBeInstanceOf(ApiError)
    expect(err.status).toBe(409)
    expect(err.code).toBe('LEAVE_BALANCE_INSUFFICIENT')
    expect(errorText(err)).toBe('年假余额不足')
  })

  it('summarises validation details and invokes the 401 handler', async () => {
    const onUnauthorized = vi.fn()
    onAuthProblem({ unauthorized: onUnauthorized })
    vi.stubGlobal('fetch', mockFetch(422, { error: { code: 'VALIDATION_ERROR', message: '请求参数校验失败',
      details: [{ loc: ['body', 'reason'], msg: 'Field required', type: 'missing' }] } }))
    const e1 = await api.post('/x').catch((e) => e)
    expect(errorText(e1)).toBe('请求参数校验失败：reason Field required')
    vi.stubGlobal('fetch', mockFetch(401, { error: { code: 'SESSION_EXPIRED', message: '未登录或登录已过期' } }))
    await api.get('/y').catch(() => null)
    expect(onUnauthorized).toHaveBeenCalledOnce()
  })

  it('reports network failures clearly', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => { throw new TypeError('fail') }))
    const e = await api.get('/z').catch((x) => x)
    expect(e.code).toBe('NETWORK_ERROR')
  })
})
