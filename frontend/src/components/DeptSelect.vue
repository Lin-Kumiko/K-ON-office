<template>
  <el-select :model-value="modelValue" filterable clearable :multiple="multiple" :placeholder="placeholder"
             style="width: 100%" @update:model-value="(v: any) => emit('update:modelValue', v)">
    <el-option v-for="d in list" :key="d.id" :label="d.name" :value="d.id" />
  </el-select>
</template>

<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { loadDepartments, type DeptOpt } from '@/utils/options'

withDefaults(defineProps<{ modelValue: any; multiple?: boolean; placeholder?: string }>(),
  { multiple: false, placeholder: '选择部门' })
const emit = defineEmits(['update:modelValue'])
const list = ref<DeptOpt[]>([])
onMounted(async () => {
  list.value = await loadDepartments()
})
</script>
