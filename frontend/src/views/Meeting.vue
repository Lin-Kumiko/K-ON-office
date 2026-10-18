<template>
  <div class="page">
    <div class="page-head">
      <div><h2>会议室</h2><div class="sub">冲突检测由后端事务与数据库触发器双重保证；讲堂与别墅会议厅需行政审批</div></div>
      <el-button type="primary" data-test="new-booking" @click="openBooking()">预约会议室</el-button>
    </div>
    <div class="card">
      <el-tabs v-model="tab" @tab-change="onTab">
        <el-tab-pane label="会议日历" name="calendar" />
        <el-tab-pane label="我的预约" name="mine" />
        <el-tab-pane label="会议室" name="rooms" />
      </el-tabs>
      <template v-if="tab === 'calendar'">
        <div class="toolbar">
          <el-button @click="shift(-7)">上一周</el-button>
          <el-date-picker v-model="weekStart" type="date" value-format="YYYY-MM-DD" :clearable="false" @change="loadCalendar" />
          <el-button @click="shift(7)">下一周</el-button>
          <el-select v-model="roomFilter" clearable placeholder="全部会议室" style="width: 160px" @change="loadCalendar">
            <el-option v-for="r in rooms" :key="r.id" :label="r.name" :value="r.id" />
          </el-select>
        </div>
        <div class="week">
          <div v-for="d in days" :key="d" class="day">
            <div class="day-head">{{ d.slice(5) }} {{ weekday(d) }}</div>
            <div v-for="b in byDay[d] || []" :key="b.id" class="evt" :class="b.status">
              <div class="mono">{{ fmtTime(b.start_at) }}-{{ fmtTime(b.end_at) }}</div>
              <div class="evt-title">{{ b.subject }}</div>
              <div class="muted small">{{ b.room_name }} · {{ b.organizer_name }}<span v-if="b.status === 'pending'">（待审批）</span></div>
            </div>
          </div>
        </div>
      </template>
      <template v-else-if="tab === 'mine'">
        <el-table :data="mine.state.items" v-loading="mine.state.loading" border empty-text="暂无预约">
          <el-table-column prop="room_name" label="会议室" width="130" />
          <el-table-column prop="subject" label="主题" min-width="160" />
          <el-table-column label="时间" width="220"><template #default="{ row }">{{ fmtDateTime(row.start_at) }} - {{ fmtTime(row.end_at) }}</template></el-table-column>
          <el-table-column label="状态" width="100"><template #default="{ row }"><StatusTag :status="row.status" /></template></el-table-column>
          <el-table-column label="操作" width="160">
            <template #default="{ row }">
              <el-button v-if="['pending', 'approved'].includes(row.status)" link type="warning" @click="cancel(row)">取消</el-button>
              <el-button v-if="row.instance_id" link @click="openFlow(row.instance_id)">审批</el-button>
            </template>
          </el-table-column>
        </el-table>
        <div class="pager"><el-pagination layout="total, prev, pager, next" :total="mine.state.total" :page-size="mine.state.pageSize" @current-change="(p: number) => mine.load(p)" /></div>
      </template>
      <template v-else>
        <div class="toolbar" v-if="auth.can('meeting:manage')"><el-button type="primary" @click="openRoom()">新增会议室</el-button></div>
        <el-table :data="rooms" border>
          <el-table-column prop="name" label="名称" width="150" />
          <el-table-column prop="location" label="位置" width="160" />
          <el-table-column prop="capacity" label="容量" width="70" />
          <el-table-column prop="equipment" label="设备" min-width="160" />
          <el-table-column label="开放时间" width="120"><template #default="{ row }">{{ row.open_from }}-{{ row.open_to }}</template></el-table-column>
          <el-table-column label="需审批" width="80"><template #default="{ row }">{{ row.requires_approval ? '是' : '否' }}</template></el-table-column>
          <el-table-column label="状态" width="80"><template #default="{ row }"><StatusTag :status="row.status" /></template></el-table-column>
          <el-table-column label="操作" width="200">
            <template #default="{ row }">
              <el-button link type="primary" @click="openBooking(row.id)">预约</el-button>
              <el-button link @click="usage(row)">使用记录</el-button>
              <el-button v-if="auth.can('meeting:manage')" link @click="openRoom(row)">编辑</el-button>
            </template>
          </el-table-column>
        </el-table>
      </template>
    </div>

    <el-dialog v-model="bookOpen" title="预约会议室" width="560px" data-test="booking-dialog">
      <el-form :model="book" label-width="80px">
        <el-form-item label="会议室" required>
          <el-select v-model="book.room_id" @change="loadAvailability" data-test="booking-room">
            <el-option v-for="r in rooms.filter((x) => x.status === 'active')" :key="r.id" :label="`${r.name}（${r.capacity}人${r.requires_approval ? '，需审批' : ''}）`" :value="r.id" />
          </el-select>
        </el-form-item>
        <el-form-item label="日期" required><span class="dt-wrap" data-test="booking-day"><el-date-picker v-model="book.day" type="date" value-format="YYYY-MM-DD" @change="loadAvailability" /></span></el-form-item>
        <el-form-item label="时间" required>
          <span class="dt-wrap" data-test="booking-start"><el-time-select v-model="book.start" start="08:00" end="21:00" step="00:30" placeholder="开始" style="width: 120px" /></span>
          <span class="mx">至</span>
          <span class="dt-wrap" data-test="booking-end"><el-time-select v-model="book.end" start="08:30" end="21:00" step="00:30" placeholder="结束" :min-time="book.start" style="width: 120px" /></span>
        </el-form-item>
        <el-form-item label="已占用">
          <span v-if="!busy.length" class="muted">当天暂无占用</span>
          <el-tag v-for="s in busy" :key="s.booking_id" :type="s.status === 'pending' ? 'warning' : 'danger'" class="mr">{{ fmtTime(s.start_at) }}-{{ fmtTime(s.end_at) }} {{ s.subject }}</el-tag>
        </el-form-item>
        <el-form-item label="主题" required><el-input v-model="book.subject" maxlength="128" data-test="booking-subject" /></el-form-item>
        <el-form-item label="参会人"><PersonSelect v-model="book.attendee_ids" mode="user" multiple /></el-form-item>
        <el-form-item label="备注"><el-input v-model="book.note" maxlength="500" /></el-form-item>
      </el-form>
      <template #footer><el-button @click="bookOpen = false">取消</el-button><el-button type="primary" data-test="booking-save" @click="saveBooking">提交预约</el-button></template>
    </el-dialog>

    <el-dialog v-model="roomOpen" title="会议室" width="480px">
      <el-form :model="room" label-width="90px">
        <el-form-item label="名称" required><el-input v-model="room.name" /></el-form-item>
        <el-form-item label="位置"><el-input v-model="room.location" /></el-form-item>
        <el-form-item label="容量"><el-input-number v-model="room.capacity" :min="1" :max="1000" /></el-form-item>
        <el-form-item label="设备"><el-input v-model="room.equipment" /></el-form-item>
        <el-form-item label="开放时间"><el-input v-model="room.open_from" style="width: 90px" /> - <el-input v-model="room.open_to" style="width: 90px" /></el-form-item>
        <el-form-item label="需审批"><el-switch v-model="room.requires_approval" /></el-form-item>
        <el-form-item label="状态"><el-radio-group v-model="room.status"><el-radio value="active">启用</el-radio><el-radio value="disabled">停用</el-radio></el-radio-group></el-form-item>
      </el-form>
      <template #footer><el-button @click="roomOpen = false">取消</el-button><el-button type="primary" @click="saveRoom">保存</el-button></template>
    </el-dialog>

    <el-dialog v-model="usageOpen" :title="`使用记录 · ${usageData?.month || ''}`" width="640px">
      <div v-if="usageData" class="muted">本月 {{ usageData.bookings }} 次，共 {{ usageData.hours }} 小时</div>
      <el-table :data="usageData?.records || []" size="small" border class="mt">
        <el-table-column prop="subject" label="主题" />
        <el-table-column prop="organizer_name" label="预约人" width="100" />
        <el-table-column label="时间" width="200"><template #default="{ row }">{{ fmtDateTime(row.start_at) }}-{{ fmtTime(row.end_at) }}</template></el-table-column>
      </el-table>
    </el-dialog>
    <InstanceDrawer v-model="drawer" :instance-id="current" @changed="mine.load()" />
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, reactive, ref } from 'vue'
import { ElMessageBox } from 'element-plus'
import { api } from '@/api/http'
import { useAuth } from '@/stores/auth'
import { act, usePaged } from '@/utils/usePaged'
import { promptLogin } from '@/utils/loginPrompt'
import { fmtDateTime, fmtTime, pad, thisMonth, today } from '@/utils/format'
import StatusTag from '@/components/StatusTag.vue'
import PersonSelect from '@/components/PersonSelect.vue'
import InstanceDrawer from '@/components/InstanceDrawer.vue'

const auth = useAuth()
const tab = ref('calendar')
const rooms = ref<any[]>([])
const roomFilter = ref<number | undefined>()
const calendar = ref<any[]>([])
const mine = usePaged('/api/meeting/bookings', () => ({ scope: 'mine' }))
const monday = (d: Date) => { const x = new Date(d); x.setDate(x.getDate() - ((x.getDay() + 6) % 7)); return x }
const fmt = (d: Date) => `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`
const weekStart = ref(fmt(monday(new Date())))
const days = computed(() => Array.from({ length: 7 }, (_, i) => { const d = new Date(weekStart.value + 'T00:00:00'); d.setDate(d.getDate() + i); return fmt(d) }))
const byDay = computed(() => {
  const m: Record<string, any[]> = {}
  for (const b of calendar.value) (m[b.start_at.slice(0, 10)] ||= []).push(b)
  return m
})
const weekday = (d: string) => '日一二三四五六'[new Date(d + 'T00:00:00').getDay()]
const bookOpen = ref(false)
const book = reactive({ room_id: undefined as number | undefined, day: today(), start: '', end: '', subject: '', attendee_ids: [] as number[], note: '' })
const busy = ref<any[]>([])
const roomOpen = ref(false)
const room = reactive<any>({})
const usageOpen = ref(false)
const usageData = ref<any>(null)
const drawer = ref(false)
const current = ref<number | null>(null)

async function loadRooms() {
  rooms.value = await api.get('/api/meeting/rooms')
}
async function loadCalendar() {
  calendar.value = await api.get('/api/meeting/calendar', { start: days.value[0], end: days.value[6], room_id: roomFilter.value })
}
function shift(n: number) {
  const d = new Date(weekStart.value + 'T00:00:00')
  d.setDate(d.getDate() + n)
  weekStart.value = fmt(d)
  loadCalendar()
}
function onTab() {
  if (tab.value === 'mine' && !auth.loggedIn) {
    tab.value = 'calendar'
    return promptLogin()
  }
  if (tab.value === 'calendar') loadCalendar()
  if (tab.value === 'mine') mine.load(1)
  if (tab.value === 'rooms') loadRooms()
}
function openBooking(roomId?: number) {
  if (!auth.loggedIn) return promptLogin()
  Object.assign(book, { room_id: roomId ?? rooms.value[0]?.id, day: today(), start: '', end: '', subject: '', attendee_ids: [], note: '' })
  bookOpen.value = true
  loadAvailability()
}
async function loadAvailability() {
  if (!book.room_id || !book.day) return
  busy.value = (await api.get(`/api/meeting/rooms/${book.room_id}/availability`, { day: book.day })).busy
}
async function saveBooking() {
  const body = { room_id: book.room_id, subject: book.subject, start_at: `${book.day}T${book.start}:00`, end_at: `${book.day}T${book.end}:00`,
                 attendee_ids: book.attendee_ids, note: book.note || null }
  if (await act(() => api.post('/api/meeting/bookings', body), '预约已提交')) {
    bookOpen.value = false
    onTab()
  } else loadAvailability()
}
async function cancel(row: any) {
  await ElMessageBox.confirm('确定取消该预约？', '取消预约')
  if (await act(() => api.post(`/api/meeting/bookings/${row.id}/cancel`), '已取消')) mine.load()
}
function openRoom(row?: any) {
  Object.keys(room).forEach((k) => delete room[k])
  Object.assign(room, row ? { ...row } : { name: '', location: '', capacity: 8, equipment: '', open_from: '08:00', open_to: '21:00', requires_approval: false, status: 'active' })
  roomOpen.value = true
}
async function saveRoom() {
  const { id, ...body } = room
  if (await act(() => (id ? api.put(`/api/meeting/rooms/${id}`, body) : api.post('/api/meeting/rooms', body)), '已保存')) {
    roomOpen.value = false
    loadRooms()
  }
}
async function usage(row: any) {
  usageData.value = await api.get(`/api/meeting/rooms/${row.id}/usage`, { month: thisMonth() })
  usageOpen.value = true
}
function openFlow(id: number) {
  current.value = id
  drawer.value = true
}

onMounted(async () => {
  await loadRooms()
  loadCalendar()
})
</script>

<style scoped>
.week {
  display: grid;
  grid-template-columns: repeat(7, minmax(0, 1fr));
  gap: 8px;
}
.day {
  background: var(--doe-bg);
  border-radius: 10px;
  padding: 8px;
  min-height: 220px;
}
.day-head {
  font-weight: 600;
  margin-bottom: 6px;
}
.evt {
  background: var(--doe-surface);
  border-left: 4px solid var(--doe-brand);
  border-radius: 6px;
  padding: 6px;
  margin-bottom: 6px;
  font-size: 12px;
}
.evt.pending {
  border-left-color: #e6a23c;
}
.evt-title {
  font-weight: 600;
}
.small {
  font-size: 11px;
}
.mx {
  margin: 0 8px;
}
.mr {
  margin-right: 4px;
}
.mt {
  margin-top: 8px;
}
@media (max-width: 900px) {
  .week {
    grid-template-columns: minmax(0, 1fr);
  }
  .day {
    min-height: auto;
  }
}
</style>
