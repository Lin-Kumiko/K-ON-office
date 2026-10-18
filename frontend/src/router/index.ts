import { createRouter, createWebHistory, type RouteRecordRaw } from 'vue-router'
import { useAuth } from '@/stores/auth'
import { bindLoginPrompt, promptLogin } from '@/utils/loginPrompt'

export const appRoutes: RouteRecordRaw[] = [
  { path: '/dashboard', name: 'dashboard', component: () => import('@/views/Home.vue'), meta: { visitor: true, title: '工作台', perm: 'dashboard:view', icon: 'House' } },
  { path: '/approvals', name: 'approvals', component: () => import('@/views/Approvals.vue'), meta: { title: '审批中心', perm: 'dashboard:view', icon: 'Stamp' } },
  { path: '/org', name: 'org', component: () => import('@/views/Org.vue'), meta: { visitor: true, title: '组织架构', perm: 'org:read', icon: 'OfficeBuilding' } },
  { path: '/employees', name: 'employees', component: () => import('@/views/Employees.vue'), meta: { title: '员工档案', perm: 'employee:read', icon: 'User' } },
  { path: '/recruitment', name: 'recruitment', component: () => import('@/views/Recruitment.vue'), meta: { title: '招聘入职', perm: 'dashboard:view', icon: 'Promotion' } },
  { path: '/hr-changes', name: 'hr-changes', component: () => import('@/views/HrChanges.vue'), meta: { title: '转正调岗', perm: 'regularization:apply', icon: 'Switch' } },
  { path: '/attendance', name: 'attendance', component: () => import('@/views/Attendance.vue'), meta: { title: '考勤管理', perm: 'attendance:read', icon: 'Clock' } },
  { path: '/leave', name: 'leave', component: () => import('@/views/Leave.vue'), meta: { title: '请假与假期', perm: 'leave:apply', icon: 'Calendar' } },
  { path: '/travel', name: 'travel', component: () => import('@/views/Travel.vue'), meta: { title: '出差管理', perm: 'travel:apply', icon: 'Van' } },
  { path: '/expense', name: 'expense', component: () => import('@/views/Expense.vue'), meta: { title: '费用报销', perm: 'expense:apply', icon: 'Money' } },
  { path: '/meeting', name: 'meeting', component: () => import('@/views/Meeting.vue'), meta: { visitor: true, title: '会议室', perm: 'meeting:book', icon: 'Microphone' } },
  { path: '/announcements', name: 'announcements', component: () => import('@/views/Announcements.vue'), meta: { visitor: true, title: '公告通知', perm: 'announcement:read', icon: 'Bell' } },
  { path: '/documents', name: 'documents', component: () => import('@/views/Documents.vue'), meta: { visitor: true, title: '文档中心', perm: 'document:read', icon: 'Folder' } },
  { path: '/performance', name: 'performance', component: () => import('@/views/Performance.vue'), meta: { title: '绩效管理', perm: 'performance:self', icon: 'TrendCharts' } },
  { path: '/payroll', name: 'payroll', component: () => import('@/views/Payroll.vue'), meta: { title: '模拟薪资', perm: 'payroll:self', icon: 'Wallet' } },
  { path: '/workflow', name: 'workflow', component: () => import('@/views/WorkflowDesigner.vue'), meta: { adminOnly: true, title: '流程设计', perm: 'workflow:manage', icon: 'Share' } },
  { path: '/reports', name: 'reports', component: () => import('@/views/Reports.vue'), meta: { title: '统计报表', perm: 'report:view', icon: 'PieChart' } },
  { path: '/system', name: 'system', component: () => import('@/views/System.vue'), meta: { adminOnly: true, title: '系统与权限', perm: ['user:manage', 'role:manage', 'audit:read', 'settings:manage'], icon: 'Setting' } },
  { path: '/profile', name: 'profile', component: () => import('@/views/Profile.vue'), meta: { title: '个人中心', hidden: true } },
  { path: '/notifications', name: 'notifications', component: () => import('@/views/Notifications.vue'), meta: { title: '通知历史', hidden: true } },
  { path: '/403', name: 'forbidden', component: () => import('@/views/Forbidden.vue'), meta: { title: '无权限', hidden: true } },
]

const routes: RouteRecordRaw[] = [
  { path: '/login', name: 'login', component: () => import('@/views/AuthPage.vue'), meta: { public: true, title: '登录' } },
  { path: '/register', name: 'register', component: () => import('@/views/AuthPage.vue'), meta: { public: true, title: '注册' } },
  { path: '/', component: () => import('@/layouts/MainLayout.vue'), redirect: '/dashboard', children: appRoutes },
  { path: '/:pathMatch(.*)*', redirect: '/dashboard' },
]

export const router = createRouter({ history: createWebHistory(), routes })
bindLoginPrompt(router)

router.beforeEach(async (to, from) => {
  const auth = useAuth()
  if (to.meta.public) return auth.loggedIn && to.name === 'login' && !to.query.redirect ? '/dashboard' : true
  if (!auth.loggedIn) {
    // anonymous visitors may browse the public pages; anything else asks them to log in first
    if (to.meta.visitor) return true
    if (from.matched.length) {
      promptLogin(to.fullPath)
      return false
    }
    return { name: 'login', query: { redirect: to.fullPath } }
  }
  if (!auth.me) {
    try {
      await auth.fetchMe()
    } catch {
      return { name: 'login' }
    }
  }
  if (auth.me?.must_change_password && to.name !== 'profile') return { name: 'profile', query: { force: '1' } }
  const perm = to.meta.perm as string | string[] | undefined
  if (perm && !auth.canAny(perm)) {
    // employees without attendance:read still have their own attendance view through punch permission
    if (!(to.name === 'attendance' && auth.can('attendance:punch'))) return { name: 'forbidden', query: { need: Array.isArray(perm) ? perm.join(' / ') : perm } }
  }
  return true
})

// The browser tab always shows the company name, whatever page is open.
router.afterEach(() => {
  document.title = '放学后茶会'
})
