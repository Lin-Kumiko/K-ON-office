<template>
  <span>{{ shown }}</span>
</template>

<script setup lang="ts">
import { onUnmounted, ref, watch } from 'vue'

// Rolls a number up to its value once; anything that is not a plain number is shown as it is.
const props = withDefaults(defineProps<{ value: number | string | null | undefined; duration?: number }>(), { duration: 700 })
const shown = ref<string>('')
let raf = 0

function still(): boolean {
  return typeof window.matchMedia === 'function' && window.matchMedia('(prefers-reduced-motion: reduce)').matches
}

function run(v: number | string | null | undefined) {
  cancelAnimationFrame(raf)
  const text = v == null ? '-' : String(v)
  const target = typeof v === 'number' ? v : Number.NaN
  if (!Number.isFinite(target) || !Number.isInteger(target) || target <= 0 || still()) {
    shown.value = text
    return
  }
  const from = performance.now()
  const step = (now: number) => {
    const t = Math.min(1, (now - from) / props.duration)
    shown.value = String(Math.round(target * (1 - Math.pow(1 - t, 3))))
    if (t < 1) raf = requestAnimationFrame(step)
  }
  shown.value = '0'
  raf = requestAnimationFrame(step)
}

watch(() => props.value, run, { immediate: true })
onUnmounted(() => cancelAnimationFrame(raf))
</script>
