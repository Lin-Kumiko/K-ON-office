<template>
  <el-drawer :model-value="modelValue" size="760px" :title="detail?.title || '审批详情'" destroy-on-close
             @update:model-value="(v: boolean) => emit('update:modelValue', v)">
    <div v-loading="loading">
      <template v-if="detail">
        <el-descriptions :column="2" border size="small">
          <el-descriptions-item label="业务类型">{{ detail.business_type_name }}</el-descriptions-item>
          <el-descriptions-item label="状态"><StatusTag :status="detail.status" /></el-descriptions-item>
          <el-descriptions-item label="发起人">{{ detail.initiator_name }}</el-descriptions-item>
          <el-descriptions-item label="流程版本">{{ detail.definition_name }} v{{ detail.version }}</el-descriptions-item>
          <el-descriptions-item label="发起时间">{{ fmtDateTime(detail.started_at) }}</el-descriptions-item>
          <el-descriptions-item label="结束时间">{{ fmtDateTime(detail.ended_at) }}</el-descriptions-item>
          <el-descriptions-item label="当前节点" :span="2">
            {{ detail.current_nodes.join('、') || '-' }}
            <span v-if="detail.current_assignees.length" class="muted">（{{ detail.current_assignees.join('、') }}）</span>
          </el-descriptions-item>
          <el-descriptions-item label="条件变量" :span="2">
            <span class="mono muted">{{ varsText }}</span>
          </el-descriptions-item>
        </el-descriptions>

        <h4>流程进度</h4>
        <WorkflowGraph :graph="detail.graph" :states="detail.node_states" :height="220" />

        <template v-if="myTask">
          <h4>我的审批</h4>
          <el-form label-width="90px" class="approve-form" @submit.prevent>
            <template v-if="formKey === 'manager_evaluation'">
              <el-form-item label="主管评分" required>
                <el-input-number v-model="form.score" :min="0" :max="100" />
              </el-form-item>
              <el-form-item label="评价内容" required>
                <el-input v-model="form.evaluation" type="textarea" :rows="3" maxlength="2000" show-word-limit />
              </el-form-item>
            </template>
            <el-form-item label="审批意见">
              <el-input v-model="form.comment" type="textarea" :rows="2" maxlength="1000" placeholder="驳回时必填"
                        data-test="approve-comment" />
            </el-form-item>
            <el-form-item>
              <el-button type="primary" :loading="busy" data-test="approve-btn" @click="approve">通过</el-button>
              <el-button type="danger" plain :loading="busy" data-test="reject-btn" @click="reject">驳回</el-button>
              <el-popover trigger="click" :width="300">
                <template #reference><el-button>转交</el-button></template>
                <PersonSelect v-model="transferTo" mode="user" placeholder="选择转交对象" />
                <el-button type="primary" size="small" style="margin-top: 8px" :disabled="!transferTo" @click="transfer">
                  确认转交</el-button>
              </el-popover>
            </el-form-item>
          </el-form>
        </template>

        <div class="toolbar" v-if="detail.status === 'running'">
          <el-button v-if="detail.initiator_id === auth.me?.id" @click="withdraw">撤回申请</el-button>
          <el-button v-if="auth.can('workflow:monitor') || detail.initiator_id === auth.me?.id" type="warning" plain
                     @click="cancel">取消流程</el-button>
        </div>

        <h4>审批任务</h4>
        <el-table :data="detail.tasks" size="small" border>
          <el-table-column prop="node_name" label="节点" min-width="120" />
          <el-table-column label="方式" width="70"><template #default="{ row }">{{ row.mode === 'and' ? '会签' : '或签' }}</template></el-table-column>
          <el-table-column prop="assignee_name" label="审批人" width="110" />
          <el-table-column label="状态" width="90"><template #default="{ row }"><StatusTag :status="row.status" /></template></el-table-column>
          <el-table-column prop="comment" label="意见" min-width="140" show-overflow-tooltip />
          <el-table-column label="处理时间" width="140"><template #default="{ row }">{{ fmtDateTime(row.acted_at) }}</template></el-table-column>
        </el-table>

        <h4>审批历史</h4>
        <el-timeline>
          <el-timeline-item v-for="h in detail.history" :key="h.id" :timestamp="fmtDateTime(h.created_at)" placement="top"
                            :type="h.action === 'reject' || h.action === 'rejected' ? 'danger' : h.action === 'end' ? 'success' : undefined">
            <b>{{ HISTORY_ACTION[h.action] || h.action }}</b>
            <span v-if="h.node_name" class="muted"> · {{ h.node_name }}</span>
            <span v-if="h.actor_name"> · {{ h.actor_name }}</span>
            <div v-if="h.comment" class="muted">“{{ h.comment }}”</div>
          </el-timeline-item>
        </el-timeline>
        <div v-if="detail.cc_users.length" class="muted">抄送：{{ detail.cc_users.join('、') }}</div>
      </template>
    </div>
  </el-drawer>
</template>

<script setup lang="ts">
import { computed, reactive, ref, watch } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { api, errorText } from '@/api/http'
import { useAuth } from '@/stores/auth'
import { fmtDateTime, HISTORY_ACTION } from '@/utils/format'
import StatusTag from './StatusTag.vue'
import WorkflowGraph from './WorkflowGraph.vue'
import PersonSelect from './PersonSelect.vue'

const props = defineProps<{ modelValue: boolean; instanceId: number | null }>()
const emit = defineEmits(['update:modelValue', 'changed'])
const auth = useAuth()
const detail = ref<any>(null)
const loading = ref(false)
const busy = ref(false)
const transferTo = ref<number | null>(null)
const form = reactive({ comment: '', score: 90, evaluation: '' })

const myTask = computed(() => detail.value?.tasks.find((t: any) => t.status === 'pending' && t.assignee_id === auth.me?.id))
const formKey = computed(() => {
  const node = detail.value?.graph.nodes.find((n: any) => n.id === myTask.value?.node_id)
  return node?.config?.form_key
})
const varsText = computed(() => JSON.stringify(detail.value?.variables || {}))

async function load() {
  if (!props.instanceId) return
  loading.value = true
  try {
    detail.value = await api.get(`/api/workflow/instances/${props.instanceId}`)
    form.comment = ''
    form.evaluation = ''
  } catch (e) {
    ElMessage.error(errorText(e))
  } finally {
    loading.value = false
  }
}

watch(() => [props.modelValue, props.instanceId], ([open]) => open && load(), { immediate: true })

async function run(fn: () => Promise<unknown>, msg: string) {
  busy.value = true
  try {
    await fn()
    ElMessage.success(msg)
    emit('changed')
    await load()
  } catch (e) {
    ElMessage.error(errorText(e))
  } finally {
    busy.value = false
  }
}

function approve() {
  const formData: Record<string, unknown> = {}
  if (formKey.value === 'manager_evaluation') {
    formData.score = form.score
    formData.evaluation = form.evaluation
  }
  if (formKey.value === 'hr_review') formData.comment = form.comment
  run(() => api.post(`/api/workflow/tasks/${myTask.value.id}/approve`,
    { comment: form.comment || null, form_data: Object.keys(formData).length ? formData : null },
    undefined, { 'Idempotency-Key': `approve-${myTask.value.id}` }), '已通过')
}

function reject() {
  if (!form.comment.trim()) {
    ElMessage.warning('驳回需要填写审批意见')
    return
  }
  run(() => api.post(`/api/workflow/tasks/${myTask.value.id}/reject`, { comment: form.comment }), '已驳回')
}

function transfer() {
  run(() => api.post(`/api/workflow/tasks/${myTask.value.id}/transfer`, { to_user_id: transferTo.value, comment: form.comment || null }), '已转交')
}

async function withdraw() {
  await ElMessageBox.confirm('撤回后可修改并重新提交，确定撤回？', '撤回申请')
  run(() => api.post(`/api/workflow/instances/${detail.value.id}/withdraw`, {}), '已撤回')
}

async function cancel() {
  await ElMessageBox.confirm('取消后单据不可再次提交，确定取消？', '取消流程', { type: 'warning' })
  run(() => api.post(`/api/workflow/instances/${detail.value.id}/cancel`, {}), '已取消')
}
</script>

<style scoped>
h4 {
  margin: 18px 0 8px;
}
.approve-form {
  background: var(--doe-brand-soft);
  padding: 12px 12px 0;
  border-radius: 10px;
}
</style>
