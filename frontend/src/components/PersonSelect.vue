<template>
  <el-select :model-value="modelValue" filterable clearable :multiple="multiple" :placeholder="placeholder"
             :loading="loading" style="width: 100%" @update:model-value="(v: any) => emit('update:modelValue', v)">
    <el-option v-for="o in options" :key="o.value" :label="o.label" :value="o.value" />
  </el-select>
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { loadPeople, type PersonOpt } from '@/utils/options'

const props = withDefaults(defineProps<{ modelValue: any; mode?: 'employee' | 'user'; multiple?: boolean; placeholder?: string }>(),
  { mode: 'employee', multiple: false, placeholder: '选择人员' })
const emit = defineEmits(['update:modelValue'])
const loading = ref(false)
const list = ref<PersonOpt[]>([])

const options = computed(() =>
  list.value
    .filter((o) => props.mode === 'employee' || o.user_id)
    .map((o) => ({ value: props.mode === 'employee' ? o.id : o.user_id, label: `${o.name}（${o.employee_no}）` })),
)

onMounted(async () => {
  loading.value = true
  try {
    list.value = await loadPeople()
  } finally {
    loading.value = false
  }
})
</script>
