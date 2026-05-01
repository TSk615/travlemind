# TravelMind AI 项目阶段总结（面试版）

> 文档用途：用于面试、项目复盘、阶段汇报与个人经验沉淀。  
> 更新时间：2026-03-21  
> 项目目录：`E:\travel`

---

## 1. 项目背景与目标

TravelMind AI 是一个面向旅行规划场景的 MVP 项目，目标是围绕“**创建旅行 -> AI 生成行程 -> 搜索补充信息 -> 导出 PDF**”打通一个最小可运行闭环。

当前仓库采用 monorepo 组织方式，实际落地的技术栈包括：

- **前端**：Vue 3 + Vite
- **后端 API**：FastAPI
- **异步任务**：ARQ + Redis
- **数据层**：SQLite（本地）/ PostgreSQL（目标生产）
- **对象导出**：本地文件导出（后续可接 S3）
- **AI 适配层**：`HelloAgentsOrchestrator`（PoC）+ `StubOrchestrator`

我的工作主要集中在三个方向：

1. **DevOps / 启动与交付基线建设**
2. **搜索结果结构化增强**
3. **用户可配置 LLM（base_url / api_key / model）能力建设**

---

## 2. 截至目前为止完成的工作

---

### 2.1 DevOps、启动和交付基线建设

这是第一阶段的工作，目标是把仓库从“有代码但启动与交付链路不稳定”的状态，推进到“本地可跑、容器可构建、CI 可校验”的状态。

#### 2.1.1 修正 Dockerfile

我对三个服务的 Dockerfile 都进行了整理和修正：

##### （1）Web Dockerfile

优化点：

- 改为更合理的 **分阶段构建**
- 先安装依赖，再复制源码，减少重复安装
- 显式复制 workspace 依赖所需的 `package.json`
- 增加 `VITE_API_BASE_URL` 构建参数，便于不同环境配置 API 地址
- 最终使用 Nginx 托管静态资源
- 增加 SPA 路由 fallback，避免用户直接刷新 `/trips/...` 等路径时出现 404

##### （2）API Dockerfile

优化点：

- 改为 build/runtime 双阶段结构
- 使用 `uv sync --frozen` 保证依赖安装更稳定
- 明确运行时 `PATH`
- 补充 `/app/storage/exports` 目录准备
- 运行方式统一为 `uvicorn travelmind_api.main:app`

##### （3）Worker Dockerfile

优化点：

- 解决 worker 运行依赖 API 源码的问题
- 同时复制 `apps/api` 和 `apps/worker`
- 显式设置 `PYTHONPATH=/app/apps/worker/src:/app/apps/api/src`
- 保证 worker 可以正常 import API 中的共享逻辑与配置

#### 2.1.2 完善 Docker Compose

我重写了 `docker-compose.yml`，让容器化运行更加接近真实 MVP 链路。

当前 compose 能力包括：

- `web`
- `api`
- `worker`
- `redis`
- `postgres`（profile 形式保留，作为后续部署占位）

主要改进：

- API / worker 默认共享同一个 `storage` volume
- 默认走 SQLite + Redis 的 MVP 组合，方便本地快速闭环
- web 构建时注入 `VITE_API_BASE_URL`
- API / worker 默认在 compose 中强制使用 `arq` 模式，避免 compose 环境被本地 `.env` 的 inline 配置覆盖
- 把 `postgres` 作为可选 profile，而不是强依赖

#### 2.1.3 补充环境模板

新增并完善了：

- `infra/.env.example`

内容包括：

- Web / API / Redis / Postgres 端口
- 本地默认数据库地址
- 导出目录
- JWT secret
- 队列模式
- Redis URL
- agent provider
- 前端构建时的 API base URL
- CORS origins

这使得：

- 本地直跑更清晰
- Docker Compose 更容易直接起
- CI/部署环境变量更容易对齐

#### 2.1.4 修正 CI 工作流

我调整了 `.github/workflows/ci.yml`，使其真正匹配当前 monorepo 结构，而不是停留在理想化脚本层面。

新增/修正内容：

- **web job**：安装依赖并执行前端构建
- **api job**：安装 Python 3.11、`uv`，执行 API 测试
- **worker job**：执行 worker 的依赖同步与导入冒烟测试
- **docker job**：验证三个 Dockerfile 能否构建，并执行 compose config 校验

这一步非常重要，因为它把“代码能写出来”变成了“代码能被持续验证”。

#### 2.1.5 完善 README

我补充了 README 中最关键的工程说明：

- 本地开发启动步骤
- web / api / worker 分别如何运行
- Docker / compose 使用方法
- `helloagents` 仅为 PoC 的许可说明
- 生产方向与本地运行方式的差异说明

这提升了新成员接手效率，也让项目对外展示时更完整。

---

### 2.2 搜索结构化增强

第二阶段的工作重点是：把原本偏“文本化”的搜索结果，升级成既能直接给前端展示、又能给 planner 复用的 **结构化 SearchDocument**。

#### 2.2.1 扩展 SearchDocument 结构

在不破坏原有评分字段的前提下，我为搜索结果新增了以下字段：

- `place_name`
- `category`
- `opening_hours`
- `price_hint`
- `address`
- `geo`
- `source_type`

同时保留旧字段：

- `id`
- `platform`
- `title`
- `url`
- `summary`
- `destination`
- `scores`

其中 `geo` 采用独立结构：

```ts
{
  lat: number,
  lng: number
}
```

这样做的意义是：

- 前端可以直接展示地点卡片
- planner 后续可以基于地址、类别、价格提示进一步重排或推荐
- 搜索层从“文本源列表”向“可消费的规范化文档”迈进

#### 2.2.2 丰富 seed 数据

我把官方旅游 seed 数据从简单页面链接，增强为更像“结构化目的地知识源”的文档。

例如新增了：

- 京都官方旅行指南
- JNTO Kyoto 页面
- Fushimi Inari 官方信息
- 东京官方旅游页面
- Senso-ji 官方信息

每条 seed 数据都尽量补充：

- 地点名
- 类别（如 shrine / temple / destination-guide）
- 开放时间提示
- 价格提示
- 地址
- 经纬度
- 来源类型

#### 2.2.3 强化 manual links 归一化逻辑

manual link 仍然保持轻量，但我做了更完整的标准化：

- 去空白
- URL 基本合法性校验（仅允许 `http` / `https`）
- 去重
- 对尾部 `/` 的重复 URL 进行归一
- 从路径或 host 中尽量猜出 `place_name`
- 自动补齐：
  - `category=external-reference`
  - `opening_hours=Check source page`
  - `price_hint=See source page`
  - `address=host`
  - `source_type=manual-link`

这样 manual source 虽然不是强结构化来源，但也能以统一格式进入前端和 planner。

#### 2.2.4 提升查询匹配逻辑

原来搜索主要基于：

- title
- summary

现在我扩展为支持在以下字段中检索：

- `title`
- `summary`
- `place_name`
- `category`
- `opening_hours`
- `price_hint`
- `address`

这意味着某些以前搜不到的内容（例如地址片段、类别词）现在也能命中。

#### 2.2.5 保持向后兼容

这一点是我刻意控制的：

- 没有删除任何旧字段
- 没有改动原有 `scores` 结构
- 老前端如果只读旧字段，不会报错
- 新前端/后续 planner 可以直接使用新增字段

也就是说，这次结构化增强是一次**增量升级**，不是破坏式重构。

---

### 2.3 用户可配置 LLM（base_url / api_key / model）能力建设

第三阶段工作是为后端补齐用户级 AI 配置能力，这也是后续真正接入不同模型网关和私有部署的基础。

#### 2.3.1 存储方案设计

我最终选择了 **直接加到 `users` 表** 的方案，而不是新建 `user_settings` 表。

新增字段：

- `llm_base_url`
- `llm_api_key`
- `llm_model`

这样设计的原因：

1. 当前需求很明确，字段只有 3 个
2. 用户设置还比较少，不需要为了“扩展性幻想”引入额外表
3. `get_current_user` 获取用户对象后，settings API 和 trip job 直接可读
4. 代码更简单，SQLite 本地更容易跑

#### 2.3.2 SQLite 兼容逻辑

为了兼容已经存在的本地 SQLite 数据库，我补了轻量 schema 兼容逻辑：

- 如果 `users` 表存在但新列不存在
- 就在启动时自动执行 `ALTER TABLE` 补列

这样可以避免：

- 老数据库直接启动时报 “no such column”
- 开发过程中必须引入复杂迁移工具

在 MVP 阶段，这是一种成本与收益比较均衡的方案。

#### 2.3.3 新增 settings API

我新增了以下接口：

- `GET /api/v1/settings/llm`
- `PUT /api/v1/settings/llm`

接口用途：

- 获取当前用户的 LLM 配置
- 修改当前用户的 LLM 配置

返回结构：

```json
{
  "base_url": "https://api.example.com/v1",
  "api_key_masked": "sk-t***************1234",
  "has_api_key": true,
  "model": "gpt-5.4-mini"
}
```

#### 2.3.4 api_key 保护策略

我没有在 GET/PUT 响应里返回完整明文 `api_key`，而是采用：

- `api_key_masked`
- `has_api_key`

例如：

- 原始 key：`sk-travelmind-secret-1234`
- 返回值：`sk-t***************1234`

这样前端可以知道：

- 用户是否配置过 key
- 当前 key 大概是哪一把

但不会直接看到完整密钥。

> 说明：当前阶段数据库内仍是明文存储，只是 API 响应不回传明文。后续如果进入更高安全等级阶段，应进一步做加密存储或接 KMS/Secret Manager。

#### 2.3.5 为 trip.generate / trip.refine 预埋读取能力

为了给后续真实 AI 执行链路做准备，我在生成/细化任务入队时，把用户当前的 LLM 配置快照写入了 job payload：

- `trip.generate`
- `trip.refine`

这样后续 jobs/agents 层如果需要使用用户指定的：

- `base_url`
- `api_key`
- `model`

已经具备读取条件。

同时，因为现有 `/api/v1/jobs/:id` 并不会把 payload 原样暴露给前端，所以不会把 key 直接泄漏到 job 查询接口。

---

## 3. 遇到的核心难点

这部分是面试里很值得展开的内容，因为它体现的是工程判断力，而不是只会写功能。

---

### 3.1 产品文档目标与当前代码现实并不完全一致

项目文档中期望的 Web 技术栈是：

- Next.js + TypeScript + App Router

但当前仓库里实际已经存在的是：

- Vue 3 + Vite

这意味着我在做 DevOps 和交付基线时，不能机械照着需求文档写，而必须先尊重**代码现实**。

我做出的判断是：

- 不强行重构前端栈
- 优先保证当前仓库“能跑、能构建、能交付”
- 在 README 中明确说明“文档目标栈”和“当前实际实现”的差异

这是一个很典型的工程场景：**需求文档 != 当前代码现状**，需要先让系统稳定，再谈大规模迁移。

---

### 3.2 Monorepo 下多服务之间的依赖边界问题

典型问题出现在 worker：

- worker 本身代码量不大
- 但它运行时依赖 API 里的配置、数据库、job handler 等逻辑

如果 Dockerfile 只复制 worker 自己，就会在容器里 import 失败。

解决方式：

- worker 镜像中同时复制 `apps/api` 和 `apps/worker`
- 显式设置 `PYTHONPATH`
- 在 CI 中增加 worker import smoke test

这实际上暴露了 monorepo 常见问题：

- 代码边界上是“模块化”
- 运行边界上却未必是真隔离

所以在早期阶段，需要先通过清晰的运行约束把边界跑稳。

---

### 3.3 环境权限与工具链问题比业务逻辑更容易卡人

在实际落地过程中，遇到过多个并不是“业务代码 bug”，而是“环境问题”的障碍：

#### （1）`apply_patch` 在当前 Windows sandbox 环境下失败

表现：

- 补丁工具无法稳定写文件

处理方式：

- 改为受控范围内直接覆盖文件内容
- 保证修改仍然在允许目录内完成

#### （2）Docker 默认读取用户目录配置报权限错误

表现：

- `docker compose config` 报 `C:\Users\...\.docker\config.json: Access is denied`

处理方式：

- 把 `DOCKER_CONFIG` 临时指向工作区内目录
- 在本地验证时绕开用户目录权限问题

#### （3）uv 默认 cache 目录在当前环境不可用

表现：

- `uv sync` 初始化 cache 失败

处理方式：

- 将 `UV_CACHE_DIR` 改到工作区本地目录

#### （4）pytest 在当前环境的默认临时目录 / cache 目录不可写

表现：

- 测试收集或 fixture 初始化报权限错误

处理方式：

- 把测试临时目录改到 `storage/.pytest_tmp`
- 使用可控的 cache 目录
- 预创建 fixture 所需目录，避免运行时 mkdir 失败

这些问题很适合在面试里强调：

> “真正做项目时，很多卡点不是算法，而是环境、权限、缓存路径、运行边界和工具链行为。”

---

### 3.4 SQLite 的 schema 演进要兼顾简单和兼容

项目当前本地默认数据库是 SQLite。SQLite 的优势是快、简单，但缺点是：

- schema 迁移不如成熟数据库规范
- 开发中很容易出现“旧库还在、新字段没加”的问题

在这个项目里，我没有直接引入完整 migration 体系，而是采用了更轻量的方式：

- 先保持 schema 简单
- 在模型层加一个 SQLite 兼容补列逻辑
- 让旧本地数据库也能平滑运行

这个方案的好处是：

- 对 MVP 阶段开发效率友好
- 避免为了 3 个字段引入过重治理成本

但我也清楚它的边界：

- 规模更大后，还是应该切到正式 migration 流程

这类“阶段性工程取舍”是很典型的面试加分点。

---

### 3.5 Secret 保护和可用性之间的平衡

当用户可以配置 `api_key` 时，一个自然问题是：

- 后端执行任务需要这把 key
- 但 API 又不能把它明文泄露给前端

我做的平衡是：

- 数据库存原值（当前阶段）
- API 返回时只给 masked 值
- job 查询接口不暴露 payload
- generate / refine 在入队时带上当前配置快照，为后续执行层准备好输入

这其实体现的是一个很现实的设计取舍：

- 当前优先保证功能闭环与接口合理性
- 安全层面先做到“**不回显、不透出**”
- 更高阶的密文存储和密钥管理，留给下一阶段

---

## 4. 已出现的 bug / 问题，以及我的修复方式

下面这部分适合直接用于面试里的“你排查过哪些 bug”。

---

### Bug 1：Web 容器在深链接刷新时出现 404

#### 现象

用户直接访问或刷新 SPA 子路由，例如：

- `/trips`
- `/trips/123`
- `/exports/123`

Nginx 会尝试查找真实文件，导致 404。

#### 原因

前端是 SPA，路由由浏览器端接管，但 Nginx 默认按静态文件路径解析。

#### 修复

增加 Nginx fallback 配置：

```nginx
try_files $uri $uri/ /index.html;
```

#### 结果

- 深链接刷新恢复正常
- 路由可直接访问
- 容器部署后的可用性提升明显

---

### Bug 2：Worker 容器内 import 失败

#### 现象

worker 在容器内启动时无法正常 import API 相关模块。

#### 原因

worker 运行依赖 API 源码，但 Dockerfile 只复制了 worker 自身代码。

#### 修复

- 容器内同时复制 `apps/api` 和 `apps/worker`
- 设置：

```bash
PYTHONPATH=/app/apps/worker/src:/app/apps/api/src
```

#### 结果

- worker 启动成功
- API/worker 间共享逻辑可以在容器环境下稳定复用

---

### Bug 3：Compose 环境被 `.env.example` 中的 inline 模式误覆盖

#### 现象

Compose 预期应该跑 `arq`，但容器内 API/worker 可能仍走 inline。

#### 原因

环境变量优先级与 compose 注入逻辑叠加，导致“本地直跑默认值”覆盖了“容器场景默认值”。

#### 修复

在 `docker-compose.yml` 中对容器场景直接写死：

- `TRAVELMIND_QUEUE_MODE=arq`
- `TRAVELMIND_REDIS_URL=redis://redis:6379/0`
- `TRAVELMIND_DATABASE_URL=sqlite:////app/storage/travelmind.db`

#### 结果

- compose 环境与本地直跑环境职责分离
- 容器里真正走异步队列模式

---

### Bug 4：搜索结果结构不够丰富，前端展示和 planner 复用价值不足

#### 现象

原始 SearchDocument 只有：

- title
- url
- summary
- destination
- scores

这对于页面做真正“地点卡片展示”不够，对 planner 做结构化消费也不够。

#### 原因

搜索层一开始更像“文档列表”，而不是“规范化地点来源”。

#### 修复

扩展字段：

- `place_name`
- `category`
- `opening_hours`
- `price_hint`
- `address`
- `geo`
- `source_type`

并增强 seed/manual link 数据生成逻辑。

#### 结果

- 前端可直接展示更多结构化信息
- planner 后续有更好的复用基础
- 仍保持向后兼容

---

### Bug 5：manual links 去重不彻底

#### 现象

以下链接会被视为不同来源：

- `https://example.com/custom-guide`
- `https://example.com/custom-guide/`

#### 原因

去重只做了简单大小写对比，没有处理路径尾部 `/` 等等价形式。

#### 修复

构建了规范化 dedupe key：

- 统一 scheme / host 小写
- 处理 path 默认值
- 去掉不必要尾部 `/`
- 组合 query 形成稳定 key

#### 结果

manual links 去重更准确，避免前端结果重复、评分重复。

---

### Bug 6：无效 URL 混入 manual links

#### 现象

`not-a-url`、`ftp://...`、空字符串等内容可能进入搜索结果。

#### 原因

输入没有做足够的 URL 合法性筛选。

#### 修复

增加校验：

- 去空
- 仅允许 `http` / `https`
- 必须存在 `netloc`

#### 结果

manual source 更干净、更稳定。

---

### Bug 7：搜索查询无法命中新结构化字段

#### 现象

像地址、类别、开放时间等新字段加入后，如果查询仍只匹配 title/summary，会导致新增结构失去一部分价值。

#### 修复

将查询匹配范围扩展到：

- `title`
- `summary`
- `place_name`
- `category`
- `opening_hours`
- `price_hint`
- `address`

#### 结果

结构化字段不仅能展示，还真正参与检索。

---

### Bug 8：新增 LLM 字段后旧 SQLite 数据库可能报缺列错误

#### 现象

如果开发者之前已经跑过旧版本数据库，再启动新版本代码，可能出现：

- `no such column: users.llm_base_url`
- 或同类缺列问题

#### 原因

数据库是旧 schema，但代码已引用新字段。

#### 修复

在模型层加入 SQLite 补列逻辑：

- 检查 `users` 表是否存在
- 检查新列是否存在
- 缺什么就 `ALTER TABLE ADD COLUMN`

#### 结果

- 旧本地 SQLite 可以继续运行
- 降低了升级成本

---

### Bug 9：LLM 配置接口如果直接返回 api_key，会造成敏感信息泄露

#### 风险

如果 GET / PUT 直接回传完整 key，会导致：

- 浏览器前端能拿到明文 secret
- 日志、抓包或错误上报中泄露密钥

#### 修复

返回结构改为：

- `api_key_masked`
- `has_api_key`

不回显明文 `api_key`。

#### 结果

满足前端“可感知是否已配置”的需要，同时避免直接泄露密钥。

---

### Bug 10：测试环境临时目录/缓存目录权限问题导致测试失败

#### 现象

测试在当前 Windows 环境中会因为某些默认临时目录不可写而失败。

#### 修复

- 将测试临时目录改到仓库可控路径 `storage/.pytest_tmp`
- 预创建 `exports` 目录
- 调整 cache 路径到可控位置

#### 结果

- API 合同测试恢复通过
- 搜索测试、设置测试、流程测试都能稳定运行

---

### Bug 11：后端重构后遗漏 import，导致运行时报错

#### 现象

在扩展 `auth_service.py` 时，一度遗漏了：

- `datetime`
- `timedelta`
- `timezone`

等 import。

#### 修复

补回 import，并重新跑全套 API 测试。

#### 结果

- 登录/发 token 链路恢复正常
- API 合同和 flow 测试全部通过

---

## 5. 测试与验证工作

为了保证这几轮修改不是“只改代码不验证”，我做了较完整的测试验证。

### 5.1 搜索相关

已验证：

- 结构化字段存在
- manual link 去重有效
- invalid URL 被过滤
- destination 过滤逻辑正常
- 新结构化字段能参与匹配

### 5.2 LLM 设置相关

已验证：

- 可以保存 LLM 设置
- 可以读取 LLM 设置
- API 返回的是 masked key，不是明文
- `users` 表里实际保存了配置
- generate/refine 任务入队时能够带上当前用户配置快照
- `/jobs/:id` 不会把 payload 直接暴露给前端

### 5.3 主链路回归

已验证原有链路未被破坏：

- 用户注册 / 登录 / 获取当前用户 / 登出
- Trip 创建 / 查询 / 更新
- Trip generate
- Trip refine
- Search 接口
- Job detail / SSE stream
- Export PDF 主链路

---

## 6. 这个项目中我可以用于面试表达的亮点

这一部分可以直接转化成面试中的表述。

---

### 6.1 我不是只做功能，而是做“可交付工程”

可以这样说：

> 我接手时，仓库已经有一定代码，但 Docker、Compose、CI、README 和本地启动链路并不稳定。我先把工程基础打稳，让项目做到本地可跑、容器可构建、CI 可校验，再往上做业务增强。这样后续任何功能开发都有了更可靠的交付基础。

---

### 6.2 我做搜索增强时，考虑的是“前端展示 + planner 复用”的双重目标

可以这样说：

> 我没有把搜索结果只当成一个给 UI 展示的列表，而是把它设计成结构化 SearchDocument。这样前端能直接展示地点卡片，后续 AI planner 也能复用地址、价格、类别、开放时间等信息，避免搜索层和规划层之间重复清洗数据。

---

### 6.3 我做配置能力时，兼顾了功能闭环和安全边界

可以这样说：

> 我为用户加了 base_url、api_key、model 配置能力，并通过 settings API 暴露出来，但不会把 api_key 明文返回给前端，而是做 mask。同时我又为 generate/refine 任务提前准备好了读取用户配置的能力，为后续真正接模型网关打下基础。

---

### 6.4 我能处理“需求理想态”和“代码现实态”的差异

可以这样说：

> 需求文档写的是 Next.js，但仓库里真实存在的是 Vue/Vite。我没有一上来推翻现有实现，而是先尊重仓库现状，把真实代码体系跑通。这种判断在真实团队协作里非常重要，因为很多时候文档和代码不会完全同步。

---

### 6.5 我对 bug 的理解不是停留在代码语法层，而是运行链路层

可以这样说：

> 我处理过的 bug 既包括业务结构问题，也包括 Docker 构建、容器 import、Windows 权限、pytest tmp/cache、环境变量覆盖、SQLite schema 演进等问题。也就是说，我不是只会写接口，而是能把一整条运行链路排通。

---

## 7. 项目当前仍然存在的限制与后续方向

这一部分在面试中也很有价值，因为它体现你知道“现在做到哪一步，还差什么”。

### 7.1 `helloagents` 仍然只是 PoC

当前项目中：

- `helloagents` 只作为 PoC 适配器边界存在
- 不适合直接作为商业发布基线

后续方向：

- 替换为正式可控的 orchestrator/provider
- 或完成授权评估

### 7.2 LLM key 目前是“响应不回显”，但还不是“加密存储”

当前阶段做到了：

- API 不回显明文 key
- job 查询不暴露 payload

但后续更理想的方式是：

- 数据库加密存储
- 接入 secret manager / KMS
- 执行层临时解密或动态注入

### 7.3 SQLite 兼容方案适合 MVP，但不适合长期迁移治理

当前的补列逻辑适合 MVP 快速迭代。  
后续如果 schema 继续扩展，建议：

- 引入正式 migration 体系（如 Alembic）
- 做更规范的版本迁移管理

### 7.4 Compose 中保留了 Postgres profile，但生产化还需要补依赖

目前：

- compose 中已经给出了 Postgres profile 占位
- 但完整切到 Postgres 还需要补充对应驱动和生产配置

---

## 8. 一段适合面试时口头表达的总结

如果让我用一段比较自然的话总结这段工作，我会这样说：

> 我在这个 TravelMind AI 项目里，先做了工程基线建设，把 API、worker、web 的 Docker、Compose、CI 和本地启动链路整理稳定；然后对搜索层做了结构化增强，把搜索结果从简单文本链接升级成可直接展示、可被 planner 复用的 SearchDocument；最后又补了用户级的 LLM 配置能力，包括 base_url、api_key、model 的存储、settings API、api_key mask，以及为 generate/refine 任务预埋读取配置的能力。这个过程中我解决了不少真实工程问题，比如容器 import、环境变量覆盖、SQLite schema 兼容、测试目录权限、敏感信息保护等。所以这段工作不仅是做功能，更像是在把一个 MVP 项目真正推向“可运行、可验证、可演进”的状态。

---

## 9. 附：建议你在面试时重点强调的关键词

- Monorepo
- MVP 闭环
- Docker / Compose
- CI 基线
- SQLite 兼容
- 结构化搜索文档
- 向后兼容
- 用户级 LLM 配置
- API key masking
- Job payload snapshot
- 环境问题排查
- 工程化与交付能力

---

如果你希望，我还可以继续基于这份文档再帮你补两版内容：

1. **一版“面试口语版”**（更像你在现场讲述）  
2. **一版“简历项目经历版”**（压缩成 3~6 条高质量简历 bullet）
