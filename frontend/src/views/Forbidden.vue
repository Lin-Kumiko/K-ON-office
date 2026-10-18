<template>
  <div class="page">
    <el-result icon="warning" title="无权访问" :sub-title="`当前账号缺少权限：${route.query.need || '未知'}。权限由后端校验，如需开通请联系管理员。`">
      <template #extra><el-button type="primary" @click="router.push('/dashboard')">返回工作台</el-button></template>
    </el-result>
  </div>
</template>

<script setup lang="ts">
import { useRoute, useRouter } from 'vue-router'

const route = useRoute()
const router = useRouter()
</script>
