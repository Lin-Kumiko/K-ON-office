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

const PALETTE = ['#b5653a', '#e88aa3', '#6b8cce', '#d4a017', '#67a77a', '#9b8fd1', '#c97d5d', '#5fa8b8']

function render() {
  if (!el.value) return
  chart?.dispose()
  chart = echarts.init(el.value, app.theme === 'dark' ? 'dark' : undefined)
  chart.setOption({ color: PALETTE, backgroundColor: 'transparent', ...props.option })
}

onMounted(() => {
  render()
  if (typeof ResizeObserver !== 'undefined' && el.value) {
    ro = new ResizeObserver(() => chart?.resize())
    ro.observe(el.value)
  }
})
watch(() => props.option, () => chart?.setOption({ color: PALETTE, ...props.option }, true), { deep: true })
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
