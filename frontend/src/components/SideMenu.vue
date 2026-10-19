<template>
  <div class="side">
    <div class="brand" :class="{ mini: collapsed }">
      <img src="/teacup.svg" alt="" class="logo" />
      <div v-if="!collapsed" class="brand-text">
        <div class="brand-name">放学后茶会</div>
        <div class="brand-sub" lang="ja">けいおん</div>
      </div>
    </div>
    <nav class="nav" aria-label="主导航">
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
import { computed } from 'vue'
import { useRoute } from 'vue-router'
import { appRoutes } from '@/router'
import { useAuth } from '@/stores/auth'

defineProps<{ collapsed: boolean }>()
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
</script>

<style scoped>
.side {
  height: 100%;
  display: flex;
  flex-direction: column;
  background: var(--doe-sidebar);
  border-right: 1px solid var(--doe-border);
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
.item {
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
.item.on {
  background: var(--doe-brand-soft);
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
  .item {
    transition: none;
  }
}
</style>
