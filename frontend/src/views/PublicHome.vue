<template>
  <div class="page" v-loading="loading">
    <section class="banner">
      <div class="banner-text">
        <h2>{{ data?.company_name || '放学后茶会株式会社' }}</h2>
        <p>{{ data?.slogan || '认真工作，然后喝茶' }}</p>
        <p v-if="data" class="facts" data-test="public-facts">
          {{ data.stats.departments }} 个部门，{{ data.stats.headcount }} 名成员，{{ data.stats.rooms }} 间会议室，
          {{ data.stats.workflows }} 条审批流程正在运行。
        </p>
        <div class="banner-actions">
          <el-button type="primary" size="large" data-test="public-login" @click="router.push({ name: 'login' })">登录</el-button>
          <el-button size="large" @click="router.push({ name: 'register' })">注册账号</el-button>
        </div>
      </div>
      <img src="/teacup.svg" alt="" class="banner-cup" />
    </section>

    <el-alert v-if="error" :title="error" type="error" show-icon class="mb" />

    <div class="grid cols-2 mb">
      <div class="card">
        <div class="card-head"><b>最新公告</b><el-button link type="primary" @click="router.push('/announcements')">全部公告</el-button></div>
        <el-empty v-if="data && !data.announcements.length" description="还没有发布公告" :image-size="60" />
        <button v-for="a in data?.announcements || []" :key="a.id" class="row" @click="router.push(`/announcements?id=${a.id}`)">
          <el-tag v-if="a.pinned" size="small" type="danger" disable-transitions>置顶</el-tag>
          <span class="row-title">{{ a.title }}</span>
          <span class="muted">{{ fmtDate(a.published_at) }}</span>
        </button>
      </div>
      <div class="card">
        <div class="card-head"><b>未来 7 天的会议</b><el-button link type="primary" @click="router.push('/meeting')">会议日历</el-button></div>
        <el-empty v-if="data && !data.meetings.length" description="这周还没有安排会议" :image-size="60" />
        <div v-for="(m, i) in data?.meetings || []" :key="i" class="row static">
          <span class="mono">{{ fmtDateTime(m.start_at) }}</span>
          <span class="row-title">{{ m.subject }}</span>
          <span class="muted">{{ m.room }}</span>
        </div>
      </div>
    </div>

    <div class="grid cols-2">
      <div class="card">
        <b>各部门人数</b>
        <EChart v-if="data?.departments.length" :option="deptOption" :height="260" />
      </div>
      <div class="card">
        <b>登录后可以做的事</b>
        <p class="muted">你现在以访客身份浏览公开信息。下面这些操作需要先登录：</p>
        <div class="actions">
          <el-button v-for="a in ACTIONS" :key="a.path" @click="go(a.path)">{{ a.label }}</el-button>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import { api, errorText } from '@/api/http'
import { fmtDate, fmtDateTime } from '@/utils/format'
import { promptLogin } from '@/utils/loginPrompt'
import EChart from '@/components/EChart.vue'

const ACTIONS = [
  { label: '上下班打卡', path: '/attendance' }, { label: '申请请假', path: '/leave' },
  { label: '提交报销', path: '/expense' }, { label: '预约会议室', path: '/meeting' },
  { label: '处理审批', path: '/approvals' }, { label: '查看工资单', path: '/payroll' },
]
const router = useRouter()
const data = ref<any>(null)
const loading = ref(false)
const error = ref('')

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
.banner {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 24px;
  padding: 28px 32px;
  margin-bottom: 16px;
  border-radius: 14px;
  color: #fff;
  background: linear-gradient(115deg, #8c7bc6 0%, #f28ca0 58%, #f7b58b 100%);
}
.banner h2 {
  margin: 0 0 6px;
  font-family: 'KaiTi', 'STKaiti', 'Kaiti SC', serif;
  font-size: 34px;
  letter-spacing: 0.06em;
}
.banner p {
  margin: 0 0 8px;
  max-width: 60ch;
}
.facts {
  opacity: 0.92;
}
.banner-actions {
  margin-top: 14px;
}
.banner-cup {
  width: 110px;
  background: #fff4ea;
  border-radius: 24px;
  padding: 14px;
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
  width: 100%;
  padding: 9px 4px;
  border: none;
  border-bottom: 1px dashed var(--doe-border);
  background: none;
  color: inherit;
  font: inherit;
  text-align: left;
  cursor: pointer;
}
.row.static {
  cursor: default;
}
.row:not(.static):hover {
  background: var(--doe-brand-soft);
}
.row-title {
  flex: 1;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.actions {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
}
.actions .el-button {
  margin: 0;
}
@media (max-width: 720px) {
  .banner {
    padding: 22px;
  }
  .banner-cup {
    display: none;
  }
}
</style>
