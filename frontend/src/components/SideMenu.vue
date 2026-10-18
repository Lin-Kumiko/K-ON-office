<template>
  <div class="side">
    <div class="brand" :class="{ mini: collapsed }">
      <img src="/teacup.svg" alt="" class="logo" />
      <div v-if="!collapsed" class="brand-text">
        <div class="brand-name">放学后茶会</div>
        <div class="brand-sub" lang="ja">けいおん</div>
      </div>
    </div>
    <el-menu :default-active="active" :collapse="collapsed" router class="menu" background-color="transparent"
             text-color="var(--doe-aside-text)" active-text-color="#ffd7b8">
      <el-menu-item v-for="m in menus" :key="m.path" :index="m.path" @click="$emit('navigate')" :data-test="`menu-${m.name}`">
        <el-icon><component :is="m.icon" /></el-icon>
        <template #title>{{ m.title }}<el-icon v-if="m.locked" class="lock" aria-label="需要登录"><Lock /></el-icon></template>
      </el-menu-item>
    </el-menu>
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
</script>

<style scoped>
.side {
  height: 100%;
  display: flex;
  flex-direction: column;
  background: var(--doe-aside);
}
.brand {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 16px 14px;
  color: #fff;
}
.brand.mini {
  justify-content: center;
  padding: 16px 0;
}
.logo {
  width: 34px;
  height: 34px;
  background: #fff4ea;
  border-radius: 10px;
  padding: 4px;
}
.brand-name {
  font-weight: 700;
  letter-spacing: 1px;
}
.brand-sub {
  font-size: 11px;
  opacity: 0.7;
}
.lock {
  margin-left: 6px;
  opacity: 0.55;
  font-size: 12px;
}
.menu {
  border-right: none;
  flex: 1;
  overflow-y: auto;
}
.menu :deep(.el-menu-item.is-active) {
  background: rgba(232, 138, 163, 0.18);
}
.menu :deep(.el-menu-item:hover) {
  background: rgba(255, 255, 255, 0.06);
}
</style>
