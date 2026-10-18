import { reactive } from 'vue'
import { ElMessage } from 'element-plus'
import { ApiError, api, errorText, type Params } from '@/api/http'

const needsLogin = (e: unknown) => e instanceof ApiError && e.code === 'LOGIN_REQUIRED'

export interface PageResult<T> {
  items: T[]
  total: number
  page: number
  page_size: number
}

/** Paged list state bound to a backend list endpoint; `params()` supplies filters on every load. */
export function usePaged<T = any>(url: string | (() => string), params: () => Params = () => ({}), pageSize = 10) {
  const state = reactive({
    items: [] as T[],
    total: 0,
    page: 1,
    pageSize,
    loading: false,
    error: '' as string,
  })

  async function load(page?: number) {
    if (page) state.page = page
    state.loading = true
    state.error = ''
    try {
      const u = typeof url === 'function' ? url() : url
      const res = await api.get<PageResult<T>>(u, { ...params(), page: state.page, page_size: state.pageSize })
      state.items = res.items as any
      state.total = res.total
    } catch (e) {
      state.error = errorText(e)
      state.items = []
      if (!needsLogin(e)) ElMessage.error(state.error)
    } finally {
      state.loading = false
    }
  }

  return { state, load }
}

/** Run an action with success / error feedback; returns true on success. */
export async function act(fn: () => Promise<unknown>, success?: string): Promise<boolean> {
  try {
    await fn()
    if (success) ElMessage.success(success)
    return true
  } catch (e) {
    if (!needsLogin(e)) ElMessage.error(errorText(e))
    return false
  }
}
