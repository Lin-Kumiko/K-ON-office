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

function token(name: string): string {
  return getComputedStyle(document.documentElement).getPropertyValue(name).trim()
}

function each(v: any, fn: (x: any) => any): any {
  return Array.isArray(v) ? v.map(fn) : v ? fn(v) : v
}

/** One look for every chart in the app: quiet axes, rounded marks, glass tooltip. Anything a page sets wins. */
function styled(option: any): any {
  const dark = app.theme === 'dark'
  const palette = dark ? DARK : LIGHT
  const muted = token('--doe-muted')
  const border = token('--doe-border')
  const text = token('--doe-text')
  const surface = token('--doe-surface')
  const series: any[] = Array.isArray(option.series) ? option.series : option.series ? [option.series] : []
  const hasBar = series.some((s) => s.type === 'bar')
  const horizontal = (Array.isArray(option.yAxis) ? option.yAxis[0] : option.yAxis)?.type === 'category'

  const axis = (a: any) => {
    const category = a.type === 'category'
    return {
      ...a,
      axisLine: { show: category, lineStyle: { color: border }, ...a.axisLine },
      axisTick: { show: false, ...a.axisTick },
      axisLabel: { color: muted, fontSize: 12, ...a.axisLabel },
      splitLine: { show: !category, lineStyle: { color: border, type: [4, 4] }, ...a.splitLine },
    }
  }

  const out: any = {
    color: palette,
    backgroundColor: 'transparent',
    textStyle: { fontFamily: token('--el-font-family') },
    animationDuration: 700,
    animationEasing: 'cubicOut',
    ...option,
  }
  if (option.tooltip) {
    out.tooltip = {
      backgroundColor: dark ? 'rgba(30, 31, 37, 0.86)' : 'rgba(255, 255, 255, 0.86)',
      borderColor: dark ? 'rgba(255, 255, 255, 0.1)' : 'rgba(20, 20, 40, 0.08)',
      borderWidth: 1,
      padding: [10, 14],
      textStyle: { color: text, fontSize: 13 },
      extraCssText: 'border-radius:12px;backdrop-filter:blur(16px) saturate(1.6);-webkit-backdrop-filter:blur(16px) saturate(1.6);'
        + 'box-shadow:0 16px 40px -18px rgba(30,20,40,.45);',
      ...option.tooltip,
      axisPointer: {
        type: hasBar ? 'shadow' : 'line',
        shadowStyle: { color: dark ? 'rgba(255, 255, 255, 0.05)' : 'rgba(158, 58, 114, 0.06)' },
        lineStyle: { color: border },
        ...option.tooltip.axisPointer,
      },
    }
  }
  if (option.legend) {
    out.legend = { icon: 'roundRect', itemWidth: 10, itemHeight: 10, itemGap: 16, textStyle: { color: muted }, ...option.legend }
  }
  if (option.xAxis) out.xAxis = each(option.xAxis, axis)
  if (option.yAxis) out.yAxis = each(option.yAxis, axis)

  const soloBar = series.filter((s) => s.type === 'bar').length === 1
  out.series = series.map((s) => {
    if (s.type === 'bar') {
      const radius = s.stack ? 2 : horizontal ? [0, 6, 6, 0] : [6, 6, 0, 0]
      const fill = soloBar
        ? { color: new echarts.graphic.LinearGradient(0, horizontal ? 0 : 1, horizontal ? 1 : 0, 0, [
            { offset: 0, color: palette[0] + (dark ? '99' : 'b3') }, { offset: 1, color: palette[0] }]) }
        : {}
      return { barMaxWidth: 28, ...s, itemStyle: { borderRadius: radius, ...fill, ...s.itemStyle },
               emphasis: { focus: s.stack ? 'series' : 'none', ...s.emphasis } }
    }
    if (s.type === 'line') {
      return { smooth: 0.35, symbol: 'circle', symbolSize: 7, showSymbol: false, ...s, lineStyle: { width: 2.5, ...s.lineStyle } }
    }
    if (s.type === 'pie') {
      return { ...s, itemStyle: { borderRadius: 7, borderColor: dark ? '#1b1c21' : surface, borderWidth: 2, ...s.itemStyle },
               label: { color: muted, ...s.label }, labelLine: { lineStyle: { color: border }, ...s.labelLine } }
    }
    return s
  })
  return out
}

function render() {
  if (!el.value) return
  chart?.dispose()
  chart = echarts.init(el.value, app.theme === 'dark' ? 'dark' : undefined)
  chart.setOption(styled(props.option))
}

onMounted(() => {
  render()
  if (typeof ResizeObserver !== 'undefined' && el.value) {
    ro = new ResizeObserver(() => chart?.resize())
    ro.observe(el.value)
  }
})
watch(() => props.option, () => chart?.setOption(styled(props.option), true), { deep: true })
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
