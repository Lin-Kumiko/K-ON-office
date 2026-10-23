# 架构说明

## 1. 总体结构（模块化单体）

```text
frontend (Vue 3 SPA) ──HTTP/JSON──▶ backend (FastAPI)
                                      ├─ api/        路由层：参数校验(Pydantic)、权限依赖、响应模型、提交事务
                                      ├─ services/   业务规则：假期、考勤、组织、各业务的工作流处理器
                                      ├─ workflow/   通用工作流引擎（与业务解耦）
                                      ├─ core/       配置、数据库会话、认证/RBAC/数据范围、错误、幂等、审计、通知
                                      └─ models/     SQLAlchemy 模型（共享身份/组织 + OA + HRM + 工作流）
                                    SQLite (WAL) ◀── Alembic 迁移
```

- OA、HRM、工作流**共享**同一套用户、角色、部门、员工模型；不存在第二套身份体系。
- 工作流引擎只认识 `business_type + business_id + variables`。业务通过 `registry.register(handler)` 注册回调（`on_approved / on_rejected / on_withdrawn / on_cancelled / on_task_approved`），引擎不 import 任何业务模块。
- 业务单据统一由 `services/documents_flow.py` 提交（状态检查 → 置为 pending → `engine.start`），审批结果由各 handler 落地到业务表。

## 2. 数据模型（64 张表）

| 领域 | 主要表 |
| --- | --- |
| 身份与权限 | users, roles, permissions, role_permissions, user_roles, user_sessions, login_logs, audit_logs, idempotency_records |
| 组织 | departments（多级，parent_id）, positions, employees（manager_id 直属上级、version 乐观锁）, job_histories, department_change_logs |
| 平台 | notifications, system_settings, holidays, files, schedules |
| 工作流 | wf_definitions, wf_definition_versions（不可变发布版本）, wf_instances, wf_tasks, wf_node_activations, wf_join_arrivals, wf_history, wf_cc |
| OA | leave_types, leave_balances, leave_ledger, leave_requests, travel_requests, expense_categories, expense_claims, expense_items, meeting_rooms, meeting_bookings, announcement_categories, announcements, announcement_reads, doc_categories, documents, document_versions, document_logs |
| HRM | attendance_rules, attendance_punches, attendance_records（可重算的派生结果）, attendance_corrections, overtime_requests, job_requisitions, candidates, interviews, offers, onboarding_requests, onboarding_tasks, regularization_requests, transfer_requests, performance_cycles, performance_indicators, performance_reviews, salary_structures, payroll_runs, payroll_adjustments, payslips |

关键约束（数据库层，迁移中创建并经测试验证）：

- 外键全部开启（`PRAGMA foreign_keys=ON`），组织类为 RESTRICT。
- `leave_balances`：`CHECK(used + pending <= total)`、非负检查 → 任何并发路径都不可能透支。
- `leave_ledger`：部分唯一索引 `(ref_type, ref_id, seq, change_type) WHERE ref_id IS NOT NULL` → 同一次提交的冻结/扣减/释放只能各发生一次。
- `wf_instances`：部分唯一索引 `(business_type, business_id) WHERE status='running'` → 同一单据不可能有两个运行中流程。
- `wf_tasks`：`(instance, node, assignee) WHERE status='pending'` 唯一；`wf_node_activations (instance, node)` 唯一 → 节点不会被重复激活。
- `meeting_bookings`：两个触发器（插入 / 更新状态与时间）在数据库层拒绝同一会议室有效预约的时间重叠。
- 金额一律以**整数分**存储（`*_cents`），API 以两位小数字符串收发；假期以**整数小时**存储（半天 = 4 小时）。

## 3. 状态设计

### 工作流

```
实例: running ─┬─▶ approved   （到达结束节点；调用 on_approved）
               ├─▶ rejected   （任一审批任务驳回；整单驳回）
               ├─▶ withdrawn  （发起人撤回；单据可修改后重提）
               └─▶ cancelled  （发起人或流程管理员取消；单据终止）
任务: pending ─┬─▶ approved / rejected
               ├─▶ transferred（转交/改派后生成新任务）
               └─▶ cancelled  （或签被他人处理、流程结束、驳回时剩余任务）
```

- 节点：start / end / approval / condition / parallel / join / cc。图必须是 DAG；发布前校验（唯一开始、可达性、条件默认分支、并行必须汇聚到同一汇聚节点、审批人配置、条件字段与类型）。
- 会签（and）：节点所有任务通过才完成；或签（or）：任一通过即完成并取消其余任务。任一驳回即整单驳回。
- 并行汇聚：`wf_join_arrivals` 记录每条入线到达，全部到达才继续。
- 版本：实例记录 `version_id`；发布新版本只把旧版本标记为 archived，运行中实例继续按原图执行。已发布版本不可编辑，只能“基于当前版本新建草稿”。停用定义只阻止新提交。
- 审批人策略：指定用户、指定角色、直属主管、部门负责人（可指定变量部门与上溯层级）、HR 管理员、按金额分档。申请人本人永不作为自己的审批人；直属主管/部门负责人不可用时沿汇报链上溯；仍为空时按 `on_empty` 处理（默认兜底给系统管理员，可选自动通过或报错阻止提交）。审批人账号停用/离职时，其待办自动转交（上级或管理员）并记入历史；管理员也可手动改派。
- 条件表达式是 JSON 数据（`all/any` + `field/op/value`），只允许声明过的变量与 8 种运算符，嵌套 ≤ 4 层，**不执行任何代码**。

### 业务单据（请假、出差、报销、补卡、加班、录用、入职、转正、调岗）

```
draft ─submit─▶ pending ─┬─▶ approved（报销继续：paid → archived；出差可 changed/cancelled）
   ▲                    ├─▶ rejected  ─┐
   └──── 修改后重提 ◀───├─▶ withdrawn ─┘
                        └─▶ cancelled（终止）
```

非法转换（未提交审批、驳回后直接完成、已完成任务再处理、已取消流程继续、已归档再确认等）均返回 409 `INVALID_STATE / TASK_ALREADY_HANDLED / INSTANCE_NOT_RUNNING`。

## 4. 事务与 SQLite 并发

- 每个请求一个会话。**写请求（非 GET）使用 `BEGIN IMMEDIATE`**：事务一开始就取得 RESERVED 锁，读-改-写序列在进程/线程间串行化，避免丢失更新；读请求使用普通 `BEGIN`，WAL 下读不阻塞写。
- `busy_timeout = 30s`：写者排队而非立即失败；仍超时则映射为 `503 DB_BUSY`（可重试）。
- 每个连接 `cache_size = 16 MB`、`temp_store = MEMORY`；服务关闭时执行 `PRAGMA optimize` 让 SQLite 按需刷新查询规划统计。
- 一个审批动作（任务认领 → 节点推进 → 业务回调 → 余额/考勤/员工档案变更 → 通知/历史）在**同一事务**中提交。任何一步失败整体回滚，任务保持 pending，修复原因后可直接重试（已由故障注入测试验证）。
- 进程崩溃 = 未提交事务丢弃；数据库中只存在提交后的一致状态。服务重启后流程可继续（真实网络测试验证）。
- 任务认领使用条件更新 `UPDATE … WHERE status='pending'` 并检查影响行数；实例有版本列。即使串行化被绕过，重复审批也只会有一个成功。
- 幂等：`Idempotency-Key` 请求头作用于创建/提交/审批/财务确认等关键写操作。结果与业务变更在同一事务中写入 `idempotency_records`；相同 Key 重放返回原响应（`Idempotent-Replay: true`），不同请求体复用同一 Key 返回 409。无 Key 时由状态机与唯一约束防重。
- 乐观锁：员工档案更新必须携带 `version`，不一致返回 409 `VERSION_CONFLICT`。
- 会议室：先在 `BEGIN IMMEDIATE` 事务内做重叠检查，再由触发器兜底。

SQLite 边界：单写者模型，适合本项目的单机部署与测试规模；未验证多进程大规模高并发、分布式事务或其他数据库的兼容性。

## 5. 认证、权限与数据范围

- 登录：PBKDF2-SHA256（21 万次迭代，盐值随机）；不透明会话令牌（只存 SHA-256 摘要），可注销、可逐个吊销；修改密码会注销其他会话。
- 连续 5 次失败锁定 15 分钟（423 `ACCOUNT_LOCKED`），全部登录尝试记入 `login_logs`；关键管理操作写入 `audit_logs`。
- RBAC：角色 = 权限集合 + 数据范围（self / department / all）。后端每个接口通过依赖检查权限；数据范围在查询层过滤（部门范围 = 本部门子树 + 自己负责的部门子树）。前端菜单仅是体验，越权直接访问由后端返回 403。
- 审批权限：只有任务处理人能处理任务；只有发起人能撤回；取消需发起人或 `workflow:monitor`。
- 敏感字段（电话、邮箱、生日）对无 `employee:sensitive` 的他人脱敏。

## 6. 时间与日期规则

- 业务时间统一存公司时区（默认 Asia/Shanghai）的本地时间；带时区的输入自动换算。
- 工作日 = 周一至周五，节假日表可配置“放假（holiday）/调休上班（workday）”。
- 请假时长 = 区间内工作日的半天槽数 × 4 小时；不允许跨自然年（需拆分）、不允许与本人已提交/已批准请假的半天槽重叠。
- 考勤：打卡归属到窗口 `[上班-前置窗口, 下班+后置窗口]` 覆盖的工作日（跨天班次可用）；60 秒内重复打卡视为同一次；半天假移动应到/应退时间；无打卡的过去工作日为缺勤；当天未结束显示“进行中”。日考勤结果可随时幂等重算。

## 7. 前端

- 路由元信息声明所需权限；全局守卫在缺少会话或权限时跳转登录页/无权限页；首次登录或被重置密码时强制跳转修改密码。
- 统一请求层：令牌注入、错误结构解析、401 自动回到登录、校验错误可读化。
- 所有页面数据均来自后端 API；表格分页/搜索/筛选，表单校验，加载/空数据/错误/成功/无权限反馈，浅色默认 + 深色模式，移动端侧栏折叠为抽屉。
- 流程设计器：SVG 连线 + 可拖拽节点，从节点右侧圆点拖出连线；属性面板配置审批人策略、会签/或签、空审批人策略、审批表单、分支条件与优先级；保存草稿 → 校验 → 发布。
