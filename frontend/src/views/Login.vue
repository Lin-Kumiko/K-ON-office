<template>
  <div class="login-page">
    <div class="hero">
      <img src="/teacup.svg" alt="" class="cup" />
      <h1>放课后茶会株式会社</h1>
      <p>DragonOffice Enterprise · OA / HRM / 工作流一体化平台</p>
      <ul>
        <li>审批、考勤、请假、报销，一个地方搞定</li>
        <li>认真工作，然后喝茶 ☕</li>
      </ul>
    </div>
    <el-card class="box" shadow="never">
      <h2>登录</h2>
      <el-form ref="formRef" :model="form" :rules="rules" label-position="top" @submit.prevent="submit">
        <el-form-item label="用户名" prop="username">
          <el-input v-model="form.username" autocomplete="username" placeholder="例如 yui" data-test="login-username" />
        </el-form-item>
        <el-form-item label="密码" prop="password">
          <el-input v-model="form.password" type="password" show-password autocomplete="current-password"
                    data-test="login-password" @keyup.enter="submit" />
        </el-form-item>
        <el-alert v-if="error" :title="error" type="error" show-icon :closable="false" class="err" />
        <el-button type="primary" native-type="submit" :loading="loading" class="btn" data-test="login-submit">登录</el-button>
      </el-form>
      <p class="muted tip">全部数据为合成数据；初始账号见项目 README。</p>
      <el-button text size="small" @click="app.toggleTheme()">{{ app.theme === 'dark' ? '浅色模式' : '深色模式' }}</el-button>
    </el-card>
  </div>
</template>

<script setup lang="ts">
import { reactive, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import type { FormInstance, FormRules } from 'element-plus'
import { errorText } from '@/api/http'
import { useAuth } from '@/stores/auth'
import { useApp } from '@/stores/app'

const auth = useAuth()
const app = useApp()
const router = useRouter()
const route = useRoute()
const formRef = ref<FormInstance>()
const loading = ref(false)
const error = ref('')
const form = reactive({ username: '', password: '' })
const rules: FormRules = {
  username: [{ required: true, message: '请输入用户名', trigger: 'blur' }],
  password: [{ required: true, message: '请输入密码', trigger: 'blur' }],
}

async function submit() {
  if (!(await formRef.value?.validate().catch(() => false))) return
  loading.value = true
  error.value = ''
  try {
    const me = await auth.login(form.username.trim(), form.password)
    router.replace(me.must_change_password ? '/profile?force=1' : (route.query.redirect as string) || '/dashboard')
  } catch (e) {
    error.value = errorText(e)
  } finally {
    loading.value = false
  }
}
</script>

<style scoped>
.login-page {
  min-height: 100vh;
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 60px;
  padding: 24px;
  background: radial-gradient(circle at 20% 20%, #fde3ea 0, transparent 40%),
    radial-gradient(circle at 80% 80%, #f6e0cc 0, transparent 45%), var(--doe-bg);
  flex-wrap: wrap;
}
:global(html.dark) .login-page {
  background: var(--doe-bg);
}
.hero {
  max-width: 420px;
}
.hero h1 {
  font-size: 30px;
  margin: 12px 0 6px;
  color: var(--doe-brand);
}
.hero ul {
  padding-left: 18px;
  color: var(--doe-muted);
  line-height: 1.9;
}
.cup {
  width: 72px;
}
.box {
  width: 360px;
  max-width: 100%;
  border-radius: 16px;
}
.btn {
  width: 100%;
}
.err {
  margin-bottom: 12px;
}
.tip {
  font-size: 12px;
}
</style>
