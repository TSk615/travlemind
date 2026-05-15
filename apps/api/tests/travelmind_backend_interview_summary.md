# TravelMind AI 后端阶段性复盘（面试版）

> 更新时间：2026-03-21  
> 适用范围：TravelMind AI MVP 后端（重点是 `apps/api` 中的 API 业务层、planner、maps/POI 抽象、OpenAI-compatible LLM 接入、测试稳定性）  
> 说明：本文档聚焦我在当前开发窗口内完成和推动的工作，同时会如实记录并行开发中观察到的系统现状、技术难点和 bug 修复过程，便于面试时讲清楚“做了什么、为什么这么做、遇到了什么坑、怎么把它修好”。

---

## 1. 项目背景与目标

TravelMind AI 的目标是做一个旅行规划产品。MVP 阶段要求先跑通核心闭环：

- 用户认证
- Trip CRUD
- AI 初版 itinerary 生成
- 合规搜索骨架
- 导出 PDF
- 异步 job + SSE 状态查询

在这个基础上，后端还需要满足几个工程要求：

1. **接口契约稳定**：前端和 worker 可以围绕稳定 API 协同开发。
2. **架构留可扩展性**：首版虽然是单 FastAPI + 单 worker 进程，但要把 maps、LLM、搜索、agent orchestration 做成可替换边界。
3. **本地可运行、可测试**：尽量不依赖外部 key，不依赖真实第三方服务。
4. **对后续商业化/替换供应商友好**：例如 helloagents 只是 PoC，maps 和 LLM 都不能绑死某个 vendor。

---

## 2. 到目前为止完成的核心工作

从后端视角，已经完成的工作可以分成 5 条主线：

### 2.1 API 契约稳定化与业务层修复

我先把 API 业务层里最容易影响联调和前端使用的部分做了稳定化：

- 认证接口：
  - `POST /api/v1/auth/register`
  - `POST /api/v1/auth/login`
  - `POST /api/v1/auth/logout`
  - `GET /api/v1/me`
- Trip 接口：
  - `POST /api/v1/trips`
  - `GET /api/v1/trips`
  - `GET /api/v1/trips/{id}`
  - `PATCH /api/v1/trips/{id}`
- 搜索接口：
  - `POST /api/v1/search`
- Job 接口：
  - `GET /api/v1/jobs/{id}`
  - `GET /api/v1/jobs/{id}/stream`

做的事情包括：

- 修正路由层逻辑问题和异常返回。
- 保证 response envelope 一致：`{ data, error, meta }`。
- 补齐 API 合同测试。
- 提升 pytest 稳定性，避免本地路径权限问题、fixture 分散问题。

### 2.2 地图 / POI provider 抽象与 planner 结构化升级

在 itinerary 生成上，我把“地点”从纯文本提升成了 **结构化地点引用**：

- 新增了 vendor-neutral 的 maps/POI 抽象接口：
  - `search_pois(query, city)`
  - `get_poi_detail(id)`
  - `estimate_route(origin, destination, mode)`
  - `batch_route_matrix(stops)`
- 实现了一个本地可运行的 `StubMapsPoiProvider`
- 把 planner（准确说是 `StubOrchestrator`）接到 maps provider 上
- 让 itinerary item 既保留原来的 `location` 文本字段，也新增结构化字段：
  - `location_ref`
  - `route_from_previous`

这一步的价值非常高，因为它让 planner 输出不再只是“字符串拼装”，而是具备了后续接高德/Google/Mapbox 的数据骨架。

### 2.3 OpenAI-compatible LLM 接入

在 agent orchestration 侧，我把原本 stub-only 的 itinerary generation 路径升级成了：

- **有配置时优先走 OpenAI-compatible LLM**
- **无配置或失败时自动退回 stub**

新增了：

- LLM 配置对象
- OpenAI-compatible HTTP client
- prompt builder
- response parser
- OpenAI-compatible orchestrator

并且保持了 `PlanningResult` 结构兼容，不破坏现有前后端和 worker 主链路。

### 2.4 测试基线与回归体系建设

为了避免“写完能运行，但一回归全坏”的问题，我在 API 侧做了比较完整的测试补强：

- 认证合同测试
- Trip CRUD 测试
- Search 结构测试
- Job detail/SSE 测试
- Maps provider 与 planner 兼容测试
- OpenAI-compatible LLM 路径测试
- 现有主链路回归：`create trip -> generate -> export`

这让后续接真实 provider、真实模型时，变更风险会小很多。

### 2.5 对已有 bug 和系统不稳定点的修复

除了新增能力，我还修了几类关键 bug：

- 登出要求强鉴权导致体验不稳定
- Trip 日期和 patch 输入校验不足
- 搜索 manual links 脏数据问题
- Job timeline JSON 序列化失败
- auth token issue 里的时间引用错误
- pytest fixture 与临时目录权限问题
- LLM 测试环境污染问题

这些问题本身很典型，面试里很适合用来讲“工程稳定性”而不是只讲功能开发。

---

## 3. 已完成工作的技术细节

### 3.1 API 契约稳定化：我具体做了什么

#### 3.1.1 Auth 路由修正

早期一个明显问题是：`/auth/logout` 依赖当前 access cookie 才能执行。现实里这会导致一种很差的 UX：

- access token 过期了
- 前端调用 logout
- 结果反而报 401
- 用户无法正常退出登录

我的修复策略是把 logout 做成**幂等操作**：

- 不强依赖当前用户鉴权成功
- 只要有 refresh cookie 就尝试撤销 refresh session
- 无论有没有 refresh session，都清理 cookie 并返回成功

这类设计在面试里可以强调：**退出登录是清理状态动作，不应该因为状态已经不一致而无法执行**。

#### 3.1.2 Auth service 输入规范化

我在 `auth_service` 里补了：

- email 标准化：`lower().strip()`
- name 去空白和最小长度判断
- 登录时统一使用标准化 email 查询

这么做的目的是：

- 防止 `" user@example.com "` 这种输入导致注册/登录行为不一致
- 防止全空格字符串绕过基础长度校验
- 让唯一性检查更可靠

#### 3.1.3 Trip service 校验补全

Trip 层原本最容易出问题的是：

- `end_date < start_date` 没被拦住
- `PATCH` 时显式传 `null` 可能把字段打坏
- `interests` 会混入空字符串、重复项

我加了：

- 日期区间校验
- null update 拒绝
- 文本字段规范化
- `interests` 去空白、去重

这样可以保证 itinerary 生成输入更干净，也能减少后续 planner/导出异常。

#### 3.1.4 Search 结果稳定化

MVP 搜索目前是 seed data + manual links，所以最关键是**输出结构稳定**。

我做了：

- manual link 去空格
- 过滤非法 scheme（只收 http/https）
- 过滤无 host 的脏链接
- 去重

这个修复点很适合面试时讲：**即使是 MVP，也不能把“临时数据源”做成随便拼字符串，否则前端和排序逻辑很快会失控。**

#### 3.1.5 Jobs / SSE 稳定化

Job 查询和 SSE 我做了两类修正：

1. 统一 404 结构：`job_not_found`
2. 让 SSE 更适合真实前端使用：
   - `meta.stream = true`
   - `Cache-Control: no-cache`
   - 终态识别更明确

这让前端轮询 / SSE 处理更容易写，状态机也更明确。

---

## 4. 地图 / POI provider 抽象：为什么重要、怎么设计

### 4.1 为什么要先做抽象，而不是直接接某个地图 SDK

如果一开始就把 planner 直接写死到某个 provider（例如 Google Maps 或高德），短期看似快，长期问题会很大：

- 替换成本高
- 国内外部署策略不同
- 商业化和计费策略可能变化
- 测试无法脱离真实 key 和网络

所以我先把接口边界抽出来。

### 4.2 抽象接口长什么样

核心接口是：

- `search_pois(query, city, limit)`
- `get_poi_detail(id)`
- `estimate_route(origin, destination, mode)`
- `batch_route_matrix(stops, mode)`

配套结构体包括：

- `GeoPoint`
- `PostalAddress`
- `PoiLocation`
- `PoiSearchResult`
- `PoiDetail`
- `RouteStop`
- `RouteEstimate`
- `RouteMatrix`
- `RouteMatrixCell`

这样设计的好处是：

1. planner 不关心 vendor-specific 字段
2. provider 只负责“查地点/算路线”
3. orchestrator 只消费统一结构
4. 测试可以完全基于 stub provider

### 4.3 StubMapsPoiProvider 做了什么

为了本地可运行和测试稳定，我做了 `StubMapsPoiProvider`，它有两类数据：

#### 4.3.1 Curated seed POI

例如 Kyoto/Tokyo 的一些固定点位：

- Ginkaku-ji
- Philosopher's Path
- Nishiki Market
- Kiyomizu-dera
- Senso-ji

每个点位都带：

- 名称
- 城市
- 分类
- summary
- tags
- 经纬度
- 地址
- district
- opening_hours
- official_url
- price_level

#### 4.3.2 Generic fallback POI

如果是未知城市，比如 Osaka 或测试城市，没有 seed 数据，也不会直接失败，而是生成确定性的 fallback 结果，例如：

- `Central Landmark`
- `Market Hall`
- `Riverside Walk`

这样做的目的是：

- 本地开发不依赖真实第三方
- planner 不因为没有特定 seed 而中断
- 测试结果稳定可复现

### 4.4 Route 能力是怎么模拟的

Stub route 不是做真实导航，而是做**可预测的近似值**：

- 用坐标估算距离
- 按不同 mode 配速度（walking / transit / driving / cycling / mixed）
- 输出 distance、duration 和 polyline
- 支持 route matrix

虽然不是生产级路线引擎，但足够支撑 planner 的“结构化 itinerary”阶段。

---

## 5. Planner 升级：从纯文本 itinerary 到结构化 itinerary

### 5.1 原来的问题

stub planner 最初更像是“模板生成器”：

- 每天固定 3 个 item
- `location` 只是一个字符串
- 没有明确的地点 ID
- 没有路线依据

这样的问题在于：

- 无法做真正的后续 refine
- 无法计算路线或转场成本
- 难以接地图、导出、排序、可视化

### 5.2 我的改法

我保留了原来的兼容字段：

- `location`

同时新增结构化字段：

- `location_ref`
- `route_from_previous`

`location_ref` 包含：

- provider
- poi_id
- name
- city
- category
- summary
- address
- coordinates

`route_from_previous` 包含：

- provider
- mode
- origin/destination 名称与 poi_id
- distance_meters
- duration_minutes
- summary

### 5.3 这样做的价值

这个改动的价值在于：

1. **向前兼容**：前端仍然可以读 `location` 文本。
2. **向后扩展**：后面可以直接做地图展示、路线分析、自动 refine。
3. **对 LLM 友好**：LLM 可以负责 itinerary draft，本地再负责结构化 enrich。

这其实是一个很典型的工程做法：

> 把“生成内容”和“结构化增强”拆开，不让大模型直接控制所有底层结构。

---

## 6. OpenAI-compatible LLM 接入：设计思路与实现细节

### 6.1 为什么做 OpenAI-compatible，而不是绑官方 SDK

这是一个很明确的架构选择：

- 产品未来可能用 OpenAI，也可能用 OpenAI-compatible gateway 或私有网关
- 不想把 planner 直接绑死到某个 SDK
- 需要兼容不同 base_url 和 model 命名
- 测试时更适合 mock HTTP

所以我采用了**纯 HTTP + OpenAI-compatible 协议**。

### 6.2 LLM 配置对象

我新增了 `LlmConfig`，支持：

- `base_url`
- `api_key`
- `model`
- `timeout_seconds`

并从环境变量读取：

- `TRAVELMIND_LLM_BASE_URL`
- `TRAVELMIND_LLM_API_KEY`
- `TRAVELMIND_LLM_MODEL`
- 兼容 `OPENAI_*`

### 6.3 实际请求走哪个 endpoint

当前实现走的是：

```http
POST {base_url}/chat/completions
```

请求体为 OpenAI 风格：

```json
{
  "model": "gpt-xxx",
  "messages": [
    {"role": "system", "content": "..."},
    {"role": "user", "content": "..."}
  ],
  "temperature": 0.2
}
```

响应解析取：

- `choices[0].message.content`

如果 content 是字符串就直接用；如果是 block list，就拼出 text blocks。

### 6.4 Prompt builder 怎么设计

prompt builder 的原则是：

- 强约束输出必须是 **JSON object only**
- 明确天数必须与 trip length 相同
- 每天 item 数量控制在合理范围
- 时间格式必须是 `HH:MM`
- score 必须在 0~1 之间

这可以减少 parser 复杂度，也能降低大模型跑偏的概率。

### 6.5 Response parser 怎么设计

parser 做了两层防御：

1. **JSON 提取**
   - 支持纯 JSON
   - 支持 code fence
   - 支持从混杂文本里截取最外层 JSON
2. **Pydantic 校验**
   - 检查 summary/days/items 等结构
   - 校验时间格式
   - score 自动 clamp

这样可以把“LLM 文本不稳定”变成“可控的 parse error”。

### 6.6 为什么 LLM 只负责生成草案，而不是直接生成最终结构

我刻意让 LLM 只负责 itinerary draft，之后由本地逻辑继续做：

- POI 解析
- 点位补全
- route 估算
- location_ref / route_from_previous 注入

这么做有几个好处：

1. 更稳定，减少模型幻觉直接污染底层结构。
2. 更可测试，maps stub 可以独立验证。
3. 更易替换模型，前后端契约不会随 prompt 大幅波动。

---

## 7. 回退策略：为什么这样设计

当前 orchestrator 选择逻辑是：

1. **如果存在 LLM 配置** -> 用 OpenAI-compatible orchestrator
2. **如果没有 LLM 配置** -> 回到 stub orchestrator
3. **如果 LLM 调用失败、解析失败、返回天数不对** -> 运行时自动回退 stub

并且在 `trace.notes` 里写清楚失败原因。

这个设计的优点是：

- 本地开发零依赖
- CI 不需要真实 key
- 第三方服务故障不会直接阻断主链路
- 对前端而言输出结构不变

这类“优雅降级”在面试里很值得讲，因为它体现的是**系统可用性优先**，不是“追求功能最炫”。

---

## 8. 遇到的难点（面试重点）

下面这些是我认为最适合在面试里展开讲的难点。

### 8.1 难点一：在并行开发环境下保持接口兼容

这是一个典型的多人并行开发问题：

- 路由、service、job、tests 可能被不同窗口同时推进
- 我不能改所有目录
- 又要保证主链路不断

处理方式：

- 尽量采用**增量兼容**而不是破坏式重构
- 保留旧字段，同时新增结构化字段
- 优先用测试和 envelope 契约保护上下游
- 避免直接改 worker/job handler 等高耦合部分

这体现的是：**我不是只写功能，而是在协作边界内推进系统演进。**

### 8.2 难点二：如何让 itinerary 从文本变成结构，又不破坏前端

如果直接把 `location` 从 string 改成 object，前端和导出大概率都会炸。

所以我采取的是：

- 保留 `location: str`
- 新增 `location_ref`
- 新增 `route_from_previous`

这样老链路不需要改，新能力也能逐步接入。

这体现的是：**结构升级要做成向后兼容，而不是一次性推翻。**

### 8.3 难点三：LLM 不稳定，怎么把它变成稳定系统的一部分

大模型天然有这些问题：

- 不一定按 schema 输出
- 可能返回 markdown fence
- 可能漏字段
- 可能天数不对
- 可能临时请求失败

我没有试图“相信模型一定会听话”，而是做了三层保障：

1. prompt 强约束
2. parser + validation
3. fallback 到 stub

这是很重要的工程思路：

> 不把模型当做 deterministic function，而是把它当做可能失败的外部依赖。

### 8.4 难点四：测试在 Windows/sandbox 环境下不稳定

实际开发里，我遇到过这些问题：

- `pytest` 不在 PATH
- `uv run pytest` 因 `pyproject.toml` 编码/TOML 问题直接失败
- 默认临时目录权限问题导致 pytest fixture 失败
- 并行开发下环境变量可能污染测试结果

处理方式：

- 使用 `uv run --no-project` 跑隔离测试
- 把测试临时目录固定到仓库内可写路径
- 把 fixture 移到共享 `conftest.py`
- 在测试前清理 LLM 相关环境变量

这体现的是：**能把开发环境问题和业务问题拆开解决，而不是被工具链卡住。**

---

## 9. 出现过的 bug 与修复方式（非常适合面试展开）

下面按“现象 / 根因 / 修复 / 验证”总结。

### Bug 1：`/auth/logout` 在 access token 失效时无法正常退出

**现象**
- 用户 session 状态漂移后，logout 反而返回 401。

**根因**
- 路由把 logout 设计成了强依赖 `get_current_user` 的鉴权接口。

**修复**
- 将 logout 改成幂等清理动作：
  - 不强依赖 access token 仍然有效
  - 有 refresh cookie 就尝试撤销 refresh session
  - 无论如何都删除 cookie 并返回 success

**验证**
- 认证合同测试覆盖 register -> me -> logout -> me 401 -> login -> me。

---

### Bug 2：Trip 可以创建非法日期区间

**现象**
- 可以创建 `end_date < start_date` 的 trip。

**根因**
- schema 只检查字段类型，没有做跨字段业务校验。

**修复**
- 在 `trip_service` 里加日期区间校验。

**验证**
- 新增测试覆盖非法日期返回 `422` 和 `invalid_trip_dates`。

---

### Bug 3：Trip PATCH 显式传 `null` 可能破坏数据

**现象**
- patch 请求如果显式把某些字段设成 `null`，有可能触发数据库错误或不一致状态。

**根因**
- service 对 patch payload 做的是机械 `setattr`。

**修复**
- 增加 null update 拒绝逻辑。

**验证**
- 相关 API 合同测试和回归链路通过。

---

### Bug 4：Search manual links 会接受脏链接和重复链接

**现象**
- `manual_links` 可能混入空字符串、非法 URL、重复项。

**根因**
- 搜索层没有做最小规范化。

**修复**
- 过滤非法 scheme、无 host、空白项，并去重。

**验证**
- 增加 search service 和 API 结构测试。

---

### Bug 5：Job timeline 写库时报 JSON 序列化错误

**现象**
- 创建 job 时，`timeline_json` 中包含 `datetime`，SQLite JSON 序列化失败。

**根因**
- timeline entry 里直接保存了 Python `datetime` 对象。

**修复**
- 在 `job_service` 中将 `recorded_at` 统一转成 ISO 字符串。

**验证**
- `create trip -> generate -> export` 主链路恢复通过。

---

### Bug 6：`auth_service.issue_tokens()` 出现时间符号引用错误

**现象**
- register/login 链路因 `datetime` 符号引用问题报错。

**根因**
- 并行改动后，时间模块引用方式和文件状态不一致。

**修复**
- 改为显式模块别名 `import datetime as dt`，统一使用 `dt.datetime / dt.timedelta / dt.timezone`。

**验证**
- auth 相关合同测试、API flow 全部通过。

---

### Bug 7：pytest fixture 分散，测试间共享不稳定

**现象**
- 不同测试文件对 `client` fixture 的依赖不一致，运行方式一变就可能找不到 fixture。

**根因**
- fixture 被放在单个测试模块内，而不是共享的 `conftest.py`。

**修复**
- 把 fixture 收敛到 `tests/conftest.py`。

**验证**
- 多组测试可以统一运行。

---

### Bug 8：Windows 环境下 pytest 默认临时目录权限问题

**现象**
- 默认 tmp 路径在某些 sandbox/权限环境下会失败。

**根因**
- pytest 默认使用系统 temp，当前执行环境对该目录访问不稳定。

**修复**
- 把测试临时目录固定到仓库内可写目录。

**验证**
- 隔离环境下的测试稳定通过。

---

### Bug 9：LLM 环境变量污染导致测试不可重复

**现象**
- 如果开发机已有 `OPENAI_*` 或 `TRAVELMIND_LLM_*`，本地测试可能误走真实 LLM 路径。

**根因**
- orchestrator 工厂会优先读取环境变量。

**修复**
- 在测试 fixture 中统一清理 LLM 相关 env。

**验证**
- stub 路径测试保持 deterministic。

---

### Bug 10：LLM 返回非 JSON 或 schema 不一致

**现象**
- 大模型可能返回非 JSON、markdown、错误字段或错误天数。

**根因**
- LLM 是非确定性外部依赖，不保证稳定输出。

**修复**
- prompt builder 强约束
- parser 负责提取 JSON
- Pydantic 做结构校验
- 失败时 fallback 到 stub
- trace 写明原因

**验证**
- 专门的 LLM orchestrator 测试覆盖 parse failure fallback。

---

## 10. 测试与验证情况

我当前重点验证的测试集合包括：

- `test_api_contracts.py`
- `test_api_flow.py`
- `test_search_service.py`
- `test_maps_provider.py`
- `test_llm_orchestrator.py`

本轮验证结果：

- **18 passed**

覆盖面包括：

- register / login / me / logout
- Trip create / list / get / update
- search 结果结构
- job detail / SSE
- trip generate -> export 主链路
- maps provider search/detail/route/matrix
- planner 与 maps provider 兼容
- 有 LLM 配置时走 OpenAI-compatible client
- 无 LLM 配置时回退 stub
- LLM 解析失败时回退 stub

---

## 11. 当前系统仍存在的已知问题 / 后续改进点

这些点不是这轮的主交付，但在面试里可以主动讲，体现你对系统边界和后续工作的判断力。

### 11.1 已知问题

1. **FastAPI startup 仍使用 `on_event`**  
   现在测试会看到 deprecation warning，后续应迁移到 lifespan。

2. **JWT secret 默认值过短**  
   测试里会触发 PyJWT 的 insecure key warning，生产环境必须改成更长的 secret。

3. **`pyproject.toml` / 构建环境存在编码问题**  
   曾观察到直接 `uv run pytest` 触发 TOML decode/build 问题，因此当前测试更依赖 `uv run --no-project` 的隔离方式。

4. **OpenAI-compatible runtime 当前固定实现的是 `/chat/completions` 路径**  
   而并行开发中用户级 LLM settings 已出现 `wire_api` 等字段，这意味着后续还可以继续扩展到 `responses` API。

5. **LLM refine 仍有继续细化空间**  
   当前 generation 主路径已接 LLM；如果要把 refine 做成专用 prompt / parser / guardrails，建议继续单独实现，而不是完全复用 planning prompt。

### 11.2 建议的下一步

1. 增加用户级 LLM 配置读取优先级（user settings > env）
2. 补 `responses` API 兼容层
3. 把 refine 设计成独立 prompt / parser / merge 流程
4. 引入 provider 级缓存、超时、熔断、重试
5. 给 itinerary 增加更强的时间顺序、预算一致性校验
6. 将结构化 POI / route 明确暴露给前端地图视图

---

## 12. 面试时可以怎么讲（推荐话术）

### 12.1 30 秒版本

我在 TravelMind AI 的 MVP 后端里主要做了三件事：第一，稳定了 auth/trips/search/jobs 的 API 契约和测试；第二，设计并接入了 vendor-neutral 的 maps/POI provider，把 itinerary 从纯文本升级成带结构化地点和路线引用的结果；第三，引入了 OpenAI-compatible LLM 调用链，在有配置时走真实 LLM，无配置或失败时自动回退 stub，确保主链路稳定可用。

### 12.2 2~3 分钟版本

这个项目最大的挑战不是单点功能，而是要在一个正在并行开发的 MVP 里，一边保证接口稳定，一边给后续扩展留边界。我先从 API 契约入手，把 auth、trip、search、job 这些最影响前后端联调的地方稳定下来，并用 pytest 把主链路和合同保护起来。然后我发现 itinerary 还是纯文本，不利于后续接地图和 refine，所以我先抽象了 maps/POI provider，做了 stub provider，让 planner 既保留旧的 `location` 字段，又新增结构化 `location_ref` 和 `route_from_previous`。最后再把 LLM 接进来，但不是直接让模型输出最终结构，而是让它输出 itinerary draft，再用本地逻辑做 POI 和 route 的结构化补全。这样做的结果是系统既能在有配置时接真实 OpenAI-compatible 模型，又能在失败时自动退回 stub，不会把主链路搞挂。

### 12.3 如果面试官追问“你解决过什么实际 bug”

可以优先讲这 4 个：

1. logout 强鉴权导致用户无法退出的问题
2. trip 日期和 patch 空值导致的数据不一致问题
3. job timeline 里 datetime 导致 JSON 序列化失败的问题
4. LLM 非 JSON 输出导致 planner 不稳定的问题，以及如何通过 parser + fallback 把它工程化

---

## 13. 我认为这个阶段最能体现的工程能力

如果从面试角度总结，这一阶段最能体现的能力有：

- **API 设计与契约稳定能力**：不是只写 happy path，而是考虑前后端协作成本。
- **架构抽象能力**：maps、LLM、agent orchestration 都做成了可替换边界。
- **可靠性思维**：对 LLM、外部 provider、测试环境都采取了“可能失败”的设计假设。
- **问题定位与修复能力**：既能修业务逻辑，也能修 JSON 序列化、测试环境、权限路径这类真实工程问题。
- **兼容演进能力**：通过 additive change 升级系统，而不是靠破坏式重构去冒大风险。

---

## 14. 一句话总结（适合写在简历项目描述里）

在 TravelMind AI 的 MVP 后端中，我主导了 API 业务层稳定化、结构化 itinerary 规划能力（maps/POI provider + route enrichment）以及 OpenAI-compatible LLM 接入与降级机制建设，并通过系统化测试把“可运行的 demo”推进成“可迭代的工程骨架”。
