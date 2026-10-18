<template>
  <div class="page">
    <div class="page-head">
      <div><h2>模拟薪资</h2><div class="sub">仅为模拟计算：不执行真实发薪、个税申报或银行支付。缺勤与事假按日薪 = 基本工资 / 21.75 扣减</div></div>
    </div>
    <div class="card">
      <el-tabs v-model="tab" @tab-change="load">
        <el-tab-pane label="我的工资单" name="mine" />
        <el-tab-pane v-if="manage" label="薪资批次" name="runs" />
        <el-tab-pane v-if="manage" label="薪酬结构" name="structures" />
      </el-tabs>
      <template v-if="tab === 'mine'">
        <el-table :data="mine" border empty-text="暂无已确认的工资单">
          <el-table-column prop="month" label="月份" width="100" />
          <el-table-column label="应发" width="120"><template #default="{ row }">{{ money(row.gross) }}</template></el-table-column>
          <el-table-column label="社保" width="110"><template #default="{ row }">{{ money(row.social_insurance) }}</template></el-table-column>
          <el-table-column label="个税（模拟）" width="120"><template #default="{ row }">{{ money(row.tax) }}</template></el-table-column>
          <el-table-column label="实发" width="120"><template #default="{ row }"><b>{{ money(row.net) }}</b></template></el-table-column>
          <el-table-column width="90"><template #default="{ row }"><el-button link @click="showSlip(row)">明细</el-button></template></el-table-column>
        </el-table>
      </template>
      <template v-else-if="tab === 'runs'">
        <div class="toolbar">
          <el-date-picker v-model="newMonth" type="month" value-format="YYYY-MM" placeholder="月份" />
          <el-button type="primary" :disabled="!newMonth" @click="createRun">创建批次</el-button>
        </div>
        <el-table :data="runs" border highlight-current-row @current-change="selectRun">
          <el-table-column prop="month" label="月份" width="100" />
          <el-table-column label="状态" width="100"><template #default="{ row }"><StatusTag :status="row.status" /></template></el-table-column>
          <el-table-column label="计算版本" width="90"><template #default="{ row }">v{{ row.calc_version }}</template></el-table-column>
          <el-table-column prop="payslip_count" label="人数" width="70" />
          <el-table-column label="实发合计" width="140"><template #default="{ row }">{{ money(row.total_net) }}</template></el-table-column>
          <el-table-column label="操作" min-width="220">
            <template #default="{ row }">
              <el-button v-if="row.status !== 'confirmed'" link type="primary" @click.stop="calc(row)">{{ row.calc_version ? '重新计算' : '计算' }}</el-button>
              <el-button v-if="row.status === 'calculated'" link type="success" @click.stop="confirmRun(row)">确认</el-button>
              <el-button link @click.stop="selectRun(row)">工资单</el-button>
            </template>
          </el-table-column>
        </el-table>
        <template v-if="run">
          <h4>{{ run.month }} 奖金 / 扣款</h4>
          <div v-if="run.status !== 'confirmed'" class="toolbar">
            <PersonSelect v-model="adj.employee_id" style="width: 200px" />
            <el-select v-model="adj.kind" style="width: 100px"><el-option label="奖金" value="bonus" /><el-option label="扣款" value="deduction" /></el-select>
            <el-input v-model="adj.amount" placeholder="金额" style="width: 120px" />
            <el-input v-model="adj.reason" placeholder="原因" style="width: 200px" />
            <el-button @click="addAdj">添加</el-button>
          </div>
          <el-table :data="adjs" border size="small">
            <el-table-column prop="employee_name" label="员工" width="100" />
            <el-table-column label="类型" width="80"><template #default="{ row }">{{ row.kind === 'bonus' ? '奖金' : '扣款' }}</template></el-table-column>
            <el-table-column label="金额" width="110"><template #default="{ row }">{{ money(row.amount) }}</template></el-table-column>
            <el-table-column prop="reason" label="原因" />
            <el-table-column width="70"><template #default="{ row }"><el-button v-if="run.status !== 'confirmed'" link type="danger" @click="delAdj(row)">删除</el-button></template></el-table-column>
          </el-table>
          <h4>工资单（当前版本）</h4>
          <el-table :data="slips" border size="small">
            <el-table-column prop="employee_name" label="员工" width="100" fixed />
            <el-table-column label="基本" width="100"><template #default="{ row }">{{ money(row.base) }}</template></el-table-column>
            <el-table-column label="津贴" width="90"><template #default="{ row }">{{ money(row.allowance) }}</template></el-table-column>
            <el-table-column label="奖金" width="90"><template #default="{ row }">{{ money(row.bonus) }}</template></el-table-column>
            <el-table-column label="扣款" width="90"><template #default="{ row }">{{ money(row.deduction) }}</template></el-table-column>
            <el-table-column label="缺勤扣" width="100"><template #default="{ row }">{{ money(row.absence_deduction) }}</template></el-table-column>
            <el-table-column label="事假扣" width="90"><template #default="{ row }">{{ money(row.unpaid_leave_deduction) }}</template></el-table-column>
            <el-table-column label="应发" width="100"><template #default="{ row }">{{ money(row.gross) }}</template></el-table-column>
            <el-table-column label="社保" width="90"><template #default="{ row }">{{ money(row.social_insurance) }}</template></el-table-column>
            <el-table-column label="个税" width="90"><template #default="{ row }">{{ money(row.tax) }}</template></el-table-column>
            <el-table-column label="实发" width="110"><template #default="{ row }"><b>{{ money(row.net) }}</b></template></el-table-column>
            <el-table-column width="90"><template #default="{ row }"><el-button link @click="history(row)">计算历史</el-button></template></el-table-column>
          </el-table>
        </template>
      </template>
      <template v-else>
        <div class="toolbar">
          <PersonSelect v-model="st.employee_id" style="width: 200px" />
          <el-input v-model="st.base" placeholder="基本工资" style="width: 120px" />
          <el-input v-model="st.allowance" placeholder="津贴" style="width: 100px" />
          <el-input-number v-model="st.social_rate_bp" :min="0" :max="5000" :step="50" /><span class="muted">基点(1050=10.5%)</span>
          <el-date-picker v-model="st.effective_from" type="date" value-format="YYYY-MM-DD" placeholder="生效日" style="width: 140px" />
          <el-button type="primary" @click="addStructure">新增调薪记录</el-button>
        </div>
        <el-table :data="structures" border size="small">
          <el-table-column prop="employee_name" label="员工" width="110" />
          <el-table-column label="基本工资" width="120"><template #default="{ row }">{{ money(row.base) }}</template></el-table-column>
          <el-table-column label="津贴" width="100"><template #default="{ row }">{{ money(row.allowance) }}</template></el-table-column>
          <el-table-column label="社保比例" width="100"><template #default="{ row }">{{ (row.social_rate_bp / 100).toFixed(2) }}%</template></el-table-column>
          <el-table-column prop="effective_from" label="生效日" width="110" />
          <el-table-column prop="note" label="说明" />
        </el-table>
      </template>
    </div>
    <el-dialog v-model="slipOpen" title="工资单明细" width="520px">
      <el-descriptions v-if="slip" :column="2" border size="small">
        <el-descriptions-item label="月份">{{ slip.month }}</el-descriptions-item>
        <el-descriptions-item label="版本">v{{ slip.calc_version }}</el-descriptions-item>
        <el-descriptions-item label="基本工资">{{ money(slip.base) }}</el-descriptions-item>
        <el-descriptions-item label="津贴">{{ money(slip.allowance) }}</el-descriptions-item>
        <el-descriptions-item label="奖金">{{ money(slip.bonus) }}</el-descriptions-item>
        <el-descriptions-item label="扣款">{{ money(slip.deduction) }}</el-descriptions-item>
        <el-descriptions-item label="缺勤扣款">{{ money(slip.absence_deduction) }}</el-descriptions-item>
        <el-descriptions-item label="事假扣款">{{ money(slip.unpaid_leave_deduction) }}</el-descriptions-item>
        <el-descriptions-item label="应发">{{ money(slip.gross) }}</el-descriptions-item>
        <el-descriptions-item label="社保">{{ money(slip.social_insurance) }}</el-descriptions-item>
        <el-descriptions-item label="个税（模拟）">{{ money(slip.tax) }}</el-descriptions-item>
        <el-descriptions-item label="实发"><b>{{ money(slip.net) }}</b></el-descriptions-item>
        <el-descriptions-item label="计算依据" :span="2"><span class="mono small">{{ JSON.stringify(slip.detail) }}</span></el-descriptions-item>
      </el-descriptions>
    </el-dialog>
    <el-dialog v-model="histOpen" title="计算历史" width="620px">
      <el-table :data="hist" border size="small">
        <el-table-column label="版本" width="70"><template #default="{ row }">v{{ row.calc_version }}{{ row.is_current ? '（当前）' : '' }}</template></el-table-column>
        <el-table-column label="应发" width="110"><template #default="{ row }">{{ money(row.gross) }}</template></el-table-column>
        <el-table-column label="实发" width="110"><template #default="{ row }">{{ money(row.net) }}</template></el-table-column>
        <el-table-column label="计算时间"><template #default="{ row }">{{ fmtDateTime(row.created_at) }}</template></el-table-column>
      </el-table>
    </el-dialog>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, reactive, ref } from 'vue'
import { ElMessageBox } from 'element-plus'
import { api } from '@/api/http'
import { useAuth } from '@/stores/auth'
import { act } from '@/utils/usePaged'
import { fmtDateTime, money, today } from '@/utils/format'
import StatusTag from '@/components/StatusTag.vue'
import PersonSelect from '@/components/PersonSelect.vue'

const auth = useAuth()
const manage = computed(() => auth.can('payroll:manage'))
const tab = ref('mine')
const mine = ref<any[]>([])
const runs = ref<any[]>([])
const run = ref<any>(null)
const slips = ref<any[]>([])
const adjs = ref<any[]>([])
const structures = ref<any[]>([])
const newMonth = ref('')
const adj = reactive<any>({ employee_id: undefined, kind: 'bonus', amount: '', reason: '' })
const st = reactive<any>({ employee_id: undefined, base: '', allowance: '0', social_rate_bp: 1050, effective_from: today() })
const slipOpen = ref(false)
const slip = ref<any>(null)
const histOpen = ref(false)
const hist = ref<any[]>([])

async function load() {
  if (tab.value === 'mine') mine.value = await api.get('/api/payroll/my-payslips')
  if (tab.value === 'runs') {
    runs.value = await api.get('/api/payroll/runs')
    if (run.value) selectRun(runs.value.find((r) => r.id === run.value.id))
  }
  if (tab.value === 'structures') structures.value = await api.get('/api/payroll/structures')
}
async function selectRun(r: any) {
  if (!r) return
  run.value = r
  slips.value = await api.get(`/api/payroll/runs/${r.id}/payslips`)
  adjs.value = await api.get(`/api/payroll/runs/${r.id}/adjustments`)
}
async function createRun() {
  if (await act(() => api.post('/api/payroll/runs', { month: newMonth.value }), '批次已创建')) load()
}
async function calc(r: any) {
  if (await act(() => api.post(`/api/payroll/runs/${r.id}/calculate`), '计算完成')) {
    run.value = r
    load()
  }
}
async function confirmRun(r: any) {
  await ElMessageBox.confirm(`确认 ${r.month} 工资单？确认后不可再修改（模拟，不会发薪）。`, '确认工资单')
  if (await act(() => api.post(`/api/payroll/runs/${r.id}/confirm`, undefined, undefined, { 'Idempotency-Key': `payroll-${r.id}` }), '已确认')) load()
}
async function addAdj() {
  if (await act(() => api.post(`/api/payroll/runs/${run.value.id}/adjustments`, adj), '已添加，需重新计算')) load()
}
async function delAdj(a: any) {
  if (await act(() => api.del(`/api/payroll/adjustments/${a.id}`), '已删除')) load()
}
async function addStructure() {
  if (await act(() => api.post('/api/payroll/structures', st), '已保存')) load()
}
function showSlip(s: any) {
  slip.value = s
  slipOpen.value = true
}
async function history(s: any) {
  hist.value = await api.get(`/api/payroll/runs/${s.run_id}/history`, { employee_id: s.employee_id })
  histOpen.value = true
}
onMounted(load)
</script>

<style scoped>
h4 {
  margin: 16px 0 8px;
}
.small {
  font-size: 12px;
}
</style>
