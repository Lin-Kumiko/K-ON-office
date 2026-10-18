# API 契约（核心）

完整、机器可读的契约以运行时 OpenAPI 为准：`GET /openapi.json`、Swagger UI `/docs`，导出副本 `backend/openapi.json`（167 个路径 / 215 个操作）。契约一致性由 `backend/tests/test_contract.py` 自动校验：所有路由均出现在 OpenAPI 中、每个操作有摘要与错误响应说明、主要 GET 接口的实际响应能通过声明的响应模型校验、分页与错误结构统一。

## 1. 通用约定

| 项 | 约定 |
| --- | --- |
| 认证 | `Authorization: Bearer <token>`（`POST /api/auth/login` 获取）。未认证 401；首次登录/被重置密码的账号在修改密码前访问 `/api/auth/*` 以外接口返回 403 `PASSWORD_CHANGE_REQUIRED` |
| 错误结构 | `{"error": {"code": "...", "message": "中文说明", "details": ...}}` |
| 状态码 | 200 成功 · 201 创建 · 401 未认证 · 403 无权限/数据范围外 · 404 不存在 · 409 状态冲突/重复/并发冲突 · 422 参数或业务校验失败 · 423 账号锁定 · 503 数据库繁忙（可重试） · 500 内部错误（不泄露细节） |
| 分页 | `?page=1&page_size=20(≤200)&sort=field` 或 `sort=-field`；响应 `{items, total, page, page_size}`；非法排序字段 422 |
| 时间 | ISO 8601；无时区按公司时区，带时区自动换算。日期 `YYYY-MM-DD` |
| 金额 | 两位小数字符串（如 `"1288.90"`），服务端以整数分计算 |
| 幂等 | 关键写操作支持 `Idempotency-Key`（≤128 字符）。相同 Key + 相同请求重放原响应并带 `Idempotent-Replay: true`；相同 Key + 不同请求 409 `IDEMPOTENCY_KEY_REUSED` |

## 2. 核心接口（节选）

### 认证与组织

| 方法 路径 | 权限 | 说明 / 后置条件 |
| --- | --- | --- |
| POST /api/auth/login | 公开 | 失败计数，5 次锁定 15 分钟；写 login_logs；返回 token + 当前用户（权限、菜单、员工信息） |
| POST /api/auth/logout | 登录 | 吊销当前会话 |
| POST /api/auth/change-password | 登录 | 校验原密码与强度；清除 must_change_password；吊销其他会话 |
| GET /api/departments/tree | org:read | 组织树（含负责人、人数） |
| POST/PUT /api/departments | org:manage | 编码唯一；上级不能是自身或下级（422 DEPARTMENT_CYCLE）；写 department_change_logs |
| POST /api/employees | employee:manage | 自动工号 HTT0001…；邮箱唯一；汇报环检查；写任职历史；发放当年假期额度；可同时建账号 |
| PUT /api/employees/{id} | employee:manage | 必须携带 `version`；不一致 409 VERSION_CONFLICT |
| POST /api/employees/{id}/resign | employee:manage | 状态 resigned、账号停用并吊销会话、下属上移、待办自动转交、写任职历史 |

### 工作流

| 方法 路径 | 权限 | 说明 |
| --- | --- | --- |
| GET /api/workflow/business-types | 登录 | 业务类型及可用条件变量 |
| POST /api/workflow/definitions | workflow:manage | 新建定义（v1 草稿，默认停用） |
| PUT /api/workflow/definitions/{id}/draft | workflow:manage | 只能修改草稿；已发布版本 409 NO_DRAFT |
| POST /api/workflow/definitions/{id}/validate | workflow:manage | 返回 `{valid, errors[]}`，不保存 |
| POST /api/workflow/definitions/{id}/publish | workflow:manage | 校验失败 422 INVALID_GRAPH（details 为错误列表）；旧发布版本归档；同业务类型其他定义停用；运行中实例不受影响 |
| GET /api/workflow/tasks?status=pending\|done | 登录 | 本人任务 |
| POST /api/workflow/tasks/{id}/approve | 任务处理人 | body `{comment, form_data}`；非处理人 403 NOT_TASK_ASSIGNEE；已处理 409 TASK_ALREADY_HANDLED；流程已结束 409 INSTANCE_NOT_RUNNING；业务回调失败整体回滚 |
| POST /api/workflow/tasks/{id}/reject | 任务处理人 | 必须填写意见（422 COMMENT_REQUIRED）；整单驳回 |
| POST /api/workflow/tasks/{id}/transfer | 任务处理人 | 目标须为有效用户且非申请人 |
| POST /api/workflow/tasks/{id}/reassign | workflow:monitor | 管理员改派 |
| POST /api/workflow/instances/{id}/withdraw | 发起人 | → withdrawn，业务单据可修改后重提 |
| POST /api/workflow/instances/{id}/cancel | 发起人 / workflow:monitor | → cancelled，业务单据终止 |
| GET /api/workflow/instances/{id} | 相关人 / monitor | 流程图、节点状态、任务、完整历史、抄送 |

### 业务（均遵循 草稿 → 提交 → 审批 → 结果）

| 方法 路径 | 说明 / 后置条件 |
| --- | --- |
| POST /api/leave/calculate | 计算时长（排除周末节假日，包含调休上班日） |
| POST /api/leave/requests[?submit=true] | 创建（并可直接提交）；余额不足 409 LEAVE_BALANCE_INSUFFICIENT；与已有请假重叠 409 LEAVE_OVERLAP；跨年 422 CROSS_YEAR_LEAVE |
| POST /api/leave/requests/{id}/submit | 冻结额度（pending += h，流水 freeze）+ 发起流程；重复提交 409 |
| 审批通过（引擎回调） | pending -= h、used += h（流水 consume，唯一约束保证只执行一次）；重算考勤为“请假”；通知申请人 |
| 驳回 / 撤回 / 取消 | 释放冻结（流水 unfreeze） |
| POST /api/attendance/punch | `punch_time` 可选（模拟打卡）；60 秒内重复打卡返回已有记录 `duplicate=true` |
| POST /api/attendance/corrections | 补卡（时间须在该工作日打卡窗口内、非全天请假日）；通过后写入打卡并重算 |
| POST /api/attendance/overtime | 加班（整小时，1-12h，不可重叠）；通过且补偿为调休时入账调休额度（一次） |
| POST /api/expense/claims[?submit=true] | 明细金额两位小数、单笔上限、票据须为本人上传；总额由服务端计算 |
| POST /api/expense/claims/{id}/finance-confirm | expense:finance；仅 approved；不能确认本人单据；生成模拟付款参考号；幂等 |
| POST /api/expense/claims/{id}/archive | 仅 paid |
| POST /api/meeting/bookings | 开放时间、容量、不能跨天/过去；冲突 409 BOOKING_CONFLICT；需审批会议室发起流程 |
| POST /api/onboarding[?submit=true] | 入职审批通过后：生成员工档案（工号、任职历史、试用期）、关联已有账号或新建账号并授予角色、发放假期额度、定薪、生成 4 条入职待办、候选人 hired、招聘需求计数 |
| POST /api/regularization[?submit=true] | 仅试用期员工；主管节点必须提交 `form_data.score/evaluation`；通过后员工转正并写任职历史 |
| POST /api/transfers | 调出/调入部门负责人并行会审 → HR；通过时校验员工原部门未变化、目标部门有效、无汇报环 |
| POST /api/payroll/runs/{id}/calculate | 生成新计算版本（旧版本保留为历史）；确认后不可再计算 |

## 3. 接口依赖顺序（业务链）

1. **请假**：login → GET balances → POST requests → POST submit → (engine) → mio POST tasks/approve → (天数>3) HR POST tasks/approve → GET requests/{id}=approved、balances、ledger、attendance records
2. **入职**：requisition → candidate → interview(+result pass) → offer(审批) → POST onboarding → submit → 用人部门负责人 approve → HR approve → GET employees/{id}、users、onboarding-tasks
3. **转正**：GET probation-employees → POST regularization(submit) → 主管 approve(form_data) → HR approve → GET employees/{id}（regular）+ history
4. **报销**：POST files(receipt) → POST claims → submit → 主管 → (>5000 社长) → 财务审核 → finance-confirm → archive
5. **会议室**：GET availability → POST bookings（冲突检测）→（需审批时）行政 approve → GET calendar

以上链路在 `backend/tests/test_chain_leave.py`、`test_chains.py`（应用内 HTTPX）与 `test_live_network.py`（真实网络）中以动态 ID 逐步执行并核对最终数据库状态。
