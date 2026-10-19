<template>
  <div class="side">
    <div class="brand" :class="{ mini: collapsed }">
      <img src="/teacup.svg" alt="" class="logo" />
      <div v-if="!collapsed" class="brand-text">
        <div class="brand-name">放学后茶会</div>
        <div class="brand-sub" lang="ja">けいおん</div>
      </div>
    </div>
    <nav ref="navEl" class="nav" aria-label="主导航">
      <span class="indicator" :style="indicator" aria-hidden="true" />
      <section v-for="g in groups" :key="g.title" class="group">
        <div v-if="!collapsed" class="group-title">{{ g.title }}</div>
        <div v-else class="group-rule" />
        <router-link v-for="m in g.items" :key="m.path" :to="m.path" class="item" :class="{ on: active === m.path }"
                     :data-test="`menu-${m.name}`" :title="collapsed ? m.title : undefined" @click="$emit('navigate')">
          <el-icon class="item-icon"><component :is="m.icon" /></el-icon>
          <template v-if="!collapsed">
            <span class="item-title">{{ m.title }}</span>
            <el-icon v-if="m.locked" class="lock" aria-label="需要登录"><Lock /></el-icon>
          </template>
        </router-link>
      </section>
    </nav>
  </div>
</template>

<script setup lang="ts">
import { computed, nextTick, onMounted, onUnmounted, ref, watch } from 'vue'
import { useRoute } from 'vue-router'
import { appRoutes } from '@/router'
import { useAuth } from '@/stores/auth'

const props = defineProps<{ collapsed: boolean }>()
defineEmits(['navigate'])
const auth = useAuth()
const route = useRoute()
const active = computed(() => route.path)

const GROUPS: [string, string[]][] = [
  ['工作', ['dashboard', 'approvals', 'announcements', 'documents', 'meeting']],
  ['考勤与申请', ['attendance', 'leave', 'travel', 'expense']],
  ['人事', ['org', 'employees', 'recruitment', 'hr-changes', 'performance', 'payroll']],
  ['管理', ['reports', 'workflow', 'system']],
]

// Visitors see the whole system (except administration); pages they cannot open yet carry a lock and
// ask them to log in when clicked (handled by the router guard).
const menus = computed(() =>
  appRoutes
    .filter((r) => !r.meta?.hidden)
    .filter((r) => (auth.loggedIn
      ? auth.canAny(r.meta?.perm as string | string[] | undefined) || (r.name === 'attendance' && auth.can('attendance:punch'))
      : !r.meta?.adminOnly))
    .map((r) => ({ path: r.path, name: r.name as string, title: r.meta?.title as string, icon: r.meta?.icon as string,
                   locked: !auth.loggedIn && !r.meta?.visitor })),
)

const groups = computed(() => {
  const byName = new Map(menus.value.map((m) => [m.name, m]))
  const used = new Set<string>()
  const out = GROUPS.map(([title, names]) => {
    const items = names.flatMap((n) => (byName.has(n) ? [byName.get(n)!] : []))
    items.forEach((i) => used.add(i.name))
    return { title, items }
  })
  const rest = menus.value.filter((m) => !used.has(m.name))
  if (rest.length) out.push({ title: '其他', items: rest })
  return out.filter((g) => g.items.length)
})

// A single highlight that glides to the active item instead of jumping.
const navEl = ref<HTMLElement>()
const indicator = ref<Record<string, string>>({ opacity: '0' })
function placeIndicator() {
  const el = navEl.value?.querySelector<HTMLElement>('.item.on')
  indicator.value = el
    ? { opacity: '1', transform: `translate(${el.offsetLeft}px, ${el.offsetTop}px)`, width: `${el.offsetWidth}px`,
        height: `${el.offsetHeight}px` }
    : { ...indicator.value, opacity: '0' }
}
watch([active, groups, () => props.collapsed], () => nextTick(placeIndicator))
onMounted(() => {
  nextTick(placeIndicator)
  window.addEventListener('resize', placeIndicator)
})
onUnmounted(() => window.removeEventListener('resize', placeIndicator))
</script>

<style scoped>
.side {
  height: 100%;
  display: flex;
  flex-direction: column;
  background: var(--glass-bg);
  -webkit-backdrop-filter: var(--glass-blur);
  backdrop-filter: var(--glass-blur);
  border-right: 1px solid var(--glass-border);
  box-shadow: 1px 0 0 var(--glass-edge);
}
.brand {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 18px 16px 14px;
}
.brand.mini {
  justify-content: center;
  padding: 18px 0 14px;
}
.logo {
  width: 32px;
  height: 32px;
  border-radius: 9px;
  background: var(--doe-brand-soft);
  padding: 4px;
}
.brand-name {
  font-weight: 650;
  font-size: 15px;
  letter-spacing: 0.02em;
}
.brand-sub {
  font-size: 11px;
  color: var(--doe-muted);
  margin-top: 1px;
}
.nav {
  position: relative;
  flex: 1;
  overflow-y: auto;
  padding: 4px 10px 16px;
}
.group + .group {
  margin-top: 14px;
}
.group-title {
  padding: 0 10px 6px;
  font-size: 12px;
  color: var(--doe-faint);
}
.group-rule {
  height: 1px;
  margin: 4px 10px 8px;
  background: var(--doe-border);
}
.indicator {
  position: absolute;
  top: 0;
  left: 0;
  z-index: 0;
  border-radius: 9px;
  background: var(--doe-brand-soft);
  box-shadow: inset 0 1px 0 var(--glass-highlight), 0 0 0 1px color-mix(in srgb, var(--doe-brand) 14%, transparent);
  transition: transform 0.38s cubic-bezier(0.2, 0.9, 0.2, 1), height 0.3s ease, width 0.3s ease, opacity 0.2s;
  pointer-events: none;
}
.item {
  position: relative;
  z-index: 1;
  display: flex;
  align-items: center;
  gap: 10px;
  height: 36px;
  padding: 0 10px;
  border-radius: 9px;
  color: var(--el-text-color-regular);
  text-decoration: none;
  font-size: 14px;
  transition: background-color 0.12s, color 0.12s;
}
.item + .item {
  margin-top: 2px;
}
.item:hover {
  background: var(--doe-hover);
  color: var(--doe-text);
}
.item.on,
.item.on:hover {
  background: transparent;
  color: var(--doe-brand);
  font-weight: 600;
}
.item-icon {
  font-size: 17px;
  flex: none;
}
.item-title {
  flex: 1;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}
.lock {
  font-size: 12px;
  color: var(--doe-faint);
}
.brand.mini + .nav .item {
  justify-content: center;
  padding: 0;
}
@media (prefers-reduced-motion: reduce) {
  .indicator,
  .item {
    transition: none;
  }
}
</style>
