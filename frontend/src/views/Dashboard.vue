<template>
  <div class="page" v-loading="loading">
    <div class="page-head">
      <div>
        <h2>{{ greeting }}，{{ data?.user.employee_name || data?.user.name }}</h2>
        <div class="sub">{{ today }} · 今天也要认真工作，然后喝茶</div>
      </div>
      <div class="toolbar">
        <el-button v-for="q in data?.quick_entries || []" :key="q.key" @click="router.push('/' + q.key)">{{ q.title }}</el-button>
      </div>
    </div>
    <el-alert v-if="error" :title="error" type="error" show-icon class="mb" />
    <template v-if="data">
      <div class="grid cols-4 mb">
        <div class="card stat" data-test="stat-pending"><span class="label">我的待办</span><span class="value">{{ data.stats.pending_tasks }}</span></div>
        <div class="card stat"><span class="label">审批中的申请</span><span class="value">{{ data.stats.running_applications }}</span></div>
        <div class="card stat"><span class="label">未读通知</span><span class="value">{{ data.stats.unread_notifications }}</span></div>
        <div class="card stat">
          <span class="label">{{ data.company_view ? '在职人数（数据范围内）' : '可用年假' }}</span>
          <span class="value">{{ data.company_view ? data.stats.headcount : data.annual_leave ? hoursToDays(data.annual_leave.available_hours) : '-' }}</span>
        </div>
      </div>
      <div class="grid cols-2 mb">
        <div class="card">
          <div class="card-head"><b>待我审批</b><el-button link type="primary" @click="router.push('/approvals')">全部</el-button></div>
          <el-empty v-if="!data.todo.length" description="没有待办，喝杯茶吧 ☕" :image-size="70" />
          <div v-for="t in data.todo" :key="t.task_id" class="row" @click="open(t.instance_id)">
            <el-tag size="small" effect="plain">{{ BUSINESS[t.business_type] }}</el-tag>
            <span class="row-title">{{ t.title }}</span>
            <span class="muted">{{ t.node_name }}</span>
          </div>
        </div>
        <div class="card">
          <div class="card-head"><b>我的申请</b><el-button link type="primary" @click="router.push('/approvals?tab=mine')">全部</el-button></div>
          <el-empty v-if="!data.my_applications.length" description="暂无申请" :image-size="70" />
          <div v-for="a in data.my_applications" :key="a.instance_id" class="row" @click="open(a.instance_id)">
            <StatusTag :status="a.status" />
            <span class="row-title">{{ a.title }}</span>
            <span class="muted">{{ fmtDateTime(a.started_at) }}</span>
          </div>
        </div>
      </div>
      <div class="grid cols-3 mb">
        <div class="card">
          <div class="card-head"><b>最新公告</b><el-button link type="primary" @click="router.push('/announcements')">更多</el-button></div>
          <el-empty v-if="!data.announcements.length" description="暂无公告" :image-size="60" />
          <div v-for="a in data.announcements" :key="a.id" class="row" @click="router.push(`/announcements?id=${a.id}`)">
            <el-tag v-if="a.pinned" size="small" type="danger">置顶</el-tag>
            <span class="row-title" :class="{ unread: !a.read }">{{ a.title }}</span>
          </div>
        </div>
        <div class="card">
          <div class="card-head"><b>近期考勤</b><el-button link type="primary" @click="router.push('/attendance')">打卡</el-button></div>
          <el-empty v-if="!data.recent_attendance.length" description="暂无考勤记录" :image-size="60" />
          <div v-for="r in data.recent_attendance" :key="r.work_date" class="row">
            <span class="mono">{{ r.work_date }}</span>
            <StatusTag :status="r.status" />
            <span class="muted mono">{{ fmtTime(r.check_in_at) }} - {{ fmtTime(r.check_out_at) }}</span>
          </div>
        </div>
        <div class="card">
          <div class="card-head"><b>日程提醒（7 天内）</b><el-button link type="primary" @click="schedDialog = true">新建日程</el-button></div>
          <el-empty v-if="!data.reminders.length" description="暂无日程" :image-size="60" />
          <div v-for="r in data.reminders" :key="r.kind + r.id" class="row">
            <el-tag size="small" :type="r.kind === 'meeting' ? 'warning' : 'info'">{{ r.kind === 'meeting' ? '会议' : '日程' }}</el-tag>
            <span class="row-title">{{ r.title }}</span>
            <span class="muted">{{ fmtDateTime(r.start_at) }}</span>
          </div>
        </div>
      </div>
      <div class="card">
        <div class="card-head"><b>{{ data.company_view ? '近 6 个月业务申请趋势（全公司/数据范围）' : '我近 6 个月的申请趋势' }}</b></div>
        <el-empty v-if="!data.trend.series.length" description="暂无业务数据" :image-size="60" />
        <EChart v-else :option="trendOption" :height="300" />
      </div>
    </template>
    <InstanceDrawer v-model="drawer" :instance-id="current" @changed="load" />
    <el-dialog v-model="schedDialog" title="新建日程" width="440px">
      <el-form :model="sched" label-width="80px">
        <el-form-item label="标题" required><el-input v-model="sched.title" maxlength="128" /></el-form-item>
        <el-form-item label="开始" required><el-date-picker v-model="sched.start_at" type="datetime" value-format="YYYY-MM-DDTHH:mm:ss" /></el-form-item>
        <el-form-item label="结束" required><el-date-picker v-model="sched.end_at" type="datetime" value-format="YYYY-MM-DDTHH:mm:ss" /></el-form-item>
        <el-form-item label="提醒"><el-date-picker v-model="sched.remind_at" type="datetime" value-format="YYYY-MM-DDTHH:mm:ss" /></el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="schedDialog = false">取消</el-button>
        <el-button type="primary" @click="saveSched">保存</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, reactive, ref } from 'vue'
import { useRouter } from 'vue-router'
import { api, errorText } from '@/api/http'
import { act } from '@/utils/usePaged'
import { BUSINESS, fmtDateTime, fmtTime, hoursToDays, today as todayStr } from '@/utils/format'
import StatusTag from '@/components/StatusTag.vue'
import EChart from '@/components/EChart.vue'
import InstanceDrawer from '@/components/InstanceDrawer.vue'

const router = useRouter()
const data = ref<any>(null)
const loading = ref(false)
const error = ref('')
const drawer = ref(false)
const current = ref<number | null>(null)
const schedDialog = ref(false)
const sched = reactive({ title: '', start_at: '', end_at: '', remind_at: '' })
const today = todayStr()
const hour = new Date().getHours()
const greeting = hour < 11 ? '早上好' : hour < 14 ? '中午好' : hour < 18 ? '下午好' : '晚上好'

const trendOption = computed(() => ({
  tooltip: { trigger: 'axis' },
  legend: { top: 0 },
  grid: { left: 40, right: 20, top: 40, bottom: 30 },
  xAxis: { type: 'category', data: data.value?.trend.months || [] },
  yAxis: { type: 'value', minInterval: 1 },
  series: (data.value?.trend.series || []).map((s: any) => ({ name: s.name, type: 'bar', stack: 'total', data: s.data })),
}))

async function load() {
  loading.value = true
  error.value = ''
  try {
    data.value = await api.get('/api/dashboard/summary')
  } catch (e) {
    error.value = errorText(e)
  } finally {
    loading.value = false
  }
}

function open(id: number) {
  current.value = id
  drawer.value = true
}

async function saveSched() {
  if (await act(() => api.post('/api/schedules', { ...sched, remind_at: sched.remind_at || null }), '日程已保存')) {
    schedDialog.value = false
    Object.assign(sched, { title: '', start_at: '', end_at: '', remind_at: '' })
    load()
  }
}

onMounted(load)
</script>

<style scoped>
.mb {
  margin-bottom: 16px;
}
.card-head {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 8px;
}
.row {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 8px 4px;
  border-bottom: 1px dashed var(--doe-border);
  cursor: pointer;
  font-size: 14px;
}
.row:hover {
  background: var(--doe-brand-soft);
}
.row-title {
  flex: 1;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.unread {
  font-weight: 600;
}
</style>
