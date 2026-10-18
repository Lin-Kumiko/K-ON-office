<template>
  <Dashboard v-if="auth.loggedIn" />
  <PublicHome v-else />
</template>

<script setup lang="ts">
import { useAuth } from '@/stores/auth'
import Dashboard from './Dashboard.vue'
import PublicHome from './PublicHome.vue'

const auth = useAuth()
</script>
