<template>
  <div class="page">
    <section class="hero card">
      <div class="hero-art"><AfterSchoolScene /></div>
      <div class="hero-text">
        <p class="hero-hello">{{ hello }}</p>
        <h2>{{ data?.company_name || '放学后茶会株式会社' }}</h2>
        <p class="hero-slogan">{{ data?.slogan || '认真工作，然后喝茶' }}</p>
        <div class="hero-actions">
          <el-button type="primary" size="large" data-test="public-login" @click="router.push({ name: 'login' })">登录</el-button>
          <el-button size="large" @click="router.push({ name: 'register' })">注册账号</el-button>
        </div>
        <dl v-if="data" class="facts" data-test="public-facts">
          <div v-for="f in facts" :key="f.unit"><dt><CountUp :value="f.value" /></dt><dd>{{ f.unit }}</dd></div>
        </dl>
        <div v-else-if="loading" class="facts facts-wait" aria-hidden="true"><span v-for="n in 4" :key="n" class="skeleton" /></div>
      </div>
    </section>

    <el-alert v-if="error" :title="error" type="error" show-icon class="mb" />

    <div v-if="loading && !data" class="grid cols-2 mb" aria-hidden="true">
      <div v-for="n in 2" :key="n" class="card"><span class="skeleton line w40" /><span v-for="m in 3" :key="m" class="skeleton line" /></div>
    </div>

    <template v-if="data">
      <div class="grid cols-2 mb">
        <div class="card">
          <div class="card-head"><b>最新公告</b><el-button link type="primary" @click="router.push('/announcements')">全部公告</el-button></div>
          <el-empty v-if="!data.announcements.length" description="还没有发布公告" :image-size="60" />
          <button v-for="a in data.announcements" :key="a.id" class="row" @click="router.push(`/announcements?id=${a.id}`)">
            <el-tag v-if="a.pinned" size="small" type="danger" disable-transitions>置顶</el-tag>
            <span class="row-title">{{ a.title }}</span>
            <span class="muted">{{ fmtDate(a.published_at) }}</span>
          </button>
        </div>
        <div class="card">
          <div class="card-head"><b>未来 7 天的会议</b><el-button link type="primary" @click="router.push('/meeting')">会议日历</el-button></div>
          <el-empty v-if="!data.meetings.length" description="这周还没有安排会议" :image-size="60" />
          <div v-for="(m, i) in data.meetings" :key="i" class="row static">
            <span class="mono">{{ fmtDateTime(m.start_at) }}</span>
            <span class="row-title">{{ m.subject }}</span>
            <span class="muted">{{ m.room }}</span>
          </div>
        </div>
      </div>

      <div class="grid cols-2">
        <div class="card">
          <b>各部门人数</b>
          <EChart v-if="data.departments.length" :option="deptOption" :height="260" />
        </div>
        <div class="card">
          <b>登录后可以做的事</b>
          <p class="muted">你现在以访客身份浏览公开信息。下面这些操作需要先登录：</p>
          <div class="actions">
            <button v-for="a in ACTIONS" :key="a.path" type="button" class="action" @click="go(a.path)">
              <el-icon class="action-icon"><component :is="a.icon" /></el-icon>
              <span>{{ a.label }}</span>
            </button>
          </div>
        </div>
      </div>
    </template>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import { api, errorText } from '@/api/http'
import { fmtDate, fmtDateTime } from '@/utils/format'
import { promptLogin } from '@/utils/loginPrompt'
import EChart from '@/components/EChart.vue'
import CountUp from '@/components/CountUp.vue'
import AfterSchoolScene from '@/components/AfterSchoolScene.vue'

const ACTIONS = [
  { label: '上下班打卡', path: '/attendance', icon: 'Clock' }, { label: '申请请假', path: '/leave', icon: 'Calendar' },
  { label: '提交报销', path: '/expense', icon: 'Money' }, { label: '预约会议室', path: '/meeting', icon: 'Microphone' },
  { label: '处理审批', path: '/approvals', icon: 'Stamp' }, { label: '查看工资单', path: '/payroll', icon: 'Wallet' },
]
const router = useRouter()
const data = ref<any>(null)
const loading = ref(false)
const error = ref('')

const hour = new Date().getHours()
const hello = hour < 11 ? '早上好，今天的第一壶茶已经泡上了' : hour < 14 ? '中午好，午休记得吃点甜的'
  : hour < 18 ? '下午好，正是放学后的茶会时间' : '晚上好，活动室的灯还亮着'
const facts = computed(() => {
  const s = data.value?.stats
  return s ? [{ value: s.departments, unit: '个部门' }, { value: s.headcount, unit: '名成员' }, { value: s.rooms, unit: '间会议室' },
              { value: s.workflows, unit: '条审批流程' }] : []
})

const deptOption = computed(() => ({
  tooltip: {}, grid: { left: 110, right: 24, top: 10, bottom: 24 },
  xAxis: { type: 'value', minInterval: 1 },
  yAxis: { type: 'category', data: (data.value?.departments || []).map((d: any) => d.name) },
  series: [{ type: 'bar', data: (data.value?.departments || []).map((d: any) => d.headcount), barMaxWidth: 22 }],
}))

function go(path: string) {
  promptLogin(path)
}

onMounted(async () => {
  loading.value = true
  try {
    data.value = await api.get('/api/public/overview')
  } catch (e) {
    error.value = errorText(e)
  } finally {
    loading.value = false
  }
})
</script>

<style scoped>
.mb {
  margin-bottom: 16px;
}
.hero {
  overflow: hidden;
  min-height: 380px;
  padding: 0;
  margin-bottom: 16px;
  display: flex;
  align-items: stretch;
}
.hero-art {
  position: absolute;
  inset: 0 0 0 38%;
  -webkit-mask-image: linear-gradient(90deg, transparent, #000 34%);
  mask-image: linear-gradient(90deg, transparent, #000 34%);
}
.hero-text {
  position: relative;
  z-index: 1;
  width: min(560px, 62%);
  padding: 44px 0 36px 44px;
  display: flex;
  flex-direction: column;
}
.hero-hello {
  margin: 0 0 14px;
  font-size: 14px;
  color: var(--doe-brand);
  font-weight: 500;
}
.hero h2 {
  margin: 0 0 12px;
  font-size: clamp(30px, 4.4vw, 52px);
  line-height: 1.12;
  font-weight: 750;
  letter-spacing: -0.02em;
  text-wrap: balance;
}
.hero-slogan {
  margin: 0;
  font-size: 17px;
  color: var(--el-text-color-regular);
}
.hero-actions {
  margin: 26px 0 30px;
  display: flex;
  gap: 10px;
}
.hero-actions .el-button {
  margin: 0;
}
.facts {
  margin: auto 0 0;
  display: flex;
  flex-wrap: wrap;
  gap: 8px 28px;
}
.facts > div {
  display: flex;
  align-items: baseline;
  gap: 6px;
}
.facts dt {
  font-size: 26px;
  font-weight: 700;
  letter-spacing: -0.02em;
  font-variant-numeric: tabular-nums;
}
.facts dd {
  margin: 0;
  font-size: 13px;
  color: var(--doe-muted);
}
.facts-wait .skeleton {
  width: 84px;
  height: 30px;
}
.skeleton.line {
  display: block;
  height: 16px;
  margin: 14px 0;
}
.skeleton.w40 {
  width: 40%;
}
button.row {
  width: calc(100% + 20px);
  border: none;
  background: none;
  color: inherit;
  font: inherit;
  text-align: left;
}
.row.static {
  cursor: default;
}
.row.static:hover {
  background: none;
}
.row .muted {
  font-size: 13px;
  white-space: nowrap;
}
.card p.muted {
  font-size: 14px;
}
.actions {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 10px;
  margin-top: 4px;
}
.action {
  display: flex;
  flex-direction: column;
  align-items: flex-start;
  gap: 10px;
  padding: 14px;
  border-radius: 12px;
  border: 1px solid var(--doe-border);
  background: var(--glass-bg);
  color: var(--doe-text);
  font: inherit;
  font-size: 14px;
  cursor: pointer;
  transition: border-color 0.14s, background-color 0.14s;
}
.action:hover {
  border-color: var(--el-color-primary-light-5);
  background: var(--doe-brand-soft);
}
.action-icon {
  font-size: 18px;
  color: var(--doe-brand);
}
@media (max-width: 900px) {
  .hero {
    flex-direction: column;
    min-height: 0;
  }
  .hero-art {
    position: relative;
    inset: auto;
    height: 200px;
    order: -1;
    -webkit-mask-image: linear-gradient(180deg, #000 60%, transparent);
    mask-image: linear-gradient(180deg, #000 60%, transparent);
  }
  .hero-text {
    width: 100%;
    padding: 8px 20px 24px;
  }
}
@media (max-width: 720px) {
  .actions {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }
}
@media (prefers-reduced-motion: reduce) {
  .action {
    transition: none;
  }
}
</style>
