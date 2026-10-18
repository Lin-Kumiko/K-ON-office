<template>
  <div class="page">
    <div class="page-head">
      <div><h2>文档中心</h2><div class="sub">支持分类、搜索、版本与访问范围（公开 / 部门 / 私有），下载会记录历史</div></div>
      <el-button v-if="auth.can('document:upload') || !auth.loggedIn" type="primary"
                 @click="auth.loggedIn ? openUpload() : promptLogin()">上传文档</el-button>
    </div>
    <div class="card">
      <div class="toolbar">
        <el-input v-model="q" placeholder="搜索标题、关键字、描述" clearable style="width: 260px" @change="list.load(1)" />
        <el-select v-model="category" placeholder="分类" clearable style="width: 140px" @change="list.load(1)">
          <el-option v-for="c in cats" :key="c.id" :label="c.name" :value="c.id" />
        </el-select>
        <el-checkbox v-model="mine" @change="list.load(1)">我上传的</el-checkbox>
      </div>
      <el-table :data="list.state.items" v-loading="list.state.loading" border empty-text="暂无文档">
        <el-table-column prop="title" label="标题" min-width="200" />
        <el-table-column prop="category_name" label="分类" width="110" />
        <el-table-column label="范围" width="140"><template #default="{ row }">{{ VIS[row.visibility] }}{{ row.department_name ? `（${row.department_name}）` : '' }}</template></el-table-column>
        <el-table-column prop="owner_name" label="上传者" width="100" />
        <el-table-column label="版本" width="70"><template #default="{ row }">v{{ row.current_version }}</template></el-table-column>
        <el-table-column label="更新时间" width="150"><template #default="{ row }">{{ fmtDateTime(row.updated_at) }}</template></el-table-column>
        <el-table-column label="操作" width="200" fixed="right">
          <template #default="{ row }">
            <el-button link type="primary" @click="detail(row)">详情</el-button>
            <el-button link @click="download(row)">下载</el-button>
            <el-button v-if="row.can_edit" link type="danger" @click="remove(row)">删除</el-button>
          </template>
        </el-table-column>
      </el-table>
      <div class="pager"><el-pagination layout="total, prev, pager, next" :total="list.state.total" :page-size="list.state.pageSize" @current-change="(p: number) => list.load(p)" /></div>
    </div>

    <el-dialog v-model="upOpen" :title="versionOf ? '上传新版本' : '上传文档'" width="520px">
      <el-form label-width="80px">
        <template v-if="!versionOf">
          <el-form-item label="标题" required><el-input v-model="meta.title" maxlength="128" /></el-form-item>
          <el-form-item label="分类"><el-select v-model="meta.category_id" clearable><el-option v-for="c in cats" :key="c.id" :label="c.name" :value="c.id" /></el-select></el-form-item>
          <el-form-item label="可见范围">
            <el-radio-group v-model="meta.visibility"><el-radio value="public">公开</el-radio><el-radio value="department">本部门</el-radio><el-radio value="private">私有</el-radio></el-radio-group>
          </el-form-item>
          <el-form-item label="关键字"><el-input v-model="meta.keywords" maxlength="255" /></el-form-item>
        </template>
        <el-form-item label="版本说明"><el-input v-model="meta.note" maxlength="255" /></el-form-item>
        <el-form-item label="文件" required>
          <input type="file" accept=".pdf,.png,.jpg,.jpeg,.txt,.md,.csv,.docx,.xlsx,.pptx" @change="onFile" />
          <div class="muted small">允许 pdf/png/jpg/txt/md/csv/docx/xlsx/pptx，最大 10MB</div>
        </el-form-item>
      </el-form>
      <template #footer><el-button @click="upOpen = false">取消</el-button><el-button type="primary" :disabled="!file" @click="doUpload">上传</el-button></template>
    </el-dialog>

    <el-drawer v-model="detailOpen" :title="doc?.title" size="640px">
      <template v-if="doc">
        <el-descriptions :column="2" border size="small">
          <el-descriptions-item label="分类">{{ doc.category_name || '-' }}</el-descriptions-item>
          <el-descriptions-item label="范围">{{ VIS[doc.visibility] }}</el-descriptions-item>
          <el-descriptions-item label="上传者">{{ doc.owner_name }}</el-descriptions-item>
          <el-descriptions-item label="当前版本">v{{ doc.current_version }}</el-descriptions-item>
          <el-descriptions-item label="关键字" :span="2">{{ doc.keywords || '-' }}</el-descriptions-item>
        </el-descriptions>
        <div class="toolbar mt" v-if="doc.can_edit">
          <el-button size="small" @click="openUpload(doc.id)">上传新版本</el-button>
          <el-select v-model="doc.visibility" size="small" style="width: 120px" @change="changeVisibility">
            <el-option label="公开" value="public" /><el-option label="本部门" value="department" /><el-option label="私有" value="private" />
          </el-select>
        </div>
        <h4>版本</h4>
        <el-table :data="doc.versions" border size="small">
          <el-table-column label="版本" width="70"><template #default="{ row }">v{{ row.version_no }}</template></el-table-column>
          <el-table-column prop="file_name" label="文件" min-width="140" />
          <el-table-column label="大小" width="90"><template #default="{ row }">{{ (row.size / 1024).toFixed(1) }} KB</template></el-table-column>
          <el-table-column prop="note" label="说明" min-width="120" />
          <el-table-column prop="uploaded_by" label="上传者" width="90" />
          <el-table-column width="70"><template #default="{ row }"><el-button link type="primary" @click="download(doc, row)">下载</el-button></template></el-table-column>
        </el-table>
        <template v-if="doc.can_edit">
          <h4>历史记录</h4>
          <el-timeline>
            <el-timeline-item v-for="l in logs" :key="l.id" :timestamp="fmtDateTime(l.created_at)">{{ LOG[l.action] || l.action }} · {{ l.user_name }}
              <span v-if="l.detail?.version" class="muted">v{{ l.detail.version }}</span></el-timeline-item>
          </el-timeline>
        </template>
      </template>
    </el-drawer>
  </div>
</template>

<script setup lang="ts">
import { onMounted, reactive, ref } from 'vue'
import { ElMessageBox } from 'element-plus'
import { api, downloadFile } from '@/api/http'
import { useAuth } from '@/stores/auth'
import { act, usePaged } from '@/utils/usePaged'
import { promptLogin } from '@/utils/loginPrompt'
import { fmtDateTime } from '@/utils/format'

const VIS: Record<string, string> = { public: '公开', department: '部门可见', private: '私有' }
const LOG: Record<string, string> = { create: '创建', upload: '上传新版本', download: '下载', update: '修改信息', permission: '修改权限', delete: '删除' }
const auth = useAuth()
const q = ref('')
const category = ref<number | undefined>()
const mine = ref(false)
const cats = ref<any[]>([])
const list = usePaged('/api/documents', () => ({ q: q.value, category_id: category.value, mine: mine.value || undefined }))
const upOpen = ref(false)
const versionOf = ref<number | null>(null)
const meta = reactive({ title: '', category_id: undefined as number | undefined, visibility: 'public', keywords: '', note: '' })
const file = ref<File | null>(null)
const detailOpen = ref(false)
const doc = ref<any>(null)
const logs = ref<any[]>([])

function onFile(e: Event) {
  file.value = (e.target as HTMLInputElement).files?.[0] || null
}
function openUpload(docId?: number) {
  versionOf.value = docId ?? null
  Object.assign(meta, { title: '', category_id: undefined, visibility: 'public', keywords: '', note: '' })
  file.value = null
  upOpen.value = true
}
async function doUpload() {
  const fd = new FormData()
  fd.append('file', file.value as File)
  if (meta.note) fd.append('note', meta.note)
  if (!versionOf.value) {
    fd.append('title', meta.title)
    fd.append('visibility', meta.visibility)
    if (meta.category_id) fd.append('category_id', String(meta.category_id))
    if (meta.keywords) fd.append('keywords', meta.keywords)
  }
  const ok = await act(() => api.upload(versionOf.value ? `/api/documents/${versionOf.value}/versions` : '/api/documents', fd), '上传成功')
  if (ok) {
    upOpen.value = false
    list.load()
    if (versionOf.value) detail({ id: versionOf.value })
  }
}
async function detail(row: any) {
  doc.value = await api.get(`/api/documents/${row.id}`)
  logs.value = doc.value.can_edit ? await api.get(`/api/documents/${row.id}/logs`) : []
  detailOpen.value = true
}
async function download(row: any, version?: any) {
  await act(() => downloadFile(`/api/documents/${row.id}/download`, version?.file_name || row.title, { version: version?.version_no }))
}
async function changeVisibility() {
  const d = doc.value
  if (await act(() => api.put(`/api/documents/${d.id}`, { title: d.title, category_id: d.category_id, visibility: d.visibility,
    department_id: d.department_id, keywords: d.keywords, description: d.description }), '访问范围已更新')) {
    detail(d)
    list.load()
  }
}
async function remove(row: any) {
  await ElMessageBox.confirm(`删除「${row.title}」？`, '删除文档', { type: 'warning' })
  if (await act(() => api.del(`/api/documents/${row.id}`), '已删除')) list.load()
}

onMounted(async () => {
  cats.value = await api.get('/api/documents/categories')
  list.load()
})
</script>

<style scoped>
.small {
  font-size: 12px;
}
.mt {
  margin-top: 12px;
}
h4 {
  margin: 16px 0 8px;
}
</style>
