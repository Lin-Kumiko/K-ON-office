<template>
  <div class="page">
    <div class="page-head">
      <div><h2>组织架构</h2><div class="sub">多级部门、部门负责人、岗位与调整记录</div></div>
      <div v-if="auth.can('org:manage')" class="toolbar">
        <el-button @click="openPos()">新增岗位</el-button>
        <el-button type="primary" @click="openDept()">新增部门</el-button>
      </div>
    </div>
    <div class="layout">
      <div class="card tree">
        <el-input v-model="filter" placeholder="筛选部门" clearable size="small" class="mb" />
        <el-tree ref="treeRef" :data="tree" node-key="id" default-expand-all highlight-current :expand-on-click-node="false"
                 :props="{ label: 'name', children: 'children' }" :filter-node-method="filterNode" @node-click="select">
          <template #default="{ data }">
            <span class="tnode">{{ data.name }} <span class="muted">({{ data.member_count }})</span></span>
          </template>
        </el-tree>
      </div>
      <div class="card main">
        <template v-if="current">
          <div class="head">
            <div>
              <h3>{{ current.name }} <el-tag size="small" effect="plain">{{ current.code }}</el-tag></h3>
              <div class="muted">负责人：{{ current.manager_name || '未设置' }} · {{ current.description || '暂无描述' }}</div>
            </div>
            <div v-if="auth.can('org:manage')" class="toolbar">
              <el-button size="small" @click="openDept(current)">编辑 / 调整上级</el-button>
              <el-button size="small" type="warning" plain @click="disable">停用</el-button>
            </div>
          </div>
          <el-tabs v-model="tab">
            <el-tab-pane label="部门人员" name="members">
              <el-empty v-if="!auth.loggedIn" description="登录后可以查看部门人员" :image-size="70">
                <el-button type="primary" @click="promptLogin()">登录查看</el-button>
              </el-empty>
              <template v-else>
              <el-checkbox v-model="withChildren" @change="loadMembers">包含下级部门</el-checkbox>
              <el-table :data="members" border size="small" class="mt" empty-text="暂无人员">
                <el-table-column prop="employee_no" label="工号" width="100" />
                <el-table-column prop="name" label="姓名" width="110" />
                <el-table-column prop="department_name" label="部门" width="120" />
                <el-table-column prop="position_name" label="岗位" width="120" />
                <el-table-column prop="manager_name" label="直属上级" width="110" />
                <el-table-column label="状态" width="90"><template #default="{ row }"><StatusTag :status="row.status" /></template></el-table-column>
                <el-table-column prop="phone" label="电话" />
              </el-table>
              </template>
            </el-tab-pane>
            <el-tab-pane label="调整记录" name="logs">
              <el-timeline class="mt">
                <el-timeline-item v-for="l in logs" :key="l.id" :timestamp="fmtDateTime(l.created_at)">
                  <b>{{ ACTION[l.action] || l.action }}</b> · {{ l.operator_name || '系统' }}
                  <div class="muted mono small">{{ JSON.stringify(l.detail) }}</div>
                </el-timeline-item>
              </el-timeline>
              <el-empty v-if="!logs.length" description="暂无记录" :image-size="60" />
            </el-tab-pane>
            <el-tab-pane label="岗位" name="positions">
              <el-table :data="positions" border size="small" class="mt">
                <el-table-column prop="code" label="编码" width="100" />
                <el-table-column prop="name" label="名称" />
                <el-table-column prop="level" label="职级" width="80" />
                <el-table-column v-if="auth.can('org:manage')" width="80"><template #default="{ row }"><el-button link @click="openPos(row)">编辑</el-button></template></el-table-column>
              </el-table>
            </el-tab-pane>
          </el-tabs>
        </template>
        <el-empty v-else description="选择左侧部门查看详情" />
      </div>
    </div>

    <el-dialog v-model="deptOpen" :title="dept.id ? '编辑部门' : '新增部门'" width="500px">
      <el-form :model="dept" label-width="90px">
        <el-form-item label="名称" required><el-input v-model="dept.name" /></el-form-item>
        <el-form-item label="编码" required><el-input v-model="dept.code" :disabled="!!dept.id" /></el-form-item>
        <el-form-item label="上级部门"><DeptSelect v-model="dept.parent_id" /></el-form-item>
        <el-form-item label="负责人"><PersonSelect v-model="dept.manager_employee_id" /></el-form-item>
        <el-form-item label="排序"><el-input-number v-model="dept.sort" :min="0" /></el-form-item>
        <el-form-item label="描述"><el-input v-model="dept.description" /></el-form-item>
      </el-form>
      <template #footer><el-button @click="deptOpen = false">取消</el-button><el-button type="primary" @click="saveDept">保存</el-button></template>
    </el-dialog>
    <el-dialog v-model="posOpen" title="岗位" width="420px">
      <el-form :model="pos" label-width="70px">
        <el-form-item label="名称" required><el-input v-model="pos.name" /></el-form-item>
        <el-form-item label="编码" required><el-input v-model="pos.code" /></el-form-item>
        <el-form-item label="职级"><el-input-number v-model="pos.level" :min="1" :max="20" /></el-form-item>
      </el-form>
      <template #footer><el-button @click="posOpen = false">取消</el-button><el-button type="primary" @click="savePos">保存</el-button></template>
    </el-dialog>
  </div>
</template>

<script setup lang="ts">
import { onMounted, reactive, ref, watch } from 'vue'
import { ElMessageBox } from 'element-plus'
import { api } from '@/api/http'
import { useAuth } from '@/stores/auth'
import { act } from '@/utils/usePaged'
import { promptLogin } from '@/utils/loginPrompt'
import { invalidate } from '@/utils/options'
import { fmtDateTime } from '@/utils/format'
import StatusTag from '@/components/StatusTag.vue'
import DeptSelect from '@/components/DeptSelect.vue'
import PersonSelect from '@/components/PersonSelect.vue'

const ACTION: Record<string, string> = { create: '创建', update: '修改', move: '调整上级', manager_change: '更换负责人', disable: '停用', enable: '启用' }
const auth = useAuth()
const tree = ref<any[]>([])
const treeRef = ref()
const filter = ref('')
const current = ref<any>(null)
const tab = ref('members')
const members = ref<any[]>([])
const logs = ref<any[]>([])
const positions = ref<any[]>([])
const withChildren = ref(true)
const deptOpen = ref(false)
const dept = reactive<any>({})
const posOpen = ref(false)
const pos = reactive<any>({})

watch(filter, (v) => treeRef.value?.filter(v))
const filterNode = (v: string, data: any) => !v || data.name.includes(v)

async function loadTree() {
  tree.value = await api.get('/api/departments/tree')
  if (!current.value && tree.value.length) select(tree.value[0])
}
async function select(d: any) {
  current.value = d
  if (!auth.loggedIn) return // member lists and change logs are only shown after login
  loadMembers()
  logs.value = await api.get(`/api/departments/${d.id}/logs`)
}
async function loadMembers() {
  members.value = await api.get(`/api/departments/${current.value.id}/members`, { include_children: withChildren.value })
}
function openDept(d?: any) {
  Object.keys(dept).forEach((k) => delete dept[k])
  Object.assign(dept, d ? { id: d.id, name: d.name, code: d.code, parent_id: d.parent_id, manager_employee_id: d.manager_employee_id, sort: d.sort, description: d.description }
    : { name: '', code: '', parent_id: current.value?.id, manager_employee_id: null, sort: 0, description: '' })
  deptOpen.value = true
}
async function saveDept() {
  const { id, code, ...rest } = dept
  const ok = await act(() => (id ? api.put(`/api/departments/${id}`, rest) : api.post('/api/departments', { code, ...rest })), '已保存')
  if (ok) {
    deptOpen.value = false
    invalidate('depts')
    current.value = null
    loadTree()
  }
}
async function disable() {
  await ElMessageBox.confirm(`停用「${current.value.name}」？部门需无在职人员与启用的下级部门。`, '停用部门', { type: 'warning' })
  if (await act(() => api.post(`/api/departments/${current.value.id}/disable`), '已停用')) {
    invalidate('depts')
    current.value = null
    loadTree()
  }
}
function openPos(p?: any) {
  Object.keys(pos).forEach((k) => delete pos[k])
  Object.assign(pos, p ? { ...p } : { name: '', code: '', level: 3 })
  posOpen.value = true
}
async function savePos() {
  const { id, name, code, level } = pos
  if (await act(() => (id ? api.put(`/api/positions/${id}`, { name, code, level }) : api.post('/api/positions', { name, code, level })), '已保存')) {
    posOpen.value = false
    invalidate('positions')
    positions.value = await api.get('/api/positions')
  }
}

onMounted(async () => {
  loadTree()
  positions.value = await api.get('/api/positions')
})
</script>

<style scoped>
.layout {
  display: grid;
  grid-template-columns: 300px minmax(0, 1fr);
  gap: 16px;
}
.head {
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
  gap: 12px;
  flex-wrap: wrap;
}
.head h3 {
  margin: 0 0 4px;
}
.mb {
  margin-bottom: 8px;
}
.mt {
  margin-top: 8px;
}
.small {
  font-size: 12px;
}
@media (max-width: 900px) {
  .layout {
    grid-template-columns: minmax(0, 1fr);
  }
}
</style>
