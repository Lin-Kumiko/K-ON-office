<template>
  <div class="wf-graph" :style="{ height: `${height}px` }">
    <svg :viewBox="`0 0 ${box.w} ${box.h}`" preserveAspectRatio="xMidYMid meet" width="100%" height="100%">
      <defs>
        <marker id="wf-arrow" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" orient="auto-start-reverse">
          <path d="M 0 0 L 10 5 L 0 10 z" fill="var(--doe-muted)" />
        </marker>
      </defs>
      <g v-for="e in edges" :key="e.id">
        <path :d="e.d" fill="none" stroke="var(--doe-muted)" stroke-width="1.6" marker-end="url(#wf-arrow)" />
        <text v-if="e.label" :x="e.mx" :y="e.my - 6" class="edge-label" text-anchor="middle">{{ e.label }}</text>
      </g>
      <g v-for="n in nodes" :key="n.id" :transform="`translate(${n.x},${n.y})`">
        <rect v-if="!round(n.type)" :x="-W / 2" :y="-H / 2" :width="W" :height="H" rx="10"
              :class="['node', n.type, states[n.id]]" />
        <circle v-else :r="H / 2" :class="['node', n.type, states[n.id]]" />
        <text class="node-text" text-anchor="middle" dy="4">{{ short(n.name) }}</text>
      </g>
    </svg>
  </div>
</template>

<script setup lang="ts">
import { computed } from 'vue'

const props = withDefaults(defineProps<{ graph: { nodes: any[]; edges: any[] }; states?: Record<string, string>; height?: number }>(),
  { states: () => ({}), height: 260 })
const W = 120
const H = 44
const round = (t: string) => t === 'start' || t === 'end'
const short = (s: string) => (s.length > 9 ? s.slice(0, 8) + '…' : s)

const nodes = computed(() => props.graph.nodes.map((n, i) => ({ ...n, x: n.x ?? 80 + i * 150, y: n.y ?? 120 })))
const box = computed(() => {
  const xs = nodes.value.map((n) => n.x)
  const ys = nodes.value.map((n) => n.y)
  return { w: Math.max(...xs, 300) + 100, h: Math.max(...ys, 150) + 80 }
})
const edges = computed(() => {
  const pos = Object.fromEntries(nodes.value.map((n) => [n.id, n]))
  return props.graph.edges
    .filter((e) => pos[e.source] && pos[e.target])
    .map((e) => {
      const a = pos[e.source]
      const b = pos[e.target]
      const half = (n: any) => (round(n.type) ? H / 2 : W / 2)
      const x1 = a.x + (b.x >= a.x ? half(a) : -half(a))
      const x2 = b.x + (b.x >= a.x ? -half(b) : half(b))
      const mx = (x1 + x2) / 2
      return { id: e.id, label: e.label || (e.default ? '默认' : ''), d: `M${x1},${a.y} C${mx},${a.y} ${mx},${b.y} ${x2},${b.y}`,
               mx, my: (a.y + b.y) / 2 }
    })
})
</script>

<style scoped>
.wf-graph {
  width: 100%;
  background: var(--doe-bg);
  border: 1px dashed var(--doe-border);
  border-radius: 10px;
}
.node {
  fill: var(--doe-surface);
  stroke: var(--doe-border);
  stroke-width: 2;
}
.node.start,
.node.end {
  fill: var(--doe-brand-soft);
}
.node.condition {
  stroke: #d4a017;
}
.node.parallel,
.node.join {
  stroke: #6b8cce;
}
.node.cc {
  stroke: #9b8fd1;
  stroke-dasharray: 4 3;
}
.node.completed {
  fill: #e3f4e1;
  stroke: #67c23a;
}
.node.active {
  fill: #fff2dc;
  stroke: #e6a23c;
  stroke-width: 3;
}
.node.rejected {
  fill: #fde2e2;
  stroke: #f56c6c;
}
.node-text {
  font-size: 12px;
  fill: #3b2f2a;
  pointer-events: none;
}
.edge-label {
  font-size: 11px;
  fill: var(--doe-muted);
}
</style>
