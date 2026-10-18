# DragonOffice Enterprise · 放课后茶会株式会社

企业级 OA、HRM 与通用工作流一体化管理平台（轻音少女主题版本）。虚拟企业「放课后茶会株式会社」的全部人员与业务数据均为**合成数据**。

- 后端：Python 3.14 · FastAPI · SQLAlchemy 2 · Alembic · Pydantic 2 · SQLite（WAL）
- 前端：Vue 3 · TypeScript · Vite 7 · Pinia · Vue Router · Element Plus · ECharts
- 测试：Pytest + HTTPX（应用内传输 + 真实网络）· Vitest · Playwright（使用本机已安装的 Google Chrome）

> 仓库：https://github.com/Lin-Kumiko/dragonoffice-enterprise-kon · 进度记录见 [PROGRESS.md](PROGRESS.md)。
> 仓库只包含源码、迁移、测试与文档；不包含数据库、上传文件、依赖目录和任何密码，克隆后按下文初始化即可。

## 0. 快速体验（克隆后）

```powershell
git clone https://github.com/Lin-Kumiko/dragonoffice-enterprise-kon.git
cd dragonoffice-enterprise-kon
python -m venv backend\.venv
backend\.venv\Scripts\python.exe -m pip install -r backend\requirements.txt
cd frontend; npm ci; cd ..
$env:DOE_SEED_PASSWORD = "YOUR_ADMIN_PASSWORD"   # 13 个内置账号（含管理员）的密码
$env:DOE_TEST_PASSWORD = "YOUR_TRIAL_PASSWORD"   # 体验账号 test 的密码（需与上面不同）
backend\.venv\Scripts\python.exe scripts\init_db.py
backend\.venv\Scripts\python.exe scripts\start.py
```

打开 http://localhost:5173 ，用 `test` 登录即可体验；需要审批、管理功能时改用第 5 节的内置账号。

## 1. 环境要求

| 项目 | 已验证版本 | 说明 |
| --- | --- | --- |
| Windows | 11 Pro 22631 | |
| Python | 3.14.3 | 依赖装入 `backend/.venv`，不写入系统 site-packages |
| Node.js / npm | 24.19.0 / 11.17.0 | 依赖装入 `frontend/node_modules` |
| SQLite | 3.50.4（Python 内置） | 无需安装数据库服务 |
| Google Chrome | 本机已安装 | 仅 E2E 使用（Playwright `channel: chrome`，不下载浏览器） |

## 2. 安装隔离依赖

```powershell
# 后端（项目根目录执行）
python -m venv backend\.venv
backend\.venv\Scripts\python.exe -m pip install -r backend\requirements.txt

# 前端（锁文件已存在时使用 npm ci）
cd frontend
npm ci
cd ..
```

依赖版本：`backend/requirements.txt`（直接依赖，精确版本）、`backend/requirements.lock.txt`（完整冻结清单）、`frontend/package.json` + `package-lock.json`（精确版本）。

> npm 11 默认不执行依赖的安装脚本（esbuild、vue-demi 会提示 allow-scripts）。已验证不执行这些脚本时 Vite/esbuild 均可正常工作，无需额外授权。

## 3. 初始化开发数据库

```powershell
# 为所有种子账号设置同一个初始密码（8-64 位，含字母和数字）；不设置则交互式隐藏输入
$env:DOE_SEED_PASSWORD = "YOUR_PASSWORD_HERE"
backend\.venv\Scripts\python.exe scripts\init_db.py
```

- 执行 Alembic 迁移到最新版本，并写入**基础合成数据**（组织、岗位、账号、角色权限、假期类型与额度、考勤规则、节假日、费用分类、会议室、10 条已发布流程定义、薪酬结构）。
- 数据库文件：`data/dev.sqlite3`；附件：`data/uploads/`。重复执行会跳过已初始化的数据库。

可选：通过**真实 HTTP API** 生成演示业务数据（打卡、请假、报销、出差、会议、公告、文档、招聘、转正、绩效、薪资）：

```powershell
# 先启动后端（见第 4 节），再执行
backend\.venv\Scripts\python.exe scripts\demo_data.py --base http://127.0.0.1:8000
```

## 4. 启动

```powershell
# 开发模式：API http://127.0.0.1:8000（文档 /docs），前端 http://localhost:5173（/api 代理到 8000）
backend\.venv\Scripts\python.exe scripts\start.py

# 一体化模式：先构建前端，再由后端在 8000 端口同时提供页面与 API
backend\.venv\Scripts\python.exe scripts\start.py --prod
```

也可分别启动：

```powershell
cd backend; .venv\Scripts\python.exe -m uvicorn app.main:create_app --factory --port 8000
cd frontend; npm run dev
```

### 主要环境变量

| 变量 | 默认值 | 说明 |
| --- | --- | --- |
| `DOE_DATA_DIR` | `data/` | 数据库与上传文件目录 |
| `DOE_DATABASE_URL` | `sqlite:///data/dev.sqlite3` | 仅支持 SQLite |
| `DOE_TIMEZONE` | `Asia/Shanghai` | 公司时区（业务时间统一按该时区存储） |
| `DOE_SESSION_HOURS` | `12` | 登录会话有效期 |
| `DOE_SIMULATION_MODE` | `true` | 是否允许普通员工使用“模拟打卡”指定时间 |
| `DOE_SEED_PASSWORD` | — | 仅 `init_db.py` / `demo_data.py` 使用 |

## 5. 账号（合成）

| 用户名 | 姓名 | 部门 / 角色 | 典型用途 |
| --- | --- | --- | --- |
| `saito` | 斋藤（琴吹家执事） | 信息系统部 · 系统管理员 | 用户、角色、流程设计、审计 |
| `ritsu` | 田井中律 | 社长 · 总经理/主管 | 大额报销审批、全局报表 |
| `mio` | 秋山澪 | 音乐制作部经理 · 主管 | 直属主管审批 |
| `yui` | 平泽唯 | 现场演出组组长 · 主管 | 员工请假、报销、出差 |
| `azusa` | 中野梓 | 现场演出组 · 员工（试用期） | 转正申请 |
| `ichigo` | 若王子苺 | 现场演出组 · 员工 | 调岗演示 |
| `mugi` | 琴吹紬 | 茶点后勤部经理 · 主管/行政 | 会议室审批、用人部门确认 |
| `megumi` / `fuuko` | 曾我部惠 / 高桥风子 | 财务部 · 财务 | 财务审核、模拟付款 |
| `nodoka` / `himeko` | 真锅和 / 立花姬子 | 人事部 · HR | 人事审核、入职、考勤、薪资 |
| `sawako` / `mika` | 山中佐和子 / 佐伯三花 | 服装设计部 | 部门主管 / 普通员工 |

密码为初始化时设置的 `YOUR_PASSWORD_HERE`（文档不记录真实值）。管理员重置密码或入职新建的账号首次登录必须修改密码。

### 体验账号（可交给他人使用）

| 用户名 | 角色 | 能做什么 | 不能做什么 |
| --- | --- | --- | --- |
| `test` | 体验访客（guest） | 浏览全公司组织、员工（敏感字段脱敏）、报表、公告、文档；以“体验用户”（音乐制作部，直属上级秋山澪）身份打卡、请假、出差、报销、预约会议室 | 任何管理功能（用户、角色、流程设计、薪资、审计）；处理他人的审批任务 |

- 创建：初始化时设置 `DOE_TEST_PASSWORD`，或对已有数据库运行 `backend\.venv\Scripts\python.exe scripts\create_test_account.py`。
- 体验账号密码**必须**与内置账号不同（脚本会拒绝重复），因此把它交给别人不会泄露管理员权限；不需要首次改密，可多人共用。
- 需要更换时：`scripts\reset_password.py test`。
- 后端默认只监听 `127.0.0.1`；若要让局域网内其他人访问你的实例，需要自行改用 `--host 0.0.0.0` 并评估网络安全。

忘记开发库密码时，可在本机重置（隐藏输入，不打印）：

```powershell
backend\.venv\Scripts\python.exe scripts\reset_password.py --all     # 或指定用户名，如 saito
```

忘记开发库密码时，可在本机重置（隐藏输入，不打印）：

```powershell
backend\.venv\Scripts\python.exe scriptseset_password.py --all     # 或指定用户名，如 saito
```

## 6. 测试

```powershell
# 后端：API（应用内 HTTPX）、真实网络链路与并发、数据库、契约、安全、异常恢复（约 3 分钟）
cd backend
.venv\Scripts\python.exe -m pytest                    # 默认排除 slow
.venv\Scripts\python.exe -m pytest -m live            # 仅真实网络 / 并发
.venv\Scripts\python.exe -m pytest -m slow -s         # 性能测量，结果写入 tests/performance.json
.venv\Scripts\python.exe -m pytest --cov=app          # 覆盖率

# 前端
cd frontend
npm run typecheck
npm test                 # Vitest
npm run build
npx playwright test      # E2E：自动启动隔离后端（tests/.e2e-data）并使用本机 Chrome
```

测试数据库全部是临时 SQLite 副本（`backend/.pytest_tmp`、`tests/.e2e-data`），不会触碰 `data/dev.sqlite3`。结果与说明见 [TEST_REPORT.md](TEST_REPORT.md)。

## 7. 文档索引

| 文件 | 内容 |
| --- | --- |
| [SPEC.md](SPEC.md) | 功能范围、业务规则、验收条件与完成状态 |
| [ARCHITECTURE.md](ARCHITECTURE.md) | 模块边界、数据模型、状态机、事务与 SQLite 并发 |
| [API_SPEC.md](API_SPEC.md) | 核心 API 契约、依赖顺序与后置条件（完整定义见 `backend/openapi.json` 与 `/docs`） |
| [PLAN.md](PLAN.md) | 五阶段计划与验收 |
| [PROGRESS.md](PROGRESS.md) | 进度、验证结果、下一步 |
| [TEST_REPORT.md](TEST_REPORT.md) | 实际执行命令、结果、范围与限制 |
| [KNOWN_ISSUES.md](KNOWN_ISSUES.md) | 已知问题与边界 |
