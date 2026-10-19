<template>
  <el-container class="layout">
    <el-aside v-if="!mobile" :width="app.collapsed ? '68px' : '232px'" class="aside">
      <SideMenu :collapsed="app.collapsed" />
    </el-aside>
    <el-drawer v-else v-model="drawer" direction="ltr" size="248px" :with-header="false" class="menu-drawer">
      <SideMenu :collapsed="false" @navigate="drawer = false" />
    </el-drawer>
    <el-container>
      <el-header class="header">
        <el-button text circle @click="mobile ? (drawer = true) : (app.collapsed = !app.collapsed)" aria-label="切换菜单">
          <el-icon size="18"><Fold v-if="!app.collapsed" /><Expand v-else /></el-icon>
        </el-button>
        <span class="title">{{ route.meta.title }}</span>
        <span class="spacer" />
        <el-tooltip :content="app.theme === 'dark' ? '切换浅色' : '切换深色'">
          <el-button text circle data-test="theme-toggle" @click="app.toggleTheme()" aria-label="切换主题">
            <el-icon size="18"><Moon v-if="app.theme === 'light'" /><Sunny v-else /></el-icon>
          </el-button>
        </el-tooltip>
        <template v-if="!auth.loggedIn">
          <el-button data-test="header-login" @click="router.push({ name: 'login', query: { redirect: route.fullPath } })">登录</el-button>
          <el-button type="primary" data-test="header-register" @click="router.push({ name: 'register' })">注册</el-button>
        </template>
        <el-popover v-if="auth.loggedIn" placement="bottom-end" :width="340" trigger="click" @show="loadNotes">
          <template #reference>
            <el-badge :value="app.unread" :hidden="!app.unread" :max="99" class="bell">
              <el-button text circle aria-label="通知" data-test="bell"><el-icon size="18"><Bell /></el-icon></el-button>
            </el-badge>
          </template>
          <div class="notes">
            <div class="notes-head">
              <b>站内通知</b>
              <el-button link type="primary" size="small" @click="readAll">全部已读</el-button>
            </div>
            <el-empty v-if="!notes.length" description="暂无未读通知" :image-size="60" />
            <div v-for="n in notes" :key="n.id" class="note" @click="openNote(n)">
              <div class="note-title">{{ n.title }}</div>
              <div class="muted note-time">{{ fmtDateTime(n.created_at) }}</div>
            </div>
            <el-button link type="primary" @click="router.push('/notifications')">查看全部通知历史</el-button>
          </div>
        </el-popover>
        <el-dropdown v-if="auth.loggedIn" @command="onCommand">
          <span class="user">
            <el-avatar :size="28" class="avatar">{{ initial }}</el-avatar>
            <span class="uname">{{ auth.me?.display_name }}</span>
          </span>
          <template #dropdown>
            <el-dropdown-menu>
              <el-dropdown-item disabled>{{ auth.me?.role_names.join(' / ') }}</el-dropdown-item>
              <el-dropdown-item command="profile" divided>个人中心 / 修改密码</el-dropdown-item>
              <el-dropdown-item command="logout" data-test="logout">退出登录</el-dropdown-item>
            </el-dropdown-menu>
          </template>
        </el-dropdown>
      </el-header>
      <el-main class="main">
        <router-view v-slot="{ Component, route: r }">
          <transition name="view">
            <component :is="Component" :key="r.path" />
          </transition>
        </router-view>
      </el-main>
    </el-container>
  </el-container>
</template>

<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useAuth } from '@/stores/auth'
import { useApp } from '@/stores/app'
import { api } from '@/api/http'
import { fmtDateTime } from '@/utils/format'
import SideMenu from '@/components/SideMenu.vue'

const auth = useAuth()
const app = useApp()
const route = useRoute()
const router = useRouter()
const drawer = ref(false)
const mobile = ref(window.innerWidth < 768)
const notes = ref<any[]>([])
const initial = computed(() => (auth.me?.display_name || '?').slice(0, 1))
let timer: number | undefined

function onResize() {
  mobile.value = window.innerWidth < 768
}

async function loadNotes() {
  notes.value = (await api.get('/api/notifications', { unread_only: true, page_size: 8 })).items
}

async function openNote(n: any) {
  await api.post(`/api/notifications/${n.id}/read`)
  app.refreshUnread()
  if (n.link) router.push(n.link)
}

async function readAll() {
  await api.post('/api/notifications/read-all')
  notes.value = []
  app.refreshUnread()
}

async function onCommand(cmd: string) {
  if (cmd === 'profile') router.push('/profile')
  if (cmd === 'logout') {
    await auth.logout()
    router.push('/dashboard')
  }
}

onMounted(() => {
  window.addEventListener('resize', onResize)
  if (auth.loggedIn) app.refreshUnread()
  timer = window.setInterval(() => auth.loggedIn && app.refreshUnread(), 30000)
})
onUnmounted(() => {
  window.removeEventListener('resize', onResize)
  window.clearInterval(timer)
})
</script>

<style scoped>
.layout {
  height: 100vh;
}
.aside {
  transition: width 0.2s;
  overflow-x: hidden;
}
.header {
  position: sticky;
  top: 0;
  z-index: 10;
  display: flex;
  align-items: center;
  gap: 6px;
  height: 60px;
  padding: 0 20px 0 14px;
  background: var(--glass-bg);
  backdrop-filter: var(--glass-blur);
  -webkit-backdrop-filter: var(--glass-blur);
  border-bottom: 1px solid var(--glass-border);
  box-shadow: 0 1px 0 var(--glass-edge);
}
.title {
  margin-left: 4px;
  font-weight: 600;
  font-size: 15px;
}
.spacer {
  flex: 1;
}
.header .el-button + .el-button {
  margin-left: 0;
}
.bell {
  margin: 0 2px;
}
.user {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-left: 6px;
  padding: 4px 10px 4px 4px;
  border-radius: 999px;
  border: 1px solid var(--glass-border);
  background: var(--glass-bg);
  box-shadow: 0 0 0 1px var(--glass-edge);
  cursor: pointer;
  outline: none;
  font-size: 14px;
}
.user:hover {
  background: var(--doe-hover);
}
.avatar {
  background: var(--doe-brand);
  color: #fff;
  font-weight: 600;
  font-size: 13px;
}
.main {
  padding: 0;
  position: relative;
  overflow-y: auto;
  overflow-x: hidden;
  background: transparent;
}
/* the outgoing page fades in place while the next one slides in on top */
.main > .view-leave-active {
  position: absolute;
  top: 0;
  left: 0;
  right: 0;
  pointer-events: none;
}
.notes-head {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 8px;
}
.note {
  padding: 9px 8px;
  border-radius: 8px;
  cursor: pointer;
}
.note:hover {
  background: var(--doe-hover);
}
.note-title {
  font-size: 13px;
}
.note-time {
  font-size: 12px;
}
@media (max-width: 720px) {
  .uname {
    display: none;
  }
  .user {
    padding: 2px;
  }
}
</style>