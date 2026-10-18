// Cached option lists for selectors (reloaded on page refresh or after invalidate()).
import { api } from '@/api/http'

export interface PersonOpt { id: number; name: string; employee_no: string; department_id: number; user_id: number | null; status: string }
export interface DeptOpt { id: number; name: string; code: string; parent_id: number | null; manager_employee_id: number | null; manager_name: string | null; status: string; member_count: number }
export interface PosOpt { id: number; name: string; code: string; level: number }

const cache = new Map<string, Promise<any>>()

function cached<T>(key: string, loader: () => Promise<T>): Promise<T> {
  if (!cache.has(key)) {
    const p = loader().catch((e) => {
      cache.delete(key)
      throw e
    })
    cache.set(key, p)
  }
  return cache.get(key) as Promise<T>
}

export const loadPeople = () => cached<PersonOpt[]>('people', () => api.get('/api/employees/options'))
export const loadDepartments = () => cached<DeptOpt[]>('depts', () => api.get('/api/departments'))
export const loadPositions = () => cached<PosOpt[]>('positions', () => api.get('/api/positions'))

export function invalidate(...keys: string[]) {
  if (!keys.length) cache.clear()
  for (const k of keys) cache.delete(k)
}
