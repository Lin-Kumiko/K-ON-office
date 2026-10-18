<template>
  <div class="page">
    <div class="page-head">
      <div><h2>转正与调岗</h2><div class="sub">转正：直属主管评分评价 → 人事审核；调岗：调出/调入部门负责人并行会审 → 人事审批</div></div>
    </div>
    <div class="card">
      <el-tabs v-model="tab" @tab-change="load">
        <el-tab-pane label="我的转正" name="mine" />
        <el-tab-pane v-if="auth.can('regularization:manage') || auth.can('employee:read')" label="试用期员工" name="probation" />
        <el-tab-pane v-if="auth.can('regularization:manage') || auth.can('employee:read')" label="转正申请" name="regs" />
        <el-tab-pane v-if="auth.can('transfer:manage')" label="调岗" name="transfers" />
      </el-tabs>

      <template v-if="tab === 'mine'">
        <el-alert v-if="auth.me?.employee?.status !== 'probation'" type="info" :closable="false" show-icon title="你当前不是试用期员工，无需申请转正。" />
        <div v-else class="toolbar"><el-button type="primary" @click="openReg()">申请转正</el-button></div>
        <RegTable :rows="mineRegs" @flow="flow" />
      </template>
      <template v-else-if="tab === 'probation'">
        <el-table :data="probation" border empty-text="暂无试用期员工">
          <el-table-column prop="employee_no" label="工号" width="100" />
          <el-table-column prop="name" label="姓名" width="110" />
          <el-table-column prop="hire_date" label="入职日期" width="110" />
          <el-table-column prop="probation_end_date" label="试用期至" width="110" />
          <el-table-column label="进行中申请" width="110"><template #default="{ row }">{{ row.has_open_request ? '有' : '无' }}</template></el-table-column>
          <el-table-column width="140"><template #default="{ row }"><el-button v-if="auth.can('regularization:manage') && !row.has_open_request" link type="primary" @click="openReg(row)">代发起转正</el-button></template></el-table-column>
        </el-table>
      </template>
      <template v-else-if="tab === 'regs'">
        <RegTable :rows="allRegs" @flow="flow" />
      </template>
      <template v-else>
        <div class="toolbar"><el-button type="primary" @click="openTr">发起调岗</el-button></div>
        <el-table :data="transfers" border empty-text="暂无调岗">
          <el-table-column prop="employee_name" label="员工" width="100" />
          <el-table-column label="部门变化" min-width="200"><template #default="{ row }">{{ row.from_department_name }} → {{ row.to_department_name }}</template></el-table-column>
          <el-table-column label="岗位变化" min-width="160"><template #default="{ row }">{{ row.from_position_name || '-' }} → {{ row.to_position_name || '-' }}</template></el-table-column>
          <el-table-column prop="effective_date" label="生效日期" width="110" />
          <el-table-column label="状态" width="90"><template #default="{ row }"><StatusTag :status="row.status" /></template></el-table-column>
          <el-table-column label="操作" width="150">
            <template #default="{ row }">
              <el-button v-if="row.instance_id" link @click="flow(row.instance_id)">进度</el-button>
              <el-button v-if="['draft', 'pending'].includes(row.status)" link type="warning" @click="cancelTr(row)">取消</el-button>
            </template>
          </el-table-column>
        </el-table>
      </template>
    </div>

    <el-dialog v-model="regOpen" title="转正申请" width="520px">
      <el-form :model="reg" label-width="90px">
        <el-form-item v-if="reg.employee_name" label="员工">{{ reg.employee_name }}</el-form-item>
        <el-form-item label="转正日期" required><el-date-picker v-model="reg.planned_date" type="date" value-format="YYYY-MM-DD" /></el-form-item>
        <el-form-item label="自我评价" required><el-input v-model="reg.self_review" type="textarea" :rows="5" maxlength="5000" show-word-limit /></el-form-item>
      </el-form>
      <template #footer><el-button @click="regOpen = false">取消</el-button><el-button type="primary" @click="saveReg">提交审批</el-button></template>
    </el-dialog>
    <el-dialog v-model="trOpen" title="发起调岗" width="520px">
      <el-form :model="tr" label-width="90px">
        <el-form-item label="员工" required><PersonSelect v-model="tr.employee_id" /></el-form-item>
        <el-form-item label="调入部门" required><DeptSelect v-model="tr.to_department_id" /></el-form-item>
        <el-form-item label="新岗位"><el-select v-model="tr.to_position_id" clearable><el-option v-for="p in positions" :key="p.id" :label="p.name" :value="p.id" /></el-select></el-form-item>
        <el-form-item label="新上级"><PersonSelect v-model="tr.to_manager_id" placeholder="默认调入部门负责人" /></el-form-item>
        <el-form-item label="生效日期" required><el-date-picker v-model="tr.effective_date" type="date" value-format="YYYY-MM-DD" /></el-form-item>
        <el-form-item label="原因" required><el-input v-model="tr.reason" type="textarea" /></el-form-item>
      </el-form>
      <template #footer><el-button @click="trOpen = false">取消</el-button><el-button type="primary" @click="saveTr">提交审批</el-button></template>
    </el-dialog>
    <InstanceDrawer v-model="drawer" :instance-id="current" @changed="load" />
  </div>
</template>

<script setup lang="ts">
import { defineComponent, h, onMounted, reactive, ref } from 'vue'
import { ElButton, ElTable, ElTableColumn } from 'element-plus'
import { api } from '@/api/http'
import { useAuth } from '@/stores/auth'
import { act } from '@/utils/usePaged'
import { invalidate } from '@/utils/options'
import { today } from '@/utils/format'
import StatusTag from '@/components/StatusTag.vue'
import DeptSelect from '@/components/DeptSelect.vue'
import PersonSelect from '@/components/PersonSelect.vue'
import InstanceDrawer from '@/components/InstanceDrawer.vue'

const RegTable = defineComponent({
  props: { rows: { type: Array, required: true } },
  emits: ['flow'],
  setup(props, { emit }) {
    return () => h(ElTable, { data: props.rows, border: true, emptyText: '暂无转正申请' }, () => [
      h(ElTableColumn, { prop: 'employee_name', label: '员工', width: 100 }),
      h(ElTableColumn, { prop: 'planned_date', label: '转正日期', width: 110 }),
      h(ElTableColumn, { prop: 'self_review', label: '自评', minWidth: 160, showOverflowTooltip: true }),
      h(ElTableColumn, { prop: 'manager_score', label: '主管评分', width: 90 }),
      h(ElTableColumn, { prop: 'manager_evaluation', label: '主管评价', minWidth: 160, showOverflowTooltip: true }),
      h(ElTableColumn, { label: '状态', width: 90 }, { default: ({ row }: any) => h(StatusTag, { status: row.status }) }),
      h(ElTableColumn, { width: 90 }, { default: ({ row }: any) => row.instance_id
        ? h(ElButton, { link: true, onClick: () => emit('flow', row.instance_id) }, () => '进度') : null }),
    ])
  },
})

const auth = useAuth()
const tab = ref('mine')
const mineRegs = ref<any[]>([])
const allRegs = ref<any[]>([])
const probation = ref<any[]>([])
const transfers = ref<any[]>([])
const positions = ref<any[]>([])
const regOpen = ref(false)
const reg = reactive<any>({})
const trOpen = ref(false)
const tr = reactive<any>({})
const drawer = ref(false)
const current = ref<number | null>(null)

async function load() {
  if (tab.value === 'mine') mineRegs.value = (await api.get('/api/regularization', { scope: 'mine' })).items
  if (tab.value === 'probation') probation.value = await api.get('/api/regularization/probation-employees')
  if (tab.value === 'regs') allRegs.value = (await api.get('/api/regularization', { scope: 'all', page_size: 100 })).items
  if (tab.value === 'transfers') transfers.value = (await api.get('/api/transfers', { page_size: 100 })).items
}
function openReg(row?: any) {
  Object.keys(reg).forEach((k) => delete reg[k])
  Object.assign(reg, { employee_id: row?.id ?? null, employee_name: row?.name, planned_date: row?.probation_end_date || today(), self_review: '' })
  regOpen.value = true
}
async function saveReg() {
  const body = { employee_id: reg.employee_id, planned_date: reg.planned_date, self_review: reg.self_review || '（HR 代为发起）' }
  if (await act(() => api.post('/api/regularization', body, { submit: true }), '转正申请已提交')) {
    regOpen.value = false
    load()
  }
}
function openTr() {
  Object.keys(tr).forEach((k) => delete tr[k])
  Object.assign(tr, { employee_id: undefined, to_department_id: undefined, to_position_id: undefined, to_manager_id: undefined, effective_date: today(), reason: '' })
  trOpen.value = true
}
async function saveTr() {
  const body = { ...tr, to_position_id: tr.to_position_id || null, to_manager_id: tr.to_manager_id || null }
  if (await act(() => api.post('/api/transfers', body), '调岗审批已发起')) {
    trOpen.value = false
    invalidate('people')
    load()
  }
}
async function cancelTr(row: any) {
  if (await act(() => api.post(`/api/transfers/${row.id}/cancel`), '已取消')) load()
}
function flow(id: number) {
  current.value = id
  drawer.value = true
}

onMounted(async () => {
  positions.value = await api.get('/api/positions')
  load()
})
</script>
