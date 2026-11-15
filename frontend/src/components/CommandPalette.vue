<template>
  <Teleport to="body">
    <Transition name="palette">
      <div v-if="app.palette" class="palette-mask" data-test="palette" @mousedown.self="close">
        <div class="palette glass" role="dialog" aria-modal="true" aria-label="快速跳转">
          <div class="search">
            <el-icon class="search-icon"><Search /></el-icon>
            <input ref="input" v-model="query" class="search-input" type="text" placeholder="搜索页面或操作" autocomplete="off"
                   spellcheck="false" role="combobox" aria-expanded="true" aria-controls="palette-list"
                   :aria-activedescendant="items[index] ? `palette-${index}` : undefined" data-test="palette-input"
                   @keydown="onKey" />
            <kbd>Esc</kbd>
          </div>
          <div id="palette-list" ref="list" class="list" role="listbox">
            <p v-if="!items.length" class="empty">没有找到“{{ query }}”。试试页面名称，比如“请假”或“报销”。</p>
            <template v-for="(it, i) in items" :key="it.id">
              <div v-if="i === 0 || items[i - 1].group !== it.group" class="group">{{ it.group }}</div>
              <div :id="`palette-${i}`" class="option" :class="{ on: i === index }" role="option" :aria-selected="i === index"
                   @mousemove="index = i" @click="run(it)">
                <el-icon class="option-icon"><component :is="it.icon" /></el-icon>
                <span class="option-title">{{ it.title }}</span>
                <el-icon v-if="it.locked" class="option-lock" aria-label="需要登录"><Lock /></el-icon>
                <span v-if="it.hint" class="option-hint">{{ it.hint }}</span>
              </div>
            </template>
          </div>
          <div class="foot">
            <span><kbd>↑</kbd><kbd>↓</kbd>选择</span>
            <span><kbd>Enter</kbd>打开</span>
            <span class="foot-right"><kbd>{{ modKey }}</kbd><kbd>K</kbd>随时呼出</span>
          </div>
        </div>
      </div>
    </Transition>
  </Teleport>
</template>

<script setup lang="ts">
import { computed, nextTick, onMounted, onUnmounted, ref, watch } from 'vue'
import { useRouter } from 'vue-router'
import { useAuth } from '@/stores/auth'
import { useApp } from '@/stores/app'
import { visibleMenus } from '@/utils/menus'

interface Item {
  id: string
  group: string
  title: string
  icon: string
  keywords: string
  hint?: string
  locked?: boolean
  action: () => void
}

const auth = useAuth()
const app = useApp()
const router = useRouter()
const query = ref('')
const index = ref(0)
const input = ref<HTMLInputElement>()
const list = ref<HTMLElement>()
const modKey = /Mac|iPhone|iPad/.test(navigator.platform) ? '⌘' : 'Ctrl'
let lastFocus: HTMLElement | null = null

const all = computed<Item[]>(() => {
  const pages: Item[] = visibleMenus(auth).map((m) => ({
    id: `page-${m.name}`, group: '页面', title: m.title, icon: m.icon, keywords: `${m.title} ${m.name}`.toLowerCase(),
    locked: m.locked, action: () => router.push(m.path),
  }))
  const actions: Item[] = [
    { id: 'theme', group: '操作', title: app.theme === 'dark' ? '切换到浅色主题' : '切换到深色主题',
      icon: app.theme === 'dark' ? 'Sunny' : 'Moon', keywords: '主题 深色 浅色 夜间 theme dark light',
      action: () => app.toggleTheme({ x: window.innerWidth / 2, y: window.innerHeight / 2 }) },
  ]
  if (auth.loggedIn) {
    actions.push(
      { id: 'notifications', group: '操作', title: '查看通知历史', icon: 'Bell', keywords: '通知 消息 notifications',
        hint: app.unread ? `${app.unread} 条未读` : undefined, action: () => router.push('/notifications') },
      { id: 'profile', group: '操作', title: '个人中心与修改密码', icon: 'User', keywords: '个人中心 密码 profile password',
        action: () => router.push('/profile') },
      { id: 'logout', group: '操作', title: '退出登录', icon: 'SwitchButton', keywords: '退出 登出 logout',
        action: async () => { await auth.logout(); router.push('/dashboard') } },
    )
  } else {
    actions.push(
      { id: 'login', group: '操作', title: '登录', icon: 'Key', keywords: '登录 login',
        action: () => router.push({ name: 'login', query: { redirect: router.currentRoute.value.fullPath } }) },
      { id: 'register', group: '操作', title: '注册账号', icon: 'EditPen', keywords: '注册 register',
        action: () => router.push({ name: 'register' }) },
    )
  }
  return [...pages, ...actions]
})

const items = computed(() => {
  const words = query.value.trim().toLowerCase().split(/\s+/).filter(Boolean)
  return words.length ? all.value.filter((it) => words.every((w) => it.keywords.includes(w))) : all.value
})

function close() {
  app.palette = false
}

function run(it: Item) {
  close()
  it.action()
}

function onKey(e: KeyboardEvent) {
  if (e.isComposing) return
  const n = items.value.length
  if (e.key === 'ArrowDown' || e.key === 'ArrowUp') {
    e.preventDefault()
    if (n) index.value = (index.value + (e.key === 'ArrowDown' ? 1 : n - 1)) % n
    nextTick(() => list.value?.querySelector('.option.on')?.scrollIntoView({ block: 'nearest' }))
  } else if (e.key === 'Enter') {
    e.preventDefault()
    if (items.value[index.value]) run(items.value[index.value])
  } else if (e.key === 'Escape') {
    e.preventDefault()
    close()
  } else if (e.key === 'Tab') {
    e.preventDefault() // focus stays in the search box while the palette is open
  }
}

function onGlobalKey(e: KeyboardEvent) {
  if ((e.ctrlKey || e.metaKey) && !e.altKey && !e.shiftKey && e.key.toLowerCase() === 'k') {
    e.preventDefault()
    app.palette = !app.palette
  }
}

watch(query, () => {
  index.value = 0
})
watch(() => app.palette, (open) => {
  if (open) {
    lastFocus = document.activeElement as HTMLElement | null
    query.value = ''
    index.value = 0
    nextTick(() => input.value?.focus())
  } else {
    lastFocus?.focus?.()
  }
})
onMounted(() => window.addEventListener('keydown', onGlobalKey))
onUnmounted(() => {
  window.removeEventListener('keydown', onGlobalKey)
  app.palette = false
})
</script>

<style scoped>
.palette-mask {
  position: fixed;
  inset: 0;
  z-index: 3000;
  display: flex;
  justify-content: center;
  align-items: flex-start;
  padding: 14vh 16px 16px;
  background: rgba(20, 16, 28, 0.32);
  -webkit-backdrop-filter: blur(4px);
  backdrop-filter: blur(4px);
}
.palette {
  width: min(600px, 100%);
  max-height: min(520px, 70vh);
  display: flex;
  flex-direction: column;
  border-radius: 18px;
  background: var(--glass-bg-strong);
  box-shadow: inset 0 1px 0 var(--glass-highlight), 0 0 0 1px var(--glass-edge), 0 40px 90px -30px rgba(30, 14, 40, 0.55);
  overflow: hidden;
}
.search {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 0 18px;
  height: 58px;
  border-bottom: 1px solid var(--doe-border);
  flex: none;
}
.search-icon {
  font-size: 18px;
  color: var(--doe-muted);
}
.search-input {
  flex: 1;
  min-width: 0;
  border: none;
  outline: none;
  background: none;
  color: var(--doe-text);
  font: inherit;
  font-size: 16px;
}
.search-input::placeholder {
  color: var(--doe-faint);
}
.list {
  flex: 1;
  overflow-y: auto;
  padding: 6px 8px 8px;
}
.group {
  padding: 10px 10px 4px;
  font-size: 12px;
  color: var(--doe-faint);
}
.option {
  display: flex;
  align-items: center;
  gap: 12px;
  height: 40px;
  padding: 0 10px;
  border-radius: 10px;
  font-size: 14px;
  cursor: pointer;
}
.option.on {
  background: var(--doe-brand-soft);
  color: var(--doe-brand);
}
.option-icon {
  font-size: 17px;
  flex: none;
}
.option-title {
  flex: 1;
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.option-lock {
  font-size: 12px;
  color: var(--doe-faint);
}
.option-hint {
  font-size: 12px;
  color: var(--doe-muted);
}
.empty {
  margin: 0;
  padding: 28px 16px;
  text-align: center;
  color: var(--doe-muted);
  font-size: 14px;
}
.foot {
  display: flex;
  gap: 16px;
  align-items: center;
  padding: 10px 16px;
  border-top: 1px solid var(--doe-border);
  font-size: 12px;
  color: var(--doe-muted);
  flex: none;
}
.foot span {
  display: inline-flex;
  align-items: center;
  gap: 4px;
}
.foot-right {
  margin-left: auto;
}
.palette-enter-active,
.palette-leave-active {
  transition: opacity 0.16s ease;
}
.palette-enter-active .palette,
.palette-leave-active .palette {
  transition: transform 0.22s cubic-bezier(0.2, 0.9, 0.2, 1), opacity 0.16s ease;
}
.palette-enter-from,
.palette-leave-to {
  opacity: 0;
}
.palette-enter-from .palette,
.palette-leave-to .palette {
  transform: translateY(-10px) scale(0.98);
  opacity: 0;
}
@media (max-width: 720px) {
  .palette-mask {
    padding-top: 8vh;
  }
  .foot {
    display: none;
  }
}
@media (prefers-reduced-motion: reduce) {
  .palette-enter-active,
  .palette-leave-active,
  .palette-enter-active .palette,
  .palette-leave-active .palette {
    transition: none;
  }
}
</style>
