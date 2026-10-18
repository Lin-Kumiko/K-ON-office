<template>
  <div class="page">
    <div class="page-head">
      <div><h2>绩效管理</h2><div class="sub">自评（30%）+ 主管评价（70%）加权得分，HR 确认后生效；等级 A≥90 B≥80 C≥70 D≥60</div></div>
      <el-button v-if="manage" type="primary" @click="openCycle()">新建考核周期</el-button>
    </div>
    <div class="card">
      <el-tabs v-model="tab" @tab-change="load">
        <el-tab-pane label="我的考核" name="mine" />
        <el-tab-pane label="待我评价" name="team" />
        <el-tab-pane v-if="manage" label="考核周期" name="cycles" />
        <el-tab-pane v-if="manage" label="全部考核与统计" name="all" />
      </el-tabs>
      <template v-if="tab === 'cycles'">
        <el-table :data="cycles" border>
          <el-table-column prop="name" label="周期" width="160" />
          <el-table-column label="时间" width="220"><template #default="{ row }">{{ row.start_date }} ~ {{ row.end_date }}</template></el-table-column>
          <el-table-column label="指标" min-width="220"><template #default="{ row }">{{ row.indicators.map((i: any) => `${i.name}(${i.weight}%)`).join('、') }}</template></el-table-column>
          <el-table-column label="进度" width="100"><template #default="{ row }">{{ row.review_confirmed }}/{{ row.review_total }}</template></el-table-column>
          <el-table-column label="状态" width="90"><template #default="{ row }"><el-tag size="small">{{ CYCLE[row.status] }}</el-tag></template></el-table-column>
          <el-table-column label="操作" width="200">
            <template #default="{ row }">
              <el-button v-if="row.status === 'draft'" link @click="openCycle(row)">编辑</el-button>
              <el-button v-if="row.status === 'draft'" link type="primary" @click="cycleAct(row, 'activate')">启动</el-button>
              <el-button v-if="row.status === 'active'" link type="warning" @click="cycleAct(row, 'close')">关闭</el-button>
            </template>
          </el-table-column>
        </el-table>
      </template>
      <template v-else>
        <div v-if="tab === 'all'" class="toolbar">
          <el-select v-model="cycleId" placeholder="选择周期" style="width: 200px" @change="load">
            <el-option v-for="c in cycles" :key="c.id" :label="c.name" :value="c.id" />
          </el-select>
        </div>
        <div v-if="tab === 'all' && stats" class="grid cols-2 mb">
          <div class="card"><b>等级分布</b><EChart :option="gradeOption" :height="220" /></div>
          <div class="card"><b>部门平均分</b><EChart :option="deptOption" :height="220" /></div>
        </div>
        <el-table :data="reviews" border empty-text="暂无考核表">
          <el-table-column prop="cycle_name" label="周期" width="140" />
          <el-table-column prop="employee_name" label="员工" width="100" />
          <el-table-column prop="department_name" label="部门" width="120" />
          <el-table-column prop="reviewer_name" label="评价人" width="100" />
          <el-table-column label="状态" width="110"><template #default="{ row }"><StatusTag :status="row.status" /></template></el-table-column>
          <el-table-column label="得分" width="80"><template #default="{ row }">{{ row.final_score ?? '-' }}</template></el-table-column>
          <el-table-column label="等级" width="70"><template #default="{ row }">{{ row.grade || '-' }}</template></el-table-column>
          <el-table-column label="操作" width="160">
            <template #default="{ row }">
              <el-button v-if="tab === 'mine' && row.status === 'self_pending'" link type="primary" @click="openScore(row, 'self')">自评</el-button>
              <el-button v-if="tab === 'team' && row.status === 'manager_pending'" link type="primary" @click="openScore(row, 'manager')">评价</el-button>
              <el-button v-if="tab === 'all' && row.status === 'confirm_pending'" link type="success" @click="confirm(row, 'confirm')">确认</el-button>
              <el-button v-if="tab === 'all' && row.status === 'confirm_pending'" link type="warning" @click="confirm(row, 'return')">退回</el-button>
              <el-button link @click="view(row)">查看</el-button>
            </template>
          </el-table-column>
        </el-table>
      </template>
    </div>

    <el-dialog v-model="cycleOpen" title="考核周期" width="600px">
      <el-form :model="cycle" label-width="80px">
        <el-form-item label="名称" required><el-input v-model="cycle.name" /></el-form-item>
        <el-form-item label="时间" required><el-date-picker v-model="cycleRange" type="daterange" value-format="YYYY-MM-DD" /></el-form-item>
        <el-form-item label="指标">
          <div v-for="(ind, i) in cycle.indicators" :key="i" class="ind">
            <el-input v-model="ind.name" placeholder="指标名称" style="width: 180px" />
            <el-input-number v-model="ind.weight" :min="1" :max="100" />%
            <el-button link type="danger" @click="cycle.indicators.splice(i, 1)">删除</el-button>
          </div>
          <el-button size="small" @click="cycle.indicators.push({ name: '', weight: 10 })">添加指标</el-button>
          <span class="muted ml">权重合计 {{ cycle.indicators.reduce((s: number, x: any) => s + x.weight, 0) }}%（需为 100%）</span>
        </el-form-item>
      </el-form>
      <template #footer><el-button @click="cycleOpen = false">取消</el-button><el-button type="primary" @click="saveCycle">保存</el-button></template>
    </el-dialog>

    <el-dialog v-model="scoreOpen" :title="scoreMode === 'self' ? '员工自评' : '主管评价'" width="520px">
      <template v-if="scoring">
        <el-form label-width="120px">
          <el-form-item v-for="i in scoring.indicators" :key="i.id" :label="`${i.name}（${i.weight}%）`">
            <el-slider v-model="scores[i.id]" :min="0" :max="100" show-input />
          </el-form-item>
          <el-form-item label="评语" required><el-input v-model="comment" type="textarea" :rows="3" /></el-form-item>
          <div v-if="scoreMode === 'manager'" class="muted">员工自评：{{ JSON.stringify(scoring.self_scores) }} · {{ scoring.self_comment }}</div>
        </el-form>
      </template>
      <template #footer><el-button @click="scoreOpen = false">取消</el-button><el-button type="primary" @click="saveScore">提交</el-button></template>
    </el-dialog>
    <el-dialog v-model="viewOpen" title="考核详情" width="520px">
      <template v-if="viewing">
        <el-descriptions :column="1" border size="small">
          <el-descriptions-item label="员工">{{ viewing.employee_name }}</el-descriptions-item>
          <el-descriptions-item v-for="i in viewing.indicators" :key="i.id" :label="i.name">
            自评 {{ viewing.self_scores?.[i.id] ?? '-' }} · 主管 {{ viewing.manager_scores?.[i.id] ?? '-' }}
          </el-descriptions-item>
          <el-descriptions-item label="自评评语">{{ viewing.self_comment || '-' }}</el-descriptions-item>
          <el-descriptions-item label="主管评语">{{ viewing.manager_comment || '-' }}</el-descriptions-item>
          <el-descriptions-item label="最终">{{ viewing.final_score ?? '-' }} / {{ viewing.grade || '-' }}</el-descriptions-item>
        </el-descriptions>
      </template>
    </el-dialog>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, reactive, ref, watch } from 'vue'
import { api } from '@/api/http'
import { useAuth } from '@/stores/auth'
import { act } from '@/utils/usePaged'
import StatusTag from '@/components/StatusTag.vue'
import EChart from '@/components/EChart.vue'

const CYCLE: Record<string, string> = { draft: '草稿', active: '进行中', closed: '已关闭' }
const auth = useAuth()
const manage = computed(() => auth.can('performance:manage'))
const tab = ref('mine')
const cycles = ref<any[]>([])
const cycleId = ref<number | undefined>()
const reviews = ref<any[]>([])
const stats = ref<any>(null)
const cycleOpen = ref(false)
const cycle = reactive<any>({ indicators: [] })
const cycleRange = ref<string[] | null>(null)
const scoreOpen = ref(false)
const scoreMode = ref<'self' | 'manager'>('self')
const scoring = ref<any>(null)
const scores = reactive<Record<string, number>>({})
const comment = ref('')
const viewOpen = ref(false)
const viewing = ref<any>(null)

watch(cycleRange, (v) => { cycle.start_date = v?.[0]; cycle.end_date = v?.[1] })

const gradeOption = computed(() => ({
  tooltip: {},
  series: [{ type: 'pie', radius: ['40%', '70%'], data: Object.entries(stats.value?.by_grade || {}).map(([k, v]) => ({ name: k, value: v })) }],
}))
const deptOption = computed(() => ({
  tooltip: {}, grid: { left: 80, right: 20, top: 10, bottom: 20 },
  xAxis: { type: 'value', max: 100 }, yAxis: { type: 'category', data: (stats.value?.avg_by_department || []).map((d: any) => d.department) },
  series: [{ type: 'bar', data: (stats.value?.avg_by_department || []).map((d: any) => d.avg) }],
}))

async function load() {
  cycles.value = await api.get('/api/performance/cycles')
  if (!cycleId.value && cycles.value.length) cycleId.value = cycles.value[0].id
  if (tab.value === 'cycles') return
  const scope = tab.value === 'mine' ? 'mine' : tab.value === 'team' ? 'team' : 'all'
  reviews.value = (await api.get('/api/performance/reviews', { scope, cycle_id: tab.value === 'all' ? cycleId.value : undefined, page_size: 200 })).items
  stats.value = tab.value === 'all' && cycleId.value ? await api.get('/api/performance/stats', { cycle_id: cycleId.value }) : null
}
function openCycle(c?: any) {
  Object.assign(cycle, c ? { ...c, indicators: c.indicators.map((i: any) => ({ name: i.name, weight: i.weight })) }
    : { id: undefined, name: '', indicators: [{ name: '演奏技术', weight: 50 }, { name: '团队协作', weight: 30 }, { name: '茶话会参与', weight: 20 }] })
  cycleRange.value = c ? [c.start_date, c.end_date] : null
  cycleOpen.value = true
}
async function saveCycle() {
  const body = { name: cycle.name, start_date: cycle.start_date, end_date: cycle.end_date, indicators: cycle.indicators }
  if (await act(() => (cycle.id ? api.put(`/api/performance/cycles/${cycle.id}`, body) : api.post('/api/performance/cycles', body)), '已保存')) {
    cycleOpen.value = false
    tab.value = 'cycles'
    load()
  }
}
async function cycleAct(c: any, a: string) {
  if (await act(() => api.post(`/api/performance/cycles/${c.id}/${a}`), a === 'activate' ? '已启动，考核表已生成' : '已关闭')) load()
}
function openScore(r: any, mode: 'self' | 'manager') {
  scoring.value = r
  scoreMode.value = mode
  Object.keys(scores).forEach((k) => delete scores[k])
  r.indicators.forEach((i: any) => (scores[i.id] = 80))
  comment.value = ''
  scoreOpen.value = true
}
async function saveScore() {
  const url = `/api/performance/reviews/${scoring.value.id}/${scoreMode.value}`
  if (await act(() => api.post(url, { scores: { ...scores }, comment: comment.value }), '已提交')) {
    scoreOpen.value = false
    load()
  }
}
async function confirm(r: any, action: string) {
  if (await act(() => api.post(`/api/performance/reviews/${r.id}/confirm`, { action }), action === 'confirm' ? '已确认' : '已退回')) load()
}
function view(r: any) {
  viewing.value = r
  viewOpen.value = true
}
onMounted(load)
</script>

<style scoped>
.ind {
  display: flex;
  gap: 8px;
  align-items: center;
  margin-bottom: 6px;
}
.ml {
  margin-left: 8px;
}
.mb {
  margin-bottom: 16px;
}
</style>
