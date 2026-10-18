<template>
  <div class="page">
    <div class="page-head">
      <div><h2>公告通知</h2><div class="sub">发布时向阅读范围内成员发送站内通知；内容以纯文本展示</div></div>
      <el-button v-if="auth.can('announcement:manage')" type="primary" @click="openForm()">新建公告</el-button>
    </div>
    <div class="card">
      <el-tabs v-model="scope" @tab-change="list.load(1)">
        <el-tab-pane label="公告列表" name="visible" />
        <el-tab-pane v-if="auth.can('announcement:manage')" label="公告管理" name="manage" />
      </el-tabs>
      <div class="toolbar">
        <el-input v-model="q" placeholder="搜索标题" clearable style="width: 200px" @change="list.load(1)" />
        <el-select v-model="category" placeholder="分类" clearable style="width: 130px" @change="list.load(1)">
          <el-option v-for="c in cats" :key="c.id" :label="c.name" :value="c.id" />
        </el-select>
        <el-checkbox v-if="scope === 'visible'" v-model="unreadOnly" @change="list.load(1)">仅未读</el-checkbox>
        <el-select v-if="scope === 'manage'" v-model="status" placeholder="状态" clearable style="width: 120px" @change="list.load(1)">
          <el-option v-for="s in ['draft', 'published', 'withdrawn']" :key="s" :label="statusText(s)" :value="s" />
        </el-select>
      </div>
      <el-table :data="list.state.items" v-loading="list.state.loading" border empty-text="暂无公告" @row-click="(r: any) => view(r)">
        <el-table-column label="标题" min-width="260">
          <template #default="{ row }">
            <el-tag v-if="row.pinned" size="small" type="danger" class="mr">置顶</el-tag>
            <span :class="{ unread: scope === 'visible' && !row.read }">{{ row.title }}</span>
          </template>
        </el-table-column>
        <el-table-column prop="category_name" label="分类" width="100" />
        <el-table-column label="范围" width="100"><template #default="{ row }">{{ row.scope_type === 'all' ? '全员' : '指定部门' }}</template></el-table-column>
        <el-table-column prop="author_name" label="发布人" width="110" />
        <el-table-column label="状态" width="90"><template #default="{ row }"><StatusTag :status="row.status" /></template></el-table-column>
        <el-table-column label="发布时间" width="150"><template #default="{ row }">{{ fmtDateTime(row.published_at) }}</template></el-table-column>
        <el-table-column v-if="scope === 'manage'" label="操作" width="260" fixed="right">
          <template #default="{ row }">
            <el-button v-if="row.status !== 'published'" link type="primary" @click.stop="openForm(row)">编辑</el-button>
            <el-button v-if="row.status !== 'published'" link type="success" @click.stop="publish(row)">发布</el-button>
            <el-button v-if="row.status === 'published'" link type="warning" @click.stop="withdraw(row)">撤回</el-button>
            <el-button v-if="row.status === 'published'" link @click.stop="reads(row)">阅读统计</el-button>
            <el-button v-if="row.status === 'draft'" link type="danger" @click.stop="remove(row)">删除</el-button>
          </template>
        </el-table-column>
      </el-table>
      <div class="pager"><el-pagination layout="total, prev, pager, next" :total="list.state.total" :page-size="list.state.pageSize" @current-change="(p: number) => list.load(p)" /></div>
    </div>

    <el-drawer v-model="viewOpen" :title="current?.title" size="560px">
      <template v-if="current">
        <div class="muted">{{ current.category_name }} · {{ current.author_name }} · {{ fmtDateTime(current.published_at) }}</div>
        <div class="content" data-test="announcement-content">{{ current.content }}</div>
      </template>
    </el-drawer>

    <el-dialog v-model="formOpen" :title="form.id ? '编辑公告' : '新建公告'" width="620px">
      <el-form :model="form" label-width="80px">
        <el-form-item label="标题" required><el-input v-model="form.title" maxlength="128" /></el-form-item>
        <el-form-item label="分类"><el-select v-model="form.category_id" clearable><el-option v-for="c in cats" :key="c.id" :label="c.name" :value="c.id" /></el-select></el-form-item>
        <el-form-item label="阅读范围">
          <el-radio-group v-model="form.scope_type"><el-radio value="all">全员</el-radio><el-radio value="departments">指定部门（含下级）</el-radio></el-radio-group>
        </el-form-item>
        <el-form-item v-if="form.scope_type === 'departments'" label="部门"><DeptSelect v-model="form.scope_department_ids" multiple /></el-form-item>
        <el-form-item label="置顶"><el-switch v-model="form.pinned" /></el-form-item>
        <el-form-item label="内容" required><el-input v-model="form.content" type="textarea" :rows="8" maxlength="20000" show-word-limit /></el-form-item>
      </el-form>
      <template #footer><el-button @click="formOpen = false">取消</el-button><el-button type="primary" @click="save">保存草稿</el-button></template>
    </el-dialog>

    <el-dialog v-model="readsOpen" title="阅读统计" width="460px">
      <template v-if="readStat">
        <el-progress :percentage="readStat.target ? Math.round((readStat.read / readStat.target) * 100) : 0" />
        <p>应读 {{ readStat.target }} 人，已读 {{ readStat.read }} 人</p>
        <p class="muted">未读：{{ readStat.unread_names.join('、') || '无' }}</p>
      </template>
    </el-dialog>
  </div>
</template>

<script setup lang="ts">
import { onMounted, reactive, ref } from 'vue'
import { useRoute } from 'vue-router'
import { ElMessageBox } from 'element-plus'
import { api } from '@/api/http'
import { useAuth } from '@/stores/auth'
import { useApp } from '@/stores/app'
import { act, usePaged } from '@/utils/usePaged'
import { fmtDateTime, statusText } from '@/utils/format'
import StatusTag from '@/components/StatusTag.vue'
import DeptSelect from '@/components/DeptSelect.vue'

const auth = useAuth()
const appStore = useApp()
const route = useRoute()
const scope = ref('visible')
const q = ref('')
const category = ref<number | undefined>()
const status = ref('')
const unreadOnly = ref(false)
const cats = ref<any[]>([])
const list = usePaged('/api/announcements', () => ({ scope: scope.value, q: q.value, category_id: category.value, status: status.value, unread_only: unreadOnly.value || undefined }))
const viewOpen = ref(false)
const current = ref<any>(null)
const formOpen = ref(false)
const blank = () => ({ id: 0, title: '', content: '', category_id: undefined as number | undefined, scope_type: 'all', scope_department_ids: [] as number[], pinned: false })
const form = reactive(blank())
const readsOpen = ref(false)
const readStat = ref<any>(null)

async function view(row: any) {
  current.value = await api.get(`/api/announcements/${row.id}`)
  viewOpen.value = true
  if (current.value.status === 'published' && !current.value.read) {
    await api.post(`/api/announcements/${row.id}/read`)
    row.read = true
    appStore.refreshUnread()
  }
}
function openForm(row?: any) {
  Object.assign(form, blank(), row ? { ...row } : {})
  formOpen.value = true
}
async function save() {
  const { id, ...rest } = form
  const body = { title: rest.title, content: rest.content, category_id: rest.category_id || null, scope_type: rest.scope_type,
                 scope_department_ids: rest.scope_department_ids, pinned: rest.pinned }
  if (await act(() => (id ? api.put(`/api/announcements/${id}`, body) : api.post('/api/announcements', body)), '已保存')) {
    formOpen.value = false
    scope.value = 'manage'
    list.load()
  }
}
async function publish(row: any) {
  if (await act(() => api.post(`/api/announcements/${row.id}/publish`), '已发布并通知阅读范围成员')) list.load()
}
async function withdraw(row: any) {
  if (await act(() => api.post(`/api/announcements/${row.id}/withdraw`), '已撤回')) list.load()
}
async function remove(row: any) {
  await ElMessageBox.confirm('删除该草稿？', '删除')
  if (await act(() => api.del(`/api/announcements/${row.id}`), '已删除')) list.load()
}
async function reads(row: any) {
  readStat.value = await api.get(`/api/announcements/${row.id}/reads`)
  readsOpen.value = true
}

onMounted(async () => {
  cats.value = await api.get('/api/announcements/categories')
  await list.load()
  if (route.query.id) view({ id: Number(route.query.id) })
})
</script>

<style scoped>
.content {
  white-space: pre-wrap;
  line-height: 1.8;
  margin-top: 16px;
}
.unread {
  font-weight: 700;
}
.mr {
  margin-right: 6px;
}
</style>
