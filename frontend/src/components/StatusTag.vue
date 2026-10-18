<template>
  <el-tag :type="statusType(status) || undefined" size="small" effect="light" round disable-transitions>{{ statusText(status) }}</el-tag>
</template>

<script setup lang="ts">
import { statusText, statusType } from '@/utils/format'

defineProps<{ status: string | null | undefined }>()
</script>
