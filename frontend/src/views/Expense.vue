<template>
  <div class="page">
    <div class="page-head">
      <div><h2>费用报销</h2><div class="sub">金额以“分”精确计算；超过 5000 元需社长审批；审批通过后由财务模拟确认付款并归档（不连接任何真实支付）</div></div>
      <el-button type="primary" data-test="new-claim" @click="openForm()">新建报销</el-button>
    </div>
    <div class="card">
      <el-tabs v-model="scope" @tab-change="list.load(1)">
        <el-tab-pane label="我的报销" name="mine" />
        <el-tab-pane v-if="auth.can('expense:finance')" label="财务处理" name="finance" />
        <el-tab-pane v-if="auth.can('employee:read')" label="团队报销" name="all" />
      </el-tabs>
      <div class="toolbar">
        <el-input v-model="q" placeholder="搜索标题/单号" clearable style="width: 200px" @change="list.load(1)" />
        <el-select v-model="status" placeholder="状态" clearable style="width: 140px" @change="list.load(1)">
          <el-option v-for="s in ['draft', 'pending', 'approved', 'paid', 'archived', 'rejected', 'withdrawn', 'cancelled']" :key="s" :label="statusText(s)" :value="s" />
        </el-select>
      </div>
      <el-table :data="list.state.items" v-loading="list.state.loading" border empty-text="暂无报销单" data-test="claim-table">
        <el-table-column prop="claim_no" label="单号" width="150" />
        <el-table-column v-if="scope !== 'mine'" prop="employee_name" label="申请人" width="100" />
        <el-table-column prop="title" label="标题" min-width="160" show-overflow-tooltip />
        <el-table-column label="金额" width="130" align="right"><template #default="{ row }"><span class="mono">{{ money(row.total) }}</span></template></el-table-column>
        <el-table-column label="明细" width="70"><template #default="{ row }">{{ row.items.length }}</template></el-table-column>
        <el-table-column label="状态" width="110"><template #default="{ row }"><StatusTag :status="row.status" /></template></el-table-column>
        <el-table-column label="付款参考" width="170"><template #default="{ row }">{{ row.payment_ref || '-' }}</template></el-table-column>
        <el-table-column label="操作" width="280" fixed="right">
          <template #default="{ row }">
            <el-button link @click="view(row)">详情</el-button>
            <template v-if="scope === 'mine'">
              <el-button v-if="editable(row)" link type="primary" @click="openForm(row)">修改</el-button>
              <el-button v-if="editable(row)" link type="primary" @click="submit(row)">提交</el-button>
              <el-button v-if="row.status === 'pending'" link @click="withdraw(row)">撤回</el-button>
              <el-button v-if="editable(row)" link type="warning" @click="cancel(row)">作废</el-button>
            </template>
            <template v-if="scope === 'finance'">
              <el-button v-if="row.status === 'approved'" link type="success" data-test="finance-confirm" @click="confirm(row)">财务确认</el-button>
              <el-button v-if="row.status === 'paid'" link type="primary" @click="archive(row)">归档</el-button>
            </template>
            <el-button v-if="row.instance_id" link @click="openFlow(row.instance_id)">进度</el-button>
          </template>
        </el-table-column>
      </el-table>
      <div class="pager"><el-pagination layout="total, prev, pager, next" :total="list.state.total" :page-size="list.state.pageSize" @current-change="(p: number) => list.load(p)" /></div>
    </div>

    <el-dialog v-model="open" :title="form.id ? '修改报销单' : '新建报销单'" width="860px" data-test="claim-dialog">
      <el-form label-width="70px">
        <el-form-item label="标题" required><el-input v-model="form.title" maxlength="128" data-test="claim-title" /></el-form-item>
      </el-form>
      <el-table :data="form.items" border size="small">
        <el-table-column label="分类" width="150">
          <template #default="{ row }"><el-select v-model="row.category_id" size="small" data-test="item-category"><el-option v-for="c in cats" :key="c.id" :label="c.name" :value="c.id" /></el-select></template>
        </el-table-column>
        <el-table-column label="日期" width="150">
          <template #default="{ row }"><span class="dt-wrap" data-test="item-date"><el-date-picker v-model="row.occurred_on" type="date" value-format="YYYY-MM-DD" size="small" style="width: 130px" /></span></template>
        </el-table-column>
        <el-table-column label="金额（元）" width="130">
          <template #default="{ row }"><el-input v-model="row.amount" size="small" placeholder="0.00" data-test="item-amount" /></template>
        </el-table-column>
        <el-table-column label="说明" min-width="140"><template #default="{ row }"><el-input v-model="row.description" size="small" /></template></el-table-column>
        <el-table-column label="票据（模拟）" width="160">
          <template #default="{ row }">
            <el-upload :show-file-list="false" :http-request="(o: any) => upload(o, row)" accept=".pdf,.png,.jpg,.jpeg">
              <el-button size="small">{{ row.receipt_name || '上传' }}</el-button>
            </el-upload>
          </template>
        </el-table-column>
        <el-table-column width="60"><template #default="{ $index }"><el-button link type="danger" @click="form.items.splice($index, 1)">删</el-button></template></el-table-column>
      </el-table>
      <div class="toolbar mt">
        <el-button size="small" @click="addItem">添加明细</el-button>
        <span class="spacer" />
        <span>合计：<b class="mono" data-test="claim-total">{{ money(total) }}</b></span>
      </div>
      <template #footer>
        <el-button @click="open = false">取消</el-button>
        <el-button @click="save(false)">保存草稿</el-button>
        <el-button type="primary" data-test="claim-submit" @click="save(true)">提交审批</el-button>
      </template>
    </el-dialog>

    <el-drawer v-model="detailOpen" title="报销单详情" size="640px">
      <template v-if="detail">
        <el-descriptions :column="2" border size="small">
          <el-descriptions-item label="单号">{{ detail.claim_no }}</el-descriptions-item>
          <el-descriptions-item label="状态"><StatusTag :status="detail.status" /></el-descriptions-item>
          <el-descriptions-item label="申请人">{{ detail.employee_name }}</el-descriptions-item>
          <el-descriptions-item label="合计">{{ money(detail.total) }}</el-descriptions-item>
          <el-descriptions-item label="财务确认">{{ detail.finance_confirmed_by || '-' }} {{ fmtDateTime(detail.finance_confirmed_at) }}</el-descriptions-item>
          <el-descriptions-item label="归档时间">{{ fmtDateTime(detail.archived_at) }}</el-descriptions-item>
        </el-descriptions>
        <el-table :data="detail.items" border size="small" class="mt">
          <el-table-column prop="category_name" label="分类" width="110" />
          <el-table-column prop="occurred_on" label="日期" width="110" />
          <el-table-column label="金额" width="110" align="right"><template #default="{ row }">{{ money(row.amount) }}</template></el-table-column>
          <el-table-column prop="description" label="说明" />
          <el-table-column label="票据" width="120">
            <template #default="{ row }"><el-button v-if="row.receipt_file_id" link type="primary" @click="downloadFile(`/api/files/${row.receipt_file_id}`, row.receipt_name)">{{ row.receipt_name }}</el-button></template>
          </el-table-column>
        </el-table>
      </template>
    </el-drawer>
    <InstanceDrawer v-model="drawer" :instance-id="current" @changed="list.load()" />
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, reactive, ref } from 'vue'
import { ElMessageBox } from 'element-plus'
import { api, downloadFile } from '@/api/http'
import { useAuth } from '@/stores/auth'
import { act, usePaged } from '@/utils/usePaged'
import { fmtDateTime, money, statusText, sumMoney, today } from '@/utils/format'
import StatusTag from '@/components/StatusTag.vue'
import InstanceDrawer from '@/components/InstanceDrawer.vue'

const auth = useAuth()
const scope = ref('mine')
const q = ref('')
const status = ref('')
const list = usePaged('/api/expense/claims', () => ({ scope: scope.value, q: q.value, status: status.value }))
const cats = ref<any[]>([])
const open = ref(false)
const form = reactive({ id: 0, title: '', items: [] as any[] })
const total = computed(() => sumMoney(form.items.map((i) => i.amount)))
const detailOpen = ref(false)
const detail = ref<any>(null)
const drawer = ref(false)
const current = ref<number | null>(null)
const editable = (r: any) => ['draft', 'rejected', 'withdrawn'].includes(r.status)

function addItem() {
  form.items.push({ category_id: cats.value[0]?.id, occurred_on: today(), amount: '', description: '', receipt_file_id: null, receipt_name: '' })
}

function openForm(row?: any) {
  form.id = row?.id || 0
  form.title = row?.title || ''
  form.items = row ? row.items.map((i: any) => ({ ...i })) : []
  if (!form.items.length) addItem()
  open.value = true
}

async function upload(o: any, row: any) {
  const fd = new FormData()
  fd.append('file', o.file)
  fd.append('purpose', 'expense_receipt')
  await act(async () => {
    const f = await api.upload('/api/files', fd)
    row.receipt_file_id = f.id
    row.receipt_name = f.original_name
  }, '票据已上传')
}

async function save(submit: boolean) {
  const body = { title: form.title, items: form.items.map((i) => ({ category_id: i.category_id, occurred_on: i.occurred_on,
    amount: i.amount, description: i.description || null, receipt_file_id: i.receipt_file_id || null })) }
  const ok = await act(async () => {
    if (form.id) {
      await api.put(`/api/expense/claims/${form.id}`, body)
      if (submit) await api.post(`/api/expense/claims/${form.id}/submit`)
    } else await api.post('/api/expense/claims', body, { submit })
  }, submit ? '已提交审批' : '已保存草稿')
  if (ok) {
    open.value = false
    list.load()
  }
}

async function submit(row: any) {
  if (await act(() => api.post(`/api/expense/claims/${row.id}/submit`), '已提交审批')) list.load()
}
async function withdraw(row: any) {
  if (await act(() => api.post(`/api/expense/claims/${row.id}/withdraw`), '已撤回')) list.load()
}
async function cancel(row: any) {
  await ElMessageBox.confirm('作废后不可再次提交', '作废报销单', { type: 'warning' })
  if (await act(() => api.post(`/api/expense/claims/${row.id}/cancel`), '已作废')) list.load()
}
async function confirm(row: any) {
  await ElMessageBox.confirm(`确认模拟付款 ${money(row.total)}？（不会产生真实支付）`, '财务确认')
  if (await act(() => api.post(`/api/expense/claims/${row.id}/finance-confirm`, { note: '模拟付款' }, undefined,
    { 'Idempotency-Key': `finance-${row.id}` }), '已确认付款（模拟）')) list.load()
}
async function archive(row: any) {
  if (await act(() => api.post(`/api/expense/claims/${row.id}/archive`), '已归档')) list.load()
}
async function view(row: any) {
  detail.value = await api.get(`/api/expense/claims/${row.id}`)
  detailOpen.value = true
}
function openFlow(id: number) {
  current.value = id
  drawer.value = true
}

onMounted(async () => {
  cats.value = await api.get('/api/expense/categories')
  list.load()
})
</script>

<style scoped>
.mt {
  margin-top: 12px;
}
</style>
