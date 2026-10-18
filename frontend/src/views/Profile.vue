<template>
  <div class="page">
    <div class="page-head"><div><h2>个人中心</h2><div class="sub">{{ auth.me?.display_name }} · {{ auth.me?.employee?.department_name }} {{ auth.me?.employee?.position_name }}</div></div></div>
    <el-alert v-if="force" type="warning" show-icon :closable="false" class="mb" title="首次登录或密码已被重置：请先修改密码，修改后才能使用其他功能。" />
    <div class="grid cols-2">
      <div class="card">
        <h3>修改密码</h3>
        <el-form ref="formRef" :model="pw" :rules="rules" label-width="90px" @submit.prevent>
          <el-form-item label="原密码" prop="old_password"><el-input v-model="pw.old_password" type="password" show-password data-test="old-password" /></el-form-item>
          <el-form-item label="新密码" prop="new_password"><el-input v-model="pw.new_password" type="password" show-password data-test="new-password" /></el-form-item>
          <el-form-item label="确认新密码" prop="confirm"><el-input v-model="pw.confirm" type="password" show-password data-test="confirm-password" /></el-form-item>
          <el-form-item><el-button type="primary" data-test="change-password" @click="change">保存</el-button></el-form-item>
        </el-form>
        <div class="muted small">8-64 位，需同时包含字母和数字；修改后其他设备上的登录会失效。</div>
      </div>
      <div class="card">
        <h3>登录会话</h3>
        <el-table :data="sessions" size="small" border>
          <el-table-column label="登录时间" width="140"><template #default="{ row }">{{ fmtDateTime(row.created_at) }}</template></el-table-column>
          <el-table-column prop="ip" label="IP" width="110" />
          <el-table-column label="当前" width="60"><template #default="{ row }">{{ row.current ? '是' : '' }}</template></el-table-column>
          <el-table-column><template #default="{ row }"><el-button v-if="!row.current" link type="danger" @click="revoke(row)">注销</el-button></template></el-table-column>
        </el-table>
        <h3>最近登录记录</h3>
        <el-table :data="logs" size="small" border>
          <el-table-column label="时间" width="140"><template #default="{ row }">{{ fmtDateTime(row.created_at) }}</template></el-table-column>
          <el-table-column label="结果" width="80"><template #default="{ row }"><el-tag :type="row.success ? 'success' : 'danger'" size="small">{{ row.success ? '成功' : '失败' }}</el-tag></template></el-table-column>
          <el-table-column prop="ip" label="IP" />
        </el-table>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, reactive, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import type { FormInstance, FormRules } from 'element-plus'
import { api } from '@/api/http'
import { useAuth } from '@/stores/auth'
import { act } from '@/utils/usePaged'
import { fmtDateTime } from '@/utils/format'

const auth = useAuth()
const route = useRoute()
const router = useRouter()
const force = computed(() => route.query.force === '1' || auth.me?.must_change_password)
const formRef = ref<FormInstance>()
const pw = reactive({ old_password: '', new_password: '', confirm: '' })
const rules: FormRules = {
  old_password: [{ required: true, message: '请输入原密码' }],
  new_password: [{ required: true, message: '请输入新密码' },
    { validator: (_r, v, cb) => (/^(?=.*[A-Za-z])(?=.*\d).{8,64}$/.test(v) ? cb() : cb(new Error('8-64 位，含字母和数字'))), trigger: 'blur' }],
  confirm: [{ validator: (_r, v, cb) => (v === pw.new_password ? cb() : cb(new Error('两次输入不一致'))), trigger: 'blur' }],
}
const sessions = ref<any[]>([])
const logs = ref<any[]>([])

async function load() {
  sessions.value = await api.get('/api/auth/sessions')
  logs.value = await api.get('/api/auth/login-logs')
}
async function change() {
  if (!(await formRef.value?.validate().catch(() => false))) return
  if (await act(() => api.post('/api/auth/change-password', { old_password: pw.old_password, new_password: pw.new_password }), '密码已修改')) {
    await auth.fetchMe()
    Object.assign(pw, { old_password: '', new_password: '', confirm: '' })
    if (route.query.force) router.replace('/dashboard')
    else load()
  }
}
async function revoke(row: any) {
  if (await act(() => api.del(`/api/auth/sessions/${row.id}`), '已注销')) load()
}
onMounted(load)
</script>

<style scoped>
.mb {
  margin-bottom: 16px;
}
.small {
  font-size: 12px;
}
h3 {
  margin-top: 0;
}
</style>
