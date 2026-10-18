# 测试报告

更新时间：2026-10-18（Asia/Shanghai）。所有结果均为本机实际执行输出，未运行或受限项单独列出。

## 1. 环境

Windows 11 Pro 22631 · Python 3.14.3（`backend/.venv`）· Node 24.19.0 / npm 11.17.0 · SQLite 3.50.4 · Google Chrome（本机安装，Playwright `channel: chrome`）。

运行日志（`tests/*.log`、`tests/e2e-results/`）为本地生成，未纳入 Git 仓库；`tests/performance.json` 已纳入。

测试数据隔离：Pytest 每个用例复制一份“迁移 + 基础种子”模板库到 `backend/.pytest_tmp`；真实网络测试为每个用例启动独立 uvicorn 进程与独立库；E2E 使用 `tests/.e2e-data`。开发库 `data/dev.sqlite3` 不参与任何测试。

## 2. 执行命令与结果

| # | 命令（目录） | 结果 |
| --- | --- | --- |
| 1 | `.venv\Scripts\python.exe -m pytest`（backend，体验账号权限调整后的最新完整回归） | **194 passed, 1 deselected（slow）**，151.2s；上一轮带覆盖率运行为 189 passed、语句覆盖率 **91%** |
| 2 | `.venv\Scripts\python.exe -m pytest tests/test_live_network.py -m live`（backend，新增链路后单独复跑） | **11 passed** |
| 2b | `.venv\Scripts\python.exe -m pytest tests/test_trial_account.py` | **4 passed**（体验账号：广泛业务与管理权限可用；用户管理、角色权限、系统设置 403；不改变审批人；可经流程监控改派后审批；密码复用被拒绝；重复执行同步权限） |
| 3 | `.venv\Scripts\python.exe -m pytest tests/test_performance.py -m slow -s`（backend） | **1 passed**，结果见第 5 节与 `tests/performance.json` |
| 4 | `.venv\Scripts\ruff.exe check app tests ../scripts --select F,E9,B`（backend） | All checks passed（已修复 15 处未使用导入/变量等） |
| 5 | `.venv\Scripts\python.exe -m compileall -q app ../scripts` | 通过 |
| 6 | Alembic `upgrade head → check → downgrade base → upgrade head`（`test_database.py`） | 通过；模型与迁移无漂移 |
| 7 | `npx vue-tsc --noEmit`（frontend） | 通过（0 错误） |
| 8 | `npx vitest run`（frontend） | **14 passed**（4 个文件） |
| 9 | `npx vite build`（frontend） | 构建成功（`frontend/dist`） |
| 10 | `npx playwright test`（frontend，系统 Chrome，headless） | **7 passed**（26.5s） |

## 3. 后端测试范围（API 测试矩阵）

| 类别 | 用例文件 | 覆盖内容 |
| --- | --- | --- |
| 单接口功能 | test_modules / test_endpoints_extra / test_security | 正常请求；缺参、类型/范围错误；资源不存在；重复创建；非法状态；未认证、无权限（12 个管理接口逐一 403）；响应结构与数据库变化 |
| 接口依赖链 | test_chain_leave / test_chains / test_live_network | 五条闭环按真实顺序执行，上游返回 ID 传给下游，逐步核对响应与状态，最后核对数据库（余额、流水、考勤、员工、账号、角色、待办、金额、日历、触发器） |
| 调用顺序 | test_workflow_engine / test_chains | 未提交不能撤回/审批；驳回后不能通过；已完成任务重复处理 409；已取消流程不能继续或重提；归档前必须财务确认；录用前必须有通过的面试；已正式员工不能再转正 |
| 跨模块集成 | 同上 + test_attendance_leave_rules | 请假↔余额、请假↔考勤、出差↔考勤、加班↔调休余额、补卡↔考勤、报销↔工作流、入职↔用户/角色/薪资/余额、转正/调岗↔员工状态与任职历史、审批↔通知/抄送、定义版本↔实例 |
| 数据一致性 | test_resilience / test_attendance_leave_rules / test_live_network | 失败操作无写入；事务失败无中间态；重复提交不重复冻结/扣减；幂等键重放；重复审批不重复执行业务 |
| SQLite 并发（真实网络、独立连接、线程屏障同时放行） | test_live_network | 同一任务 8 路并发审批 → 仅 1 成功；或签两人并发 → 1 成功 1 冲突；同一请假单 8 路并发提交 → 1 成功、只冻结一次；5 张请假并发争抢 5 天余额 → 恰好 2 成功；8 人并发抢同一会议室时段 → 1 成功；同一档案 5 路并发修改 → 1 成功 4 个 VERSION_CONFLICT；同一幂等键 6 路并发 → 只创建一次 |
| 异常与恢复 | test_resilience / test_workflow_engine / test_live_network | 审批末段写库失败整体回滚并可重试；业务回调失败（部门已停用）回滚、修复后重试成功；文件存储失败无残留记录；数据库繁忙 → 503 可重试且无半写入；未处理异常 → 500 不泄露细节；上下游状态不一致被识别（409 BUSINESS_STATE_MISMATCH）并可由管理员取消修复；进程被强制终止后重启，流程继续完成；审批人停用/离职自动转交 |
| 契约 | test_contract | OpenAPI 与实际路由集合完全一致（215 个操作）；每个操作有摘要与错误说明；56 个 GET 接口的实际响应通过声明的响应模型校验；分页结构与排序；404/401/422 错误结构（遍历全部操作的未认证访问） |
| 数据库 | test_database | 迁移往返与漂移检查；外键（含 RESTRICT）；唯一约束；CHECK（余额不透支、状态枚举、禁止自己做自己上级、金额为正）；部分唯一索引（运行中实例）；事务回滚；PRAGMA（外键、WAL、busy_timeout） |
| 单元 | test_attendance_leave_rules / test_workflow_engine / test_modules | 请假时长（半天、周末、节假日、调休、跨年、非法区间）；考勤计算（迟到早退宽限、缺卡、缺勤、进行中、半天假、跨天夜班归属、规则校验）；流程图校验（9 类非法图 + 嵌套并行 + 金额策略）；受限条件语言（代码样式输入不被执行）；模拟个税 |
| 基础安全 | test_security | 登录失败锁定与日志；会话吊销与伪造令牌；改密强度与吊销其他会话；停用账号；越权与数据隔离；敏感字段脱敏；搜索参数中的 SQL 注入无效；XSS 载荷按纯文本 JSON 返回并带 `nosniff`；上传类型/内容/大小/空文件/路径穿越/用途限制与下载授权 |

## 4. 前端与 E2E 范围

- Vitest（14 项）：金额精确求和与格式化、状态映射、请求层（令牌、查询串、统一错误、校验信息、401 回调、网络错误）、StatusTag、流程图渲染与节点状态、权限判断、登录表单校验/失败提示/成功跳转。
- Playwright（7 项，真实浏览器 + 隔离后端 + 构建产物）：
  1. 管理员登录 → 新建员工（含账号）→ 列表核对 → 新账号首次登录强制改密
  2. 员工请假（4 天）→ 主管审批 → HR 审核 → 结果、余额与审批历史
  3. 报销两条明细（前端合计 ¥1,288.90）→ 主管 → 财务审核 → 模拟财务确认
  4. 流程设计器：新建草稿 → 删除连线 → 添加审批节点并配置 HR → 拖拽连线 → 校验 → 发布 v2 → 新出差单按 v2 执行（主管 + HR）
  5. 普通员工看不到管理菜单，直接访问被拦截，后端返回 403
  6. 登录失败提示、深色模式、手机宽度（390px）无横向溢出且侧栏抽屉化
  7. 打卡与重复打卡提示、会议室冲突由后端拒绝并在界面提示

开发服务器人工巡检（HR 账号）：17 个菜单页依次打开，无前端异常、无接口错误提示。

## 5. 性能测量（`tests/performance.json`）

数据量：1003 名员工、29700 条打卡、120 条流程实例；进程内 HTTP（TestClient），单进程，开发机。

| 操作 | p50 | p95 / 最大 |
| --- | --- | --- |
| 员工列表（关键字过滤，50 条/页） | ~7 ms | 8 / 11 ms |
| 员工列表（部门子树，200 条/页） | 11 ms | 13 ms |
| 员工选择器（全部） | 16 ms | 17 ms |
| 全员月度考勤统计（实时计算） | 225 ms | 229 ms |
| 全员当月考勤重算（写库） | 1.05 s | — |
| 统计报表总览 | 215 ms | 218 ms |
| 社长工作台 | 7 ms | 13 ms |
| 批量审批 100 单（顺序） | 17.9 ms/单 | 合计 1.79 s |
| 4 用户并发提交 + 读取（40 请求） | 45 ms | 最大 384 ms，0 错误 |

结论：在目标数据量下无明显瓶颈，未做额外优化（遵循“先测量再优化”）。

## 6. 最终验收运行

最后一次代码修改（体验账号权限放宽、菜单“任一权限”判断）之后按顺序重新执行：

| 检查 | 结果 | 日志 |
| --- | --- | --- |
| 后端完整回归（体验账号权限调整后） | 194 passed | `tests/backend-last-run.log` |
| 真实网络 / 并发子集（含新增三条链路） | 11 passed | 命令行输出 |
| 前端类型检查 / Vitest / 构建 | 0 错误 / 14 passed / 成功 | `tests/frontend-final.log` |
| Playwright E2E | 7 passed，0 失败，0 跳过 | `tests/e2e-results/last-run.log`、`report.json` |

E2E 修复过程说明：前两轮失败均为测试选择器问题（Element Plus 将 `data-test` 透传到内部 input、日期控件丢弃该属性、正在关闭的旧下拉框被误匹配、新节点生成在画布可视区外），已改为包裹元素 + 通过 `aria-controls` 定位当前下拉框；不涉及业务缺陷，未使用重试掩盖失败。

## 7. 未覆盖与限制

- 未进行多进程/多机部署、长时间压力或数据库级高并发测试；SQLite 结果不代表其他数据库或生产级并发能力。
- 未测试 Firefox/Safari；E2E 只使用本机 Chrome（headless）。
- 未做外部渗透、扫描或复杂漏洞利用研究（按要求保持低风险基础安全检查）。
- 薪资/个税为模拟计算，不对接任何真实服务，不验证税法正确性。
