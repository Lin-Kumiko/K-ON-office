<template>
  <div class="page">
    <div class="page-head">
      <div><h2>流程设计</h2><div class="sub">拖拽节点、从节点右侧圆点拖出连线；条件使用受限规则（字段 / 运算符 / 值），不执行任何代码。发布后版本不可修改，运行中实例保持原版本</div></div>
      <el-button type="primary" @click="newOpen = true">新建流程</el-button>
    </div>
    <div class="designer">
      <div class="card defs">
        <div v-for="d in defs" :key="d.id" class="def" :class="{ active: d.id === def?.id }" :data-test="`def-${d.key}`" @click="selectDef(d.id)">
          <div class="def-name">{{ d.name }}</div>
          <div class="muted small">{{ d.business_type_name }} · v{{ d.current_version ?? '-' }} <StatusTag :status="d.status" />
            <el-tag v-if="d.draft_version_id" size="small" type="warning">有草稿</el-tag></div>
        </div>
      </div>
      <div class="card canvas-card" v-if="def">
        <div class="toolbar">
          <b>{{ def.name }}</b>
          <el-select v-model="versionId" size="small" style="width: 170px" @change="loadVersion">
            <el-option v-for="v in def.versions" :key="v.id" :label="`v${v.version} · ${VSTATUS[v.status]}`" :value="v.id" />
          </el-select>
          <span class="spacer" />
          <template v-if="editable">
            <el-button-group>
              <el-button v-for="t in PALETTE" :key="t.type" size="small" :data-test="`add-${t.type}`" @click="addNode(t.type)">{{ t.label }}</el-button>
            </el-button-group>
            <el-button size="small" :disabled="!selNode && !selEdge" type="danger" plain data-test="delete-selected" @click="removeSelected">删除所选</el-button>
            <el-button size="small" data-test="save-draft" @click="saveDraft">保存草稿</el-button>
            <el-button size="small" data-test="validate" @click="validate">校验</el-button>
            <el-button size="small" type="primary" data-test="publish" @click="publish">发布</el-button>
          </template>
          <template v-else>
            <el-button size="small" :disabled="!!def.draft_version_id" data-test="new-draft" @click="newDraft">基于当前版本新建草稿</el-button>
          </template>
          <el-button size="small" @click="toggleStatus">{{ def.status === 'active' ? '停用' : '启用' }}</el-button>
          <el-button size="small" @click="previewOpen = true">预览</el-button>
        </div>
        <el-alert v-if="errors.length" type="error" :closable="false" class="mb">
          <div v-for="(e, i) in errors" :key="i">{{ e }}</div>
        </el-alert>
        <el-alert v-else-if="validMsg" type="success" :title="validMsg" :closable="false" class="mb" />
        <div class="workspace">
          <div ref="canvas" class="canvas" data-test="canvas" @mousemove="onMove" @mouseup="onUp" @click.self="clearSel">
            <svg class="edges" :width="size.w" :height="size.h">
              <defs>
                <marker id="d-arrow" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" orient="auto-start-reverse">
                  <path d="M 0 0 L 10 5 L 0 10 z" fill="#8a7a70" />
                </marker>
              </defs>
              <g v-for="e in edgePaths" :key="e.id" class="edge" :class="{ sel: selEdge?.id === e.id }" :data-test="`edge-${e.id}`" @click.stop="selectEdge(e.id)">
                <path :d="e.d" class="hit" />
                <path :d="e.d" class="line" marker-end="url(#d-arrow)" />
                <text :x="e.mx" :y="e.my - 6" text-anchor="middle" class="elabel">{{ e.label }}</text>
              </g>
              <path v-if="linking" :d="`M${linking.x1},${linking.y1} L${linking.x2},${linking.y2}`" class="line temp" />
            </svg>
            <div v-for="n in graph.nodes" :key="n.id" class="node" :class="[n.type, { sel: selNode?.id === n.id }]"
                 :style="{ left: `${n.x - W / 2}px`, top: `${n.y - H / 2}px` }" :data-test="`node-${n.id}`"
                 @mousedown.stop="startDrag($event, n)" @mouseup.stop="finishLink(n)" @click.stop="selectNode(n.id)">
              <span class="ntype">{{ TYPE_LABEL[n.type] }}</span>
              <span class="nname">{{ n.name }}</span>
              <span v-if="editable && n.type !== 'end'" class="port" :data-test="`port-${n.id}`" @mousedown.stop="startLink($event, n)" />
            </div>
          </div>
          <div class="props">
            <template v-if="selNode">
              <h4>节点属性</h4>
              <el-form label-position="top" size="small" :disabled="!editable">
                <el-form-item label="ID"><el-input :model-value="selNode.id" disabled /></el-form-item>
                <el-form-item label="名称"><el-input v-model="selNode.name" data-test="prop-name" /></el-form-item>
                <template v-if="selNode.type === 'approval' || selNode.type === 'cc'">
                  <el-form-item :label="selNode.type === 'cc' ? '抄送对象' : '审批人策略'">
                    <el-select v-model="cfgTarget.type" data-test="prop-approver" @change="onApproverType">
                      <el-option v-for="(v, k) in APPROVER" v-show="selNode.type === 'approval' || k !== 'amount_based'" :key="k" :label="v" :value="k" />
                    </el-select>
                  </el-form-item>
                  <ApproverFields :cfg="cfgTarget" :roles="roles" :vars="numericVars" />
                  <template v-if="cfgTarget.type === 'amount_based'">
                    <div v-for="(r, i) in cfgTarget.rules" :key="i" class="rule-box">
                      <el-form-item :label="i === cfgTarget.rules.length - 1 ? '其余金额' : `金额 ≤`">
                        <el-input-number v-if="i !== cfgTarget.rules.length - 1" v-model="r.max" :min="0" />
                      </el-form-item>
                      <el-select v-model="r.approver.type" class="mb4">
                        <el-option v-for="(v, k) in APPROVER" v-show="k !== 'amount_based'" :key="k" :label="v" :value="k" />
                      </el-select>
                      <ApproverFields :cfg="r.approver" :roles="roles" :vars="numericVars" />
                    </div>
                    <el-button size="small" @click="cfgTarget.rules.splice(cfgTarget.rules.length - 1, 0, { max: 1000, approver: { type: 'direct_manager' } })">添加金额档位</el-button>
                  </template>
                  <template v-if="selNode.type === 'approval'">
                    <el-form-item label="多人审批方式">
                      <el-radio-group v-model="selNode.config.mode"><el-radio value="or">或签（任一）</el-radio><el-radio value="and">会签（全部）</el-radio></el-radio-group>
                    </el-form-item>
                    <el-form-item label="找不到审批人时">
                      <el-select v-model="selNode.config.on_empty">
                        <el-option label="转交系统管理员" value="fallback" /><el-option label="自动通过" value="auto_pass" /><el-option label="报错阻止提交" value="error" />
                      </el-select>
                    </el-form-item>
                    <el-form-item label="审批表单">
                      <el-select v-model="selNode.config.form_key" clearable placeholder="无">
                        <el-option label="主管评价（评分+评语）" value="manager_evaluation" /><el-option label="人事审核意见" value="hr_review" />
                      </el-select>
                    </el-form-item>
                  </template>
                </template>
                <div v-if="selNode.type === 'condition'" class="muted small">选中从该节点出发的连线，配置分支条件；必须保留一条默认分支。</div>
                <div v-if="selNode.type === 'parallel'" class="muted small">并行节点的所有出线同时执行，必须在同一个汇聚节点合并。</div>
              </el-form>
            </template>
            <template v-else-if="selEdge">
              <h4>连线属性</h4>
              <el-form label-position="top" size="small" :disabled="!editable">
                <el-form-item label="显示文字"><el-input v-model="selEdge.label" /></el-form-item>
                <template v-if="graphNode(selEdge.source)?.type === 'condition'">
                  <el-form-item><el-checkbox v-model="selEdge.default" data-test="edge-default" @change="onDefault">默认分支（其他条件都不满足时）</el-checkbox></el-form-item>
                  <template v-if="!selEdge.default">
                    <el-form-item label="优先级（小的先判断）"><el-input-number v-model="selEdge.priority" :min="1" :max="99" /></el-form-item>
                    <el-form-item label="条件组合">
                      <el-radio-group v-model="condMode" @change="syncCond"><el-radio value="all">全部满足</el-radio><el-radio value="any">任一满足</el-radio></el-radio-group>
                    </el-form-item>
                    <div v-for="(c, i) in condRows" :key="i" class="cond">
                      <el-select v-model="c.field" placeholder="字段" style="width: 110px" data-test="cond-field" @change="syncCond">
                        <el-option v-for="(t, f) in vars" :key="f" :label="f" :value="f" />
                      </el-select>
                      <el-select v-model="c.op" style="width: 70px" data-test="cond-op" @change="syncCond"><el-option v-for="o in OPS" :key="o" :label="o" :value="o" /></el-select>
                      <el-input v-model="c.value" style="width: 80px" data-test="cond-value" @change="syncCond" />
                      <el-button link type="danger" @click="condRows.splice(i, 1); syncCond()">×</el-button>
                    </div>
                    <el-button size="small" data-test="add-cond" @click="condRows.push({ field: Object.keys(vars)[0], op: '>', value: '' }); syncCond()">添加条件</el-button>
                  </template>
                </template>
              </el-form>
            </template>
            <template v-else>
              <h4>使用说明</h4>
              <ul class="muted small help">
                <li>工具栏添加节点，拖动摆放位置</li>
                <li>按住节点右侧圆点拖到目标节点即可连线</li>
                <li>点击节点 / 连线编辑属性，点击空白处取消选择</li>
                <li>可用条件变量：{{ Object.entries(vars).map(([k, t]) => `${k}(${t})`).join('、') }}</li>
              </ul>
            </template>
          </div>
        </div>
      </div>
      <div v-else class="card"><el-empty description="选择左侧流程定义" /></div>
    </div>

    <el-dialog v-model="newOpen" title="新建流程定义" width="460px">
      <el-form :model="nd" label-width="80px">
        <el-form-item label="标识" required><el-input v-model="nd.key" placeholder="小写字母开头，如 leave_v2" /></el-form-item>
        <el-form-item label="名称" required><el-input v-model="nd.name" /></el-form-item>
        <el-form-item label="业务类型" required><el-select v-model="nd.business_type"><el-option v-for="b in btypes" :key="b.code" :label="b.name" :value="b.code" /></el-select></el-form-item>
      </el-form>
      <template #footer><el-button @click="newOpen = false">取消</el-button><el-button type="primary" @click="createDef">创建</el-button></template>
    </el-dialog>
    <el-dialog v-model="previewOpen" title="流程预览" width="900px">
      <WorkflowGraph :graph="graph" :height="360" />
    </el-dialog>
  </div>
</template>

<script setup lang="ts">
import { computed, defineComponent, h, onMounted, reactive, ref } from 'vue'
import { ElFormItem, ElInputNumber, ElMessage, ElMessageBox, ElOption, ElSelect } from 'element-plus'
import { api, errorText } from '@/api/http'
import { act } from '@/utils/usePaged'
import StatusTag from '@/components/StatusTag.vue'
import WorkflowGraph from '@/components/WorkflowGraph.vue'
import PersonSelect from '@/components/PersonSelect.vue'

const W = 132
const H = 50
const PALETTE = [
  { type: 'approval', label: '审批' }, { type: 'condition', label: '条件' }, { type: 'parallel', label: '并行' },
  { type: 'join', label: '汇聚' }, { type: 'cc', label: '抄送' }, { type: 'end', label: '结束' },
]
const TYPE_LABEL: Record<string, string> = { start: '开始', end: '结束', approval: '审批', condition: '条件', parallel: '并行', join: '汇聚', cc: '抄送' }
const APPROVER: Record<string, string> = { direct_manager: '直属主管', department_manager: '部门负责人', role: '指定角色', user: '指定用户', hr_admin: 'HR 管理员', amount_based: '按金额选择' }
const VSTATUS: Record<string, string> = { draft: '草稿', published: '已发布', archived: '已归档' }
const OPS = ['>', '>=', '<', '<=', '==', '!=']

const ApproverFields = defineComponent({
  props: { cfg: { type: Object, required: true }, roles: { type: Array, required: true }, vars: { type: Array, required: true } },
  setup(props) {
    return () => {
      const c: any = props.cfg
      if (c.type === 'role') return h(ElFormItem, { label: '角色' }, () => h(ElSelect, { modelValue: c.role_code, 'onUpdate:modelValue': (v: string) => (c.role_code = v) },
        () => (props.roles as any[]).map((r) => h(ElOption, { label: r.name, value: r.code, key: r.code }))))
      if (c.type === 'user') return h(ElFormItem, { label: '用户' }, () => h(PersonSelect, { modelValue: c.user_ids, mode: 'user', multiple: true,
        'onUpdate:modelValue': (v: number[]) => (c.user_ids = v) }))
      if (c.type === 'department_manager') return [
        h(ElFormItem, { label: '部门来源' }, () => h(ElSelect, { modelValue: c.department_var ?? '', clearable: true, placeholder: '申请人所在部门',
          'onUpdate:modelValue': (v: string) => (c.department_var = v || undefined) },
        () => (props.vars as string[]).filter((x) => x.includes('department')).map((x) => h(ElOption, { label: `变量 ${x}`, value: x, key: x })))),
        h(ElFormItem, { label: '向上级别（1=本部门）' }, () => h(ElInputNumber, { modelValue: c.level ?? 1, min: 1, max: 5, 'onUpdate:modelValue': (v: number | undefined) => (c.level = v ?? 1) })),
      ]
      return null
    }
  },
})

const defs = ref<any[]>([])
const def = ref<any>(null)
const versionId = ref<number | null>(null)
const graph = reactive<{ nodes: any[]; edges: any[] }>({ nodes: [], edges: [] })
const roles = ref<any[]>([])
const btypes = ref<any[]>([])
const errors = ref<string[]>([])
const validMsg = ref('')
const selNodeId = ref<string | null>(null)
const selEdgeId = ref<string | null>(null)
const canvas = ref<HTMLDivElement>()
const drag = ref<{ id: string; dx: number; dy: number } | null>(null)
const linking = ref<{ from: string; x1: number; y1: number; x2: number; y2: number } | null>(null)
const condMode = ref<'all' | 'any'>('all')
const condRows = ref<{ field: string; op: string; value: string }[]>([])
const newOpen = ref(false)
const nd = reactive({ key: '', name: '', business_type: 'leave' })
const previewOpen = ref(false)

const version = computed(() => def.value?.versions.find((v: any) => v.id === versionId.value))
const editable = computed(() => version.value?.status === 'draft')
const vars = computed<Record<string, string>>(() => btypes.value.find((b) => b.code === def.value?.business_type)?.variables || {})
const numericVars = computed(() => Object.keys(vars.value))
const selNode = computed(() => graph.nodes.find((n) => n.id === selNodeId.value) || null)
const selEdge = computed(() => graph.edges.find((e) => e.id === selEdgeId.value) || null)
const cfgTarget = computed<any>(() => {
  const n = selNode.value
  if (!n) return {}
  n.config ||= {}
  const key = n.type === 'cc' ? 'targets' : 'approver'
  n.config[key] ||= { type: 'direct_manager' }
  return n.config[key]
})
const size = computed(() => ({ w: Math.max(1100, ...graph.nodes.map((n) => n.x + W)), h: Math.max(460, ...graph.nodes.map((n) => n.y + H + 20)) }))
const graphNode = (id: string) => graph.nodes.find((n) => n.id === id)
const edgePaths = computed(() => graph.edges.map((e) => {
  const a = graphNode(e.source)
  const b = graphNode(e.target)
  if (!a || !b) return { id: e.id, d: '', mx: 0, my: 0, label: '' }
  const x1 = a.x + W / 2
  const x2 = b.x - W / 2
  const mx = (x1 + x2) / 2
  const label = e.label || (e.default ? '默认' : e.condition ? condText(e.condition) : '')
  return { id: e.id, d: `M${x1},${a.y} C${mx},${a.y} ${mx},${b.y} ${x2},${b.y}`, mx, my: (a.y + b.y) / 2, label }
}))

function condText(c: any): string {
  const items = c.all || c.any || [c]
  return items.map((x: any) => `${x.field}${x.op}${x.value}`).join(c.any ? ' 或 ' : ' 且 ')
}

async function loadDefs() {
  defs.value = await api.get('/api/workflow/definitions')
}
async function selectDef(id: number) {
  def.value = await api.get(`/api/workflow/definitions/${id}`)
  versionId.value = def.value.draft_version_id || def.value.current_version_id || def.value.versions[0]?.id
  loadVersion()
}
function loadVersion() {
  const g = JSON.parse(JSON.stringify(version.value?.graph || { nodes: [], edges: [] }))
  const nodes = g.nodes.map((n: any, i: number) => ({ ...n, x: n.x ?? 80 + i * 160, y: n.y ?? 200, config: n.config || {} }))
  // keep every node fully inside the canvas
  const dx = Math.max(0, 20 + W / 2 - Math.min(...nodes.map((n: any) => n.x), Infinity))
  const dy = Math.max(0, 20 + H / 2 - Math.min(...nodes.map((n: any) => n.y), Infinity))
  graph.nodes = nodes.map((n: any) => ({ ...n, x: n.x + dx, y: n.y + dy }))
  graph.edges = g.edges
  clearSel()
  errors.value = []
  validMsg.value = ''
}
function clearSel() {
  selNodeId.value = null
  selEdgeId.value = null
}
function selectNode(id: string) {
  selEdgeId.value = null
  selNodeId.value = id
}
function selectEdge(id: string) {
  selNodeId.value = null
  selEdgeId.value = id
  const c = selEdge.value?.condition
  condMode.value = c?.any ? 'any' : 'all'
  condRows.value = (c ? c.all || c.any || [c] : []).map((x: any) => ({ field: x.field, op: x.op, value: String(x.value ?? '') }))
}
function syncCond() {
  const e = selEdge.value
  if (!e || e.default) return
  const rows = condRows.value.filter((r) => r.field).map((r) => ({ field: r.field, op: r.op,
    value: vars.value[r.field] === 'number' && r.value !== '' && !isNaN(Number(r.value)) ? Number(r.value) : r.value }))
  e.condition = { [condMode.value]: rows }
}
function onDefault(v: boolean) {
  const e = selEdge.value
  if (!e) return
  if (v) {
    for (const o of graph.edges) if (o.source === e.source && o.id !== e.id) delete o.default
    delete e.condition
  } else syncCond()
}
function onApproverType(t: string) {
  const c = cfgTarget.value
  for (const k of Object.keys(c)) if (k !== 'type') delete c[k]
  if (t === 'role') c.role_code = roles.value[0]?.code
  if (t === 'user') c.user_ids = []
  if (t === 'amount_based') {
    c.field = 'amount'
    c.rules = [{ max: 5000, approver: { type: 'direct_manager' } }, { max: null, approver: { type: 'role', role_code: 'ceo' } }]
  }
}
function uid(prefix: string) {
  let i = 1
  while (graph.nodes.some((n) => n.id === `${prefix}${i}`) || graph.edges.some((e) => e.id === `${prefix}${i}`)) i++
  return `${prefix}${i}`
}
function addNode(type: string) {
  const id = uid(type === 'approval' ? 'n' : type.slice(0, 2))
  // Place new nodes inside the currently visible part of the canvas, staggered so they don't stack.
  const el = canvas.value
  const left = (el?.scrollLeft ?? 0) + W / 2 + 20
  const right = Math.max(left, (el?.scrollLeft ?? 0) + (el?.clientWidth ?? 1100) - W / 2 - 20)
  const step = graph.nodes.length % 6
  const x = Math.min(right, left + 40 + step * 150)
  const y = (el?.scrollTop ?? 0) + 80 + Math.floor(graph.nodes.length / 6) * 110
  const node: any = { id, type, name: `${TYPE_LABEL[type]}节点`, x: Math.round(x / 10) * 10, y: Math.round(y / 10) * 10, config: {} }
  if (type === 'approval') node.config = { approver: { type: 'direct_manager' }, mode: 'or', on_empty: 'fallback' }
  if (type === 'cc') node.config = { targets: { type: 'role', role_code: 'hr' } }
  graph.nodes.push(node)
  selectNode(id)
}
function removeSelected() {
  if (selNode.value) {
    if (selNode.value.type === 'start') return ElMessage.warning('开始节点不能删除')
    const id = selNode.value.id
    graph.nodes = graph.nodes.filter((n) => n.id !== id)
    graph.edges = graph.edges.filter((e) => e.source !== id && e.target !== id)
  } else if (selEdge.value) {
    const id = selEdge.value.id
    graph.edges = graph.edges.filter((e) => e.id !== id)
  }
  clearSel()
}
function point(ev: MouseEvent) {
  const r = canvas.value!.getBoundingClientRect()
  return { x: ev.clientX - r.left + canvas.value!.scrollLeft, y: ev.clientY - r.top + canvas.value!.scrollTop }
}
function startDrag(ev: MouseEvent, n: any) {
  if (!editable.value) return
  const p = point(ev)
  drag.value = { id: n.id, dx: p.x - n.x, dy: p.y - n.y }
}
function startLink(ev: MouseEvent, n: any) {
  const p = point(ev)
  linking.value = { from: n.id, x1: n.x + W / 2, y1: n.y, x2: p.x, y2: p.y }
}
function onMove(ev: MouseEvent) {
  const p = point(ev)
  if (drag.value) {
    const n = graphNode(drag.value.id)
    if (n) {
      n.x = Math.max(W / 2, Math.round((p.x - drag.value.dx) / 10) * 10)
      n.y = Math.max(H / 2, Math.round((p.y - drag.value.dy) / 10) * 10)
    }
  }
  if (linking.value) {
    linking.value.x2 = p.x
    linking.value.y2 = p.y
  }
}
function onUp() {
  drag.value = null
  linking.value = null
}
function finishLink(target: any) {
  drag.value = null
  const l = linking.value
  linking.value = null
  if (!l || l.from === target.id || target.type === 'start') return
  if (graph.edges.some((e) => e.source === l.from && e.target === target.id)) return ElMessage.warning('已存在相同连线')
  const edge: any = { id: uid('e'), source: l.from, target: target.id }
  if (graphNode(l.from)?.type === 'condition') {
    const siblings = graph.edges.filter((e) => e.source === l.from)
    if (!siblings.some((e) => e.default)) edge.default = true
    else edge.condition = { all: [] }
  }
  graph.edges.push(edge)
  selectEdge(edge.id)
}
function cleanGraph() {
  return { nodes: graph.nodes.map((n) => {
    const out: any = { id: n.id, type: n.type, name: n.name, x: n.x, y: n.y }
    if (n.type === 'approval' || n.type === 'cc') out.config = JSON.parse(JSON.stringify(n.config))
    return out
  }), edges: graph.edges.map((e) => JSON.parse(JSON.stringify(e))) }
}
async function saveDraft() {
  if (await act(() => api.put(`/api/workflow/definitions/${def.value.id}/draft`, { graph: cleanGraph() }), '草稿已保存')) {
    await selectDefKeep()
  }
}
async function validate() {
  try {
    const r = await api.post(`/api/workflow/definitions/${def.value.id}/validate`, { graph: cleanGraph() })
    errors.value = r.errors
    validMsg.value = r.valid ? '校验通过，可以发布' : ''
  } catch (e) {
    ElMessage.error(errorText(e))
  }
}
async function publish() {
  await ElMessageBox.confirm('发布后该版本不可修改，新提交的单据将使用新版本；运行中的流程继续按原版本执行。', '发布流程')
  try {
    await api.put(`/api/workflow/definitions/${def.value.id}/draft`, { graph: cleanGraph() })
    await api.post(`/api/workflow/definitions/${def.value.id}/publish`)
    ElMessage.success('已发布')
    errors.value = []
    await loadDefs()
    await selectDef(def.value.id)
  } catch (e: any) {
    errors.value = Array.isArray(e?.details) ? e.details : []
    ElMessage.error(errorText(e))
  }
}
async function newDraft() {
  if (await act(() => api.post(`/api/workflow/definitions/${def.value.id}/draft`), '已创建草稿')) {
    await loadDefs()
    await selectDef(def.value.id)
  }
}
async function toggleStatus() {
  if (await act(() => api.post(`/api/workflow/definitions/${def.value.id}/status`, { status: def.value.status === 'active' ? 'disabled' : 'active' }), '状态已更新')) {
    await loadDefs()
    await selectDefKeep()
  }
}
async function selectDefKeep() {
  const keep = versionId.value
  def.value = await api.get(`/api/workflow/definitions/${def.value.id}`)
  versionId.value = keep
  defs.value = await api.get('/api/workflow/definitions')
}
async function createDef() {
  try {
    const d = await api.post('/api/workflow/definitions', nd)
    newOpen.value = false
    await loadDefs()
    await selectDef(d.id)
  } catch (e) {
    ElMessage.error(errorText(e))
  }
}

onMounted(async () => {
  ;[roles.value, btypes.value] = await Promise.all([api.get('/api/roles'), api.get('/api/workflow/business-types')])
  await loadDefs()
  if (defs.value.length) selectDef(defs.value[0].id)
})
</script>

<style scoped>
.designer {
  display: grid;
  grid-template-columns: 230px minmax(0, 1fr);
  gap: 16px;
}
.defs {
  padding: 8px;
  max-height: 78vh;
  overflow: auto;
}
.def {
  padding: 10px;
  border-radius: 8px;
  cursor: pointer;
  margin-bottom: 4px;
}
.def:hover,
.def.active {
  background: var(--doe-brand-soft);
}
.def-name {
  font-weight: 600;
}
.small {
  font-size: 12px;
}
.mb {
  margin-bottom: 10px;
}
.mb4 {
  margin-bottom: 4px;
}
.workspace {
  display: grid;
  grid-template-columns: minmax(0, 1fr) 280px;
  gap: 12px;
}
.canvas {
  position: relative;
  height: 520px;
  overflow: auto;
  background-color: var(--doe-bg);
  background-image: radial-gradient(var(--doe-border) 1px, transparent 1px);
  background-size: 20px 20px;
  border-radius: 10px;
  border: 1px solid var(--doe-border);
  user-select: none;
}
.edges {
  position: absolute;
  left: 0;
  top: 0;
}
.edge .line {
  fill: none;
  stroke: #8a7a70;
  stroke-width: 2;
}
.edge .hit {
  fill: none;
  stroke: transparent;
  stroke-width: 14;
  cursor: pointer;
}
.edge.sel .line {
  stroke: var(--doe-brand);
  stroke-width: 3;
}
.line.temp {
  stroke: var(--doe-sakura);
  stroke-dasharray: 5 4;
  stroke-width: 2;
}
.elabel {
  font-size: 11px;
  fill: var(--doe-muted);
}
.node {
  position: absolute;
  width: 132px;
  height: 50px;
  border-radius: 10px;
  background: var(--doe-surface);
  border: 2px solid var(--doe-border);
  display: flex;
  flex-direction: column;
  justify-content: center;
  padding: 0 10px;
  cursor: move;
  box-shadow: 0 2px 6px rgba(0, 0, 0, 0.06);
}
.node.sel {
  border-color: var(--doe-brand);
  box-shadow: 0 0 0 3px var(--doe-brand-soft);
}
.node.start,
.node.end {
  border-radius: 25px;
  background: var(--doe-brand-soft);
}
.node.condition {
  border-color: #d4a017;
}
.node.parallel,
.node.join {
  border-color: #6b8cce;
}
.node.cc {
  border-style: dashed;
  border-color: #9b8fd1;
}
.ntype {
  font-size: 10px;
  color: var(--doe-muted);
}
.nname {
  font-size: 13px;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}
.port {
  position: absolute;
  right: -8px;
  top: 17px;
  width: 14px;
  height: 14px;
  border-radius: 50%;
  background: var(--doe-sakura);
  border: 2px solid #fff;
  cursor: crosshair;
}
.props {
  border-left: 1px solid var(--doe-border);
  padding-left: 12px;
  max-height: 520px;
  overflow: auto;
}
.props h4 {
  margin: 0 0 8px;
}
.cond {
  display: flex;
  gap: 4px;
  margin-bottom: 6px;
  align-items: center;
}
.rule-box {
  border: 1px dashed var(--doe-border);
  border-radius: 8px;
  padding: 6px;
  margin-bottom: 6px;
}
.help {
  padding-left: 16px;
  line-height: 1.8;
}
@media (max-width: 1100px) {
  .designer,
  .workspace {
    grid-template-columns: minmax(0, 1fr);
  }
}
</style>
