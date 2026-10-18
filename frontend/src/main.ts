import { createApp } from 'vue'
import { createPinia } from 'pinia'
import ElementPlus, { ElMessage } from 'element-plus'
import zhCn from 'element-plus/es/locale/lang/zh-cn'
import * as Icons from '@element-plus/icons-vue'
import 'element-plus/dist/index.css'
import 'element-plus/theme-chalk/dark/css-vars.css'
import './styles/theme.css'
import App from './App.vue'
import { router } from './router'
import { onAuthProblem } from './api/http'
import { promptLogin } from './utils/loginPrompt'
import { useAuth } from './stores/auth'
import { useApp } from './stores/app'

const app = createApp(App)
const pinia = createPinia()
app.use(pinia)
app.use(router)
app.use(ElementPlus, { locale: zhCn })
for (const [name, comp] of Object.entries(Icons)) app.component(name, comp)

onAuthProblem({
  unauthorized: (err) => {
    const auth = useAuth()
    if (err.code === 'LOGIN_REQUIRED' && !auth.token) {
      promptLogin()
    } else if (auth.token) {
      auth.logout(false)
      ElMessage.warning('登录已失效，请重新登录')
      router.push({ name: 'login', query: { redirect: router.currentRoute.value.fullPath } })
    }
  },
  passwordChange: () => {
    router.push({ name: 'profile', query: { force: '1' } })
  },
})

useApp().applyTheme()
app.mount('#app')
