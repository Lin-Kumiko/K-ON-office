# 开发进度

更新时间：2026-10-18（Asia/Shanghai）

## 项目位置说明

提示词中写的根目录 `D:\Daily\CodexProj\DragonOfficeEnterprise` 已存在另一套（非轻音主题）工程。经用户确认，本项目在 **`D:\Daily\ClaudeProj\enterprise`** 从零独立开发，未读取或修改 Codex 目录下的任何文件；提示词中的相对路径均以本目录为准。生效指令为 Claude 的全局 `CLAUDE.md`（提示词中提到的 Codex `AGENTS.md` 不适用于本执行环境，未读取）。

提示词原要求不使用 Git；交付后用户明确要求上传，已发布到公开仓库 https://github.com/Lin-Kumiko/K-ON-office（`.gitignore` 排除数据库、上传文件、依赖、构建产物、测试运行产物与本机工具配置）。

## 已完成

- **阶段 1–5 全部完成**（见 PLAN.md）。
- 后端：64 张表、Alembic 初始迁移（含会议室防重叠触发器与部分唯一索引）、215 个 API 操作、OpenAPI 导出 `backend/openapi.json`。
- 通用工作流引擎：7 类节点、受限条件语言、6 种审批人策略、会签/或签、转交/改派、撤回/取消、不可变版本、空审批人兜底与上溯、事务内业务回调与回滚、完整历史。
- 业务：认证/RBAC/数据范围/审计、组织与员工、请假与假期、考勤（含跨天班次、补卡、加班）、出差、报销、会议室、公告通知、日程、文档、招聘/录用/入职、转正、调岗、绩效、模拟薪资、工作台、报表、系统设置。
- 前端：22 个页面/视图全部对接真实 API；流程可视化设计器；深色模式；移动端布局。
- 合成数据：`scripts/init_db.py`（基础数据）+ `scripts/demo_data.py`（全部经真实 HTTP API 生成业务数据）。开发库已初始化并生成演示数据。
- 测试：后端 225 项（含 11 项真实网络/并发、访客与注册专项）+ 1 项性能；前端 Vitest 17 项；Playwright E2E 8 项。详见 TEST_REPORT.md。
- 访客与注册：未登录可浏览公开内容，任何操作提示“请先登录”；`POST /api/auth/register` 仅用户名 + 密码，注册后登录，自动成为普通员工（新成员部门），IP 限频；轻音主题登录/注册页（原创矢量插画）。
- 超级管理员：`ui`（平泽忧，原 saito 账号改名，密码不变；admin 角色显示为“超级管理员”）。体验账号功能已按用户要求删除。演示数据中的招聘候选人改为奥田直，避免与管理员重名。
- 品牌名统一为“放学后茶会”，浏览器标签页标题固定为“放学后茶会”。

## 最新验证结果

| 项目 | 结果 |
| --- | --- |
| 后端完整回归 | 225 passed（含 11 项真实网络、访客与注册专项）；此前覆盖率 91% |
| 性能测量 | 千人规模下各操作 p50 ≤ 225ms（重算 1.05s），4 并发 0 错误 |
| Lint / 编译 | ruff（F/E9/B）通过；compileall 通过 |
| 前端 | vue-tsc 0 错误；Vitest 17 passed；vite build 成功 |
| E2E（本机 Chrome） | 8 passed（含访客浏览 → 提示登录 → 注册 → 登录） |

## 未完成 / 当前阻塞

无阻塞。限制与可改进项见 KNOWN_ISSUES.md（SQLite 单写者、跨年请假需拆分、无“销假”、前端包体积等）。

## 后续接续指引

1. 先读本文件、TEST_REPORT.md、KNOWN_ISSUES.md，再核对源码与最新日志（`tests/backend-last-run.log`、`tests/e2e-results/last-run.log`）。
2. 修改后至少运行：`backend` 下 `pytest`；前端 `npm run typecheck && npm test && npm run build`；涉及界面流程时 `npx playwright test`。
3. 接口变更需同步：路由响应模型 → `backend/openapi.json`（重新导出）→ API_SPEC.md → 契约测试。
4. 可选改进：Element Plus 按需引入以减小首屏体积；“销假”流程；跨年请假自动拆分。
