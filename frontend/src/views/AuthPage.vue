<template>
  <main class="auth">
    <AfterSchoolScene />
    <section class="board" :aria-label="isRegister ? '注册' : '登录'">
      <p class="board-note">今日茶点：草莓蛋糕</p>
      <h1 class="title">放学后茶会</h1>
      <p class="sub">今天也一起练习，然后喝茶吧</p>

      <nav class="switch" aria-label="登录或注册">
        <router-link :to="{ name: 'login', query: route.query }" :class="{ on: !isRegister }" data-test="tab-login">登录</router-link>
        <router-link :to="{ name: 'register', query: route.query }" :class="{ on: isRegister }" data-test="tab-register">注册</router-link>
      </nav>

      <el-form ref="formRef" :model="form" :rules="rules" label-position="top" class="chalk-form" @submit.prevent="submit">
        <el-form-item label="用户名" prop="username">
          <el-input v-model="form.username" autocomplete="username" :placeholder="isRegister ? '3-20 位字母、数字或下划线' : '你的用户名'"
                    data-test="auth-username" />
        </el-form-item>
        <el-form-item label="密码" prop="password">
          <el-input v-model="form.password" type="password" show-password
                    :autocomplete="isRegister ? 'new-password' : 'current-password'"
                    :placeholder="isRegister ? '至少 8 位，含字母和数字' : '你的密码'" data-test="auth-password"
                    @keyup.enter="submit" />
        </el-form-item>
        <p v-if="notice" class="notice" role="status" data-test="auth-notice">{{ notice }}</p>
        <p v-if="error" class="error" role="alert" data-test="auth-error">{{ error }}</p>
        <button class="go" type="submit" :disabled="loading" data-test="auth-submit">
          {{ loading ? '请稍候…' : isRegister ? '注册' : '登录' }}
        </button>
      </el-form>

      <p class="foot">
        <template v-if="isRegister">已经有账号了？<router-link :to="{ name: 'login' }">去登录</router-link></template>
        <template v-else>还没有账号？<router-link :to="{ name: 'register' }">先注册一个</router-link></template>
        <span class="sep" />
        <router-link to="/dashboard" data-test="browse-as-visitor">先随便看看</router-link>
      </p>
      <div class="tray" aria-hidden="true"><i /><i /><i /><b /></div>
    </section>
  </main>
</template>

<script setup lang="ts">
import { computed, reactive, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import type { FormInstance, FormRules } from 'element-plus'
import { api, errorText } from '@/api/http'
import { useAuth } from '@/stores/auth'
import AfterSchoolScene from '@/components/AfterSchoolScene.vue'

const auth = useAuth()
const route = useRoute()
const router = useRouter()
const isRegister = computed(() => route.name === 'register')
const formRef = ref<FormInstance>()
const loading = ref(false)
const error = ref('')
const notice = ref((route.query.registered as string) ? '注册成功，请登录' : '')
const form = reactive({ username: (route.query.username as string) || '', password: '' })

const rules = computed<FormRules>(() => ({
  username: [
    { required: true, message: '请填写用户名', trigger: 'blur' },
    ...(isRegister.value ? [{ pattern: /^[A-Za-z0-9_.-]{3,20}$/, message: '3-20 位字母、数字、下划线、点或短横线', trigger: 'blur' }] : []),
  ],
  password: [
    { required: true, message: '请填写密码', trigger: 'blur' },
    ...(isRegister.value ? [{ pattern: /^(?=.*[A-Za-z])(?=.*\d).{8,64}$/, message: '至少 8 位，并同时包含字母和数字', trigger: 'blur' }] : []),
  ],
}))

watch(isRegister, () => {
  error.value = ''
  formRef.value?.clearValidate()
})

async function submit() {
  if (loading.value || !(await formRef.value?.validate().catch(() => false))) return
  loading.value = true
  error.value = ''
  notice.value = ''
  try {
    const username = form.username.trim()
    if (isRegister.value) {
      await api.post('/api/auth/register', { username, password: form.password })
      form.password = ''
      router.replace({ name: 'login', query: { username, registered: '1', redirect: route.query.redirect } })
      notice.value = '注册成功，请登录'
    } else {
      const me = await auth.login(username, form.password)
      router.replace(me.must_change_password ? '/profile?force=1' : (route.query.redirect as string) || '/dashboard')
    }
  } catch (e) {
    error.value = errorText(e)
  } finally {
    loading.value = false
  }
}
</script>

<style scoped>
.auth {
  --chalk: #f4f1e6;
  --chalk-dim: rgba(244, 241, 230, 0.62);
  --board: #2e4a3f;
  --wood: #8a5a35;
  --yellow: #f6d365;
  --sakura: #f28ca0;
  position: relative;
  min-height: 100vh;
  display: flex;
  align-items: center;
  justify-content: flex-end;
  padding: 40px clamp(16px, 7vw, 120px);
  overflow: hidden;
  font-family: 'PingFang SC', 'Microsoft YaHei', 'Noto Sans SC', system-ui, sans-serif;
}
.board {
  position: relative;
  width: min(440px, 100%);
  padding: 34px 40px 46px;
  background: radial-gradient(120% 90% at 30% 20%, #36594b 0%, var(--board) 60%, #263d34 100%);
  border: 14px solid var(--wood);
  border-radius: 10px;
  box-shadow: 0 24px 60px rgba(60, 25, 30, 0.45), inset 0 0 40px rgba(0, 0, 0, 0.35);
  color: var(--chalk);
}
.board-note {
  position: absolute;
  top: 14px;
  right: 18px;
  margin: 0;
  font-family: 'KaiTi', 'STKaiti', 'Kaiti SC', serif;
  font-size: 14px;
  color: #fbc8d6;
  transform: rotate(3deg);
}
.title {
  margin: 10px 0 2px;
  font-family: 'KaiTi', 'STKaiti', 'Kaiti SC', serif;
  font-size: clamp(40px, 6vw, 54px);
  font-weight: 700;
  letter-spacing: 0.08em;
  line-height: 1.15;
  text-shadow: 0 0 1px rgba(244, 241, 230, 0.9), 1px 1px 0 rgba(244, 241, 230, 0.25);
}
.sub {
  margin: 0 0 22px;
  font-family: 'KaiTi', 'STKaiti', 'Kaiti SC', serif;
  font-size: 18px;
  color: var(--chalk-dim);
}
.switch {
  display: flex;
  gap: 26px;
  margin-bottom: 18px;
}
.switch a {
  color: var(--chalk-dim);
  text-decoration: none;
  font-size: 18px;
  padding-bottom: 4px;
  border-bottom: 3px solid transparent;
}
.switch a.on {
  color: var(--chalk);
  border-bottom-color: var(--yellow);
}
.switch a:focus-visible,
.foot a:focus-visible,
.go:focus-visible {
  outline: 3px solid var(--yellow);
  outline-offset: 3px;
  border-radius: 4px;
}
.chalk-form :deep(.el-form-item__label) {
  color: var(--chalk);
  font-size: 15px;
}
.chalk-form :deep(.el-input__wrapper) {
  background: rgba(244, 241, 230, 0.07);
  box-shadow: inset 0 -2px 0 var(--chalk-dim);
  border-radius: 4px 4px 0 0;
  padding: 4px 10px;
}
.chalk-form :deep(.el-input__wrapper.is-focus) {
  box-shadow: inset 0 -3px 0 var(--yellow);
}
.chalk-form :deep(.el-input__inner) {
  color: var(--chalk);
  font-size: 16px;
  height: 36px;
}
.chalk-form :deep(.el-input__inner::placeholder) {
  color: rgba(244, 241, 230, 0.4);
}
.chalk-form :deep(.el-input__password),
.chalk-form :deep(.el-input__clear) {
  color: var(--chalk-dim);
}
.chalk-form :deep(.el-form-item__error) {
  color: #ffb3c2;
}
.notice,
.error {
  margin: 0 0 12px;
  font-size: 14px;
}
.notice {
  color: #c9f0c9;
}
.error {
  color: #ffb3c2;
}
.go {
  width: 100%;
  margin-top: 6px;
  padding: 12px 0;
  border: none;
  border-radius: 999px;
  background: var(--yellow);
  color: #263d34;
  font-size: 17px;
  font-weight: 700;
  letter-spacing: 0.2em;
  cursor: pointer;
  box-shadow: 0 4px 0 #c9a23d;
}
.go:hover {
  background: #f9dd84;
}
.go:active {
  transform: translateY(2px);
  box-shadow: 0 2px 0 #c9a23d;
}
.go:disabled {
  opacity: 0.7;
  cursor: wait;
}
.foot {
  margin: 18px 0 0;
  font-size: 14px;
  color: var(--chalk-dim);
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 4px;
}
.foot a {
  color: var(--chalk);
}
.sep {
  flex: 1;
}
.tray {
  position: absolute;
  left: -14px;
  right: -14px;
  bottom: -22px;
  height: 14px;
  background: #74472a;
  border-radius: 0 0 6px 6px;
  display: flex;
  align-items: center;
  gap: 10px;
  padding-left: 40px;
}
.tray i {
  width: 34px;
  height: 7px;
  border-radius: 4px;
  background: #fffdf6;
  margin-top: -10px;
}
.tray i:nth-child(2) {
  background: #fbc8d6;
}
.tray i:nth-child(3) {
  background: var(--yellow);
}
.tray b {
  width: 46px;
  height: 14px;
  margin-top: -12px;
  margin-left: auto;
  margin-right: 40px;
  border-radius: 3px;
  background: linear-gradient(#5d6f8a 0 45%, #e9e2d0 45%);
}
@media (max-width: 900px) {
  .auth {
    justify-content: center;
    align-items: flex-start;
    padding-top: 12vh;
  }
}
@media (max-width: 480px) {
  .board {
    padding: 26px 22px 38px;
    border-width: 10px;
  }
}
</style>
