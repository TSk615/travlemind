# TravelMind AI 半全栈面试学习清单

> 适用目标：把当前 TravelMind AI 项目作为简历项目，并从“AI 辅助完成的项目”提升到“自己能解释、修改、调试、验证的项目”。  
> 推荐定位：前端偏强的半全栈 / AI 应用工程候选人。  
> 项目技术栈：Vue 3 + Vite + TypeScript + FastAPI + SQLAlchemy + ARQ + Redis + SQLite/PostgreSQL + Docker + LLM Provider。

---

## 1. 你现在最需要补的不是“会写更多代码”

这个项目已经有比较完整的工程形态：

- 前端：Vue 3、Vite、TypeScript、Pinia、Vue Router
- 后端：FastAPI、Pydantic、SQLAlchemy
- 异步任务：ARQ、Redis、inline fallback
- 数据库：本地 SQLite，生产目标 PostgreSQL
- AI 能力：LLM settings、OpenAI-compatible client、stub fallback、search grounding
- 交付工程：Docker、Compose、README、测试、CI 思路

如果这个项目主要是通过 vibe coding 完成的，面试前最重要的任务不是重新写一遍，而是把它变成“你真正拥有的项目”。

面试官真正会考察的是：

1. 你是否能讲清楚系统为什么这么设计。
2. 你是否能从页面操作追到后端服务和数据库。
3. 你是否能解释关键 bug 的现象、原因和修复。
4. 你是否能独立新增一个小功能并补测试。
5. 你是否知道当前系统的不足和后续演进方向。

一句话目标：

> 从“我让 AI 帮我生成了项目”，升级成“我能解释、维护、验证和继续演进这个项目”。

---

## 2. 面试定位建议

不要把自己包装成“完整资深全栈架构师”。这个项目虽然覆盖面很广，但如果你目前基础还在补，最稳妥的定位是：

> 前端偏强，具备后端接口开发、AI 应用集成、异步任务理解和工程化交付意识的半全栈开发者。

简历上可以突出：

- 复杂前端工作台开发
- 前后端 API 联调
- AI 旅行规划业务闭环
- 异步任务状态机
- LLM 配置与 fallback
- Docker / Compose / CI 基线
- 测试和问题排查

不要重点吹：

- “精通分布式架构”
- “主导高并发系统”
- “深度掌握大模型训练”
- “生产级商业化平台”

这些容易被追问穿。

更适合你的表达是：

> 我做的是一个 AI 旅行规划 MVP，从创建旅行、生成行程、搜索补充、refine、异步进度到 PDF 导出，打通了一个可运行、可观察、可测试的全栈闭环。

---

## 3. 项目整体架构必须讲熟

你至少要能手画这张链路图：

```text
Browser / Vue App
    |
    | HTTP API
    v
FastAPI Backend
    |
    | creates job
    v
Job System
    |
    | inline mode or ARQ + Redis
    v
Worker / Job Handler
    |
    | calls orchestrator
    v
LLM / Stub / Search / Maps Provider
    |
    | persists result
    v
Database + Export Files
    |
    | query status / download
    v
Vue Trip Workbench
```

你要能解释这些目录：

- `apps/web`：前端单页应用，负责页面、路由、状态、API 调用、工作台交互。
- `apps/api`：FastAPI 后端，负责认证、Trip、Job、Search、Settings、Export 等 API。
- `apps/worker`：异步任务 worker，负责消费 ARQ 队列里的 job。
- `packages/shared-types`：前端共享类型，减少接口字段漂移。
- `packages/ui`：共享 UI tokens 和基础样式。
- `infra`：Docker Compose、Nginx、环境变量模板。
- `docs`：架构、开发、部署、面试总结文档。

你要能解释核心请求链路：

1. 用户在 Vue 前端创建 Trip。
2. 前端调用 `POST /api/v1/trips`。
3. FastAPI 校验请求并写入数据库。
4. 用户点击 Generate。
5. 后端创建 job，返回 `job_id`。
6. job 进入 inline 执行或 ARQ + Redis 队列。
7. handler 调用 orchestrator。
8. orchestrator 根据配置选择真实 LLM 或 stub。
9. 结果写回 Trip。
10. 前端轮询或 SSE 获取 job 状态。
11. 用户查看 itinerary，继续 refine 或 export。

---

## 4. 第一优先级：项目 Owner 能力

这是你最该补的一层。它比单独学 Vue 或 FastAPI 更重要。

### 4.1 必须掌握的问题

你要能回答：

- 这个项目解决什么用户问题？
- MVP 主链路是什么？
- 为什么要拆成 web / api / worker？
- 为什么本地支持 inline job？
- 为什么生产方向要 Redis + worker？
- 为什么用统一 response envelope？
- 为什么 search result 要结构化？
- 为什么 LLM 要有 stub fallback？
- 为什么 API key 不能明文返回给前端？
- 为什么 Trip 创建和 Generate 是两个动作？

### 4.2 必须能做的操作

你要能独立完成：

- 按 README 启动前端。
- 按 README 启动后端。
- 注册/登录一个用户。
- 创建一个 Trip。
- 触发 Generate。
- 查看 job 状态变化。
- 触发 refine。
- 导出 PDF。
- 跑 API 测试。
- 定位一次接口报错来自前端、后端、数据库还是环境。

### 4.3 推荐练习

选一个页面按钮，例如 `Generate itinerary`，追完整链路：

1. Vue 页面中按钮在哪里。
2. 点击后调用了哪个函数。
3. 函数调用了 `api.ts` 中哪个请求。
4. 后端哪个 route 接住请求。
5. route 调用了哪个 service。
6. service 创建了什么 job。
7. job handler 做了什么。
8. 数据库哪个字段被更新。
9. 前端怎么拿到最终结果。

这件事练 3 遍，你的项目理解会明显变扎实。

---

## 5. 前端能力清单

这个项目里，前端是你的主战场。面试时建议把前端讲成强项。

### 5.1 Vue 3 基础

必须掌握：

- `ref`
- `reactive`
- `computed`
- `watch`
- `onMounted`
- props
- emits
- 组件拆分
- 条件渲染
- 列表渲染
- 表单绑定

你要能解释：

- 为什么复杂页面不能所有逻辑都写在 template 里。
- 为什么派生状态适合用 `computed`。
- 为什么接口请求状态要有 loading / error / empty。
- 为什么表单提交前要做基础校验。

项目对应文件：

- `apps/web/src/views/TripDetailView.vue`
- `apps/web/src/views/NewTripView.vue`
- `apps/web/src/views/SettingsView.vue`
- `apps/web/src/views/ExportView.vue`

### 5.2 Vue Router

必须掌握：

- 路由配置
- 动态路由参数
- query 参数
- 路由守卫
- 受保护页面
- 登录后 redirect
- admin 权限判断

项目对应文件：

- `apps/web/src/router.ts`

你要能解释：

- `/trips/:id` 为什么需要 `props`。
- 未登录访问受保护页面为什么跳到 login。
- 登录后为什么要回到 redirect。
- admin 页面为什么要检查 `requiresAdmin`。

### 5.3 Pinia / Store 思想

项目中有几个关键 store：

- `auth.ts`：登录态、当前用户、bootstrap。
- `locale.ts`：语言切换。
- `llmSettings.ts`：模型配置、是否已配置、masked key。
- `jobGuard.ts`：job 相关保护逻辑。

必须理解：

- 为什么登录态不能每个页面自己判断。
- 为什么模型配置不能散落在多个页面。
- 为什么 store 是“同一事实的统一来源”。
- 为什么页面应该消费业务状态，而不是关心底层存储细节。

### 5.4 TypeScript

必须掌握：

- interface
- type
- union type
- optional field
- generic
- API response 类型
- 避免滥用 `any`

项目对应文件：

- `packages/shared-types/src/index.ts`
- `apps/web/src/lib/api.ts`

你要能解释：

- 为什么前后端共享类型可以减少字段漂移。
- 为什么 `request<T>()` 要使用泛型。
- 为什么新增后端字段时，前端类型也要同步。

### 5.5 API 封装

必须掌握：

- `fetch` 基础
- HTTP method
- request body
- cookie / credential
- status code
- 错误处理
- 统一 response envelope

你要能解释：

- 为什么页面不应该直接到处写 `fetch`。
- 为什么 API 错误要统一处理。
- 为什么后端返回 `{ data, error, meta }` 比裸返回更稳定。

项目对应文件：

- `apps/web/src/lib/api.ts`

### 5.6 复杂页面组织

Trip Detail 是项目里最值得讲的复杂页面。它不是普通详情页，而是 AI 工作台。

它承载：

- Trip brief
- LLM status
- 当前 job
- progress
- timeline
- itinerary
- search grounding
- refine actions
- export entry

你要能解释：

- 为什么这个页面叫 workbench，而不是普通 detail。
- 为什么 AI 产品要展示过程，而不只是展示结果。
- 为什么 generate / refine / export 要统一成 job 状态体验。
- 为什么用户需要知道当前走真实模型还是 fallback。

---

## 6. 后端能力清单

你不需要把自己包装成纯后端，但要能看懂、能改、能讲清楚。

### 6.1 FastAPI

必须掌握：

- `FastAPI()`
- router
- dependency
- request schema
- response schema
- exception handler
- middleware
- static files
- lifespan

项目对应文件：

- `apps/api/src/travelmind_api/main.py`
- `apps/api/src/travelmind_api/api/router.py`
- `apps/api/src/travelmind_api/api/routes/*.py`

你要能解释：

- `create_app()` 做了什么。
- CORS 为什么需要配置。
- `/exports/files` 为什么要静态挂载。
- 为什么要统一处理 `HTTPException` 和 validation error。

### 6.2 Pydantic Schema

必须掌握：

- 请求模型
- 响应模型
- 字段校验
- 默认值
- 可选字段
- 嵌套结构

项目对应文件：

- `apps/api/src/travelmind_api/api/schemas/*.py`

你要能解释：

- schema 和数据库 model 的区别。
- 为什么不能直接把数据库对象裸返回。
- 为什么错误响应也要有固定结构。

### 6.3 SQLAlchemy

必须掌握：

- model
- session
- query
- insert/update
- transaction
- SQLite 和 Postgres 差异

项目对应文件：

- `apps/api/src/travelmind_api/db/models.py`
- `apps/api/src/travelmind_api/core/database.py`

你要能解释：

- `User`、`Trip`、`JobRecord` 大概存什么。
- 为什么本地 SQLite 方便开发。
- 为什么正式生产更适合 PostgreSQL。
- 为什么 schema 演进最终应该引入 migration。

### 6.4 Service 分层

项目不是把所有逻辑都堆在 route 里，而是有 service 层。

典型 service：

- `auth_service.py`
- `trip_service.py`
- `job_service.py`
- `search_service.py`
- `export_service.py`
- `image_generation.py`

你要能解释：

- route 负责接请求和返回响应。
- service 负责业务规则。
- model 负责数据结构。
- schema 负责 API 合同。

这句话很适合面试：

> 我倾向于让 route 保持薄一些，把校验、状态推进和业务写入放到 service 层，这样更容易测试和复用。

### 6.5 Auth 与安全

必须掌握：

- JWT 是什么。
- access token 和 refresh token 的区别。
- cookie 登录态的基本思路。
- logout 为什么最好是幂等的。
- API key 为什么不能明文回显。
- CORS 是什么。
- `.env` 为什么不能提交真实密钥。

项目亮点：

- LLM API key 返回时只给 masked 值。
- job 查询接口不暴露完整 payload。
- logout 作为清理状态动作，不应因为 access token 过期就失败。

---

## 7. 异步任务与 Job 系统

这是这个项目最有技术含量、也最适合面试展开的部分。

### 7.1 为什么需要异步任务

Generate、refine、export 都可能耗时：

- LLM 调用可能慢。
- 搜索和结构化处理可能慢。
- PDF 导出可能慢。
- 后续真实地图、酒店、图片服务也可能慢。

如果这些都放在 HTTP 请求里同步执行，用户会遇到：

- 页面卡住
- 请求超时
- 后端 worker 被占满
- 失败不可观测

所以项目引入 job 系统。

### 7.2 Job 状态机

核心状态：

```text
queued -> running -> completed
                  -> failed
```

辅助字段：

- `stage`
- `stage_message`
- `progress_percent`
- `timeline_json`
- `error_message`
- `result_json`

你要能解释：

- `status` 解决任务是否结束。
- `stage` 解决任务当前在哪一步。
- `progress_percent` 解决用户等待感。
- `timeline_json` 解决过程可追踪。
- `error_message` 解决失败可解释。

### 7.3 inline vs ARQ

项目支持两种执行模式：

```text
inline: API 进程内直接执行 job
arq: API 入队 Redis，worker 异步消费
```

inline 的价值：

- 本地开发简单。
- 测试稳定。
- 不依赖 Redis。

ARQ 的价值：

- 更接近生产。
- 长任务不会阻塞 API 请求。
- worker 可以独立扩展。

面试表达：

> 我们没有强迫本地开发必须启动 Redis 和 worker，而是保留 inline 模式保证开发闭环；同时在 Docker/生产方向使用 ARQ + Redis，把长任务从 API 请求里拆出去。

### 7.4 SSE 与轮询

项目支持普通 job detail，也支持 SSE stream。

你要能解释：

- 轮询：前端定期请求 `/jobs/:id`。
- SSE：后端持续推送 job 状态变化。
- 两者最好返回同一套序列化结构，避免前端维护两套逻辑。

### 7.5 必讲 bug

推荐准备这个案例：

> Redis 不可用时，ARQ 入队失败，但 job 如果还停留在 queued，用户会一直看到处理中。修复方式是 enqueue 失败时立即把 job 标记为 failed，并写入 error_message，让 detail 和 SSE 都能收敛到终态。

这个例子能体现：

- 你理解异步任务不是只会入队。
- 你关注失败状态。
- 你知道用户体验和系统状态一致性。

---

## 8. AI 应用工程能力

这个项目的 AI 亮点不是“调用了某个模型”，而是把 LLM 放进了可控的工程系统。

### 8.1 LLM 不是可靠函数

你要记住这句话：

> 大模型不是 deterministic function，而是一个可能失败、可能超时、可能返回脏数据的外部依赖。

所以系统要处理：

- 无 API key
- base_url 配错
- model 配错
- 网络失败
- 返回非 JSON
- 返回 markdown 包裹的 JSON
- 字段缺失
- 天数不对
- 结构不符合预期

### 8.2 Prompt + Parser + Fallback

推荐用三层来讲：

1. Prompt 强约束：要求模型只返回 JSON。
2. Parser 防御：从文本里提取 JSON，并用 schema 校验。
3. Fallback 保底：失败时退回 stub，保证主链路还能跑。

面试表达：

> 我没有把 LLM 当成绝对可靠的业务函数，而是把它作为外部 provider，通过 prompt 约束、parser 校验和 fallback 降级放进系统里。

### 8.3 OpenAI-compatible 设计

项目中不是只绑定某一个官方 SDK，而是支持 OpenAI-compatible 风格的配置：

- `base_url`
- `api_key`
- `model`
- `wire_api`

好处：

- 可以接 OpenAI。
- 可以接兼容网关。
- 可以接私有部署。
- 测试时更容易 mock。

### 8.4 Search Grounding

搜索结果不是简单链接，而是结构化 `SearchDocument`。

字段包括：

- `title`
- `url`
- `summary`
- `place_name`
- `category`
- `opening_hours`
- `price_hint`
- `address`
- `geo`
- `source_type`
- `scores`

你要能解释：

- 前端可以直接展示地点卡片。
- planner 可以复用地址、类别、价格、开放时间。
- 结构化数据比纯文本更适合后续排序、推荐和导出。

### 8.5 LLM Settings

项目支持用户配置模型：

- `base_url`
- `api_key`
- `model`

安全设计：

- GET/PUT 响应不返回完整 API key。
- 只返回 `api_key_masked` 和 `has_api_key`。
- job detail 不暴露完整 payload。

你要能诚实说明：

> 当前阶段已经做到 API 不回显明文 key，但数据库明文存储仍不是最终生产级方案。后续应该接加密存储、KMS 或 secret manager。

---

## 9. 测试与工程化

### 9.1 为什么测试很重要

如果你是通过 AI 辅助开发项目，测试尤其重要。因为测试能证明你不是只把代码“生成出来”，而是知道怎么验证它。

你要能讲：

- API 合同测试保护前后端接口。
- 主链路测试保护 create -> generate -> export。
- search 测试保护结构化结果。
- LLM 测试保护 fallback。
- worker smoke test 保护 import 和运行边界。

### 9.2 你必须会跑的命令

前端：

```powershell
npm install
npm run dev:web
npm run build:web
```

后端：

```powershell
uv sync --frozen --project apps/api
uv run --project apps/api pytest apps/api/tests
uv run --project apps/api uvicorn travelmind_api.main:app --reload --host 127.0.0.1 --port 8000
```

Docker：

```powershell
docker compose --env-file infra/.env.example -f infra/docker-compose.yml up --build
```

### 9.3 你要能解释的环境变量

- `TRAVELMIND_AGENT_PROVIDER`
- `TRAVELMIND_QUEUE_MODE`
- `TRAVELMIND_REDIS_URL`
- `TRAVELMIND_DATABASE_URL`
- `TRAVELMIND_CORS_ORIGINS`
- `VITE_API_BASE_URL`
- `TRAVELMIND_LLM_BASE_URL`
- `TRAVELMIND_LLM_API_KEY`
- `TRAVELMIND_LLM_MODEL`

### 9.4 Docker / Compose 基础

必须掌握：

- Dockerfile 是镜像构建说明。
- Compose 是多服务编排。
- web / api / worker / redis 为什么拆开。
- volume 为什么用于共享 storage。
- web 容器为什么用 Nginx 托管静态资源。
- SPA 深链接为什么需要 fallback 到 `index.html`。

---

## 10. 需要补的计算机基础

这个项目很应用层，但面试一定会穿插基础。

### 10.1 HTTP

必须掌握：

- GET / POST / PATCH / PUT / DELETE
- status code：200、201、400、401、403、404、422、500
- header
- cookie
- CORS
- JSON request / response
- SSE

### 10.2 数据库

必须掌握：

- 表
- 主键
- 外键
- 索引
- transaction
- migration
- SQLite 和 PostgreSQL 的差异

### 10.3 JavaScript / TypeScript

必须掌握：

- async / await
- Promise
- array map/filter/reduce
- object destructuring
- module import/export
- type/interface
- error handling

### 10.4 Python

必须掌握：

- function
- class
- dataclass / Pydantic model
- async 基础
- context manager
- exception
- type hint
- package import

---

## 11. 12 周学习路线

### 第 1-2 周：项目跑通和架构理解

目标：

- 能完整启动前后端。
- 能创建 Trip 并生成结果。
- 能画出项目架构图。
- 能讲清楚主链路。

任务：

- 阅读 `README.md`。
- 阅读 `docs/architecture.md`。
- 跑通 web 和 api。
- 走一遍 create -> generate -> export。
- 写一份自己的链路笔记。

验收：

- 不看文档，能口头讲 3 分钟项目整体架构。

### 第 3-4 周：前端主战场

目标：

- 能看懂主要 Vue 页面。
- 能改一个小 UI / 状态逻辑。
- 能解释 router、store、api 封装。

任务：

- 精读 `router.ts`。
- 精读 `api.ts`。
- 精读 `auth.ts` 和 `llmSettings.ts`。
- 精读 `TripDetailView.vue`。
- 给某个页面加一个小字段展示。

验收：

- 面试官问“点击 Generate 后前端发生什么”，你能从组件讲到 API 请求。

### 第 5-6 周：后端 API 和数据库

目标：

- 能看懂 FastAPI route。
- 能看懂 service。
- 能看懂 schema 和 model。
- 能新增一个简单接口。

任务：

- 精读 `main.py`。
- 精读 `api/router.py`。
- 精读 `routes/trips.py`、`routes/jobs.py`。
- 精读 `trip_service.py`、`job_service.py`。
- 给 Trip 增加一个只读统计字段或简单备注字段。

验收：

- 能解释 route / schema / service / model 的分工。

### 第 7-8 周：异步任务系统

目标：

- 吃透 job 状态机。
- 理解 inline 和 ARQ。
- 理解 SSE 和轮询。

任务：

- 找到 job 创建逻辑。
- 找到 job handler。
- 找到 worker 入口。
- 找到前端轮询 job 的逻辑。
- 画 job 状态流转图。

验收：

- 能讲清楚“为什么 Redis 挂了不能让 job 一直 queued”。

### 第 9-10 周：AI 应用工程

目标：

- 理解 LLM provider。
- 理解 prompt、parser、fallback。
- 理解 search grounding。

任务：

- 精读 LLM config/client/parser 相关文件。
- 精读 search service。
- 精读 settings API。
- 用自己的话写一段“LLM 失败时系统怎么处理”。

验收：

- 能讲清楚“为什么 LLM 不是可靠函数，以及系统怎么兜底”。

### 第 11-12 周：面试表达和模拟

目标：

- 简历 bullet 打磨。
- 项目 3 分钟介绍。
- 准备 10 个高频追问。
- 做模拟面试。

任务：

- 准备一版 30 秒项目介绍。
- 准备一版 3 分钟项目介绍。
- 准备 3 个 bug 案例。
- 准备 2 个架构权衡。
- 准备 1 个“我用 AI 辅助开发但如何确保质量”的回答。

验收：

- 不看稿能讲完项目。
- 被追问到具体文件和链路时不慌。

---

## 12. 必须准备的面试故事

### 故事 1：项目整体介绍

结构：

1. 项目做什么。
2. 技术栈是什么。
3. 核心链路是什么。
4. 你主要负责什么。
5. 当前做到什么程度。

示例：

> TravelMind AI 是一个 AI 旅行规划 MVP，用户可以创建旅行 brief，触发行程生成，查看异步任务进度，基于搜索 grounding 做 refine，最后导出 PDF。技术上是 Vue 3 + FastAPI 的 monorepo，后端用 ARQ + Redis 处理长任务，本地也支持 inline 模式。我的重点是把前端工作台、后端 API、job 状态机、LLM 配置和 fallback 串成一个可运行闭环。

### 故事 2：异步任务难点

重点讲：

- 为什么需要 job。
- 状态机怎么设计。
- inline 和 ARQ 怎么取舍。
- 入队失败怎么处理。
- SSE 和轮询怎么统一。

### 故事 3：AI 可靠性

重点讲：

- LLM 可能失败。
- prompt 约束输出。
- parser 校验结构。
- 失败 fallback。
- trace 记录原因。

### 故事 4：前端工作台

重点讲：

- Trip Detail 从详情页变成 workbench。
- 用户能看到输入、过程、输出。
- generate/refine/export 统一 job 体验。
- 模型状态提示减少用户困惑。

### 故事 5：工程化交付

重点讲：

- README 本地启动。
- Dockerfile / Compose。
- CI 思路。
- API 测试。
- 环境权限问题排查。

### 故事 6：诚实讲 AI 辅助开发

推荐表达：

> 这个项目开发过程中我大量使用了 AI 辅助生成和重构代码，但我没有把它当成黑盒交付。我主要做的是需求拆解、代码审查、链路调试、测试验证和复盘总结。面试前我也专门把主链路、关键模块和 bug 修复重新梳理了一遍，确保自己能独立解释和继续维护。

这比硬说“全部都是我手写的”更稳，也更真实。

---

## 13. 高频面试问题清单

### 项目类

1. 这个项目的核心业务流程是什么？
2. 你在项目里主要负责哪几块？
3. 为什么选择 Vue + FastAPI？
4. monorepo 的好处和问题是什么？
5. 前后端接口如何保持一致？
6. 你遇到过最难的 bug 是什么？
7. 如果让你继续优化，你会先做什么？

### 前端类

1. Vue Router 的鉴权怎么做？
2. Pinia store 解决了什么问题？
3. TripDetailView 为什么复杂？
4. 前端如何处理 loading / error / empty？
5. API 封装为什么要用泛型？
6. LLM settings 为什么要抽成 store？

### 后端类

1. FastAPI route 和 service 怎么分工？
2. Pydantic schema 和 SQLAlchemy model 有什么区别？
3. 认证流程怎么做？
4. logout 为什么要幂等？
5. API key 为什么不能明文返回？
6. SQLite 和 PostgreSQL 有什么差异？

### 异步任务类

1. 为什么 generate 不直接同步返回？
2. job 状态机怎么设计？
3. inline 和 ARQ 有什么区别？
4. Redis 挂了怎么办？
5. 如何避免 job 重复执行？
6. SSE 和轮询有什么区别？

### AI 应用类

1. LLM 输出不稳定怎么办？
2. 为什么需要 stub fallback？
3. OpenAI-compatible 是什么？
4. Search grounding 的价值是什么？
5. 如何保护用户 API key？
6. 如果模型返回非 JSON 怎么处理？

---

## 14. 简历 bullet 示例

可以写成：

- 基于 Vue 3 + TypeScript + FastAPI 搭建 AI 旅行规划 MVP，打通 Trip 创建、行程生成、Refine、搜索补充与 PDF 导出闭环。
- 设计并实现异步 Job 状态展示，支持 queued/running/completed/failed 状态、阶段进度、timeline 记录与 SSE/轮询查询。
- 封装 LLM 配置与 OpenAI-compatible 调用链，支持用户配置 base_url/api_key/model，并在模型不可用时 fallback 到本地 stub，提升本地开发与测试稳定性。
- 将搜索结果结构化为 SearchDocument，包含地点名称、类别、营业时间、价格提示、地址、坐标和评分信息，支撑前端地点卡片展示与后续 planner grounding。
- 完善 Docker Compose、本地启动文档与 API 测试，提升多服务 monorepo 的可运行性和可验证性。

注意：

- 如果你还不能深入讲某个 bullet，就先不要写得太重。
- 简历上写的每句话，都要准备 2-3 分钟解释。

---

## 15. 自测标准

当你能做到下面这些，基本可以把项目放到简历上比较稳地讲：

### 基础达标

- 能独立启动项目。
- 能跑一遍主流程。
- 能解释项目目录。
- 能解释前后端 API 如何通信。
- 能解释 job 状态机。

### 面试达标

- 能讲 3 分钟项目介绍。
- 能回答 10 个常见追问。
- 能讲 3 个真实 bug。
- 能解释 2 个架构权衡。
- 能新增一个小字段或小接口。
- 能给新增接口补一个测试。

### 更高水平

- 能把 SQLite schema 兼容升级成 Alembic migration。
- 能把 LLM key 改成加密存储。
- 能给 job 增加重试和超时。
- 能给 LLM parser 增加 schema 修复。
- 能把 search grounding 和 itinerary item 做关联。
- 能设计一个真实地图 provider adapter。

---

## 16. 最重要的心态

你现在不是要证明“我从来没用过 AI”，而是要证明：

> 我能利用 AI 提高开发速度，同时通过理解、调试、测试和复盘，把生成出来的东西变成可靠工程。

面试官不会因为你使用 AI 就一定否定你。真正危险的是：

- 你说不清项目架构。
- 你说不清代码在哪。
- 你说不清 bug 怎么修。
- 你说不清为什么这么设计。
- 你不能在项目上做任何独立修改。

所以接下来的学习重点不是泛泛地刷课，而是围绕这个项目做“反向 owning”：

1. 追链路。
2. 画架构。
3. 改小功能。
4. 补测试。
5. 讲故事。
6. 做模拟面试。

只要这 6 件事做扎实，这个项目就可以从 vibe coding 作品，变成你简历上真正能撑住追问的项目。

---

## 17. 高频面试问题参考答案

下面这些答案不是让你逐字背诵，而是给你一套表达骨架。真正面试时，要用自己的话讲，并且尽量结合 TravelMind AI 里的具体文件、链路和 bug。

---

## 17.1 项目类问题

### Q1：这个项目的核心业务流程是什么？

参考答案：

TravelMind AI 的核心业务流程是围绕旅行规划闭环展开的。用户先注册/登录，然后创建一个 Trip brief，填写目的地、日期、预算、人数、兴趣、节奏等信息。创建完成后，用户可以触发 Generate，后端会创建一个异步 job，通过 inline 模式或 ARQ + Redis worker 执行行程生成逻辑。生成过程中，前端可以通过 job detail 或 SSE 查看状态、阶段、进度和 timeline。生成完成后，itinerary 会写回 Trip，用户可以继续 refine 调整行程，也可以导出 PDF。

从工程链路看，是：

```text
Vue 页面 -> API 请求 -> FastAPI route -> service -> job -> orchestrator -> LLM/stub/search -> 数据库 -> 前端展示
```

这个项目不是单纯的 CRUD，而是把“输入、生成、可观测任务、二次调整、导出交付”串成了一个 MVP 闭环。

### Q2：你在项目里主要负责哪几块？

参考答案：

我主要可以从三块来讲。第一是前端工作台，把 Trip 详情页从简单结果页升级成可以查看 brief、模型状态、job 进度、timeline、itinerary、search grounding 和 refine 操作的工作台。第二是后端和异步任务链路，包括 Trip generate/refine/export 这些操作都通过统一 job 系统处理，支持状态、阶段和失败信息。第三是 AI 应用集成，包括 LLM settings、OpenAI-compatible 调用方式、search grounding 和 stub fallback。

如果面试官继续追问，我会重点展开异步 job 状态机、LLM fallback，以及前端如何把这些后端状态展示成用户能理解的工作流。

### Q3：为什么选择 Vue + FastAPI？

参考答案：

Vue 3 + Vite 比较适合快速搭建交互型工作台，Composition API 和组件化能力可以支撑 Trip Detail 这种复杂页面。TypeScript 也能帮助前端和 shared types 保持字段一致。FastAPI 的优势是开发效率高、Pydantic schema 清晰、接口文档和类型校验方便，也适合做 AI 应用后端，因为 Python 生态更容易接 LLM、PDF、搜索、worker 等能力。

这个项目是 MVP 阶段，重点是快速打通闭环，同时保持后续可扩展性。Vue + FastAPI 的组合能兼顾开发速度和工程结构。

### Q4：monorepo 的好处和问题是什么？

参考答案：

monorepo 的好处是前端、后端、worker、shared types、infra 都在一个仓库里，开发和联调更方便。比如 shared types 可以在 `packages/shared-types` 里统一维护，前端和接口字段不容易漂移；Docker、README、Compose 也可以集中管理。

问题是模块边界容易变模糊。比如 worker 运行时依赖 API 里的配置、数据库和 job handler，如果 Dockerfile 只复制 worker 自己，就会 import 失败。所以 monorepo 里要特别注意运行边界和依赖边界。这个项目里通过 `apps/web`、`apps/api`、`apps/worker`、`packages/*` 做了基本分层，但后续如果规模变大，还可以继续把共享后端逻辑拆成更明确的 package。

### Q5：前后端接口如何保持一致？

参考答案：

项目里主要通过三点保持一致。第一，后端使用 Pydantic schema 定义请求和响应结构。第二，前端在 `packages/shared-types` 里维护共享类型，例如 Trip、Job、LLM settings、SearchDocument 等。第三，API 返回统一 envelope，也就是 `{ data, error, meta }`，前端的 `request<T>()` 可以用泛型统一处理成功和失败。

这样做的好处是接口新增字段时可以增量演进，前端不会到处写散乱的 fetch 和错误判断。SSE 和普通 job detail 也尽量复用同一套序列化结构，避免前端为两种数据源维护两套逻辑。

### Q6：你遇到过最难的 bug 是什么？

参考答案：

我会讲 ARQ 入队失败导致 job 卡在 queued 的问题。现象是 Redis 不可用或入队失败时，用户已经点击 Generate，但 job 实际不会被 worker 消费。如果系统仍然让 job 保持 queued，前端会一直显示处理中，用户不知道发生了什么。

这个问题的本质不是单纯的 Redis 报错，而是异步任务状态没有和真实执行结果保持一致。修复思路是：如果 enqueue 失败，就立即把 job 标记为 failed，并写入 error_message，让 `/jobs/:id` 和 SSE 都能收敛到失败终态。这样前端能展示明确错误，而不是无限等待。

这个 bug 体现了我对异步任务的理解：任务系统不只是“能入队”，还要处理失败、终态、用户反馈和状态一致性。

### Q7：如果让你继续优化，你会先做什么？

参考答案：

我会优先做四件事。第一，引入正式数据库 migration，比如 Alembic，替代现在 MVP 阶段的 SQLite 自动补列逻辑。第二，把 LLM API key 从明文存储升级成加密存储，或接入 KMS/Secret Manager。第三，给 job 系统补充更完整的超时、重试和失败分类。第四，增强 LLM parser 和 schema 校验，让模型返回不稳定时可以自动修复或更清晰地报错。

如果偏前端方向，我还会做 itinerary 对比视图，让用户能看到 refine 前后的变化；如果偏后端方向，我会优先做 provider 缓存、限流和真实地图 provider adapter。

---

## 17.2 前端类问题

### Q1：Vue Router 的鉴权怎么做？

参考答案：

项目里在 router 配置中给需要登录的页面加了 `meta.requiresAuth`，例如 trips、trip detail、settings、admin 等页面。全局 `beforeEach` 守卫会先调用 auth store 的 `bootstrap()` 初始化当前用户状态。如果目标页面需要登录但当前没有 user，就跳转到 login，并把原始地址放到 `redirect` query 里。登录成功后可以跳回原页面。

admin 页面还额外使用 `meta.requiresAdmin`，如果当前用户不是 admin，就重定向到普通 trips 页面。这样鉴权逻辑集中在 router 和 auth store，而不是散落到每个页面。

### Q2：Pinia store 解决了什么问题？

参考答案：

Pinia store 解决的是“同一事实多个页面共享”的问题。比如登录态、语言、LLM 配置这些状态，不适合每个页面自己请求、自己判断。否则很容易出现某个页面认为已登录，另一个页面认为未登录，或者某个页面显示已配置模型，另一个页面显示未配置。

项目里 `auth.ts` 管理用户和登录状态，`locale.ts` 管理中英文，`llmSettings.ts` 管理模型配置、是否已配置、masked key 和 resolved config。页面只消费 store 暴露出的业务状态，不直接关心配置来自后端还是 localStorage，这样后续迁移存储方式时代码改动更小。

### Q3：TripDetailView 为什么复杂？

参考答案：

TripDetailView 不是普通详情页，而是 AI 旅行规划工作台。它同时承载输入、过程和输出：输入是 trip brief，过程是当前 job、stage、progress、timeline，输出是 itinerary、search grounding 和 export 入口。另外它还支持 refine 操作和模型状态提示。

复杂点在于它要把多个异步状态统一成用户能理解的工作流。用户点击 Generate 后，页面不能只是等待结果，而要显示任务是否 queued/running、当前阶段是什么、失败原因是什么、是否可以继续 refine 或 export。这个页面体现的是 AI 产品的一个关键特点：不只展示最终文本，还要解释生成过程和系统状态。

### Q4：前端如何处理 loading / error / empty？

参考答案：

我会把页面状态拆成至少四类：loading、error、empty、ready。loading 表示请求还在进行中；error 表示接口失败或业务失败；empty 表示请求成功但没有数据，比如还没有 itinerary；ready 表示数据可展示。

在这个项目里，Trip 刚创建但还没有 Generate 时，就应该是 empty 或 next-step 状态，而不是错误。job failed 时应该展示 error_message，而不是只在 console 打印。Export 没有 itinerary 时按钮应该禁用，这样能避免用户进入无效流程。

### Q5：API 封装为什么要用泛型？

参考答案：

因为后端返回的是统一 envelope，但不同接口的 `data` 类型不同。比如 Trip 接口返回 Trip，Job 接口返回 Job，Search 接口返回 SearchDocument 列表。如果 `request<T>()` 使用泛型，调用方可以明确声明这次请求期望的数据类型，TypeScript 会在页面层提供类型提示和编译检查。

这样可以减少 `any`，也能在后端字段变化时更早发现前端代码问题。对于 monorepo 项目，泛型 API 封装配合 shared types，可以降低接口漂移带来的维护成本。

### Q6：LLM settings 为什么要抽成 store？

参考答案：

LLM settings 会被多个页面使用，比如 Settings 页、Trip 列表页、New Trip 页、Trip Detail 页和 LLM Demo 页。如果每个页面都自己判断 base_url、api_key、model 是否存在，就会出现状态不一致。

抽成 store 后，是否已配置模型、masked key、resolved config 都由统一逻辑计算。页面只关心 `isConfigured` 或当前状态提示，不需要知道底层配置来自 localStorage 还是后端 settings API。这样后续如果从浏览器本地配置迁移到服务端持久化，页面层不用大改。

---

## 17.3 后端类问题

### Q1：FastAPI route 和 service 怎么分工？

参考答案：

route 主要负责接收请求、做依赖注入、调用 service、组织响应。service 负责真正的业务规则，比如创建 Trip、校验日期、创建 job、写数据库、更新状态等。schema 负责 API 输入输出结构，model 负责数据库表结构。

这样分层的好处是 route 不会变得过于臃肿，业务逻辑可以被测试和复用。比如 Trip 创建不只是插入数据库，还要做字段规范化、日期校验、interests 去重等，这些更适合放在 service 层。

### Q2：Pydantic schema 和 SQLAlchemy model 有什么区别？

参考答案：

Pydantic schema 是 API 层的数据合同，用来校验请求和序列化响应。SQLAlchemy model 是数据库层的表结构，用来描述数据如何持久化。

两者不能混为一谈。比如数据库里的 User 可能有 password hash、api key 等敏感字段，但 API 响应不能直接返回这些字段。再比如 API 输入可能有一些临时字段或可选字段，不一定和数据库列一一对应。所以项目里通过 schema 控制对外暴露的数据，通过 model 控制内部持久化。

### Q3：认证流程怎么做？

参考答案：

项目里基础认证流程是注册、登录、获取当前用户、登出。注册时会规范化 email、校验用户信息、保存 password hash。登录时校验账号密码，签发 token 或设置 cookie。前端通过 auth store 的 bootstrap 获取当前用户，从而判断是否允许进入受保护页面。

登出最好做成幂等操作，即使 access token 过期，也应该尽量清理 refresh session 和 cookie，而不是因为 401 导致用户无法退出。这个设计更符合用户体验，因为 logout 本质是清理客户端和服务端 session 状态。

### Q4：logout 为什么要幂等？

参考答案：

因为用户点击退出时，系统状态可能已经不一致了。比如 access token 过期、refresh token 失效、服务端 session 已经被撤销。如果 logout 强依赖当前 access token 有效，用户可能会遇到“想退出却因为 401 退不出去”的情况。

所以 logout 更适合设计成幂等清理动作：有 refresh session 就撤销，没有也不报错；无论如何都清理 cookie，并返回成功。这样前端可以稳定地把用户带回未登录状态。

### Q5：API key 为什么不能明文返回？

参考答案：

API key 是敏感凭据。如果 GET settings 或 PUT settings 后把完整 key 返回给前端，就可能通过浏览器、日志、错误上报、抓包等途径泄露。用户只需要知道“是否配置过”和“大概是哪一把 key”，不需要每次看到完整明文。

所以项目里返回 `has_api_key` 和 `api_key_masked`，例如只显示前后几位。这样既能支持前端展示“已配置”，又避免直接回显明文。需要诚实说明的是，当前 MVP 阶段如果数据库仍明文存储，后续生产化还应该升级为加密存储或接 KMS。

### Q6：SQLite 和 PostgreSQL 有什么差异？

参考答案：

SQLite 适合本地开发和测试，因为它轻量、无需单独启动数据库服务，开发闭环很快。但它在并发、迁移治理、生产可观测性、复杂查询能力上不如 PostgreSQL。PostgreSQL 更适合生产环境，支持更强的事务、并发、索引、扩展和运维能力。

这个项目本地使用 SQLite 是为了 MVP 快速启动，Compose 里保留 PostgreSQL profile 是为了后续生产方向。当前的 SQLite 自动补列适合 MVP，但长期应该引入 Alembic 这类正式 migration 工具。

---

## 17.4 异步任务类问题

### Q1：为什么 generate 不直接同步返回？

参考答案：

Generate 可能涉及 LLM 调用、搜索、结构化处理、地图或路线补全，执行时间不可控。如果直接在 HTTP 请求里同步处理，容易出现请求超时、用户页面卡住、API worker 被长任务占满等问题。

所以项目把 generate 做成异步 job。前端提交 generate 后拿到 job_id，再通过轮询或 SSE 查看状态。这样用户能看到 queued/running/completed/failed，也能看到 stage、progress 和 timeline，系统也更容易处理失败和重试。

### Q2：job 状态机怎么设计？

参考答案：

核心状态是：

```text
queued -> running -> completed
                  -> failed
```

queued 表示任务已创建但还未执行，running 表示正在执行，completed 表示成功完成，failed 表示失败终态。除了 status，还需要 stage、stage_message、progress_percent、timeline_json、error_message 和 result_json。

这样设计的原因是 status 只能告诉用户任务有没有结束，而 stage 和 timeline 可以告诉用户任务进行到哪一步、发生过什么。对于 AI 产品和导出任务，这种可观测性很重要。

### Q3：inline 和 ARQ 有什么区别？

参考答案：

inline 是 API 进程内直接执行 job，不依赖 Redis 和 worker，适合本地开发和测试。它的好处是启动简单、结果稳定、调试方便。ARQ 是把 job 放进 Redis 队列，由 worker 异步消费，更接近生产形态，适合处理长任务，也方便后续横向扩展 worker。

这个项目同时保留两种模式，是为了兼顾开发体验和生产架构。本地不应该为了跑一个测试就强制启动 Redis，但生产方向也不能让 API 请求一直阻塞在长任务里。

### Q4：Redis 挂了怎么办？

参考答案：

如果是 ARQ 模式，Redis 挂了会导致 job 无法入队或 worker 无法消费。关键是不能让用户看到一个永远 queued 的任务。正确做法是入队失败时立即把 job 标记为 failed，并写入 error_message，让前端能展示明确失败。

如果是在本地开发，也可以切回 inline 模式绕开 Redis。生产环境还应该增加 Redis 健康检查、重试策略、告警，以及更清晰的失败分类。

### Q5：如何避免 job 重复执行？

参考答案：

核心思路是 claim。也就是 worker 或 inline executor 在执行前，先尝试把 job 从 queued 原子更新为 running。只有状态转换成功的一方才能继续执行，其他执行方发现已经不是 queued 就直接退出。

这样可以避免同一个 job 被 inline 和 worker 同时执行，或者多个 worker 重复消费。对于 generate 和 export 这种会写回结果或生成文件的任务，避免重复执行非常重要。

### Q6：SSE 和轮询有什么区别？

参考答案：

轮询是前端每隔一段时间请求一次 `/jobs/:id`，实现简单，但会产生重复请求，也不够实时。SSE 是后端通过一个长连接持续向前端推送状态变化，更实时，也适合展示 job timeline。

项目里两者的重点不是谁替代谁，而是返回结构要一致。普通 detail 和 SSE event 都应该使用同一套 job 序列化结构，这样前端不需要为轮询和 SSE 写两套状态解析逻辑。

---

## 17.5 AI 应用类问题

### Q1：LLM 输出不稳定怎么办？

参考答案：

我会把 LLM 当成不稳定外部依赖，而不是可靠函数。处理方式分三层：第一，prompt 里强约束输出格式，比如要求只返回 JSON object。第二，parser 做防御性解析，支持从 markdown code fence 或混杂文本中提取 JSON，再用 schema 校验字段。第三，如果解析失败、请求失败或结构不符合预期，就 fallback 到 stub，保证主链路不被模型失败拖垮。

这样系统既可以接真实模型，又不会因为模型偶发乱输出导致用户流程完全中断。

### Q2：为什么需要 stub fallback？

参考答案：

stub fallback 的价值有三个。第一，本地开发不需要真实 API key，也能跑通 create -> generate -> export。第二，CI 测试不依赖外部模型，结果稳定可重复。第三，当真实 LLM 请求失败或返回不合法时，系统仍然可以给出一个可用的结果，避免主链路中断。

对于 MVP 来说，fallback 不是“假功能”，而是保证系统可用性和测试稳定性的工程手段。

### Q3：OpenAI-compatible 是什么？

参考答案：

OpenAI-compatible 指的是使用类似 OpenAI API 的协议格式，比如通过 `base_url`、`api_key`、`model` 配置请求地址和模型名，请求体使用 chat completions 或 responses 风格。很多第三方模型网关或私有部署会兼容这种格式。

项目采用 OpenAI-compatible 思路，是为了不把业务逻辑绑死在某一个 SDK 或供应商上。这样后续可以接 OpenAI，也可以接兼容网关、私有模型服务或 NewAPI 类接口。

### Q4：Search grounding 的价值是什么？

参考答案：

Search grounding 的价值是给 LLM 或 planner 提供外部事实来源，减少纯模型生成带来的幻觉。比如旅行规划里，景点地址、开放时间、价格提示、官方链接这些信息都不应该完全靠模型编。

项目里 SearchDocument 做成结构化结果，包含 place_name、category、opening_hours、price_hint、address、geo、source_type 和 scores。前端可以直接展示地点卡片，planner 后续也可以基于这些字段做排序、筛选和行程补全。

### Q5：如何保护用户 API key？

参考答案：

首先 API 响应不能明文返回完整 key，只返回 `has_api_key` 和 masked key。其次 job detail 这类接口不能把包含 key 的 payload 直接暴露给前端。再次，日志里不能打印完整 key。

如果进入生产级，还应该把数据库里的 key 做加密存储，或者接 KMS/Secret Manager。执行任务时只在后端临时解密或注入，不把密钥暴露给浏览器和普通响应。

### Q6：如果模型返回非 JSON 怎么处理？

参考答案：

处理方式是先做容错解析，再做 schema 校验。比如模型可能返回 markdown code fence，也可能在 JSON 前后加解释文本。parser 可以尝试提取最外层 JSON object，然后交给 Pydantic 或前端 schema 校验。如果仍然解析失败，就记录 trace/error，并 fallback 到 stub 或提示用户重试。

关键点是不要直接相信模型输出，也不要让非 JSON 响应一路污染业务数据。模型输出必须经过解析、校验和失败兜底。

---

## 18. 这些答案怎么变成你自己的话

准备面试时，不要只背上面的参考答案。建议你按这个方式改写：

1. 每个问题保留 3 个关键词。
2. 每个答案都加一个项目里的具体文件或模块。
3. 每个技术点都配一个“为什么”。
4. 每个 bug 都按“现象 -> 原因 -> 修复 -> 验证”讲。

例如讲 job 系统时，你可以记：

```text
关键词：状态机、ARQ/inline、失败收敛
文件：job_service / jobs route / worker
为什么：长任务不能阻塞 HTTP，请求失败不能让用户无限等待
```

这样就算面试紧张，你也能靠关键词把答案组织出来。

---

## 19. 结合当前项目源码的补充问答

> 本节基于当前 `E:/travel` 源码补充。前面章节偏学习路线，这里偏“面试时怎么把代码讲清楚”。回答时优先带上文件名、链路和边界，不要只背概念。

### 19.1 项目 Owner 类问题

#### Q1：当前 TravelMind AI 的核心闭环是什么？

参考答案：

当前项目不是单纯的“调用模型生成一段文本”，而是一个旅行规划工作台闭环：用户创建 Trip brief，配置模型、搜索和图片服务，然后在 Trip Detail 中生成或微调行程，系统把 itinerary、trace、grounding documents 保存回 Trip，后续还能执行图片补全、PDF/Markdown/JSON 导出、社区发布和管理后台治理。

可以按这条链路讲：

```text
NewTripView 创建 Trip
-> TripDetailView 生成 / refine / 搜索 / 保存行程
-> settings 保存用户级 agent/search/image 配置
-> 后端 jobs 处理 HelloAgents、补图、导出等长任务
-> Trip / JobRecord / CommunityPost / ImageGeneration 持久化
-> ExportView、Community、Admin 做结果消费和治理
```

对应文件：

- `apps/web/src/views/NewTripView.vue`
- `apps/web/src/views/TripDetailView.vue`
- `apps/web/src/lib/browserPlanner.ts`
- `apps/api/src/travelmind_api/api/routes/trips.py`
- `apps/api/src/travelmind_api/jobs/handlers.py`
- `apps/api/src/travelmind_api/services/export_service.py`
- `apps/api/src/travelmind_api/services/community_service.py`

#### Q2：为什么当前 generate / refine 有浏览器侧和后端 job 两种路径？

参考答案：

当前标准模式下，`TripDetailView.vue` 会在浏览器侧组织 prompt、解析模型返回，并通过 `/api/v1/llm/proxy` 让后端转发模型请求。这个路径不是把 API key 暴露在浏览器里，API key 仍然来自后端保存的用户 settings；浏览器主要负责工作台交互、prompt 上下文整理和结果保存。

当用户选择 `helloagents` provider 时，generate 会走 `POST /api/v1/trips/{id}/generate` 创建后端 job，因为 HelloAgents 涉及多角色编排、工具调用、搜索 grounding 和 progress callback，更适合放在服务端任务系统中执行。PDF 导出和景点补图也继续走 job，因为它们会写文件或调用后端工具，不适合完全放在浏览器里。

面试时可以诚实说：早期文档里把 generate/refine/export 都描述成后端 job，但当前实现为了更快的标准模型体验，把标准 generate/refine 调整成“浏览器组织 + 后端 relay + 保存结果”；HelloAgents、export、image enrich 仍然保留后端异步任务链路。

#### Q3：为什么 Trip 创建和 Generate 要拆成两个动作？

参考答案：

创建 Trip 的职责是保存结构化 brief，例如 origin、destination、date、budget、travelers、interests，并做日期和必填字段校验。Generate 的职责是基于已持久化的 Trip 去调用模型、搜索、工具或 job。拆开以后有三个好处：

1. 用户可以先创建草稿，再选择模型配置后生成。
2. Generate 失败不会丢失用户输入，可以重试或切换配置。
3. 后端可以把 Trip CRUD 和长任务状态机分开测试。

源码上，创建在 `trip_service.create_trip()`，生成入口在 `trips.py` 的 `generate_trip_endpoint()`，前端对应 `NewTripView.vue` 的 `submit()` / `submitAndGenerate()`。

#### Q4：这个项目和普通 CRUD 项目最大的区别是什么？

参考答案：

普通 CRUD 主要关注表单、列表、详情和增删改查。这个项目除了 CRUD，还要处理非确定性的 AI 输出、搜索 grounding、多源配置、长任务状态、导出文件、用户密钥保护和失败兜底。

例如 Trip 详情页不仅展示数据，还要展示模型配置状态、当前 job、timeline、grounding documents、refine memory、导出入口、社区发布状态和图片补全状态。这就是为什么文档里建议把 `TripDetailView.vue` 讲成 workbench，而不是普通 detail page。

#### Q5：当前项目有哪些必须诚实说明的边界？

参考答案：

可以主动说这还是 MVP，不要包装成生产级平台。当前边界包括：

- 本地默认 SQLite，PostgreSQL 是生产方向；README 也说明当前依赖里还没有 PostgreSQL driver。
- SQLite 兼容补列写在 `db/models.py`，适合 MVP，本质上不是正式 migration；长期应该引入 Alembic。
- 用户 API key 当前不明文返回前端，但数据库字段仍是普通文本，生产应升级为加密存储或 KMS。
- HelloAgents 是 PoC adapter，README 提醒不能把它当成商业生产依赖。
- 标准 generate/refine 当前由浏览器侧组织 prompt，后端 relay 转发模型请求；这和纯后端 planner 架构不同。
- `prompt-trends` 等部分能力目前还是 placeholder 或保留接口。

这样讲反而更可信，因为你能区分“已实现”“MVP 够用”和“生产化待补”。

### 19.2 前端类问题

#### Q1：Vue Router 鉴权和 admin 权限怎么做？

参考答案：

前端路由在 `apps/web/src/router.ts` 里用 `meta.requiresAuth` 和 `meta.requiresAdmin` 标记页面。`beforeEach` 里先调用 `auth.bootstrap()` 获取当前用户；未登录访问受保护页面时跳到 login，并带上 `redirect`；登录后会回到原目标页面。admin 页面还会检查 `auth.user?.is_admin`，不是管理员就回到 trips。

后端也有同样的保护：普通接口用 `get_current_user`，admin 接口用 `require_admin_user`。所以前端 guard 负责体验，后端 dependency 负责真正的安全边界。

#### Q2：`api.ts` 为什么要统一封装？

参考答案：

`apps/web/src/lib/api.ts` 统一处理了几个重复问题：API base URL、`credentials: "include"`、统一 envelope、错误转换成 `ApiError`、401 自动 refresh、以及泛型返回类型。页面不需要每次自己写 `fetch`、判断 status、拆 `data/error/meta`，只要调用 `api.createTrip()`、`api.getJob()`、`api.updateLlmSettings()` 这些业务方法。

这里比较值得讲的是 401 refresh：`apiFetch()` 遇到 401 会调用 `/api/v1/auth/refresh`，并用 `refreshSessionPromise` 做单飞，避免多个并发请求同时刷新 session。

#### Q3：Pinia store 在项目里解决了什么？

参考答案：

Pinia 负责跨页面共享的业务状态，而不是替代所有本地状态。`auth.ts` 管登录用户、bootstrap、logout；`llmSettings.ts` 管 agent/search/image settings、masked key、配置是否完成；`jobGuard.ts` 管进行中的阻塞任务，避免用户在 generate/refine 过程中无意离开。

页面局部状态仍然放在组件里，例如 TripDetail 的 `generatePending`、`searchResults`、`refineModalOpen`。这样分层比较清楚：跨页面的一致事实放 store，页面临时交互放组件。

#### Q4：TripDetailView 为什么复杂，怎么讲才不乱？

参考答案：

可以按“输入、过程、输出、后续动作”四块讲：

- 输入：Trip brief、模型配置、搜索 query、手动链接、refine instruction、上传 guide、社区 source。
- 过程：browser job 或后端 job、stage、progress、timeline、错误状态、jobGuard。
- 输出：itinerary、budget、trace、grounding documents、图片状态。
- 后续动作：refine、保存手改 itinerary、补图、导出、社区发布、删除 Trip。

这样比按代码行讲清楚得多。重点文件是 `TripDetailView.vue`、`browserPlanner.ts`、`api.ts` 和 `jobGuard.ts`。

#### Q5：为什么标准生成说是“浏览器侧”，但 API key 仍然安全？

参考答案：

浏览器侧指的是 prompt 组织、上下文拼装、JSON 解析和 UI 状态由前端完成；真正的上游模型请求仍然通过 `/api/v1/llm/proxy` 发给后端。`browserPlanner.ts` 调用 relay 时没有把保存的 API key 传到浏览器，后端 `llm.py` 会从当前用户的 settings 解析 `api_key`。

所以更准确的表述是：标准模式是“frontend-orchestrated, backend-relayed”，不是“浏览器直接带 key 调第三方模型”。

#### Q6：NewTrip 的表单模式和对话模式怎么解释？

参考答案：

`NewTripView.vue` 提供两种创建方式：表单适合用户已经知道目的地、日期、预算等信息；对话模式通过 `/api/v1/trips/intake/chat` 让后端 intake assistant 帮用户补全 draft，并返回 `missing_required_fields` 和 `ready_to_create`。

这体现的是产品思路：AI 不是只在生成行程时出现，也可以在输入阶段降低用户填写成本。但最后创建 Trip 仍然走 `POST /api/v1/trips`，保证进入系统的是结构化数据。

### 19.3 后端类问题

#### Q1：`create_app()` 做了什么？

参考答案：

`apps/api/src/travelmind_api/main.py` 的 `create_app()` 负责组装 FastAPI 应用：配置 CORS、挂载 `/exports/files` 和图片静态文件、注册 `/api/v1` 路由、提供 `/health`，并统一处理 validation error、HTTPException 和未捕获异常，把它们都包装成 `{ data, error, meta }` envelope。

`lifespan` 里还会配置日志、记录启动事件并调用 `init_db()`。这说明后端入口不仅是 route 注册，也承担本地 MVP 的初始化职责。

#### Q2：route、service、schema、model 怎么分工？

参考答案：

route 负责接 HTTP 请求、依赖注入和返回 envelope；service 负责业务规则；schema 负责 API 输入输出合同；model 负责数据库表结构。

例如 Trip 创建：`trips.py` 接收 `TripCreateRequest`，调用 `trip_service.create_trip()`；service 里做日期校验、origin/destination 规范化、interest 去重、自动 title；`Trip` model 才是数据库表。这样 route 不会膨胀，业务逻辑也更容易测。

#### Q3：认证流程为什么用 HttpOnly cookie + refresh session？

参考答案：

登录和注册后，后端签发 access token 和 refresh token，并通过 HttpOnly cookie 写给浏览器。access token 是短期 JWT，refresh token 会 hash 后存入 `RefreshSession` 表。前端请求时自动带 cookie，不需要把 token 存到 localStorage。

刷新时，`POST /api/v1/auth/refresh` 校验 refresh session 后只重发 access cookie。退出时，`logout` 会撤销 refresh session 并清 cookie，即使 refresh token 缺失也会尽量清理本地状态，所以更接近幂等操作。

对应文件：

- `api/routes/auth.py`
- `core/deps.py`
- `core/security.py`
- `services/auth_service.py`

#### Q4：settings API 为什么现在不只是 LLM settings？

参考答案：

接口路径仍叫 `/settings/llm`，但响应实际是 runtime settings，包含三组配置：agent、search、image。这样一个 Settings 页面可以统一管理文本模型、搜索 grounding 服务和图片生成模型，同时每组配置都有自己的 `configured`、masked key 和 provider 字段。

后端 `serialize_runtime_settings()` 会返回 `api_key_masked` 和 `has_api_key`，不会返回完整 key。前端 `llmSettings.ts` 再把它规范化成 `runtimeConfig`、`imageRuntimeConfig`、`isConfigured` 等页面可直接消费的状态。

#### Q5：admin 模块怎么体现安全和治理？

参考答案：

admin 路由通过 `require_admin_user` 限制，管理员名单来自 `TRAVELMIND_ADMIN_EMAILS`。功能包括用户列表/详情、禁用/启用用户、Trip 管理、社区帖子管理、Job 查看。禁用用户时会设置 `disabled_at` 和 `disabled_reason`，同时删除 refresh session，让已登录会话失效。

删除或禁用这类敏感动作会写入 `AdminAuditLog`，保留 admin、action、target、reason 和 details。admin detail 也只显示 `has_llm_api_key`、`has_search_api_key`、`has_image_api_key`，不泄露完整密钥。

对应文件：

- `api/routes/admin.py`
- `services/admin_service.py`
- `db/models.py`
- `apps/web/src/views/AdminView.vue`

#### Q6：为什么不应该把数据库对象直接返回给前端？

参考答案：

数据库对象可能包含不该暴露的字段，例如 `User.password_hash`、`llm_api_key`、`search_service_api_key`、`image_api_key`、`JobRecord.payload_json` 等。项目里通过 Pydantic schema 和 serializer 控制返回内容，例如 `serialize_user()`、`serialize_runtime_settings()`、`serialize_job()`。

这也是为什么 schema 和 model 要分开：model 是内部持久化结构，schema 是对外合同。

### 19.4 异步任务和 Job 类问题

#### Q1：Job 生命周期怎么走？

参考答案：

后端 job 由 `create_job()` 创建，初始状态是 `queued`，同时写入第一条 timeline。`dispatch_job()` 根据 `TRAVELMIND_QUEUE_MODE` 选择 inline 后台任务或 ARQ 入队。执行时 `process_job()` 先 `_claim_job()`，只有把状态从 `queued` 原子更新成 `running` 的执行者才能继续，防止重复执行。

执行中通过 `_transition_job()` 更新 `stage`、`stage_message`、`progress_percent` 和 timeline；成功后 `_mark_complete()`，失败后 `_mark_failed()`。前端通过 `/jobs/{id}` 轮询，或者 `/jobs/{id}/stream` SSE 获取同一套 `serialize_job()` 结构。

#### Q2：Redis 或 ARQ 入队失败怎么办？

参考答案：

项目里不是让 job 永远停在 `queued`。`dispatch_job()` 在 ARQ 模式下如果入队失败，会调用 `_mark_dispatch_failed()`，把 job 标记为 `failed`，写入 `error_message` 和终态时间。这样前端 job detail 和 SSE 都能收到失败状态。

这个 bug 很适合面试讲：现象是用户一直看到处理中；原因是入队失败后没有终态；修复是 dispatch 失败立即收敛为 failed；验证可以看 `test_api_contracts.py` 和 job detail/SSE 的结构测试。

#### Q3：为什么需要 `stage`、`progress_percent` 和 `timeline_json`？

参考答案：

`status` 只说明任务有没有结束，不能说明任务正在做什么。AI 规划、补图、导出都可能慢，如果只显示 running，用户体验会很差。`stage` 说明阶段，比如 `brief_parsing`、`source_search`、`route_planning`、`export_ready`；`progress_percent` 给等待感；`timeline_json` 让前端和调试者看到每次状态变更。

前端 `TripDetailView.vue` 用这些字段展示 progress track、metric card 和 timeline。

#### Q4：为什么 generate 后还会创建 followup image enrichment job？

参考答案：

生成 itinerary 后，系统会先把行程保存下来，然后创建 `trip.image_enrich` followup job。这样主行程不需要等所有图片都补完才给用户看，图片补全可以异步进行。`handlers.py` 里 `_process_trip_generation()` 和 `_process_trip_refine()` 都会调用 `prepare_plan_images_for_async_enrichment()`，并创建后续补图任务。

这体现了一个产品取舍：核心文本结果优先可用，图片增强作为渐进增强。

#### Q5：导出为什么也做成 job？

参考答案：

导出会读取 itinerary、调用 orchestrator 生成导出草稿、用 ReportLab 写 PDF、同时可能生成 Markdown 和 JSON，并把文件放到 `storage/exports` 下通过 `/exports/files` 访问。这个过程可能耗时，也涉及文件 IO，所以用 `export.pdf` job 更稳妥。

对应文件是 `api/routes/exports.py`、`jobs/handlers.py` 的 `_process_pdf_export()`、`services/export_service.py`。

### 19.5 AI、搜索和图片类问题

#### Q1：LLM 输出不稳定，项目里怎么处理？

参考答案：

当前项目有多层防御。后端 `OpenAICompatibleClient` 支持 OpenAI Responses、Chat Completions、Gemini、Claude、NewAPI、NeiAPI 风格，并处理 SSE、非 JSON、空文本、Responses fallback 到 Chat Completions、stream EOF retry 等情况。浏览器侧 `browserPlanner.ts` 会要求模型只返回 JSON，并在 `parsePayload()` 里去掉 code fence、截取最外层 JSON object，再校验 summary 和 days。

如果是后端 orchestrator 路径，测试里还覆盖了 parse error fallback 到 stub 的场景。面试时可以总结成：LLM 不是可靠函数，所以系统用 prompt 约束、解析校验、协议兼容和 fallback 来兜底。

#### Q2：`/api/v1/llm/proxy` 的价值是什么？

参考答案：

它让前端可以测试和使用不同模型协议，但不需要保存或暴露完整 API key。前端传 provider protocol、wire api 和上游 payload；后端从当前用户 settings 或显式 payload 中解析配置，再把请求发给上游。

它同时支持 streaming response 透传、非流式响应、模型列表、连接测试、搜索服务调试和图片搜索调试。面试时要注意说清楚：proxy 是后端 relay，不是绕过后端把密钥放到浏览器。

#### Q3：Search grounding 当前有哪些来源？

参考答案：

`search_service.py` 组合了四类来源：

- 内置官方 seed，例如 Kyoto、Tokyo、Fushimi Inari。
- 用户配置的远程搜索服务，目前支持 GrokSearch MCP 和 Tavily API。
- 小红书来源，前提是用户开启 `xhs_source_enabled` 且绑定 session 可用。
- 手动链接，用户可以把官方或参考页面贴进来。

结果都会规范成 `SearchDocumentResponse`，带 `title`、`url`、`summary`、`place_name`、`category`、`image_urls`、`source_type` 和 `ScoreBreakdown`。排序会按平台优先级、final score 和 title 去重。

#### Q4：为什么 GrokSearch 只能 MCP，Tavily 只能 API？

参考答案：

这是当前 connector 的能力边界。`SearchServiceConfig.from_mapping()` 明确限制：`groksearch` 只接受 `mcp` transport，`tavily` 只接受 `api` transport。Settings 页面也会在选择 provider 时自动锁定 transport，避免保存不支持的组合。

这个设计的好处是把错误前移：用户在 settings 保存阶段就会被提示，而不是等到搜索或生成时才失败。

#### Q5：小红书绑定和搜索怎么讲？

参考答案：

小红书不是公共搜索接口，而是通过用户自己的 session 做社交内容补充。`account` 路由负责绑定状态和解绑，`xhs_account` 负责读取 session 状态，`search_service` 在 `xhs_source_enabled` 打开时尝试调用 crawler。若 session 缺失或过期，搜索会回退到非小红书来源，不让主链路失败。

面试时可以强调：社交来源是增强项，不是主链路硬依赖。

#### Q6：图片能力分成哪两块？

参考答案：

一块是 itinerary item 图片补全：生成行程后创建 `trip.image_enrich` job，后端基于 Tavily/image search 给景点补图，并把 `image_urls`、`image_status` 等字段写回 itinerary。

另一块是 AI Image Studio：用户保存 image model settings 后，可以创建 `ImageGeneration`，上传源图或参考图，生成图片 job，结果保存在 `storage/images` 并可以公开到 feed。对应类型在 `packages/shared-types/src/index.ts`，后端表在 `ImageGeneration` model。

### 19.6 测试和工程化类问题

#### Q1：这个项目有哪些测试能证明你不是只会跑页面？

参考答案：

后端测试覆盖面比较广：认证、Trip CRUD、generate/refine/export flow、job detail/SSE、settings mask、LLM proxy、orchestrator fallback、search connector、search service、小红书 crawler、图片生成、图片补全、社区、admin 等。可以从 `apps/api/tests` 里选 3-5 个最贴项目亮点的测试讲。

推荐面试前至少会跑：

```powershell
uv run --project apps/api pytest apps/api/tests
npm run build:web
```

CI 里也跑 web build、API pytest、worker import smoke test、Dockerfile build 和 compose config。对应 `.github/workflows/ci.yml`。

#### Q2：最重要的环境变量有哪些？

参考答案：

可以按模块记：

- 启动和 API：`TRAVELMIND_DATABASE_URL`、`TRAVELMIND_CORS_ORIGINS`、`TRAVELMIND_PUBLIC_API_URL`
- 认证和权限：`TRAVELMIND_JWT_SECRET`、`TRAVELMIND_ADMIN_EMAILS`
- 任务：`TRAVELMIND_QUEUE_MODE`、`TRAVELMIND_REDIS_URL`
- Agent：`TRAVELMIND_AGENT_PROVIDER`、`TRAVELMIND_LLM_BASE_URL`、`TRAVELMIND_LLM_API_KEY`、`TRAVELMIND_LLM_MODEL`
- 搜索：`TRAVELMIND_SEARCH_SERVICE_PROVIDER`、`TRAVELMIND_GROKSEARCH_BRIDGE_BASE_URL`、`TRAVELMIND_GROKSEARCH_BRIDGE_API_KEY`、`TRAVELMIND_TAVILY_API_KEY`
- 文件：`TRAVELMIND_EXPORT_ROOT`、`TRAVELMIND_IMAGE_ROOT`、`TRAVELMIND_LOG_ROOT`

前端最关键的是 `VITE_API_BASE_URL`。

#### Q3：Docker / Compose 当前怎么定位？

参考答案：

Compose 当前用于跑 MVP stack：web、api、worker、redis，共享 storage volume。默认仍然可以用 SQLite，Redis 支撑 ARQ worker。Postgres profile 是生产方向占位，但 README 里明确说当前 Python dependencies 还没有 PostgreSQL driver，所以不能把它吹成已经完整生产化。

这类边界要主动讲清楚：Docker 基线已经有，但数据库 migration、secret 加密、Postgres driver、监控告警还属于后续生产化工作。

### 19.7 面试追问时可以直接用的短答案

#### Q1：你最能体现排错能力的 bug 是哪个？

参考答案：

可以讲 ARQ 入队失败。现象是 job 一直 queued，用户看不到明确失败；原因是 Redis 不可用时没有把任务收敛到终态；修复是在 `dispatch_job()` 捕获异常后调用 `_mark_dispatch_failed()`，写入 `failed` 和 `error_message`；验证是 job detail 和 SSE 都能返回同一套失败结构。

#### Q2：如果面试官问“你是不是把 key 暴露在前端了”怎么答？

参考答案：

不是。前端 Settings 只显示 masked key，保存后也会清空输入框。标准 generate/refine 虽然由浏览器组织 prompt，但模型请求通过后端 `/api/v1/llm/proxy` 转发，后端从当前用户 settings 取 key。真正需要改进的是数据库里的 key 生产环境应加密存储。

#### Q3：如果面试官问“为什么不用全部后端生成”怎么答？

参考答案：

当前是 MVP 取舍。标准模型路径放在浏览器侧组织，能让工作台交互更直接，方便调试 prompt、grounding docs 和 parser；涉及多 agent、工具调用、文件 IO 或长任务的部分仍放后端 job。后续如果要统一审计、重试、成本统计和模型观测，可以把标准 generate/refine 也迁回后端 orchestrator。

#### Q4：如果面试官问“你最想优先优化什么”怎么答？

参考答案：

我会优先做三件事：第一，引入 Alembic，替换当前 SQLite 补列逻辑；第二，把用户 API key 做加密存储或接 Secret Manager；第三，统一标准 generate/refine 和后端 job 的观测口径，让成本、trace、失败重试和限流更可控。

#### Q5：一句话怎么介绍这个项目？

参考答案：

这是一个 AI 旅行规划 MVP，核心价值是把 Trip brief、模型配置、搜索 grounding、生成/微调、异步补图、PDF 导出、社区分享和 admin 治理串成一个可运行、可观察、可测试的全栈闭环；我重点能讲清楚前端工作台、后端 API/service 分层、job 状态机、密钥保护和 AI 可靠性兜底。
