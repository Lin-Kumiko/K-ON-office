<template>
  <div class="page">
    <div class="page-head">
      <div><h2>招聘与入职</h2><div class="sub">需求 → 候选人 → 面试 → 录用审批（人事会签）→ 入职审批 → 自动生成档案、账号与入职待办</div></div>
    </div>
    <div class="card">
      <el-tabs v-model="tab" @tab-change="load">
        <el-tab-pane v-if="hr" label="招聘需求" name="reqs" />
        <el-tab-pane v-if="hr" label="候选人" name="cands" />
        <el-tab-pane label="面试" name="interviews" />
        <el-tab-pane v-if="hr" label="录用审批" name="offers" />
        <el-tab-pane v-if="onb" label="入职申请" name="onboarding" />
        <el-tab-pane label="入职待办" name="tasks" />
      </el-tabs>

      <template v-if="tab === 'reqs'">
        <div class="toolbar"><el-button type="primary" @click="openReq()">新建需求</el-button></div>
        <el-table :data="reqs" border>
          <el-table-column prop="title" label="职位" min-width="140" />
          <el-table-column prop="department_name" label="部门" width="120" />
          <el-table-column prop="position_name" label="岗位" width="110" />
          <el-table-column label="进度" width="110"><template #default="{ row }">{{ row.hired_count }}/{{ row.headcount }}</template></el-table-column>
          <el-table-column prop="candidate_count" label="候选人" width="80" />
          <el-table-column label="状态" width="90"><template #default="{ row }"><StatusTag :status="row.status" /></template></el-table-column>
          <el-table-column label="操作" width="160">
            <template #default="{ row }">
              <el-button link @click="openReq(row)">编辑</el-button>
              <el-button link @click="toggleReq(row)">{{ row.status === 'open' ? '关闭' : '重新开启' }}</el-button>
            </template>
          </el-table-column>
        </el-table>
      </template>

      <template v-else-if="tab === 'cands'">
        <div class="toolbar"><el-button type="primary" @click="openCand()">新建候选人</el-button></div>
        <el-table :data="cands" border>
          <el-table-column prop="name" label="姓名" width="100" />
          <el-table-column prop="requisition_title" label="应聘职位" width="140" />
          <el-table-column prop="email" label="邮箱" min-width="160" />
          <el-table-column prop="source" label="来源" width="120" />
          <el-table-column prop="interview_count" label="面试" width="70" />
          <el-table-column label="状态" width="110"><template #default="{ row }"><StatusTag :status="row.status" /></template></el-table-column>
          <el-table-column label="操作" width="280">
            <template #default="{ row }">
              <el-button v-if="['new', 'interviewing'].includes(row.status)" link type="primary" @click="openIv(row)">安排面试</el-button>
              <el-button v-if="row.status === 'interviewing'" link type="success" @click="openOffer(row)">发起录用</el-button>
              <el-button v-if="row.status === 'offered'" link type="success" @click="openOnb(row)">办理入职</el-button>
              <el-button v-if="['new', 'interviewing'].includes(row.status)" link type="danger" @click="rejectCand(row)">淘汰</el-button>
            </template>
          </el-table-column>
        </el-table>
      </template>

      <template v-else-if="tab === 'interviews'">
        <el-table :data="ivs" border empty-text="暂无面试">
          <el-table-column prop="candidate_name" label="候选人" width="100" />
          <el-table-column prop="round" label="轮次" width="70" />
          <el-table-column prop="interviewer_name" label="面试官" width="100" />
          <el-table-column label="时间" width="150"><template #default="{ row }">{{ fmtDateTime(row.scheduled_at) }}</template></el-table-column>
          <el-table-column label="结果" width="90"><template #default="{ row }"><el-tag :type="row.result === 'pass' ? 'success' : row.result === 'fail' ? 'danger' : 'info'" size="small">{{ RESULT[row.result] }}</el-tag></template></el-table-column>
          <el-table-column prop="score" label="评分" width="70" />
          <el-table-column prop="feedback" label="反馈" min-width="160" show-overflow-tooltip />
          <el-table-column width="100"><template #default="{ row }"><el-button v-if="row.result === 'pending'" link type="primary" @click="openResult(row)">登记结果</el-button></template></el-table-column>
        </el-table>
      </template>

      <template v-else-if="tab === 'offers'">
        <el-table :data="offers" border>
          <el-table-column prop="candidate_name" label="候选人" width="100" />
          <el-table-column prop="department_name" label="部门" width="120" />
          <el-table-column prop="position_name" label="岗位" width="110" />
          <el-table-column label="薪资" width="120"><template #default="{ row }">{{ money(row.salary) }}</template></el-table-column>
          <el-table-column prop="hire_date" label="入职日期" width="110" />
          <el-table-column label="状态" width="100"><template #default="{ row }"><StatusTag :status="row.status" /></template></el-table-column>
          <el-table-column width="100"><template #default="{ row }"><el-button v-if="row.instance_id" link @click="flow(row.instance_id)">审批进度</el-button></template></el-table-column>
        </el-table>
      </template>

      <template v-else-if="tab === 'onboarding'">
        <div class="toolbar"><el-button type="primary" @click="openOnb()">新建入职申请</el-button></div>
        <el-table :data="onbs" border>
          <el-table-column prop="name" label="姓名" width="100" />
          <el-table-column prop="department_name" label="部门" width="120" />
          <el-table-column prop="position_name" label="岗位" width="110" />
          <el-table-column prop="hire_date" label="入职日期" width="110" />
          <el-table-column prop="username" label="账号" width="100" />
          <el-table-column label="状态" width="100"><template #default="{ row }"><StatusTag :status="row.status" /></template></el-table-column>
          <el-table-column label="结果" width="160"><template #default="{ row }">{{ row.employee_id ? `已建档 #${row.employee_id}${row.account_linked ? '（关联已有账号）' : ''}` : '-' }}</template></el-table-column>
          <el-table-column label="操作" width="200">
            <template #default="{ row }">
              <el-button v-if="['draft', 'rejected', 'withdrawn'].includes(row.status)" link type="primary" @click="submitOnb(row)">提交审批</el-button>
              <el-button v-if="row.status === 'pending'" link @click="withdrawOnb(row)">撤回</el-button>
              <el-button v-if="row.instance_id" link @click="flow(row.instance_id)">进度</el-button>
            </template>
          </el-table-column>
        </el-table>
      </template>

      <template v-else>
        <div class="toolbar" v-if="onb"><el-radio-group v-model="taskScope" @change="load"><el-radio-button value="mine">我的</el-radio-button><el-radio-button value="all">全部</el-radio-button></el-radio-group></div>
        <el-table :data="tasks" border empty-text="暂无入职待办">
          <el-table-column prop="employee_name" label="新员工" width="100" />
          <el-table-column prop="title" label="待办" min-width="200" />
          <el-table-column prop="assignee_name" label="负责人" width="100" />
          <el-table-column prop="due_date" label="截止" width="110" />
          <el-table-column label="状态" width="90"><template #default="{ row }"><StatusTag :status="row.status" /></template></el-table-column>
          <el-table-column width="90"><template #default="{ row }"><el-button v-if="row.status === 'todo'" link type="primary" @click="doneTask(row)">完成</el-button></template></el-table-column>
        </el-table>
      </template>
    </div>

    <el-dialog v-model="reqOpen" title="招聘需求" width="500px">
      <el-form :model="req" label-width="80px">
        <el-form-item label="职位" required><el-input v-model="req.title" /></el-form-item>
        <el-form-item label="部门" required><DeptSelect v-model="req.department_id" /></el-form-item>
        <el-form-item label="岗位"><el-select v-model="req.position_id" clearable><el-option v-for="p in positions" :key="p.id" :label="p.name" :value="p.id" /></el-select></el-form-item>
        <el-form-item label="人数"><el-input-number v-model="req.headcount" :min="1" :max="100" /></el-form-item>
        <el-form-item label="描述"><el-input v-model="req.description" type="textarea" /></el-form-item>
      </el-form>
      <template #footer><el-button @click="reqOpen = false">取消</el-button><el-button type="primary" @click="saveReq">保存</el-button></template>
    </el-dialog>
    <el-dialog v-model="candOpen" title="候选人" width="500px">
      <el-form :model="cand" label-width="80px">
        <el-form-item label="应聘职位"><el-select v-model="cand.requisition_id" clearable><el-option v-for="r in reqs.filter((x) => x.status === 'open')" :key="r.id" :label="r.title" :value="r.id" /></el-select></el-form-item>
        <el-form-item label="姓名" required><el-input v-model="cand.name" /></el-form-item>
        <el-form-item label="性别"><el-radio-group v-model="cand.gender"><el-radio value="女">女</el-radio><el-radio value="男">男</el-radio></el-radio-group></el-form-item>
        <el-form-item label="邮箱"><el-input v-model="cand.email" /></el-form-item>
        <el-form-item label="电话"><el-input v-model="cand.phone" /></el-form-item>
        <el-form-item label="来源"><el-input v-model="cand.source" /></el-form-item>
        <el-form-item label="简历"><input type="file" accept=".pdf,.docx,.txt" @change="onResume" /></el-form-item>
      </el-form>
      <template #footer><el-button @click="candOpen = false">取消</el-button><el-button type="primary" @click="saveCand">保存</el-button></template>
    </el-dialog>
    <el-dialog v-model="ivOpen" title="安排面试" width="440px">
      <el-form :model="iv" label-width="80px">
        <el-form-item label="面试官" required><PersonSelect v-model="iv.interviewer_id" mode="user" /></el-form-item>
        <el-form-item label="时间" required><el-date-picker v-model="iv.scheduled_at" type="datetime" value-format="YYYY-MM-DDTHH:mm:ss" /></el-form-item>
        <el-form-item label="轮次"><el-input-number v-model="iv.round" :min="1" :max="10" /></el-form-item>
      </el-form>
      <template #footer><el-button @click="ivOpen = false">取消</el-button><el-button type="primary" @click="saveIv">保存</el-button></template>
    </el-dialog>
    <el-dialog v-model="resOpen" title="面试结果" width="440px">
      <el-form :model="res" label-width="80px">
        <el-form-item label="评分"><el-input-number v-model="res.score" :min="0" :max="100" /></el-form-item>
        <el-form-item label="结果"><el-radio-group v-model="res.result"><el-radio value="pass">通过</el-radio><el-radio value="fail">不通过</el-radio></el-radio-group></el-form-item>
        <el-form-item label="反馈" required><el-input v-model="res.feedback" type="textarea" /></el-form-item>
      </el-form>
      <template #footer><el-button @click="resOpen = false">取消</el-button><el-button type="primary" @click="saveRes">提交</el-button></template>
    </el-dialog>
    <el-dialog v-model="offerOpen" title="发起录用审批" width="460px">
      <el-form :model="offer" label-width="80px">
        <el-form-item label="部门" required><DeptSelect v-model="offer.department_id" /></el-form-item>
        <el-form-item label="岗位"><el-select v-model="offer.position_id" clearable><el-option v-for="p in positions" :key="p.id" :label="p.name" :value="p.id" /></el-select></el-form-item>
        <el-form-item label="月薪" required><el-input v-model="offer.salary" placeholder="0.00" /></el-form-item>
        <el-form-item label="入职日期" required><el-date-picker v-model="offer.hire_date" type="date" value-format="YYYY-MM-DD" /></el-form-item>
      </el-form>
      <template #footer><el-button @click="offerOpen = false">取消</el-button><el-button type="primary" @click="saveOffer">提交审批</el-button></template>
    </el-dialog>
    <el-dialog v-model="onbOpen" title="入职申请" width="560px">
      <el-form :model="ob" label-width="100px">
        <el-form-item label="姓名" required><el-input v-model="ob.name" /></el-form-item>
        <el-form-item label="邮箱" required><el-input v-model="ob.email" /></el-form-item>
        <el-form-item label="电话"><el-input v-model="ob.phone" /></el-form-item>
        <el-form-item label="部门" required><DeptSelect v-model="ob.department_id" /></el-form-item>
        <el-form-item label="岗位"><el-select v-model="ob.position_id" clearable><el-option v-for="p in positions" :key="p.id" :label="p.name" :value="p.id" /></el-select></el-form-item>
        <el-form-item label="直属上级"><PersonSelect v-model="ob.manager_id" placeholder="默认部门负责人" /></el-form-item>
        <el-form-item label="入职日期" required><el-date-picker v-model="ob.hire_date" type="date" value-format="YYYY-MM-DD" /></el-form-item>
        <el-form-item label="试用期(月)"><el-input-number v-model="ob.probation_months" :min="0" :max="6" /></el-form-item>
        <el-form-item label="基本工资"><el-input v-model="ob.base_salary" placeholder="可选，0.00" /></el-form-item>
        <el-form-item label="创建账号"><el-switch v-model="ob.create_account" /></el-form-item>
        <el-form-item v-if="ob.create_account" label="用户名"><el-input v-model="ob.username" placeholder="已存在且未关联员工的账号将被关联" /></el-form-item>
      </el-form>
      <template #footer><el-button @click="onbOpen = false">取消</el-button><el-button @click="saveOnb(false)">保存</el-button><el-button type="primary" @click="saveOnb(true)">提交审批</el-button></template>
    </el-dialog>
    <InstanceDrawer v-model="drawer" :instance-id="current" @changed="load" />
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, reactive, ref } from 'vue'
import { useRoute } from 'vue-router'
import { ElMessageBox } from 'element-plus'
import { api } from '@/api/http'
import { useAuth } from '@/stores/auth'
import { act } from '@/utils/usePaged'
import { invalidate } from '@/utils/options'
import { fmtDateTime, money, today } from '@/utils/format'
import StatusTag from '@/components/StatusTag.vue'
import DeptSelect from '@/components/DeptSelect.vue'
import PersonSelect from '@/components/PersonSelect.vue'
import InstanceDrawer from '@/components/InstanceDrawer.vue'

const RESULT: Record<string, string> = { pending: '待登记', pass: '通过', fail: '不通过' }
const auth = useAuth()
const route = useRoute()
const hr = computed(() => auth.can('recruit:manage'))
const onb = computed(() => auth.can('onboarding:manage'))
const tab = ref((route.query.tab as string) || (auth.can('recruit:manage') ? 'reqs' : 'interviews'))
const reqs = ref<any[]>([])
const cands = ref<any[]>([])
const ivs = ref<any[]>([])
const offers = ref<any[]>([])
const onbs = ref<any[]>([])
const tasks = ref<any[]>([])
const taskScope = ref('mine')
const positions = ref<any[]>([])
const drawer = ref(false)
const current = ref<number | null>(null)
const reqOpen = ref(false)
const req = reactive<any>({})
const candOpen = ref(false)
const cand = reactive<any>({})
const ivOpen = ref(false)
const iv = reactive<any>({})
const resOpen = ref(false)
const res = reactive<any>({})
const offerOpen = ref(false)
const offer = reactive<any>({})
const onbOpen = ref(false)
const ob = reactive<any>({})

async function load() {
  if (tab.value === 'reqs' || tab.value === 'cands') reqs.value = (await api.get('/api/recruitment/requisitions', { page_size: 100 })).items
  if (tab.value === 'cands') cands.value = (await api.get('/api/recruitment/candidates', { page_size: 100 })).items
  if (tab.value === 'interviews') ivs.value = await api.get('/api/recruitment/interviews')
  if (tab.value === 'offers') offers.value = (await api.get('/api/recruitment/offers', { page_size: 100 })).items
  if (tab.value === 'onboarding') onbs.value = (await api.get('/api/onboarding', { page_size: 100 })).items
  if (tab.value === 'tasks') tasks.value = await api.get('/api/onboarding-tasks', { scope: taskScope.value })
}
const reset = (o: any, v: any) => { Object.keys(o).forEach((k) => delete o[k]); Object.assign(o, v) }

function openReq(r?: any) {
  reset(req, r ? { ...r } : { title: '', department_id: undefined, position_id: undefined, headcount: 1, description: '' })
  reqOpen.value = true
}
async function saveReq() {
  const body = { title: req.title, department_id: req.department_id, position_id: req.position_id || null, headcount: req.headcount, description: req.description || null }
  if (await act(() => (req.id ? api.put(`/api/recruitment/requisitions/${req.id}`, body) : api.post('/api/recruitment/requisitions', body)), '已保存')) {
    reqOpen.value = false
    load()
  }
}
async function toggleReq(r: any) {
  if (await act(() => api.post(`/api/recruitment/requisitions/${r.id}/status`, { status: r.status === 'open' ? 'closed' : 'open' }), '已更新')) load()
}
function openCand() {
  reset(cand, { requisition_id: undefined, name: '', gender: '女', email: '', phone: '', source: '', resume_file_id: null })
  candOpen.value = true
}
async function onResume(e: Event) {
  const f = (e.target as HTMLInputElement).files?.[0]
  if (!f) return
  const fd = new FormData()
  fd.append('file', f)
  fd.append('purpose', 'resume')
  await act(async () => { cand.resume_file_id = (await api.upload('/api/files', fd)).id }, '简历已上传')
}
async function saveCand() {
  const body = { ...cand, email: cand.email || null, phone: cand.phone || null, requisition_id: cand.requisition_id || null }
  if (await act(() => api.post('/api/recruitment/candidates', body), '已保存')) {
    candOpen.value = false
    load()
  }
}
async function rejectCand(c: any) {
  await ElMessageBox.confirm(`淘汰候选人 ${c.name}？`, '淘汰')
  if (await act(() => api.post(`/api/recruitment/candidates/${c.id}/reject`), '已淘汰')) load()
}
function openIv(c: any) {
  reset(iv, { candidate_id: c.id, interviewer_id: undefined, scheduled_at: '', round: c.interview_count + 1 })
  ivOpen.value = true
}
async function saveIv() {
  const { candidate_id, ...body } = iv
  if (await act(() => api.post(`/api/recruitment/candidates/${candidate_id}/interviews`, body), '已安排')) {
    ivOpen.value = false
    load()
  }
}
function openResult(i: any) {
  reset(res, { id: i.id, score: 80, result: 'pass', feedback: '' })
  resOpen.value = true
}
async function saveRes() {
  const { id, ...body } = res
  if (await act(() => api.post(`/api/recruitment/interviews/${id}/result`, body), '已登记')) {
    resOpen.value = false
    load()
  }
}
function openOffer(c: any) {
  const r = reqs.value.find((x) => x.id === c.requisition_id)
  reset(offer, { candidate_id: c.id, department_id: r?.department_id, position_id: r?.position_id, salary: '', hire_date: today() })
  offerOpen.value = true
}
async function saveOffer() {
  if (await act(() => api.post('/api/recruitment/offers', { ...offer, position_id: offer.position_id || null }), '录用审批已发起')) {
    offerOpen.value = false
    load()
  }
}
async function openOnb(c?: any) {
  let base: any = { candidate_id: null, name: '', email: '', phone: '', department_id: undefined, position_id: undefined, manager_id: undefined,
    hire_date: today(), probation_months: 3, create_account: true, username: '', base_salary: '' }
  if (c) {
    const o = (await api.get('/api/recruitment/offers', { page_size: 100 })).items.find((x: any) => x.candidate_id === c.id && x.status === 'approved')
    base = { ...base, candidate_id: c.id, name: c.name, email: c.email || '', phone: c.phone || '', department_id: o?.department_id,
      position_id: o?.position_id, hire_date: o?.hire_date || today(), base_salary: o?.salary || '' }
  }
  reset(ob, base)
  onbOpen.value = true
}
async function saveOnb(submit: boolean) {
  const body = { ...ob, phone: ob.phone || null, position_id: ob.position_id || null, manager_id: ob.manager_id || null,
    username: ob.create_account ? ob.username || null : null, base_salary: ob.base_salary || null }
  if (await act(() => api.post('/api/onboarding', body, { submit }), submit ? '入职审批已发起' : '已保存')) {
    onbOpen.value = false
    tab.value = 'onboarding'
    load()
  }
}
async function submitOnb(o: any) {
  if (await act(() => api.post(`/api/onboarding/${o.id}/submit`), '已提交')) load()
}
async function withdrawOnb(o: any) {
  if (await act(() => api.post(`/api/onboarding/${o.id}/withdraw`), '已撤回')) load()
}
async function doneTask(t: any) {
  if (await act(() => api.post(`/api/onboarding-tasks/${t.id}/done`), '已完成')) load()
}
function flow(id: number) {
  current.value = id
  drawer.value = true
  invalidate('people')
}

onMounted(async () => {
  positions.value = await api.get('/api/positions')
  load()
})
</script>
