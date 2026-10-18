<template>
  <div class="page">
    <div class="page-head">
      <div><h2>请假与假期</h2><div class="sub">时长按工作日计算（半天 = 4 小时），提交即冻结额度，审批通过后扣减并同步考勤</div></div>
      <el-button type="primary" data-test="new-leave" @click="openForm()">发起请假</el-button>
    </div>
    <div class="grid cols-4 mb">
      <div v-for="b in balances" :key="b.id" class="card stat" :data-test="`balance-${b.leave_type_code}`">
        <span class="label">{{ b.leave_type_name }}（{{ year }}）</span>
        <span class="value">{{ hoursToDays(b.available_hours) }}</span>
        <span class="muted small">总 {{ hoursToDays(b.total_hours) }} · 已用 {{ hoursToDays(b.used_hours) }} · 冻结 {{ hoursToDays(b.pending_hours) }}</span>
      </div>
      <div v-if="!balances.length" class="card muted">暂无余额记录</div>
    </div>
    <div class="card">
      <el-tabs v-model="tab" @tab-change="onTab">
        <el-tab-pane label="我的请假" name="mine" />
        <el-tab-pane label="余额流水" name="ledger" />
        <el-tab-pane v-if="auth.can('employee:read') || auth.can('leave:manage')" label="团队请假" name="all" />
        <el-tab-pane v-if="auth.can('leave:manage')" label="假期管理" name="manage" />
      </el-tabs>

      <template v-if="tab === 'mine' || tab === 'all'">
        <div class="toolbar">
          <el-select v-model="status" placeholder="状态" clearable style="width: 130px" @change="list.load(1)">
            <el-option v-for="s in ['draft', 'pending', 'approved', 'rejected', 'withdrawn', 'cancelled']" :key="s" :label="statusText(s)" :value="s" />
          </el-select>
        </div>
        <el-table v-loading="list.state.loading" :data="list.state.items" border empty-text="暂无请假记录" data-test="leave-table">
          <el-table-column v-if="tab === 'all'" prop="employee_name" label="员工" width="100" />
          <el-table-column prop="leave_type_name" label="类型" width="80" />
          <el-table-column label="时间" min-width="220">
            <template #default="{ row }">{{ row.start_date }} {{ half(row.start_half) }} ~ {{ row.end_date }} {{ half(row.end_half) }}</template>
          </el-table-column>
          <el-table-column label="时长" width="80"><template #default="{ row }">{{ hoursToDays(row.hours) }}</template></el-table-column>
          <el-table-column prop="reason" label="事由" min-width="160" show-overflow-tooltip />
          <el-table-column label="状态" width="90"><template #default="{ row }"><StatusTag :status="row.status" /></template></el-table-column>
          <el-table-column label="操作" width="250" fixed="right">
            <template #default="{ row }">
              <template v-if="tab === 'mine'">
                <el-button v-if="editable(row)" link type="primary" @click="openForm(row)">修改</el-button>
                <el-button v-if="editable(row)" link type="primary" data-test="submit-leave" @click="submit(row)">提交</el-button>
                <el-button v-if="row.status === 'pending'" link @click="withdraw(row)">撤回</el-button>
                <el-button v-if="editable(row) || row.status === 'pending'" link type="warning" @click="cancel(row)">取消</el-button>
              </template>
              <el-button v-if="row.instance_id" link @click="openFlow(row.instance_id)">审批进度</el-button>
            </template>
          </el-table-column>
        </el-table>
        <div class="pager">
          <el-pagination layout="total, prev, pager, next" :total="list.state.total" :page-size="list.state.pageSize"
                         :current-page="list.state.page" @current-change="(p: number) => list.load(p)" />
        </div>
      </template>

      <template v-else-if="tab === 'ledger'">
        <el-table v-loading="ledger.state.loading" :data="ledger.state.items" border empty-text="暂无流水">
          <el-table-column prop="leave_type_name" label="类型" width="80" />
          <el-table-column label="变动" width="120"><template #default="{ row }">{{ LEDGER[row.change_type] || row.change_type }}</template></el-table-column>
          <el-table-column label="时长" width="90"><template #default="{ row }"><span :class="row.hours < 0 ? 'neg' : 'pos'">{{ row.hours > 0 ? '+' : '' }}{{ row.hours }}h</span></template></el-table-column>
          <el-table-column label="变动后（总/已用/冻结）" width="180"><template #default="{ row }">{{ row.total_after }}/{{ row.used_after }}/{{ row.pending_after }} h</template></el-table-column>
          <el-table-column prop="remark" label="说明" min-width="160" />
          <el-table-column label="关联" width="140"><template #default="{ row }">{{ row.ref_type ? `${row.ref_type} #${row.ref_id}` : '-' }}</template></el-table-column>
          <el-table-column label="时间" width="150"><template #default="{ row }">{{ fmtDateTime(row.created_at) }}</template></el-table-column>
        </el-table>
        <div class="pager">
          <el-pagination layout="total, prev, pager, next" :total="ledger.state.total" :page-size="ledger.state.pageSize"
                         :current-page="ledger.state.page" @current-change="(p: number) => ledger.load(p)" />
        </div>
      </template>

      <template v-else-if="tab === 'manage'">
        <div class="grid cols-2">
          <div>
            <h4>假期类型</h4>
            <el-table :data="types" border size="small">
              <el-table-column prop="name" label="名称" width="80" />
              <el-table-column prop="code" label="编码" width="90" />
              <el-table-column label="带薪" width="60"><template #default="{ row }">{{ row.paid ? '是' : '否' }}</template></el-table-column>
              <el-table-column label="扣余额" width="70"><template #default="{ row }">{{ row.requires_balance ? '是' : '否' }}</template></el-table-column>
              <el-table-column label="年度额度" width="90"><template #default="{ row }">{{ hoursToDays(row.default_hours) }}</template></el-table-column>
              <el-table-column prop="description" label="说明" min-width="120" show-overflow-tooltip />
            </el-table>
            <h4>余额调整</h4>
            <el-form :model="adj" label-width="80px" size="small">
              <el-form-item label="员工"><PersonSelect v-model="adj.employee_id" /></el-form-item>
              <el-form-item label="类型">
                <el-select v-model="adj.leave_type_id"><el-option v-for="t in types.filter((x: any) => x.requires_balance)" :key="t.id" :label="t.name" :value="t.id" /></el-select>
              </el-form-item>
              <el-form-item label="小时数"><el-input-number v-model="adj.hours" :min="-2400" :max="2400" :step="4" /></el-form-item>
              <el-form-item label="原因"><el-input v-model="adj.remark" maxlength="255" /></el-form-item>
              <el-form-item>
                <el-button type="primary" @click="adjust">调整</el-button>
                <el-button @click="grantAnnual">发放 {{ year }} 年度额度（幂等）</el-button>
              </el-form-item>
            </el-form>
          </div>
          <div>
            <h4>节假日与调休（{{ year }}）</h4>
            <div class="toolbar">
              <el-date-picker v-model="hol.day" type="date" value-format="YYYY-MM-DD" placeholder="日期" style="width: 150px" />
              <el-input v-model="hol.name" placeholder="名称" style="width: 140px" />
              <el-select v-model="hol.kind" style="width: 110px">
                <el-option label="放假" value="holiday" /><el-option label="调休上班" value="workday" />
              </el-select>
              <el-button type="primary" @click="addHoliday">添加</el-button>
            </div>
            <el-table :data="holidays" border size="small" max-height="420">
              <el-table-column prop="day" label="日期" width="110" />
              <el-table-column prop="name" label="名称" />
              <el-table-column label="类型" width="90"><template #default="{ row }">{{ row.kind === 'holiday' ? '放假' : '调休上班' }}</template></el-table-column>
              <el-table-column width="70"><template #default="{ row }"><el-button link type="danger" @click="delHoliday(row)">删除</el-button></template></el-table-column>
            </el-table>
          </div>
        </div>
      </template>
    </div>

    <el-dialog v-model="formOpen" :title="form.id ? '修改请假单' : '发起请假'" width="560px" data-test="leave-dialog">
      <el-form ref="formRef" :model="form" :rules="rules" label-width="90px">
        <el-form-item label="假期类型" prop="leave_type_id">
          <el-select v-model="form.leave_type_id" placeholder="选择类型" data-test="leave-type">
            <el-option v-for="t in types.filter((x: any) => x.status === 'active')" :key="t.id" :label="t.name" :value="t.id" />
          </el-select>
        </el-form-item>
        <el-form-item label="开始" prop="start_date">
          <span class="dt-wrap" data-test="leave-start"><el-date-picker v-model="form.start_date" type="date" value-format="YYYY-MM-DD" style="width: 160px" @change="calc" /></span>
          <el-radio-group v-model="form.start_half" class="ml" @change="calc"><el-radio-button value="AM">上午</el-radio-button><el-radio-button value="PM">下午</el-radio-button></el-radio-group>
        </el-form-item>
        <el-form-item label="结束" prop="end_date">
          <span class="dt-wrap" data-test="leave-end"><el-date-picker v-model="form.end_date" type="date" value-format="YYYY-MM-DD" style="width: 160px" @change="calc" /></span>
          <el-radio-group v-model="form.end_half" class="ml" @change="calc"><el-radio-button value="AM">上午</el-radio-button><el-radio-button value="PM">下午</el-radio-button></el-radio-group>
        </el-form-item>
        <el-form-item label="请假时长">
          <span v-if="calcRes" data-test="leave-calc"><b>{{ hoursToDays(calcRes.hours) }}</b>（{{ calcRes.hours }} 小时，已排除周末与节假日）</span>
          <span v-else-if="calcErr" class="neg">{{ calcErr }}</span>
          <span v-else class="muted">选择日期后自动计算</span>
        </el-form-item>
        <el-form-item label="事由" prop="reason"><el-input v-model="form.reason" type="textarea" :rows="3" maxlength="500" show-word-limit data-test="leave-reason" /></el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="formOpen = false">取消</el-button>
        <el-button :loading="saving" @click="save(false)">保存草稿</el-button>
        <el-button type="primary" :loading="saving" data-test="leave-submit" @click="save(true)">提交审批</el-button>
      </template>
    </el-dialog>
    <InstanceDrawer v-model="drawer" :instance-id="current" @changed="refresh" />
  </div>
</template>

<script setup lang="ts">
import { onMounted, reactive, ref } from 'vue'
import { ElMessageBox, type FormInstance, type FormRules } from 'element-plus'
import { api, errorText } from '@/api/http'
import { useAuth } from '@/stores/auth'
import { act, usePaged } from '@/utils/usePaged'
import { fmtDateTime, hoursToDays, statusText } from '@/utils/format'
import StatusTag from '@/components/StatusTag.vue'
import PersonSelect from '@/components/PersonSelect.vue'
import InstanceDrawer from '@/components/InstanceDrawer.vue'

const auth = useAuth()
const year = new Date().getFullYear()
const tab = ref('mine')
const status = ref('')
const balances = ref<any[]>([])
const types = ref<any[]>([])
const holidays = ref<any[]>([])
const drawer = ref(false)
const current = ref<number | null>(null)
const LEDGER: Record<string, string> = { grant: '年度发放', adjust: '人工调整', freeze: '提交冻结', unfreeze: '释放冻结', consume: '审批扣减', overtime_credit: '加班转调休' }
const half = (h: string) => (h === 'AM' ? '上午' : '下午')
const editable = (r: any) => ['draft', 'rejected', 'withdrawn'].includes(r.status)

const list = usePaged('/api/leave/requests', () => ({ scope: tab.value === 'all' ? 'all' : 'mine', status: status.value }))
const ledger = usePaged('/api/leave/ledger')

const formRef = ref<FormInstance>()
const formOpen = ref(false)
const saving = ref(false)
const calcRes = ref<any>(null)
const calcErr = ref('')
const blank = () => ({ id: 0, leave_type_id: undefined as number | undefined, start_date: '', start_half: 'AM', end_date: '', end_half: 'PM', reason: '' })
const form = reactive(blank())
const rules: FormRules = {
  leave_type_id: [{ required: true, message: '请选择类型' }],
  start_date: [{ required: true, message: '请选择开始日期' }],
  end_date: [{ required: true, message: '请选择结束日期' }],
  reason: [{ required: true, message: '请填写事由', trigger: 'blur' }],
}
const adj = reactive({ employee_id: undefined as number | undefined, leave_type_id: undefined as number | undefined, hours: 8, remark: '' })
const hol = reactive({ day: '', name: '', kind: 'holiday' })

async function loadBalances() {
  balances.value = await api.get('/api/leave/balances')
}

function refresh() {
  loadBalances()
  if (tab.value === 'ledger') ledger.load()
  else list.load()
}

function onTab() {
  if (tab.value === 'ledger') ledger.load(1)
  else if (tab.value === 'manage') loadHolidays()
  else list.load(1)
}

async function calc() {
  calcRes.value = null
  calcErr.value = ''
  if (!form.start_date || !form.end_date) return
  try {
    calcRes.value = await api.post('/api/leave/calculate', { start_date: form.start_date, start_half: form.start_half, end_date: form.end_date, end_half: form.end_half })
  } catch (e) {
    calcErr.value = errorText(e)
  }
}

function openForm(row?: any) {
  Object.assign(form, blank(), row ? { id: row.id, leave_type_id: row.leave_type_id, start_date: row.start_date, start_half: row.start_half, end_date: row.end_date, end_half: row.end_half, reason: row.reason } : {})
  calcRes.value = null
  formOpen.value = true
  if (row) calc()
}

async function save(submitNow: boolean) {
  if (!(await formRef.value?.validate().catch(() => false))) return
  saving.value = true
  const body = { leave_type_id: form.leave_type_id, start_date: form.start_date, start_half: form.start_half, end_date: form.end_date, end_half: form.end_half, reason: form.reason }
  const ok = await act(async () => {
    if (form.id) {
      await api.put(`/api/leave/requests/${form.id}`, body)
      if (submitNow) await api.post(`/api/leave/requests/${form.id}/submit`)
    } else {
      await api.post('/api/leave/requests', body, { submit: submitNow }, { 'Idempotency-Key': `leave-${Date.now()}-${Math.random().toString(36).slice(2)}` })
    }
  }, submitNow ? '已提交审批' : '已保存草稿')
  saving.value = false
  if (ok) {
    formOpen.value = false
    refresh()
  }
}

async function submit(row: any) {
  if (await act(() => api.post(`/api/leave/requests/${row.id}/submit`), '已提交审批')) refresh()
}

async function withdraw(row: any) {
  await ElMessageBox.confirm('撤回后会释放冻结额度，可修改后重新提交。', '撤回请假')
  if (await act(() => api.post(`/api/leave/requests/${row.id}/withdraw`, {}), '已撤回')) refresh()
}

async function cancel(row: any) {
  await ElMessageBox.confirm('取消后该请假单不可再次提交。', '取消请假', { type: 'warning' })
  if (await act(() => api.post(`/api/leave/requests/${row.id}/cancel`), '已取消')) refresh()
}

function openFlow(id: number) {
  current.value = id
  drawer.value = true
}

async function adjust() {
  if (await act(() => api.post('/api/leave/balances/adjust', { ...adj, year }), '已调整')) refresh()
}

async function grantAnnual() {
  await act(() => api.post('/api/leave/balances/grant-annual', { year }), '已发放')
}

async function loadHolidays() {
  holidays.value = await api.get('/api/holidays', { year })
}

async function addHoliday() {
  if (await act(() => api.post('/api/holidays', hol), '已添加')) loadHolidays()
}

async function delHoliday(row: any) {
  if (await act(() => api.del(`/api/holidays/${row.id}`), '已删除')) loadHolidays()
}

onMounted(async () => {
  types.value = await api.get('/api/leave/types')
  refresh()
})
</script>

<style scoped>
.mb {
  margin-bottom: 16px;
}
.small {
  font-size: 12px;
}
.ml {
  margin-left: 10px;
}
.neg {
  color: #d9534f;
}
.pos {
  color: #3c9a5f;
}
h4 {
  margin: 8px 0;
}
</style>
