<template>
  <div class="page">
    <div class="page-head"><div><h2>系统与权限</h2><div class="sub">RBAC：角色 = 菜单/接口权限 + 数据范围（本人 / 本部门及下级 / 全部）。所有校验在后端执行</div></div></div>
    <div class="card">
      <el-tabs v-model="tab" @tab-change="load">
        <el-tab-pane v-if="auth.can('user:manage')" label="用户" name="users" />
        <el-tab-pane v-if="auth.can('role:manage')" label="角色与权限" name="roles" />
        <el-tab-pane v-if="auth.can('audit:read')" label="审计日志" name="audit" />
        <el-tab-pane v-if="auth.can('audit:read')" label="登录日志" name="logins" />
        <el-tab-pane v-if="auth.can('settings:manage')" label="系统设置" name="settings" />
      </el-tabs>

      <template v-if="tab === 'users'">
        <div class="toolbar">
          <el-input v-model="uq" placeholder="用户名 / 姓名" clearable style="width: 200px" @change="users.load(1)" />
          <el-select v-model="urole" placeholder="角色" clearable style="width: 140px" @change="users.load(1)">
            <el-option v-for="r in roles" :key="r.code" :label="r.name" :value="r.code" />
          </el-select>
          <span class="spacer" />
          <el-button type="primary" @click="openUser">新建用户</el-button>
        </div>
        <el-table :data="users.state.items" v-loading="users.state.loading" border>
          <el-table-column prop="username" label="用户名" width="110" />
          <el-table-column prop="display_name" label="姓名" width="150" />
          <el-table-column prop="employee_name" label="关联员工" width="110" />
          <el-table-column label="角色" min-width="200"><template #default="{ row }"><el-tag v-for="r in row.roles" :key="r" size="small" class="mr">{{ roleName(r) }}</el-tag></template></el-table-column>
          <el-table-column label="状态" width="120"><template #default="{ row }"><StatusTag :status="row.status" /><el-tag v-if="row.locked" size="small" type="danger" class="ml">锁定</el-tag></template></el-table-column>
          <el-table-column label="最后登录" width="150"><template #default="{ row }">{{ fmtDateTime(row.last_login_at) }}</template></el-table-column>
          <el-table-column label="操作" width="300" fixed="right">
            <template #default="{ row }">
              <el-button link type="primary" @click="openRoles(row)">分配角色</el-button>
              <el-button link @click="resetPw(row)">重置密码</el-button>
              <el-button v-if="row.locked" link @click="unlock(row)">解锁</el-button>
              <el-button link :type="row.status === 'active' ? 'danger' : 'success'" @click="toggle(row)">{{ row.status === 'active' ? '停用' : '启用' }}</el-button>
            </template>
          </el-table-column>
        </el-table>
        <div class="pager"><el-pagination layout="total, prev, pager, next" :total="users.state.total" :page-size="users.state.pageSize" @current-change="(p: number) => users.load(p)" /></div>
      </template>

      <template v-else-if="tab === 'roles'">
        <div class="toolbar"><el-button type="primary" @click="openRole()">新建角色</el-button></div>
        <el-table :data="roles" border>
          <el-table-column prop="code" label="编码" width="120" />
          <el-table-column prop="name" label="名称" width="120" />
          <el-table-column label="数据范围" width="130"><template #default="{ row }">{{ SCOPE[row.data_scope] }}</template></el-table-column>
          <el-table-column prop="user_count" label="用户数" width="80" />
          <el-table-column label="权限" min-width="300"><template #default="{ row }"><span class="muted small">{{ row.permissions.length }} 项：{{ row.permissions.slice(0, 6).join('、') }}{{ row.permissions.length > 6 ? '…' : '' }}</span></template></el-table-column>
          <el-table-column label="操作" width="150">
            <template #default="{ row }">
              <el-button v-if="row.code !== 'admin'" link type="primary" @click="openRole(row)">编辑</el-button>
              <el-button v-if="!row.is_system" link type="danger" @click="delRole(row)">删除</el-button>
            </template>
          </el-table-column>
        </el-table>
      </template>

      <template v-else-if="tab === 'audit'">
        <div class="toolbar"><el-input v-model="aq" placeholder="按动作过滤，如 publish_wf_definition" clearable style="width: 280px" @change="audit.load(1)" /></div>
        <el-table :data="audit.state.items" v-loading="audit.state.loading" border size="small">
          <el-table-column label="时间" width="150"><template #default="{ row }">{{ fmtDateTime(row.created_at) }}</template></el-table-column>
          <el-table-column prop="username" label="用户" width="100" />
          <el-table-column prop="action" label="动作" width="200" />
          <el-table-column label="对象" width="160"><template #default="{ row }">{{ row.resource_type }} #{{ row.resource_id }}</template></el-table-column>
          <el-table-column label="详情" min-width="200"><template #default="{ row }"><span class="mono small">{{ row.detail ? JSON.stringify(row.detail) : '' }}</span></template></el-table-column>
          <el-table-column prop="ip" label="IP" width="110" />
        </el-table>
        <div class="pager"><el-pagination layout="total, prev, pager, next" :total="audit.state.total" :page-size="audit.state.pageSize" @current-change="(p: number) => audit.load(p)" /></div>
      </template>

      <template v-else-if="tab === 'logins'">
        <el-table :data="logins.state.items" v-loading="logins.state.loading" border size="small">
          <el-table-column label="时间" width="150"><template #default="{ row }">{{ fmtDateTime(row.created_at) }}</template></el-table-column>
          <el-table-column prop="username" label="用户名" width="110" />
          <el-table-column label="结果" width="80"><template #default="{ row }"><el-tag :type="row.success ? 'success' : 'danger'" size="small">{{ row.success ? '成功' : '失败' }}</el-tag></template></el-table-column>
          <el-table-column prop="reason" label="原因" width="120" />
          <el-table-column prop="ip" label="IP" width="120" />
          <el-table-column prop="user_agent" label="客户端" show-overflow-tooltip />
        </el-table>
        <div class="pager"><el-pagination layout="total, prev, pager, next" :total="logins.state.total" :page-size="logins.state.pageSize" @current-change="(p: number) => logins.load(p)" /></div>
      </template>

      <template v-else>
        <el-form label-width="200px" style="max-width: 640px">
          <el-form-item v-for="s in settings" :key="s.key" :label="s.description || s.key">
            <el-input v-if="typeof s.value === 'string' || s.value === null" v-model="s.value" />
            <el-input-number v-else v-model="s.value" />
          </el-form-item>
          <el-form-item><el-button type="primary" @click="saveSettings">保存设置</el-button></el-form-item>
        </el-form>
      </template>
    </div>

    <el-dialog v-model="userOpen" title="新建用户" width="480px">
      <el-form :model="nu" label-width="90px">
        <el-form-item label="用户名" required><el-input v-model="nu.username" /></el-form-item>
        <el-form-item label="姓名" required><el-input v-model="nu.display_name" /></el-form-item>
        <el-form-item label="邮箱"><el-input v-model="nu.email" /></el-form-item>
        <el-form-item label="初始密码"><el-input v-model="nu.password" type="password" show-password placeholder="首次登录需修改" /></el-form-item>
        <el-form-item label="角色"><el-select v-model="nu.role_codes" multiple><el-option v-for="r in roles" :key="r.code" :label="r.name" :value="r.code" /></el-select></el-form-item>
      </el-form>
      <template #footer><el-button @click="userOpen = false">取消</el-button><el-button type="primary" @click="saveUser">保存</el-button></template>
    </el-dialog>
    <el-dialog v-model="rolesOpen" :title="`分配角色 · ${editingUser?.display_name}`" width="440px">
      <el-checkbox-group v-model="userRoles">
        <el-checkbox v-for="r in roles" :key="r.code" :value="r.code">{{ r.name }}</el-checkbox>
      </el-checkbox-group>
      <template #footer><el-button @click="rolesOpen = false">取消</el-button><el-button type="primary" @click="saveRoles">保存</el-button></template>
    </el-dialog>
    <el-dialog v-model="roleOpen" title="角色权限" width="720px">
      <el-form :model="role" label-width="90px">
        <el-form-item label="编码" required><el-input v-model="role.code" :disabled="!!role.id" /></el-form-item>
        <el-form-item label="名称" required><el-input v-model="role.name" /></el-form-item>
        <el-form-item label="数据范围">
          <el-radio-group v-model="role.data_scope"><el-radio value="self">本人</el-radio><el-radio value="department">本部门及下级</el-radio><el-radio value="all">全部</el-radio></el-radio-group>
        </el-form-item>
        <el-form-item label="权限">
          <div class="perm-groups">
            <div v-for="(items, g) in permGroups" :key="g" class="perm-group">
              <b>{{ g }}</b>
              <el-checkbox-group v-model="role.permissions">
                <el-checkbox v-for="p in items" :key="p.code" :value="p.code">{{ p.name }}</el-checkbox>
              </el-checkbox-group>
            </div>
          </div>
        </el-form-item>
      </el-form>
      <template #footer><el-button @click="roleOpen = false">取消</el-button><el-button type="primary" @click="saveRole">保存</el-button></template>
    </el-dialog>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, reactive, ref } from 'vue'
import { ElMessageBox } from 'element-plus'
import { api } from '@/api/http'
import { useAuth } from '@/stores/auth'
import { act, usePaged } from '@/utils/usePaged'
import { fmtDateTime } from '@/utils/format'
import StatusTag from '@/components/StatusTag.vue'

const SCOPE: Record<string, string> = { self: '本人', department: '本部门及下级', all: '全部' }
const auth = useAuth()
const TAB_PERMS: [string, string][] = [['users', 'user:manage'], ['roles', 'role:manage'], ['audit', 'audit:read'],
  ['settings', 'settings:manage']]
const tab = ref(TAB_PERMS.find(([, p]) => auth.can(p))?.[0] ?? 'users') // first tab the user may open
const uq = ref('')
const urole = ref('')
const aq = ref('')
const users = usePaged('/api/users', () => ({ q: uq.value, role: urole.value }))
const audit = usePaged('/api/audit-logs', () => ({ action: aq.value }), 15)
const logins = usePaged('/api/login-logs', () => ({}), 15)
const roles = ref<any[]>([])
const perms = ref<any[]>([])
const settings = ref<any[]>([])
const userOpen = ref(false)
const nu = reactive<any>({})
const rolesOpen = ref(false)
const editingUser = ref<any>(null)
const userRoles = ref<string[]>([])
const roleOpen = ref(false)
const role = reactive<any>({ permissions: [] })
const roleName = (c: string) => roles.value.find((r) => r.code === c)?.name || c
const permGroups = computed(() => perms.value.reduce((m: Record<string, any[]>, p) => ((m[p.group] ||= []).push(p), m), {}))

async function load() {
  if (auth.can('user:manage') || auth.can('role:manage')) roles.value = await api.get('/api/roles')
  if (tab.value === 'users') users.load()
  if (tab.value === 'roles') perms.value = await api.get('/api/permissions')
  if (tab.value === 'audit') audit.load(1)
  if (tab.value === 'logins') logins.load(1)
  if (tab.value === 'settings') settings.value = await api.get('/api/settings')
}
function openUser() {
  Object.assign(nu, { username: '', display_name: '', email: '', password: '', role_codes: ['employee'] })
  userOpen.value = true
}
async function saveUser() {
  const body = { ...nu, email: nu.email || null, password: nu.password || null }
  if (await act(() => api.post('/api/users', body), '用户已创建')) {
    userOpen.value = false
    users.load()
  }
}
function openRoles(u: any) {
  editingUser.value = u
  userRoles.value = [...u.roles]
  rolesOpen.value = true
}
async function saveRoles() {
  if (await act(() => api.put(`/api/users/${editingUser.value.id}/roles`, { role_codes: userRoles.value }), '已保存')) {
    rolesOpen.value = false
    users.load()
  }
}
async function resetPw(u: any) {
  const { value } = await ElMessageBox.prompt(`为 ${u.display_name} 设置临时密码（8 位以上，含字母和数字；用户下次登录需修改）`, '重置密码',
    { inputType: 'password', inputValidator: (v) => /^(?=.*[A-Za-z])(?=.*\d).{8,64}$/.test(v || '') || '密码强度不足' })
  await act(() => api.post(`/api/users/${u.id}/reset-password`, { new_password: value }), '已重置')
}
async function unlock(u: any) {
  if (await act(() => api.post(`/api/users/${u.id}/unlock`), '已解锁')) users.load()
}
async function toggle(u: any) {
  const status = u.status === 'active' ? 'disabled' : 'active'
  if (status === 'disabled') await ElMessageBox.confirm(`停用 ${u.display_name}？其会话将失效，待办自动转交。`, '停用用户', { type: 'warning' })
  if (await act(() => api.post(`/api/users/${u.id}/status`, { status }), '已更新')) users.load()
}
async function openRole(r?: any) {
  if (!perms.value.length) perms.value = await api.get('/api/permissions')
  Object.keys(role).forEach((k) => delete role[k])
  Object.assign(role, r ? { ...r, permissions: [...r.permissions] } : { code: '', name: '', data_scope: 'self', permissions: ['dashboard:view'] })
  roleOpen.value = true
}
async function saveRole() {
  const body = { name: role.name, description: role.description || null, data_scope: role.data_scope, permissions: role.permissions }
  if (await act(() => (role.id ? api.put(`/api/roles/${role.id}`, body) : api.post('/api/roles', { code: role.code, ...body })), '已保存')) {
    roleOpen.value = false
    load()
  }
}
async function delRole(r: any) {
  await ElMessageBox.confirm(`删除角色 ${r.name}？`, '删除角色')
  if (await act(() => api.del(`/api/roles/${r.id}`), '已删除')) load()
}
async function saveSettings() {
  const values = Object.fromEntries(settings.value.filter((s) => s.value !== null).map((s) => [s.key, s.value]))
  await act(() => api.put('/api/settings', { values }), '设置已保存')
}
onMounted(load)
</script>

<style scoped>
.mr {
  margin-right: 4px;
}
.ml {
  margin-left: 4px;
}
.small {
  font-size: 12px;
}
.perm-groups {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 10px;
}
.perm-group {
  border: 1px solid var(--doe-border);
  border-radius: 8px;
  padding: 8px;
}
</style>
