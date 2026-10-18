import { describe, expect, it, beforeEach } from 'vitest'
import { mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import ElementPlus from 'element-plus'
import StatusTag from '@/components/StatusTag.vue'
import WorkflowGraph from '@/components/WorkflowGraph.vue'
import { useAuth } from '@/stores/auth'

beforeEach(() => setActivePinia(createPinia()))

describe('StatusTag', () => {
  it('renders the Chinese label with the right tag type', () => {
    const w = mount(StatusTag, { props: { status: 'approved' }, global: { plugins: [ElementPlus] } })
    expect(w.text()).toBe('已通过')
    expect(w.find('.el-tag--success').exists()).toBe(true)
  })
})

describe('WorkflowGraph', () => {
  const graph = {
    nodes: [
      { id: 'start', type: 'start', name: '开始', x: 60, y: 100 },
      { id: 'mgr', type: 'approval', name: '直属主管审批', x: 220, y: 100 },
      { id: 'end', type: 'end', name: '结束', x: 380, y: 100 },
    ],
    edges: [{ id: 'e1', source: 'start', target: 'mgr' }, { id: 'e2', source: 'mgr', target: 'end' }],
  }
  it('draws every node and edge and highlights node states', () => {
    const w = mount(WorkflowGraph, { props: { graph, states: { start: 'completed', mgr: 'active' } } })
    expect(w.findAll('g text.node-text').map((t) => t.text())).toEqual(['开始', '直属主管审批', '结束'])
    expect(w.findAll('path[marker-end]')).toHaveLength(2)
    expect(w.find('rect.node.active').exists()).toBe(true)
    expect(w.find('circle.node.completed').exists()).toBe(true)
  })
})

describe('auth store permission checks', () => {
  it('admin has every permission; others only granted ones', () => {
    const auth = useAuth()
    auth.me = { id: 1, username: 'mika', display_name: '佐伯三花', email: null, must_change_password: false, roles: ['employee'],
      role_names: ['普通员工'], permissions: ['leave:apply'], data_scope: 'self', menus: [], employee: null }
    expect(auth.can('leave:apply')).toBe(true)
    expect(auth.can('user:manage')).toBe(false)
    auth.me = { ...auth.me, roles: ['admin'], permissions: [] }
    expect(auth.can('user:manage')).toBe(true)
  })
})
