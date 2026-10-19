<template>
  <main class="auth">
    <aside class="art">
      <AfterSchoolScene />
      <p class="art-note">今日茶点：草莓蛋糕</p>
    </aside>
    <section class="panel" :aria-label="isRegister ? '注册' : '登录'">
      <div class="panel-inner">
        <router-link to="/dashboard" class="brand" aria-label="返回首页">
          <img src="/teacup.svg" alt="" class="logo" />
          <span class="brand-name">放学后茶会</span>
          <span class="brand-sub" lang="ja">けいおん</span>
        </router-link>

        <h1 class="title">{{ isRegister ? '创建账号' : '欢迎回来' }}</h1>
        <p class="sub">{{ isRegister ? '只需要用户名和密码，注册后再登录。' : '今天也一起练习，然后喝茶吧。' }}</p>

        <nav class="switch" aria-label="登录或注册">
          <router-link :to="{ name: 'login', query: route.query }" :class="{ on: !isRegister }" data-test="tab-login">登录</router-link>
          <router-link :to="{ name: 'register', query: route.query }" :class="{ on: isRegister }" data-test="tab-register">注册</router-link>
        </nav>

        <el-form ref="formRef" :model="form" :rules="rules" label-position="top" class="form" @submit.prevent="submit">
          <el-form-item label="用户名" prop="username">
            <el-input v-model="form.username" size="large" autocomplete="username"
                      :placeholder="isRegister ? '3-20 位字母、数字或下划线' : '你的用户名'" data-test="auth-username" />
          </el-form-item>
          <el-form-item label="密码" prop="password">
            <el-input v-model="form.password" size="large" type="password" show-password
                      :autocomplete="isRegister ? 'new-password' : 'current-password'"
                      :placeholder="isRegister ? '至少 8 位，含字母和数字' : '你的密码'" data-test="auth-password"
                      @keyup.enter="submit" />
          </el-form-item>
          <p v-if="notice" class="notice" role="status" data-test="auth-notice">{{ notice }}</p>
          <p v-if="error" class="error" role="alert" data-test="auth-error">{{ error }}</p>
          <el-button class="go" type="primary" size="large" native-type="submit" :loading="loading" data-test="auth-submit">
            {{ loading ? '请稍候…' : isRegister ? '注册' : '登录' }}
          </el-button>
        </el-form>

        <p class="foot">
          <template v-if="isRegister">已经有账号了？<router-link :to="{ name: 'login' }">去登录</router-link></template>
          <template v-else>还没有账号？<router-link :to="{ name: 'register' }">先注册一个</router-link></template>
        </p>
        <router-link to="/dashboard" class="visit" data-test="browse-as-visitor">先随便看看，不登录</router-link>
      </div>
    </section>
  </main>
</template>
<script setup lang="ts">
import { computed, reactive, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessageBox, type FormInstance, type FormRules } from 'element-plus'
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
      loading.value = false
      // Confirm first, then move to the login form with the new username filled in.
      await ElMessageBox.alert(`账号「${username}」已创建。确认后前往登录页，用刚设置的密码登录。`, '注册成功', {
        type: 'success', confirmButtonText: '去登录', showClose: false, closeOnPressEscape: false,
        customClass: 'register-done',
      }).catch(() => undefined)
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
  min-height: 100vh;
  display: grid;
  grid-template-columns: minmax(0, 1.15fr) minmax(400px, 1fr);
  background: var(--doe-surface);
}
.art {
  position: relative;
  overflow: hidden;
  margin: 12px 0 12px 12px;
  border-radius: 22px;
}
.art-note {
  position: absolute;
  left: 20px;
  bottom: 20px;
  margin: 0;
  padding: 6px 12px;
  border-radius: 999px;
  font-size: 13px;
  color: #3b2a2e;
  background: rgba(255, 255, 255, 0.78);
  backdrop-filter: blur(8px);
  -webkit-backdrop-filter: blur(8px);
}
.panel {
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 48px 24px;
}
.panel-inner {
  width: min(380px, 100%);
}
.brand {
  display: inline-flex;
  align-items: center;
  gap: 8px;
  color: var(--doe-text);
  text-decoration: none;
  margin-bottom: 40px;
}
.logo {
  width: 30px;
  height: 30px;
  padding: 4px;
  border-radius: 8px;
  background: var(--doe-brand-soft);
}
.brand-name {
  font-weight: 650;
}
.brand-sub {
  font-size: 12px;
  color: var(--doe-muted);
}
.title {
  margin: 0 0 8px;
  font-size: 30px;
  line-height: 1.2;
  font-weight: 700;
  letter-spacing: -0.02em;
}
.sub {
  margin: 0 0 28px;
  color: var(--doe-muted);
  font-size: 15px;
}
.switch {
  display: grid;
  grid-template-columns: 1fr 1fr;
  padding: 4px;
  margin-bottom: 24px;
  border-radius: 12px;
  background: var(--doe-hover);
}
.switch a {
  padding: 8px 0;
  border-radius: 9px;
  text-align: center;
  font-size: 14px;
  font-weight: 500;
  color: var(--doe-muted);
  text-decoration: none;
  transition: background-color 0.12s, color 0.12s;
}
.switch a.on {
  background: var(--doe-surface);
  color: var(--doe-text);
  box-shadow: 0 1px 2px rgba(20, 20, 30, 0.08), 0 0 0 1px var(--doe-border);
}
.form :deep(.el-form-item__label) {
  font-weight: 500;
  color: var(--doe-text);
}
.notice,
.error {
  margin: -4px 0 14px;
  font-size: 14px;
}
.notice {
  color: var(--el-color-success);
}
.error {
  color: var(--el-color-danger);
}
.go {
  width: 100%;
  margin-top: 4px;
  height: 44px;
  font-size: 15px;
}
.foot {
  margin: 22px 0 8px;
  font-size: 14px;
  color: var(--doe-muted);
}
.foot a,
.visit {
  color: var(--doe-brand);
  font-weight: 500;
  text-decoration: none;
}
.foot a:hover,
.visit:hover {
  text-decoration: underline;
}
.visit {
  font-size: 14px;
}
@media (prefers-reduced-motion: reduce) {
  .switch a {
    transition: none;
  }
}
@media (max-width: 900px) {
  .auth {
    grid-template-columns: minmax(0, 1fr);
    grid-template-rows: 220px auto;
  }
  .art {
    margin: 12px 12px 0;
  }
  .panel {
    align-items: flex-start;
    padding: 32px 16px 40px;
  }
  .brand {
    margin-bottom: 24px;
  }
}
</style>