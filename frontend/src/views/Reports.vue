<template>
  <div class="page" v-loading="loading">
    <div class="page-head">
      <div><h2>统计报表</h2><div class="sub">数据来自实时业务数据，按你的数据权限范围（{{ data?.scope === 'all' ? '全公司' : '本部门及下级' }}）统计</div></div>
      <el-date-picker v-model="month" type="month" value-format="YYYY-MM" :clearable="false" @change="load" />
    </div>
    <el-alert v-if="error" :title="error" type="error" show-icon />
    <div v-if="data" class="grid cols-2">
      <div class="card"><b>部门人数</b><EChart :option="pie(data.headcount_by_department)" /></div>
      <div class="card"><b>近 6 个月入职人数</b><EChart :option="bar(data.hires_by_month.months, data.hires_by_month.data, '入职')" /></div>
      <div class="card"><b>请假时长（小时，近 6 个月，按类型）</b><EChart :option="pie(data.leave_hours_by_type)" /></div>
      <div class="card"><b>报销金额（元，按月）</b><EChart :option="bar(data.expense_by_month.months, data.expense_by_month.data, '报销')" /></div>
      <div class="card"><b>报销金额（元，按分类）</b><EChart :option="pie(data.expense_by_category)" /></div>
      <div class="card"><b>{{ month }} 各部门考勤异常</b><EChart :option="attOption" /></div>
      <div class="card"><b>流程状态分布</b><EChart :option="pie(data.workflow_status, statusText)" /></div>
      <div class="card">
        <b>流程平均审批时长（小时）</b>
        <el-table :data="data.workflow_avg_duration" size="small" border class="mt" empty-text="暂无已完成流程">
          <el-table-column prop="business_type" label="业务" />
          <el-table-column prop="count" label="完成数" width="90" />
          <el-table-column prop="avg_hours" label="平均时长(h)" width="120" />
        </el-table>
        <b class="mt block">绩效等级分布</b>
        <div class="muted">{{ Object.entries(data.performance_grades).map(([g, n]) => `${g}: ${n}`).join('  ') || '暂无已确认绩效' }}</div>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { api, errorText } from '@/api/http'
import { statusText, thisMonth } from '@/utils/format'
import EChart from '@/components/EChart.vue'

const month = ref(thisMonth())
const data = ref<any>(null)
const loading = ref(false)
const error = ref('')

const pie = (obj: Record<string, number>, label: (k: string) => string = (k) => k) => ({
  tooltip: { trigger: 'item' }, legend: { bottom: 0, type: 'scroll' },
  series: [{ type: 'pie', radius: ['35%', '65%'], data: Object.entries(obj || {}).map(([k, v]) => ({ name: label(k), value: v })) }],
})
const bar = (x: string[], y: number[], name: string) => ({
  tooltip: { trigger: 'axis' }, grid: { left: 50, right: 20, top: 20, bottom: 30 },
  xAxis: { type: 'category', data: x }, yAxis: { type: 'value' }, series: [{ name, type: 'bar', data: y, barMaxWidth: 36 }],
})
const attOption = computed(() => {
  const d = data.value?.attendance_by_department || {}
  const names = Object.keys(d)
  const keys: [string, string][] = [['late', '迟到'], ['early', '早退'], ['missing', '缺卡'], ['absent', '缺勤']]
  return { tooltip: { trigger: 'axis' }, legend: { top: 0 }, grid: { left: 50, right: 20, top: 40, bottom: 40 },
    xAxis: { type: 'category', data: names, axisLabel: { interval: 0, rotate: 20 } }, yAxis: { type: 'value', minInterval: 1 },
    series: keys.map(([k, n]) => ({ name: n, type: 'bar', stack: 'a', data: names.map((x) => d[x][k]) })) }
})

async function load() {
  loading.value = true
  error.value = ''
  try {
    data.value = await api.get('/api/reports/overview', { month: month.value })
  } catch (e) {
    error.value = errorText(e)
  } finally {
    loading.value = false
  }
}
onMounted(load)
</script>

<style scoped>
.mt {
  margin-top: 10px;
}
.block {
  display: block;
}
</style>
