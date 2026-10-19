<template>
  <div class="page">
    <div class="page-head">
      <div><h2>审批中心</h2><div class="sub">所有业务审批统一处理，状态由工作流引擎驱动</div></div>
    </div>
    <div class="card">
      <el-tabs v-model="tab" @tab-change="reload">
        <el-tab-pane label="待我审批" name="todo" />
        <el-tab-pane label="我已处理" name="done" />
        <el-tab-pane label="我发起的" name="mine" />
        <el-tab-pane label="抄送我的" name="cc" />
        <el-tab-pane v-if="auth.can('workflow:monitor')" label="流程监控" name="all" />
      </el-tabs>
      <div class="toolbar">
        <el-select v-if="tab !== 'cc'" v-model="btype" placeholder="业务类型" clearable style="width: 160px" @change="reload">
          <el-option v-for="(v, k) in BUSINESS" :key="k" :label="v" :value="k" />
        </el-select>
        <el-select v-if="tab === 'mine' || tab === 'all'" v-model="status" placeholder="状态" clearable style="width: 130px" @change="reload">
          <el-option v-for="s in ['running', 'approved', 'rejected', 'withdrawn', 'cancelled']" :key="s" :label="statusText(s)" :value="s" />
        </el-select>
        <el-input v-if="tab === 'all' || tab === 'mine'" v-model="q" placeholder="搜索标题" clearable style="width: 200px" @change="reload" />
        <span class="spacer" />
        <el-button @click="reload">刷新</el-button>
      </div>

      <el-table v-if="tab === 'todo' || tab === 'done'" v-loading="tasks.state.loading" :data="tasks.state.items" border
                empty-text="暂无任务" data-test="task-table" @row-click="(r: any) => open(r.instance_id)">
        <el-table-column label="业务" width="100"><template #default="{ row }">{{ BUSINESS[row.business_type] }}</template></el-table-column>
        <el-table-column prop="instance_title" label="标题" min-width="240" show-overflow-tooltip />
        <el-table-column prop="node_name" label="节点" width="150" />
        <el-table-column prop="initiator_name" label="发起人" width="100" />
        <el-table-column label="任务状态" width="100"><template #default="{ row }"><StatusTag :status="row.status" /></template></el-table-column>
        <el-table-column label="到达时间" width="150"><template #default="{ row }">{{ fmtDateTime(row.created_at) }}</template></el-table-column>
        <el-table-column label="操作" width="90" fixed="right">
          <template #default="{ row }"><el-button link type="primary" @click.stop="open(row.instance_id)">{{ row.status === 'pending' ? '处理' : '查看' }}</el-button></template>
        </el-table-column>
      </el-table>
      <el-table v-else-if="tab === 'cc'" v-loading="cc.state.loading" :data="cc.state.items" border empty-text="暂无抄送"
                @row-click="(r: any) => openCc(r)">
        <el-table-column prop="title" label="标题" min-width="260" />
        <el-table-column label="流程状态" width="110"><template #default="{ row }"><StatusTag :status="row.status" /></template></el-table-column>
        <el-table-column label="已读" width="80"><template #default="{ row }">{{ row.read_at ? '是' : '否' }}</template></el-table-column>
        <el-table-column label="时间" width="160"><template #default="{ row }">{{ fmtDateTime(row.created_at) }}</template></el-table-column>
      </el-table>
      <el-table v-else v-loading="insts.state.loading" :data="insts.state.items" border empty-text="暂无流程"
                @row-click="(r: any) => open(r.id)">
        <el-table-column prop="business_type_name" label="业务" width="100" />
        <el-table-column prop="title" label="标题" min-width="240" show-overflow-tooltip />
        <el-table-column prop="initiator_name" label="发起人" width="100" />
        <el-table-column label="状态" width="90"><template #default="{ row }"><StatusTag :status="row.status" /></template></el-table-column>
        <el-table-column label="当前节点" min-width="160">
          <template #default="{ row }">{{ row.current_nodes.join('、') || '-' }}<span class="muted" v-if="row.current_assignees.length">（{{ row.current_assignees.join('、') }}）</span></template>
        </el-table-column>
        <el-table-column label="版本" width="70"><template #default="{ row }">v{{ row.version }}</template></el-table-column>
        <el-table-column label="发起时间" width="150"><template #default="{ row }">{{ fmtDateTime(row.started_at) }}</template></el-table-column>
      </el-table>
      <div class="pager">
        <el-pagination layout="total, prev, pager, next" :total="active.state.total" :page-size="active.state.pageSize"
                       :current-page="active.state.page" @current-change="(p: number) => active.load(p)" />
      </div>
    </div>
    <InstanceDrawer v-model="drawer" :instance-id="current" @changed="reload" />
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { useRoute } from 'vue-router'
import { api } from '@/api/http'
import { useAuth } from '@/stores/auth'
import { usePaged } from '@/utils/usePaged'
import { BUSINESS, fmtDateTime, statusText } from '@/utils/format'
import StatusTag from '@/components/StatusTag.vue'
import InstanceDrawer from '@/components/InstanceDrawer.vue'

const auth = useAuth()
const route = useRoute()
const tab = ref((route.query.tab as string) || 'todo')
const btype = ref('')
const status = ref((route.query.status as string) || '')
const q = ref('')
const drawer = ref(false)
const current = ref<number | null>(null)

const tasks = usePaged('/api/workflow/tasks', () => ({ status: tab.value === 'todo' ? 'pending' : 'done', business_type: btype.value }))
const insts = usePaged('/api/workflow/instances', () => ({ scope: tab.value === 'all' ? 'all' : 'mine', status: status.value, business_type: btype.value, q: q.value }))
const cc = usePaged('/api/workflow/cc')
const active = computed(() => (tab.value === 'todo' || tab.value === 'done' ? tasks : tab.value === 'cc' ? cc : insts))

function reload() {
  active.value.load(1)
}

function open(id: number) {
  current.value = id
  drawer.value = true
}

async function openCc(r: any) {
  if (!r.read_at) await api.post(`/api/workflow/cc/${r.id}/read`)
  open(r.instance_id)
}

onMounted(async () => {
  reload()
  if (route.query.instance) open(Number(route.query.instance))
  else if (route.query.task) {
    const t = await api.get('/api/workflow/tasks', { status: 'all', page_size: 200 })
    const hit = t.items.find((x: any) => x.id === Number(route.query.task))
    if (hit) open(hit.instance_id)
  }
})
</script>
