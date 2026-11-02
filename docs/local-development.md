# 本地运行与容器启动

本指南对应 TravelMind AI 的 Vue 3 / Vite 前端、FastAPI 接口、ARQ Worker 和可选 GrokSearch 桥接服务。初次体验建议先使用离线模式，不必准备模型密钥。

## 环境要求

- Node.js 20 或更高版本。
- Python 3.11 或更高版本及 `uv`。
- 使用容器方案时，安装 Docker Desktop 或带 Compose 插件的 Docker Engine。

## 方案一：最简离线演示

在项目根目录执行：

```powershell
npm ci
uv sync --frozen --project apps/api
```

终端 1 启动 API：

```powershell
$env:TRAVELMIND_AGENT_PROVIDER="stub"
$env:TRAVELMIND_QUEUE_MODE="inline"
uv run --project apps/api uvicorn travelmind_api.main:app --reload --host 127.0.0.1 --port 8000
```

终端 2 启动前端：

```powershell
$env:VITE_API_BASE_URL="http://127.0.0.1:8000"
npm run dev:web
```

打开 `http://127.0.0.1:5173`，注册本地账户。这个模式不需要 Redis 或 PostgreSQL，也不调用付费模型；生成的是固定示例，不能作为真实 AI 规划效果。

如需覆盖默认环境配置，从 [环境变量模板](../infra/.env.example) 复制相应字段到项目根目录 `.env`。不要提交包含真实密钥的 `.env`。

### Windows 一键启动与停止

```powershell
.\start.cmd
.\stop.cmd
```

脚本在后台管理本地前端、API 和可选搜索桥接，日志和进程状态放在 `.tmp/local-dev`。请在正常联网的 PowerShell 或 Windows Terminal 中执行；启动器会拒绝在网络被禁用的沙箱内启动外部服务。

默认使用内联任务和离线规划，不启动 Redis 或 Worker。需要 ARQ 时先启动 Redis，再使用 `start.cmd -ArqMode`。脚本还提供 `-SkipBridge`、`-SkipApi`、`-SkipWorker`、`-SkipWeb`、`-LangGraph` 以及自定义端口选项。

## 方案二：真实模型与多角色规划

在本地账户的模型设置中填写自己有权使用的服务地址、API Key、模型和协议。根据需要配置研究模型、搜索、地图及旅行 MCP。

- `langgraph`：多角色研究和规划，可持久化检查点。
- `standard`：标准单模型实现。
- `stub`：离线演示和测试，不调用真实模型。

真实生成会消耗上游服务的额度，供应商错误、超时或无效模型名称会影响结果。仅能拉取模型列表，不代表一次完整行程生成必然成功。

## 方案三：Redis 与后台 Worker

内联执行无需 Worker。需要后台任务时，先启动 Redis：

```powershell
docker compose -f infra/docker-compose.yml up redis -d
```

在 API 和 Worker 两边使用相同配置：

```powershell
$env:TRAVELMIND_QUEUE_MODE="arq"
$env:TRAVELMIND_REDIS_URL="redis://127.0.0.1:6379/0"
$env:TRAVELMIND_AGENT_PROVIDER="stub"
```

单独启动 Worker：

```powershell
uv sync --project apps/worker
uv run --project apps/worker python -m travelmind_worker.worker
```

再启动 API：

```powershell
uv run --project apps/api uvicorn travelmind_api.main:app --reload --host 127.0.0.1 --port 8000
```

多进程 LangGraph 部署还必须让 API 和 Worker 使用同一个 PostgreSQL 检查点存储，不能各自使用独立 SQLite 文件。

## 方案四：Docker Compose

从项目根目录执行：

```powershell
docker compose --env-file infra/.env.example -f infra/docker-compose.yml up --build
```

该方案构建 Web、API 和 Worker，启动 PostgreSQL 存放业务数据与共享检查点，使用 Redis 执行 ARQ 任务。可写 `storage` 卷用于 PDF 等生成文件。

| 服务 | 地址 |
| --- | --- |
| 前端 | `http://localhost:3000` |
| API | `http://localhost:8000` |
| 健康检查 | `http://localhost:8000/health` |
| GrokSearch 桥接 | `http://localhost:8085/mcp` |

停止容器：

```powershell
docker compose --env-file infra/.env.example -f infra/docker-compose.yml down
```

只启动 PostgreSQL：

```powershell
docker compose --env-file infra/.env.example -f infra/docker-compose.yml up postgres -d
```

应用数据库使用 `TRAVELMIND_COMPOSE_DATABASE_URL`，LangGraph 检查点使用 `TRAVELMIND_COMPOSE_WORKFLOW_CHECKPOINT_URL`。两个 Python 服务均包含 Psycopg 驱动。

### 分别构建镜像

```powershell
docker build --build-arg VITE_API_BASE_URL=http://localhost:8000 -f apps/web/Dockerfile -t travelmind-web .
docker build -f apps/api/Dockerfile -t travelmind-api .
docker build -f apps/worker/Dockerfile -t travelmind-worker .
docker build -f apps/groksearch-bridge/Dockerfile -t travelmind-groksearch-bridge .
```

以上是本地开发配置。生产环境需要单独配置密钥、HTTPS、数据库、跨域、Cookie、CSRF 和限流，不能原样照搬演示环境。当前线上方案见 [VPS 部署运维](vps-deployment.md)。

## GrokSearch 桥接的本地准备

```powershell
.\scripts\setup-groksearch-local.ps1 -PrintEnvTemplate
.\scripts\setup-groksearch-local.ps1 -CheckOnly
```

第一条准备环境并打印配置模板，第二条仅检查现有安装。详细说明见 [本地搜索配置](groksearch-local-setup.md) 和 [搜索桥接部署](groksearch-bridge-deploy.md)。

## 常用环境变量

| 变量 | 说明 |
| --- | --- |
| `TRAVELMIND_AGENT_PROVIDER` | 规划实现，离线使用 `stub` |
| `TRAVELMIND_QUEUE_MODE` | `inline` 为内联执行，`arq` 使用队列 |
| `TRAVELMIND_REDIS_URL` | API 和 Worker 共用的 Redis 地址 |
| `TRAVELMIND_WORKFLOW_CHECKPOINT_URL` | 多进程部署共用的 PostgreSQL 检查点连接 |
| `VITE_API_BASE_URL` | 前端构建时写入的接口地址，修改后需重新构建 |
| `TRAVELMIND_CORS_ORIGINS` | 允许访问 API 的浏览器来源 |
| `TRAVELMIND_SEARCH_SERVICE_PROVIDER` | 搜索服务选择，例如 `groksearch` |
| `TRAVELMIND_GROKSEARCH_BRIDGE_API_KEY` | 搜索桥接接口的访问保护密钥 |

## 持续集成检查

[GitHub Actions](../.github/workflows/ci.yml) 包含代码格式与 Python 编译、前端单元测试与生产构建、Chromium 浏览器测试、基于 PostgreSQL 的后端测试、Worker 测试和容器构建检查。

本地可执行：

```powershell
npm run test:web:unit
npm run build:web
npm run test:web:e2e
uv run --project apps/api pytest apps/api/tests -q
```

未配置独立 PostgreSQL 测试地址时，部分专项会跳过。不要将测试库地址指向生产库。公开账户创建、额度和访问限制见 [公开体验说明](public-demo.md)。
