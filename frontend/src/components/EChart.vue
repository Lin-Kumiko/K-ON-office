<template>
  <div ref="el" class="echart" :style="{ height: `${height}px` }" />
</template>

<script setup lang="ts">
import { onMounted, onUnmounted, ref, watch } from 'vue'
import * as echarts from 'echarts'
import { useApp } from '@/stores/app'

const props = withDefaults(defineProps<{ option: echarts.EChartsCoreOption; height?: number }>(), { height: 280 })
const el = ref<HTMLDivElement>()
const app = useApp()
let chart: echarts.ECharts | null = null
let ro: ResizeObserver | null = null

const LIGHT = ['#9e3a72', '#3f7cc4', '#d9982a', '#3a9a77', '#d06a4f', '#7b6cc2', '#4f9fb0', '#a8825a']
const DARK = ['#e07ab0', '#6aa7ec', '#f0be62', '#5cc29b', '#ec8a70', '#a395ee', '#7cc5d4', '#d4a87c']

function base() {
  const dark = app.theme === 'dark'
  return {
    color: dark ? DARK : LIGHT,
    backgroundColor: 'transparent',
    textStyle: { fontFamily: getComputedStyle(document.documentElement).getPropertyValue('--el-font-family') },
  }
}

function render() {
  if (!el.value) return
  chart?.dispose()
  chart = echarts.init(el.value, app.theme === 'dark' ? 'dark' : undefined)
  chart.setOption({ ...base(), ...props.option })
}

onMounted(() => {
  render()
  if (typeof ResizeObserver !== 'undefined' && el.value) {
    ro = new ResizeObserver(() => chart?.resize())
    ro.observe(el.value)
  }
})
watch(() => props.option, () => chart?.setOption({ ...base(), ...props.option }, true), { deep: true })
watch(() => app.theme, render)
onUnmounted(() => {
  ro?.disconnect()
  chart?.dispose()
})
</script>

<style scoped>
.echart {
  width: 100%;
}
</style>
