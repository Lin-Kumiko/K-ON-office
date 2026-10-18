<template>
  <div class="page">
    <div class="page-head">
      <div><h2>员工档案</h2><div class="sub">列表按数据权限过滤；敏感字段对无权限者脱敏；修改采用乐观锁防止覆盖他人修改</div></div>
      <el-button v-if="auth.can('employee:manage')" type="primary" data-test="new-employee" @click="openCreate">新建员工</el-button>
    </div>
    <div class="card">
      <div class="toolbar">
        <el-input v-model="q" placeholder="姓名 / 工号" clearable style="width: 200px" data-test="employee-search" @change="list.load(1)" />
        <DeptSelect v-model="dept" style="width: 180px" @update:model-value="list.load(1)" />
        <el-select v-model="status" placeholder="状态" clearable style="width: 120px" @change="list.load(1)">
          <el-option label="在职" value="active" /><el-option label="试用期" value="probation" /><el-option label="正式" value="regular" /><el-option label="离职" value="resigned" />
        </el-select>
      </div>
      <el-table :data="list.state.items" v-loading="list.state.loading" border empty-text="暂无员工" data-test="employee-table">
        <el-table-column prop="employee_no" label="工号" width="100" sortable />
        <el-table-column prop="name" label="姓名" width="110" />
        <el-table-column prop="department_name" label="部门" width="120" />
        <el-table-column prop="position_name" label="岗位" width="110" />
        <el-table-column prop="manager_name" label="直属上级" width="110" />
        <el-table-column prop="hire_date" label="入职日期" width="110" />
        <el-table-column label="状态" width="90"><template #default="{ row }"><StatusTag :status="row.status" /></template></el-table-column>
        <el-table-column prop="phone" label="电话" width="130" />
        <el-table-column prop="username" label="账号" width="100" />
        <el-table-column label="操作" width="200" fixed="right">
          <template #default="{ row }">
            <el-button link type="primary" @click="openDetail(row)">档案</el-button>
            <el-button v-if="auth.can('employee:manage') && row.status !== 'resigned'" link @click="openEdit(row)">编辑</el-button>
            <el-button v-if="auth.can('employee:manage') && row.status !== 'resigned'" link type="danger" @click="resign(row)">离职</el-button>
          </template>
        </el-table-column>
      </el-table>
      <div class="pager"><el-pagination layout="total, prev, pager, next" :total="list.state.total" :page-size="list.state.pageSize" @current-change="(p: number) => list.load(p)" /></div>
    </div>

    <el-dialog v-model="createOpen" title="新建员工档案" width="620px" data-test="employee-dialog">
      <el-form ref="createRef" :model="c" :rules="createRules" label-width="100px">
        <el-form-item label="姓名" prop="name"><el-input v-model="c.name" data-test="emp-name" /></el-form-item>
        <el-form-item label="性别"><el-radio-group v-model="c.gender"><el-radio value="女">女</el-radio><el-radio value="男">男</el-radio></el-radio-group></el-form-item>
        <el-form-item label="邮箱" prop="email"><el-input v-model="c.email" data-test="emp-email" /></el-form-item>
        <el-form-item label="电话"><el-input v-model="c.phone" /></el-form-item>
        <el-form-item label="部门" prop="department_id"><DeptSelect v-model="c.department_id" data-test="emp-dept" /></el-form-item>
        <el-form-item label="岗位"><el-select v-model="c.position_id" clearable><el-option v-for="p in positions" :key="p.id" :label="p.name" :value="p.id" /></el-select></el-form-item>
        <el-form-item label="直属上级"><PersonSelect v-model="c.manager_id" /></el-form-item>
        <el-form-item label="入职日期" prop="hire_date"><span class="dt-wrap" data-test="emp-hire"><el-date-picker v-model="c.hire_date" type="date" value-format="YYYY-MM-DD" /></span></el-form-item>
        <el-form-item label="试用期(月)"><el-input-number v-model="c.probation_months" :min="0" :max="6" /></el-form-item>
        <el-form-item label="创建账号"><el-switch v-model="c.create_account" /></el-form-item>
        <template v-if="c.create_account">
          <el-form-item label="用户名"><el-input v-model="c.username" data-test="emp-username" /></el-form-item>
          <el-form-item label="初始密码"><el-input v-model="c.password" type="password" show-password placeholder="留空则需管理员重置后启用" /></el-form-item>
        </template>
      </el-form>
      <template #footer><el-button @click="createOpen = false">取消</el-button><el-button type="primary" data-test="emp-save" @click="create">保存</el-button></template>
    </el-dialog>

    <el-dialog v-model="editOpen" title="编辑档案" width="600px">
      <el-form :model="e" label-width="90px">
        <el-form-item label="姓名"><el-input v-model="e.name" /></el-form-item>
        <el-form-item label="邮箱"><el-input v-model="e.email" /></el-form-item>
        <el-form-item label="电话"><el-input v-model="e.phone" /></el-form-item>
        <el-form-item label="部门"><DeptSelect v-model="e.department_id" /></el-form-item>
        <el-form-item label="岗位"><el-select v-model="e.position_id" clearable><el-option v-for="p in positions" :key="p.id" :label="p.name" :value="p.id" /></el-select></el-form-item>
        <el-form-item label="直属上级"><PersonSelect v-model="e.manager_id" /></el-form-item>
        <el-form-item label="备注"><el-input v-model="e.remark" /></el-form-item>
        <el-form-item label="版本号"><span class="muted">v{{ e.version }}（他人已修改时保存会被拒绝）</span></el-form-item>
      </el-form>
      <template #footer><el-button @click="editOpen = false">取消</el-button><el-button type="primary" @click="saveEdit">保存</el-button></template>
    </el-dialog>

    <el-drawer v-model="detailOpen" :title="detail?.name" size="620px">
      <template v-if="detail">
        <el-descriptions :column="2" border size="small">
          <el-descriptions-item label="工号">{{ detail.employee_no }}</el-descriptions-item>
          <el-descriptions-item label="状态"><StatusTag :status="detail.status" /></el-descriptions-item>
          <el-descriptions-item label="部门">{{ detail.department_name }}</el-descriptions-item>
          <el-descriptions-item label="岗位">{{ detail.position_name || '-' }}</el-descriptions-item>
          <el-descriptions-item label="直属上级">{{ detail.manager_name || '-' }}</el-descriptions-item>
          <el-descriptions-item label="账号">{{ detail.username || '-' }}</el-descriptions-item>
          <el-descriptions-item label="入职">{{ detail.hire_date }}</el-descriptions-item>
          <el-descriptions-item label="试用期至">{{ detail.probation_end_date || '-' }}</el-descriptions-item>
          <el-descriptions-item label="转正日期">{{ detail.regularized_date || '-' }}</el-descriptions-item>
          <el-descriptions-item label="离职日期">{{ detail.resign_date || '-' }}</el-descriptions-item>
          <el-descriptions-item label="电话">{{ detail.phone || '-' }}</el-descriptions-item>
          <el-descriptions-item label="邮箱">{{ detail.email || '-' }}</el-descriptions-item>
        </el-descriptions>
        <h4>任职历史</h4>
        <el-timeline>
          <el-timeline-item v-for="h in history" :key="h.id" :timestamp="h.effective_date">
            <b>{{ CHANGE[h.change_type] || h.change_type }}</b>
            <span v-if="h.from_department !== h.to_department && h.from_department"> · {{ h.from_department }} → {{ h.to_department }}</span>
            <span v-else-if="h.to_department"> · {{ h.to_department }}</span>
            <span v-if="h.from_status !== h.to_status && h.from_status"> · {{ statusText(h.from_status) }} → {{ statusText(h.to_status) }}</span>
            <div class="muted">{{ h.reason }}</div>
          </el-timeline-item>
        </el-timeline>
      </template>
    </el-drawer>
  </div>
</template>

<script setup lang="ts">
import { onMounted, reactive, ref } from 'vue'
import { ElMessageBox, type FormInstance, type FormRules } from 'element-plus'
import { api } from '@/api/http'
import { useAuth } from '@/stores/auth'
import { act, usePaged } from '@/utils/usePaged'
import { invalidate } from '@/utils/options'
import { statusText, today } from '@/utils/format'
import StatusTag from '@/components/StatusTag.vue'
import DeptSelect from '@/components/DeptSelect.vue'
import PersonSelect from '@/components/PersonSelect.vue'

const CHANGE: Record<string, string> = { onboard: '入职', regularize: '转正', transfer: '调岗', resign: '离职', adjust: '档案调整' }
const auth = useAuth()
const q = ref('')
const dept = ref<number | undefined>()
const status = ref('active')
const list = usePaged('/api/employees', () => ({ q: q.value, department_id: dept.value, status: status.value, sort: 'employee_no' }))
const positions = ref<any[]>([])
const createOpen = ref(false)
const createRef = ref<FormInstance>()
const blank = () => ({ name: '', gender: '女', email: '', phone: '', department_id: undefined as number | undefined, position_id: undefined as number | undefined,
  manager_id: undefined as number | undefined, hire_date: today(), probation_months: 3, create_account: true, username: '', password: '' })
const c = reactive(blank())
const createRules: FormRules = {
  name: [{ required: true, message: '必填' }],
  email: [{ required: true, message: '必填' }, { type: 'email', message: '邮箱格式不正确' }],
  department_id: [{ required: true, message: '必填' }],
  hire_date: [{ required: true, message: '必填' }],
}
const editOpen = ref(false)
const e = reactive<any>({})
const detailOpen = ref(false)
const detail = ref<any>(null)
const history = ref<any[]>([])

function openCreate() {
  Object.assign(c, blank())
  createOpen.value = true
}
async function create() {
  if (!(await createRef.value?.validate().catch(() => false))) return
  const body: any = { ...c, phone: c.phone || null, position_id: c.position_id || null, manager_id: c.manager_id || null,
    username: c.create_account ? c.username : null, password: c.create_account && c.password ? c.password : null }
  if (await act(() => api.post('/api/employees', body), '员工档案已创建')) {
    createOpen.value = false
    invalidate('people')
    list.load()
  }
}
async function openEdit(row: any) {
  const full = await api.get(`/api/employees/${row.id}`)
  Object.keys(e).forEach((k) => delete e[k])
  Object.assign(e, full)
  editOpen.value = true
}
async function saveEdit() {
  const body = { version: e.version, name: e.name, gender: e.gender, birth_date: e.birth_date, phone: e.phone || null, email: e.email,
    department_id: e.department_id, position_id: e.position_id || null, manager_id: e.manager_id || null, remark: e.remark || null }
  if (await act(() => api.put(`/api/employees/${e.id}`, body), '已保存')) {
    editOpen.value = false
    invalidate('people')
    list.load()
  }
}
async function openDetail(row: any) {
  detail.value = await api.get(`/api/employees/${row.id}`)
  history.value = await api.get(`/api/employees/${row.id}/history`)
  detailOpen.value = true
}
async function resign(row: any) {
  const { value } = await ElMessageBox.prompt(`为 ${row.name} 办理离职：请输入离职原因（账号将停用，待办自动转交）`, '办理离职',
    { inputValidator: (v) => !!v?.trim() || '必填', type: 'warning' })
  if (await act(() => api.post(`/api/employees/${row.id}/resign`, { resign_date: today(), reason: value }), '已办理离职')) {
    invalidate('people')
    list.load()
  }
}

onMounted(async () => {
  positions.value = await api.get('/api/positions')
  list.load()
})
</script>

<style scoped>
h4 {
  margin: 16px 0 8px;
}
</style>
