// Thin fetch wrapper: token handling, query building and a uniform ApiError.
export class ApiError extends Error {
  status: number
  code: string
  details: unknown
  constructor(status: number, code: string, message: string, details?: unknown) {
    super(message)
    this.status = status
    this.code = code
    this.details = details
  }
}

const TOKEN_KEY = 'doe_token'

function storage(): Storage | null {
  try {
    return window.localStorage
  } catch {
    return null
  }
}

export function getToken(): string | null {
  return storage()?.getItem(TOKEN_KEY) ?? null
}

export function setToken(token: string | null) {
  const s = storage()
  if (!s) return
  if (token) s.setItem(TOKEN_KEY, token)
  else s.removeItem(TOKEN_KEY)
}

type Handler = (err: ApiError) => void
const handlers: { unauthorized?: Handler; passwordChange?: Handler } = {}
export function onAuthProblem(h: typeof handlers) {
  Object.assign(handlers, h)
}

export type Params = Record<string, string | number | boolean | null | undefined>

export function buildUrl(url: string, params?: Params): string {
  if (!params) return url
  const q = new URLSearchParams()
  for (const [k, v] of Object.entries(params)) {
    if (v === undefined || v === null || v === '') continue
    q.append(k, String(v))
  }
  const s = q.toString()
  return s ? `${url}${url.includes('?') ? '&' : '?'}${s}` : url
}

interface Options {
  params?: Params
  body?: unknown
  headers?: Record<string, string>
  blob?: boolean
}

export async function request<T = any>(method: string, url: string, opts: Options = {}): Promise<T> {
  const headers: Record<string, string> = { ...(opts.headers || {}) }
  const token = getToken()
  if (token) headers.Authorization = `Bearer ${token}`
  let body: BodyInit | undefined
  if (opts.body instanceof FormData) body = opts.body
  else if (opts.body !== undefined) {
    headers['Content-Type'] = 'application/json'
    body = JSON.stringify(opts.body)
  }
  let resp: Response
  try {
    resp = await fetch(buildUrl(url, opts.params), { method, headers, body })
  } catch {
    throw new ApiError(0, 'NETWORK_ERROR', '无法连接服务器，请检查后端是否启动')
  }
  if (resp.ok) {
    if (opts.blob) return (await resp.blob()) as T
    if (resp.status === 204) return undefined as T
    return (await resp.json()) as T
  }
  let code = 'HTTP_ERROR'
  let message = `请求失败（${resp.status}）`
  let details: unknown
  try {
    const data = await resp.json()
    if (data?.error) {
      code = data.error.code
      message = data.error.message
      details = data.error.details
    }
  } catch {
    /* non-JSON error body */
  }
  const err = new ApiError(resp.status, code, message, details)
  if (resp.status === 401 && handlers.unauthorized) handlers.unauthorized(err)
  if (resp.status === 403 && code === 'PASSWORD_CHANGE_REQUIRED' && handlers.passwordChange) handlers.passwordChange(err)
  throw err
}

export const api = {
  get: <T = any>(url: string, params?: Params) => request<T>('GET', url, { params }),
  post: <T = any>(url: string, body?: unknown, params?: Params, headers?: Record<string, string>) =>
    request<T>('POST', url, { body, params, headers }),
  put: <T = any>(url: string, body?: unknown) => request<T>('PUT', url, { body }),
  del: <T = any>(url: string) => request<T>('DELETE', url),
  upload: <T = any>(url: string, form: FormData) => request<T>('POST', url, { body: form }),
  blob: (url: string, params?: Params) => request<Blob>('GET', url, { params, blob: true }),
}

export async function downloadFile(url: string, filename: string, params?: Params) {
  const blob = await api.blob(url, params)
  const href = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = href
  a.download = filename
  a.click()
  setTimeout(() => URL.revokeObjectURL(href), 1000)
}

/** Format validation details into a short readable sentence. */
export function errorText(e: unknown): string {
  if (e instanceof ApiError) {
    if (e.code === 'VALIDATION_ERROR' && Array.isArray(e.details) && e.details.length) {
      const d = e.details[0] as { loc: string[]; msg: string }
      return `${e.message}：${d.loc.filter((x) => x !== 'body').join('.')} ${d.msg}`
    }
    if (e.code === 'INVALID_GRAPH' && Array.isArray(e.details)) return `${e.message}：${(e.details as string[]).join('；')}`
    return e.message
  }
  return e instanceof Error ? e.message : String(e)
}
