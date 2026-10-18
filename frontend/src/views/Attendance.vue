<template>
  <div class="page">
    <div class="page-head">
      <div><h2>考勤管理</h2><div class="sub">迟到/早退/缺卡/缺勤由后端按规则计算；跨天班次按打卡窗口归属工作日</div></div>
    </div>
    <div class="grid cols-3 mb">
      <div class="card punch">
        <div class="clock mono">{{ clock }}</div>
        <el-button type="primary" size="large" round :loading="punching" data-test="punch-now" @click="punch()">立即打卡</el-button>
        <div class="sim">
          <span class="dt-wrap" data-test="sim-time"><el-date-picker v-model="simTime" type="datetime" value-format="YYYY-MM-DDTHH:mm:ss" placeholder="模拟打卡时间"
                          size="small" /></span>
          <el-button size="small" :disabled="!simTime" data-test="punch-sim" @click="punch(simTime)">模拟打卡</el-button>
        </div>
        <div v-if="lastPunch" class="muted small" data-test="punch-result">
          {{ lastPunch.duplicate ? '重复打卡已忽略' : '打卡成功' }}：{{ fmtDateTime(lastPunch.punched_at) }}（归属 {{ lastPunch.work_date }}，{{ statusText(lastPunch.record?.status) }}）
        </div>
      </div>
      <div class="card">
        <b>{{ month }} 我的统计</b>
        <div v-if="mine" class="stats">
          <span>应出勤 <b>{{ mine.workdays }}</b> 天</span><span>正常 <b>{{ mine.normal }}</b></span>
          <span>迟到 <b class="warn">{{ mine.late }}</b></span><span>早退 <b class="warn">{{ mine.early }}</b></span>
          <span>缺卡 <b class="neg">{{ mine.missing }}</b></span><span>缺勤 <b class="neg">{{ mine.absent }}</b></span>
          <span>请假 <b>{{ hoursToDays(mine.leave_hours) }}</b></span><span>出差 <b>{{ mine.travel_days }}</b> 天</span>
          <span>加班 <b>{{ mine.overtime_hours }}</b> 小时</span>
        </div>
        <el-empty v-else :image-size="50" description="暂无统计" />
      </div>
      <div class="card">
        <b>当前规则</b>
        <div v-for="r in rules.filter((x: any) => x.is_default)" :key="r.id" class="muted rule">
          {{ r.name }}：{{ r.work_start }}-{{ r.work_end }}，午休 {{ r.break_start }}-{{ r.break_end }}，迟到宽限 {{ r.late_grace_minutes }} 分钟
        </div>
      </div>
    </div>
    <div class="card">
      <el-tabs v-model="tab" @tab-change="onTab">
        <el-tab-pane label="我的考勤" name="records" />
        <el-tab-pane label="补卡申请" name="corrections" />
        <el-tab-pane label="加班申请" name="overtime" />
        <el-tab-pane v-if="auth.can('employee:read') || auth.can('attendance:manage')" label="月度统计" name="monthly" />
        <el-tab-pane v-if="auth.can('attendance:manage')" label="考勤规则" name="rules" />
      </el-tabs>

      <template v-if="tab === 'records'">
        <div class="toolbar">
          <el-date-picker v-model="month" type="month" value-format="YYYY-MM" :clearable="false" @change="loadRecords" />
        </div>
        <el-table :data="records" border v-loading="loadingRecords" empty-text="本月暂无考勤记录" data-test="records-table">
          <el-table-column prop="work_date" label="日期" width="120" />
          <el-table-column label="状态" width="110"><template #default="{ row }"><StatusTag :status="row.status" /></template></el-table-column>
          <el-table-column label="应到/应退" width="140"><template #default="{ row }">{{ fmtTime(row.expected_start) }} / {{ fmtTime(row.expected_end) }}</template></el-table-column>
          <el-table-column label="上班打卡" width="100"><template #default="{ row }">{{ fmtTime(row.check_in_at) }}</template></el-table-column>
          <el-table-column label="下班打卡" width="100"><template #default="{ row }">{{ fmtTime(row.check_out_at) }}</template></el-table-column>
          <el-table-column label="迟到(分)" width="90" prop="late_minutes" />
          <el-table-column label="早退(分)" width="90" prop="early_minutes" />
          <el-table-column label="请假" width="80"><template #default="{ row }">{{ row.leave_hours ? row.leave_hours + 'h' : '-' }}</template></el-table-column>
          <el-table-column label="操作" min-width="100">
            <template #default="{ row }">
              <el-button v-if="['missing', 'absent', 'late', 'early', 'late_early'].includes(row.status)" link type="primary"
                         @click="openCorrection(row)">补卡</el-button>
            </template>
          </el-table-column>
        </el-table>
      </template>

      <template v-else-if="tab === 'corrections'">
        <div class="toolbar"><el-button type="primary" @click="openCorrection()">新建补卡</el-button></div>
        <el-table :data="corr.state.items" v-loading="corr.state.loading" border empty-text="暂无补卡申请">
          <el-table-column prop="work_date" label="日期" width="120" />
          <el-table-column label="类型" width="80"><template #default="{ row }">{{ row.kind === 'in' ? '上班' : '下班' }}</template></el-table-column>
          <el-table-column label="补卡时间" width="160"><template #default="{ row }">{{ fmtDateTime(row.corrected_time) }}</template></el-table-column>
          <el-table-column prop="reason" label="原因" min-width="160" />
          <el-table-column label="状态" width="90"><template #default="{ row }"><StatusTag :status="row.status" /></template></el-table-column>
          <el-table-column label="操作" width="160">
            <template #default="{ row }">
              <el-button v-if="row.status === 'pending'" link @click="withdrawCorr(row)">撤回</el-button>
              <el-button v-if="row.instance_id" link @click="openFlow(row.instance_id)">进度</el-button>
            </template>
          </el-table-column>
        </el-table>
        <div class="pager"><el-pagination layout="total, prev, pager, next" :total="corr.state.total" :page-size="corr.state.pageSize" @current-change="(p: number) => corr.load(p)" /></div>
      </template>

      <template v-else-if="tab === 'overtime'">
        <div class="toolbar"><el-button type="primary" @click="otOpen = true">新建加班</el-button></div>
        <el-table :data="ot.state.items" v-loading="ot.state.loading" border empty-text="暂无加班申请">
          <el-table-column label="时间" min-width="240"><template #default="{ row }">{{ fmtDateTime(row.start_at) }} ~ {{ fmtTime(row.end_at) }}</template></el-table-column>
          <el-table-column label="时长" width="80"><template #default="{ row }">{{ row.hours }}h</template></el-table-column>
          <el-table-column label="补偿" width="90"><template #default="{ row }">{{ row.compensation === 'leave' ? '转调休' : '加班费' }}</template></el-table-column>
          <el-table-column prop="reason" label="原因" min-width="160" />
          <el-table-column label="状态" width="90"><template #default="{ row }"><StatusTag :status="row.status" /></template></el-table-column>
          <el-table-column label="操作" width="160">
            <template #default="{ row }">
              <el-button v-if="row.status === 'pending'" link @click="withdrawOt(row)">撤回</el-button>
              <el-button v-if="row.instance_id" link @click="openFlow(row.instance_id)">进度</el-button>
            </template>
          </el-table-column>
        </el-table>
        <div class="pager"><el-pagination layout="total, prev, pager, next" :total="ot.state.total" :page-size="ot.state.pageSize" @current-change="(p: number) => ot.load(p)" /></div>
      </template>

      <template v-else-if="tab === 'monthly'">
        <div class="toolbar">
          <el-date-picker v-model="month" type="month" value-format="YYYY-MM" :clearable="false" @change="loadMonthly" />
          <DeptSelect v-model="dept" style="width: 180px" @update:model-value="loadMonthly" />
          <el-button v-if="auth.can('attendance:manage')" @click="rebuild">重算本月考勤</el-button>
        </div>
        <el-table :data="monthly" border v-loading="loadingMonthly" empty-text="暂无数据">
          <el-table-column prop="employee_no" label="工号" width="100" />
          <el-table-column prop="name" label="姓名" width="100" />
          <el-table-column prop="workdays" label="应出勤" width="80" />
          <el-table-column prop="normal" label="正常" width="70" />
          <el-table-column prop="late" label="迟到" width="70" />
          <el-table-column prop="early" label="早退" width="70" />
          <el-table-column prop="missing" label="缺卡" width="70" />
          <el-table-column prop="absent" label="缺勤" width="70" />
          <el-table-column label="请假" width="80"><template #default="{ row }">{{ hoursToDays(row.leave_hours) }}</template></el-table-column>
          <el-table-column prop="travel_days" label="出差" width="70" />
          <el-table-column prop="overtime_hours" label="加班(h)" width="80" />
          <el-table-column prop="late_minutes" label="迟到分钟" width="90" />
        </el-table>
      </template>

      <template v-else-if="tab === 'rules'">
        <div class="toolbar"><el-button type="primary" @click="openRule()">新增规则</el-button></div>
        <el-table :data="rules" border>
          <el-table-column prop="name" label="名称" min-width="180" />
          <el-table-column label="班次" width="160"><template #default="{ row }">{{ row.work_start }}-{{ row.work_end }}{{ row.cross_day ? '（次日）' : '' }}</template></el-table-column>
          <el-table-column label="休息" width="120"><template #default="{ row }">{{ row.break_start || '-' }}-{{ row.break_end || '-' }}</template></el-table-column>
          <el-table-column label="宽限(迟/早)" width="110"><template #default="{ row }">{{ row.late_grace_minutes }}/{{ row.early_grace_minutes }}</template></el-table-column>
          <el-table-column label="打卡窗口(前/后)" width="130"><template #default="{ row }">{{ row.window_before_minutes }}/{{ row.window_after_minutes }}</template></el-table-column>
          <el-table-column label="默认" width="70"><template #default="{ row }">{{ row.is_default ? '是' : '' }}</template></el-table-column>
          <el-table-column width="80"><template #default="{ row }"><el-button link type="primary" @click="openRule(row)">编辑</el-button></template></el-table-column>
        </el-table>
      </template>
    </div>

    <el-dialog v-model="corrOpen" title="补卡申请" width="460px">
      <el-form :model="corrForm" label-width="80px">
        <el-form-item label="工作日" required><el-date-picker v-model="corrForm.work_date" type="date" value-format="YYYY-MM-DD" /></el-form-item>
        <el-form-item label="类型"><el-radio-group v-model="corrForm.kind"><el-radio-button value="in">上班</el-radio-button><el-radio-button value="out">下班</el-radio-button></el-radio-group></el-form-item>
        <el-form-item label="补卡时间" required><el-date-picker v-model="corrForm.corrected_time" type="datetime" value-format="YYYY-MM-DDTHH:mm:ss" /></el-form-item>
        <el-form-item label="原因" required><el-input v-model="corrForm.reason" maxlength="255" /></el-form-item>
      </el-form>
      <template #footer><el-button @click="corrOpen = false">取消</el-button><el-button type="primary" @click="saveCorrection">提交审批</el-button></template>
    </el-dialog>
    <el-dialog v-model="otOpen" title="加班申请" width="460px">
      <el-form :model="otForm" label-width="80px">
        <el-form-item label="开始" required><el-date-picker v-model="otForm.start_at" type="datetime" value-format="YYYY-MM-DDTHH:mm:ss" /></el-form-item>
        <el-form-item label="结束" required><el-date-picker v-model="otForm.end_at" type="datetime" value-format="YYYY-MM-DDTHH:mm:ss" /></el-form-item>
        <el-form-item label="补偿"><el-radio-group v-model="otForm.compensation"><el-radio-button value="leave">转调休</el-radio-button><el-radio-button value="pay">加班费</el-radio-button></el-radio-group></el-form-item>
        <el-form-item label="原因" required><el-input v-model="otForm.reason" maxlength="255" /></el-form-item>
      </el-form>
      <template #footer><el-button @click="otOpen = false">取消</el-button><el-button type="primary" @click="saveOt">提交审批</el-button></template>
    </el-dialog>
    <el-dialog v-model="ruleOpen" title="考勤规则" width="520px">
      <el-form :model="ruleForm" label-width="110px">
        <el-form-item label="名称" required><el-input v-model="ruleForm.name" /></el-form-item>
        <el-form-item label="上/下班"><el-input v-model="ruleForm.work_start" style="width: 90px" /> - <el-input v-model="ruleForm.work_end" style="width: 90px" /><el-checkbox v-model="ruleForm.cross_day" class="ml">跨天</el-checkbox></el-form-item>
        <el-form-item label="休息"><el-input v-model="ruleForm.break_start" style="width: 90px" /> - <el-input v-model="ruleForm.break_end" style="width: 90px" /></el-form-item>
        <el-form-item label="迟到/早退宽限"><el-input-number v-model="ruleForm.late_grace_minutes" :min="0" :max="120" /> <el-input-number v-model="ruleForm.early_grace_minutes" :min="0" :max="120" class="ml" /></el-form-item>
        <el-form-item label="窗口前/后(分)"><el-input-number v-model="ruleForm.window_before_minutes" :min="0" :max="720" /> <el-input-number v-model="ruleForm.window_after_minutes" :min="0" :max="720" class="ml" /></el-form-item>
        <el-form-item label="默认规则"><el-switch v-model="ruleForm.is_default" /></el-form-item>
      </el-form>
      <template #footer><el-button @click="ruleOpen = false">取消</el-button><el-button type="primary" @click="saveRule">保存</el-button></template>
    </el-dialog>
    <InstanceDrawer v-model="drawer" :instance-id="current" @changed="onTab" />
  </div>
</template>

<script setup lang="ts">
import { onMounted, onUnmounted, reactive, ref } from 'vue'
import { api, errorText } from '@/api/http'
import { useAuth } from '@/stores/auth'
import { act, usePaged } from '@/utils/usePaged'
import { fmtDateTime, fmtTime, hoursToDays, pad, statusText, thisMonth } from '@/utils/format'
import { ElMessage } from 'element-plus'
import StatusTag from '@/components/StatusTag.vue'
import DeptSelect from '@/components/DeptSelect.vue'
import InstanceDrawer from '@/components/InstanceDrawer.vue'

const auth = useAuth()
const tab = ref('records')
const month = ref(thisMonth())
const clock = ref('')
const simTime = ref('')
const punching = ref(false)
const lastPunch = ref<any>(null)
const records = ref<any[]>([])
const loadingRecords = ref(false)
const monthly = ref<any[]>([])
const loadingMonthly = ref(false)
const mine = ref<any>(null)
const rules = ref<any[]>([])
const dept = ref<number | undefined>()
const drawer = ref(false)
const current = ref<number | null>(null)
const corr = usePaged('/api/attendance/corrections')
const ot = usePaged('/api/attendance/overtime')
const corrOpen = ref(false)
const corrForm = reactive({ work_date: '', kind: 'out', corrected_time: '', reason: '' })
const otOpen = ref(false)
const otForm = reactive({ start_at: '', end_at: '', compensation: 'leave', reason: '' })
const ruleOpen = ref(false)
const ruleForm = reactive<any>({})
let timer: number | undefined

function tick() {
  const d = new Date()
  clock.value = `${pad(d.getHours())}:${pad(d.getMinutes())}:${pad(d.getSeconds())}`
}

function monthRange() {
  const [y, m] = month.value.split('-').map(Number)
  const last = new Date(y, m, 0).getDate()
  return { start: `${month.value}-01`, end: `${month.value}-${pad(last)}` }
}

async function loadRecords() {
  loadingRecords.value = true
  try {
    records.value = await api.get('/api/attendance/records', monthRange())
    const rows = await api.get('/api/attendance/monthly', { month: month.value })
    mine.value = rows.find((r: any) => r.employee_id === auth.me?.employee?.id) || null
  } catch (e) {
    ElMessage.error(errorText(e))
  } finally {
    loadingRecords.value = false
  }
}

async function loadMonthly() {
  loadingMonthly.value = true
  try {
    monthly.value = await api.get('/api/attendance/monthly', { month: month.value, department_id: dept.value })
  } finally {
    loadingMonthly.value = false
  }
}

async function punch(at?: string) {
  punching.value = true
  try {
    lastPunch.value = await api.post('/api/attendance/punch', { punch_time: at || null })
    ElMessage.success(lastPunch.value.duplicate ? '60 秒内重复打卡，已忽略' : '打卡成功')
    loadRecords()
  } catch (e) {
    ElMessage.error(errorText(e))
  } finally {
    punching.value = false
  }
}

function onTab() {
  if (tab.value === 'records') loadRecords()
  if (tab.value === 'corrections') corr.load(1)
  if (tab.value === 'overtime') ot.load(1)
  if (tab.value === 'monthly') loadMonthly()
  if (tab.value === 'rules') loadRules()
}

function openCorrection(row?: any) {
  Object.assign(corrForm, { work_date: row?.work_date || '', kind: row?.check_in_at ? 'out' : 'in', corrected_time: '', reason: '' })
  corrOpen.value = true
}

async function saveCorrection() {
  if (await act(() => api.post('/api/attendance/corrections', corrForm), '补卡申请已提交')) {
    corrOpen.value = false
    tab.value = 'corrections'
    onTab()
  }
}

async function withdrawCorr(row: any) {
  if (await act(() => api.post(`/api/attendance/corrections/${row.id}/withdraw`, {}), '已撤回')) corr.load()
}

async function saveOt() {
  if (await act(() => api.post('/api/attendance/overtime', otForm), '加班申请已提交')) {
    otOpen.value = false
    ot.load(1)
  }
}

async function withdrawOt(row: any) {
  if (await act(() => api.post(`/api/attendance/overtime/${row.id}/withdraw`), '已撤回')) ot.load()
}

async function loadRules() {
  rules.value = await api.get('/api/attendance/rules')
}

function openRule(row?: any) {
  Object.keys(ruleForm).forEach((k) => delete ruleForm[k])
  Object.assign(ruleForm, row ? { ...row } : { name: '', work_start: '09:00', work_end: '18:00', break_start: '12:00', break_end: '13:00', cross_day: false, late_grace_minutes: 0, early_grace_minutes: 0, window_before_minutes: 240, window_after_minutes: 360, is_default: false })
  ruleOpen.value = true
}

async function saveRule() {
  const { id, ...body } = ruleForm
  if (await act(() => (id ? api.put(`/api/attendance/rules/${id}`, body) : api.post('/api/attendance/rules', body)), '规则已保存')) {
    ruleOpen.value = false
    loadRules()
  }
}

async function rebuild() {
  const r = monthRange()
  if (await act(() => api.post('/api/attendance/rebuild', { ...r, department_id: dept.value || null }), '已重算')) loadMonthly()
}

function openFlow(id: number) {
  current.value = id
  drawer.value = true
}

onMounted(() => {
  tick()
  timer = window.setInterval(tick, 1000)
  loadRules()
  loadRecords()
})
onUnmounted(() => window.clearInterval(timer))
</script>

<style scoped>
.mb {
  margin-bottom: 16px;
}
.punch {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 10px;
}
.clock {
  font-size: 36px;
  font-weight: 600;
  color: var(--doe-brand);
}
.sim {
  display: flex;
  gap: 6px;
}
.stats {
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  gap: 8px;
  margin-top: 10px;
  font-size: 13px;
}
.warn {
  color: #d4880f;
}
.neg {
  color: #d9534f;
}
.small {
  font-size: 12px;
  text-align: center;
}
.rule {
  margin-top: 10px;
  font-size: 13px;
}
.ml {
  margin-left: 8px;
}
</style>
