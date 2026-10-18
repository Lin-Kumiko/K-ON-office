<template>
  <div class="page">
    <div class="page-head">
      <div><h2>出差管理</h2><div class="sub">审批通过的出差会同步为考勤“出差”；已批准行程可变更（需重新审批）或在出发前取消</div></div>
      <el-button type="primary" @click="openForm()">新建出差</el-button>
    </div>
    <div class="card">
      <el-tabs v-model="scope" @tab-change="list.load(1)">
        <el-tab-pane label="我的出差" name="mine" />
        <el-tab-pane v-if="auth.can('employee:read')" label="团队出差" name="all" />
      </el-tabs>
      <div class="toolbar">
        <el-input v-model="q" placeholder="搜索目的地" clearable style="width: 200px" @change="list.load(1)" />
        <el-select v-model="status" placeholder="状态" clearable style="width: 130px" @change="list.load(1)">
          <el-option v-for="s in ['draft', 'pending', 'approved', 'rejected', 'withdrawn', 'cancelled', 'changed']" :key="s" :label="statusText(s)" :value="s" />
        </el-select>
      </div>
      <el-table :data="list.state.items" v-loading="list.state.loading" border empty-text="暂无出差记录">
        <el-table-column v-if="scope === 'all'" prop="employee_name" label="员工" width="100" />
        <el-table-column prop="destination" label="目的地" width="140" />
        <el-table-column label="时间" width="220"><template #default="{ row }">{{ row.start_date }} ~ {{ row.end_date }}（{{ row.days }} 天）</template></el-table-column>
        <el-table-column prop="purpose" label="事由" min-width="160" show-overflow-tooltip />
        <el-table-column label="预计费用" width="120"><template #default="{ row }">{{ money(row.estimated_cost) }}</template></el-table-column>
        <el-table-column label="状态" width="100">
          <template #default="{ row }"><StatusTag :status="row.status" /><el-tag v-if="row.original_id" size="small" type="info" class="ml">变更单</el-tag></template>
        </el-table-column>
        <el-table-column label="操作" width="250" fixed="right">
          <template #default="{ row }">
            <template v-if="scope === 'mine'">
              <el-button v-if="editable(row)" link type="primary" @click="openForm(row)">修改</el-button>
              <el-button v-if="editable(row)" link type="primary" @click="doSubmit(row)">提交</el-button>
              <el-button v-if="row.status === 'pending'" link @click="withdraw(row)">撤回</el-button>
              <el-button v-if="row.status === 'approved'" link type="primary" @click="openForm(row, true)">变更</el-button>
              <el-button v-if="['draft', 'pending', 'approved', 'rejected', 'withdrawn'].includes(row.status)" link type="warning" @click="cancel(row)">取消</el-button>
            </template>
            <el-button v-if="row.instance_id" link @click="openFlow(row.instance_id)">进度</el-button>
          </template>
        </el-table-column>
      </el-table>
      <div class="pager"><el-pagination layout="total, prev, pager, next" :total="list.state.total" :page-size="list.state.pageSize" @current-change="(p: number) => list.load(p)" /></div>
    </div>
    <el-dialog v-model="open" :title="changeOf ? '变更出差（重新审批）' : form.id ? '修改出差' : '新建出差'" width="520px">
      <el-form ref="formRef" :model="form" :rules="rules" label-width="90px">
        <el-form-item label="目的地" prop="destination"><el-input v-model="form.destination" maxlength="128" /></el-form-item>
        <el-form-item label="日期" prop="start_date">
          <el-date-picker v-model="range" type="daterange" value-format="YYYY-MM-DD" start-placeholder="出发" end-placeholder="返回" />
        </el-form-item>
        <el-form-item label="交通方式"><el-select v-model="form.transport" clearable><el-option v-for="t in ['飞机', '高铁', '大巴', '自驾', '琴吹家专车']" :key="t" :label="t" :value="t" /></el-select></el-form-item>
        <el-form-item label="预计费用"><el-input v-model="form.estimated_cost" placeholder="0.00" /></el-form-item>
        <el-form-item label="事由" prop="purpose"><el-input v-model="form.purpose" type="textarea" :rows="3" maxlength="500" /></el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="open = false">取消</el-button>
        <el-button v-if="!changeOf" @click="save(false)">保存草稿</el-button>
        <el-button type="primary" @click="save(true)">提交审批</el-button>
      </template>
    </el-dialog>
    <InstanceDrawer v-model="drawer" :instance-id="current" @changed="list.load()" />
  </div>
</template>

<script setup lang="ts">
import { onMounted, reactive, ref, watch } from 'vue'
import { ElMessageBox, type FormInstance, type FormRules } from 'element-plus'
import { api } from '@/api/http'
import { useAuth } from '@/stores/auth'
import { act, usePaged } from '@/utils/usePaged'
import { money, statusText } from '@/utils/format'
import StatusTag from '@/components/StatusTag.vue'
import InstanceDrawer from '@/components/InstanceDrawer.vue'

const auth = useAuth()
const scope = ref('mine')
const q = ref('')
const status = ref('')
const list = usePaged('/api/travel', () => ({ scope: scope.value, q: q.value, status: status.value }))
const open = ref(false)
const changeOf = ref<number | null>(null)
const formRef = ref<FormInstance>()
const range = ref<string[] | null>(null)
const blank = () => ({ id: 0, destination: '', start_date: '', end_date: '', purpose: '', transport: '', estimated_cost: '0.00' })
const form = reactive(blank())
const rules: FormRules = {
  destination: [{ required: true, message: '请填写目的地' }],
  start_date: [{ required: true, message: '请选择日期' }],
  purpose: [{ required: true, message: '请填写事由' }],
}
const drawer = ref(false)
const current = ref<number | null>(null)
const editable = (r: any) => ['draft', 'rejected', 'withdrawn'].includes(r.status)

watch(range, (v) => {
  form.start_date = v?.[0] || ''
  form.end_date = v?.[1] || ''
})

function openForm(row?: any, change = false) {
  Object.assign(form, blank(), row ? { ...row, id: change ? 0 : row.id } : {})
  range.value = row ? [row.start_date, row.end_date] : null
  changeOf.value = change ? row.id : null
  open.value = true
}

async function save(submit: boolean) {
  if (!(await formRef.value?.validate().catch(() => false))) return
  const body = { destination: form.destination, start_date: form.start_date, end_date: form.end_date, purpose: form.purpose,
                 transport: form.transport || null, estimated_cost: form.estimated_cost || '0' }
  const ok = await act(async () => {
    if (changeOf.value) await api.post(`/api/travel/${changeOf.value}/change`, body)
    else if (form.id) {
      await api.put(`/api/travel/${form.id}`, body)
      if (submit) await api.post(`/api/travel/${form.id}/submit`)
    } else await api.post('/api/travel', body, { submit })
  }, submit ? '已提交审批' : '已保存')
  if (ok) {
    open.value = false
    list.load()
  }
}

async function doSubmit(row: any) {
  if (await act(() => api.post(`/api/travel/${row.id}/submit`), '已提交审批')) list.load()
}

async function withdraw(row: any) {
  if (await act(() => api.post(`/api/travel/${row.id}/withdraw`), '已撤回')) list.load()
}

async function cancel(row: any) {
  const { value } = await ElMessageBox.prompt('请填写取消原因', '取消出差', { inputValidator: (v) => !!v?.trim() || '必填' })
  if (await act(() => api.post(`/api/travel/${row.id}/cancel`, { reason: value }), '已取消')) list.load()
}

function openFlow(id: number) {
  current.value = id
  drawer.value = true
}

onMounted(() => list.load())
</script>

<style scoped>
.ml {
  margin-left: 4px;
}
</style>
