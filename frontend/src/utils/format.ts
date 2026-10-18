// Display helpers shared by all views (labels, dates, money, durations).
export const STATUS: Record<string, { text: string; type: '' | 'success' | 'warning' | 'danger' | 'info' | 'primary' }> = {
  draft: { text: '草稿', type: 'info' },
  pending: { text: '审批中', type: 'warning' },
  running: { text: '进行中', type: 'warning' },
  approved: { text: '已通过', type: 'success' },
  rejected: { text: '已驳回', type: 'danger' },
  withdrawn: { text: '已撤回', type: 'info' },
  cancelled: { text: '已取消', type: 'info' },
  transferred: { text: '已转交', type: 'info' },
  changed: { text: '已变更', type: 'info' },
  paid: { text: '已确认付款', type: 'success' },
  archived: { text: '已归档', type: 'primary' },
  published: { text: '已发布', type: 'success' },
  active: { text: '启用', type: 'success' },
  disabled: { text: '停用', type: 'info' },
  probation: { text: '试用期', type: 'warning' },
  regular: { text: '正式', type: 'success' },
  resigned: { text: '离职', type: 'info' },
  open: { text: '招聘中', type: 'success' },
  closed: { text: '已关闭', type: 'info' },
  new: { text: '新候选人', type: 'info' },
  interviewing: { text: '面试中', type: 'warning' },
  offer_pending: { text: '录用审批中', type: 'warning' },
  offered: { text: '已录用', type: 'success' },
  onboarding: { text: '入职办理中', type: 'warning' },
  hired: { text: '已入职', type: 'success' },
  todo: { text: '待办', type: 'warning' },
  done: { text: '已完成', type: 'success' },
  self_pending: { text: '待自评', type: 'warning' },
  manager_pending: { text: '待主管评价', type: 'warning' },
  confirm_pending: { text: '待 HR 确认', type: 'warning' },
  confirmed: { text: '已确认', type: 'success' },
  calculated: { text: '已计算', type: 'primary' },
  // attendance
  normal: { text: '正常', type: 'success' },
  late: { text: '迟到', type: 'warning' },
  early: { text: '早退', type: 'warning' },
  late_early: { text: '迟到+早退', type: 'danger' },
  missing: { text: '缺卡', type: 'danger' },
  absent: { text: '缺勤', type: 'danger' },
  leave: { text: '请假', type: 'primary' },
  travel: { text: '出差', type: 'primary' },
  rest: { text: '休息日', type: 'info' },
  holiday: { text: '节假日', type: 'info' },
  upcoming: { text: '未开始', type: 'info' },
}

export function statusText(s: string | null | undefined): string {
  return s ? STATUS[s]?.text ?? s : '-'
}

export function statusType(s: string | null | undefined) {
  return (s && STATUS[s]?.type) || 'info'
}

export const BUSINESS: Record<string, string> = {
  leave: '请假', expense: '费用报销', travel: '出差', onboarding: '员工入职', regularization: '员工转正',
  transfer: '调岗', offer: '录用审批', meeting: '会议室预约', attendance_correction: '补卡', overtime: '加班',
}

export const HISTORY_ACTION: Record<string, string> = {
  start: '发起', task_created: '生成任务', approve: '通过', reject: '驳回', transfer: '转交', reassign: '改派',
  withdrawn: '撤回', cancelled: '取消', rejected: '流程驳回', end: '流程结束（通过）', condition: '条件判断',
  fork: '并行分支', join_arrive: '汇聚到达', cc: '抄送', node_completed: '节点完成', escalate: '审批人上溯',
  fallback: '兜底给管理员', auto_pass: '自动通过',
}

export function pad(n: number) {
  return n < 10 ? `0${n}` : `${n}`
}

export function fmtDateTime(v: string | null | undefined): string {
  if (!v) return '-'
  return v.replace('T', ' ').slice(0, 16)
}

export function fmtDate(v: string | null | undefined): string {
  return v ? v.slice(0, 10) : '-'
}

export function fmtTime(v: string | null | undefined): string {
  return v ? v.replace('T', ' ').slice(11, 16) : '--:--'
}

export function hoursToDays(h: number): string {
  const d = h / 8
  return Number.isInteger(d) ? `${d} 天` : `${d.toFixed(1)} 天`
}

export function money(v: string | number | null | undefined): string {
  if (v === null || v === undefined || v === '') return '-'
  const n = typeof v === 'number' ? v : Number(v)
  return `¥${n.toLocaleString('zh-CN', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`
}

export function toLocalInput(d: Date): string {
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}T${pad(d.getHours())}:${pad(d.getMinutes())}:00`
}

export function today(): string {
  const d = new Date()
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`
}

export function thisMonth(): string {
  return today().slice(0, 7)
}

/** Sum a list of 2-decimal money strings exactly (in cents). */
export function sumMoney(values: (string | number)[]): string {
  let cents = 0
  for (const v of values) {
    const s = String(v ?? '').trim()
    if (!/^\d+(\.\d{1,2})?$/.test(s)) continue
    const [i, f = ''] = s.split('.')
    cents += Number(i) * 100 + Number((f + '00').slice(0, 2))
  }
  return `${Math.floor(cents / 100)}.${pad(cents % 100)}`
}
