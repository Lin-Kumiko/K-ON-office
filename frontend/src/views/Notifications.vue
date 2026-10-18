<template>
  <div class="page">
    <div class="page-head">
      <div><h2>通知历史</h2><div class="sub">审批待办、审批结果、抄送、公告、会议、入职待办等站内通知</div></div>
      <el-button @click="readAll">全部标记已读</el-button>
    </div>
    <div class="card">
      <div class="toolbar">
        <el-checkbox v-model="unreadOnly" @change="list.load(1)">仅未读</el-checkbox>
        <el-select v-model="category" placeholder="类别" clearable style="width: 160px" @change="list.load(1)">
          <el-option v-for="(v, k) in CATS" :key="k" :label="v" :value="k" />
        </el-select>
      </div>
      <el-table :data="list.state.items" v-loading="list.state.loading" border empty-text="暂无通知" @row-click="open">
        <el-table-column label="类别" width="110"><template #default="{ row }">{{ CATS[row.category] || row.category }}</template></el-table-column>
        <el-table-column label="标题" min-width="260"><template #default="{ row }"><span :class="{ unread: !row.read_at }">{{ row.title }}</span></template></el-table-column>
        <el-table-column prop="content" label="内容" min-width="200" show-overflow-tooltip />
        <el-table-column label="时间" width="150"><template #default="{ row }">{{ fmtDateTime(row.created_at) }}</template></el-table-column>
      </el-table>
      <div class="pager"><el-pagination layout="total, prev, pager, next" :total="list.state.total" :page-size="list.state.pageSize" @current-change="(p: number) => list.load(p)" /></div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import { api } from '@/api/http'
import { useApp } from '@/stores/app'
import { act, usePaged } from '@/utils/usePaged'
import { fmtDateTime } from '@/utils/format'

const CATS: Record<string, string> = { workflow_todo: '审批待办', workflow_result: '审批结果', workflow_cc: '抄送', announcement: '公告',
  meeting: '会议', expense: '报销', expense_finance: '财务待办', onboarding_task: '入职待办', interview: '面试', performance: '绩效', payroll: '薪资' }
const router = useRouter()
const app = useApp()
const unreadOnly = ref(false)
const category = ref('')
const list = usePaged('/api/notifications', () => ({ unread_only: unreadOnly.value || undefined, category: category.value }), 15)

async function open(row: any) {
  if (!row.read_at) {
    await api.post(`/api/notifications/${row.id}/read`)
    app.refreshUnread()
  }
  if (row.link) router.push(row.link)
  else list.load()
}
async function readAll() {
  if (await act(() => api.post('/api/notifications/read-all'), '已全部标记已读')) {
    app.refreshUnread()
    list.load()
  }
}
onMounted(() => list.load())
</script>

<style scoped>
.unread {
  font-weight: 700;
}
</style>
