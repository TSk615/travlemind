# AI / Full-stack Interview Q&A Answers

> 使用建议：这份文档按面试问题来源分组，但很多问题本质相同。面试时不需要逐字背，可以先讲“项目背景 + 架构 + 关键技术 + 难点 + 结果”，追问时再展开。涉及用户量、DAU、token 成本、降本比例等真实经营数据，请替换成你自己的真实数据；如果项目是 PoC/MVP，就按 PoC/MVP 口径说清楚，反而更可信。

## 项目统一口径：TravelMind AI

我最近比较核心的 AI 项目可以用 TravelMind AI 来讲。它是一个旅行规划 AI 系统，前端是 Vue 3 + Vite，后端是 FastAPI，异步任务用 ARQ + Redis，数据库本地支持 SQLite，生产目标是 PostgreSQL。系统主要解决从用户旅行偏好输入，到搜索可信资料，再到生成结构化行程、图片内容、PDF 导出的闭环。

从架构上看，它大致分为几层：

1. 前端交互层：Vue 3 SPA，包含登录、行程创建、行程详情、AI 图片、社区、设置等页面。
2. API 接入层：FastAPI 提供认证、行程、搜索、LLM 设置、图片、导出、任务流等 REST 接口。
3. AI 编排层：内部定义 `AgentOrchestrator` 抽象，屏蔽具体模型和 Agent 实现；本地测试用 `StubOrchestrator`，PoC 用 `HelloAgentsOrchestrator`。
4. 工具与检索层：整合官方旅游源、用户手工链接、GrokSearch MCP Bridge、Tavily、小红书增强源，并对结果做可信度、质量、时效性、广告风险评分。
5. 异步任务层：长任务如行程生成、图片增强、PDF 导出通过 `job_records` 记录状态，通过 ARQ/Redis 或 inline 模式执行。
6. 数据层：用户、行程、刷新会话、任务、社区帖子、图片生成记录、管理审计日志等通过 SQLAlchemy 模型管理。
7. 部署层：Docker Compose 包含 web、api、worker、redis、groksearch-bridge，可选 postgres 和 xhs-crawler。

可以引用的项目细节：

- API 统一返回 `{ data, error, meta }`，方便前端统一处理异常和类型。
- LLM 客户端支持 OpenAI Responses、Chat Completions、Gemini、Claude、NewAPI、NeiAPI 风格接口。
- 行程生成不是一次 prompt 直接出结果，而是拆成需求解析、POI、天气、酒店、交通、最终行程规划等角色。
- 搜索结果有 `ScoreBreakdown`，包含 trust、quality、freshness、ad、final 分数。
- Job 状态有 `queued / running / completed / failed`，并保存 `stage / stage_message / progress_percent / timeline_json`，前端可通过 SSE 感知进度。

## ML 公司

### AI xx 系统主要做什么？

我会以 TravelMind AI 来介绍：它主要做 AI 旅行规划和内容生成。用户输入目的地、时间、预算、出行偏好、住宿偏好、节奏等信息后，系统会先做需求结构化，再调用搜索服务拿到官方旅游信息、远程搜索结果、用户手工链接和可选的小红书内容，然后由多角色 Agent 生成可执行的每日行程，包含景点、餐饮、交通、预算、风险提醒、天气建议、预订提醒等。后续还能做行程 refine、图片生成、PDF 导出和社区发布。

这个系统的价值不只是“生成一段文本”，而是把 AI 输出变成业务可用数据：行程按天结构化，每个 item 有时间、地点、路线、费用、注意事项、来源追踪，长任务有状态，前端能展示进度，导出时能生成稳定的 PDF。

### LangChain / LangGraph 主要用了什么 AI 技术？

LangChain 和 LangGraph 本身不是模型，而是 LLM 应用编排框架。常见会用到这些 AI 技术：

- Prompt 模板和消息编排：把 system、user、tool、history 组织成稳定上下文。
- Tool Calling / Function Calling：让模型按 schema 调用搜索、数据库、地图、业务接口。
- RAG：先检索知识库或搜索结果，再把相关证据放入上下文生成答案。
- Memory / Context 管理：控制历史消息、摘要、短期记忆和长期记忆。
- Agent Loop：模型规划、调用工具、观察结果、继续推理，直到完成任务。
- State Graph：LangGraph 的核心是把 Agent 流程显式建模成图，节点负责执行任务，边负责条件跳转，状态在节点之间流转。
- Structured Output：用 JSON Schema、Pydantic、Zod 等约束输出结构。
- Retry / Guardrail：工具失败重试、输出解析失败修复、敏感内容过滤、事实校验。

如果结合 TravelMind，类似 LangGraph 的思想体现在：先解析用户需求，再并行查 POI/天气，再查酒店/交通，最后汇总成 itinerary planner 的结构化输出。虽然项目里没有强依赖 LangGraph，但内部 `AgentOrchestrator` 抽象和角色流水线实现的是相同思路。

### 是否了解 Manus 这种通用 Agent？通用 Agent 分几层？

了解。Manus 这类通用 Agent 的核心是把用户目标拆成任务计划，并能跨工具执行，例如浏览网页、读写文件、运行代码、生成文档、调用外部 API，最后交付结果。

我理解通用 Agent 通常分为六层：

1. 交互层：接收用户目标、澄清需求、展示过程和结果。
2. 规划层：把目标拆成步骤，决定先做什么、后做什么。
3. 模型推理层：LLM 负责理解、推理、生成、反思。
4. 工具执行层：浏览器、代码执行器、数据库、文件系统、第三方 API、MCP 工具等。
5. 记忆与上下文层：短期上下文、长期记忆、任务状态、已执行步骤、失败记录。
6. 安全与治理层：权限、沙箱、成本控制、敏感操作审批、日志审计、结果校验。

### 有没有构建过 Multi-Agent？什么是多 Agent，为什么需要？

有做过类似多 Agent 的架构。TravelMind 的 HelloAgents PoC 里把一个旅行规划任务拆成多个角色：`brief_parser` 负责解析需求，`poi_specialist` 负责景点和餐饮资料，`weather_specialist` 负责天气和穿搭建议，`hotel_specialist` 负责住宿区域和酒店建议，`transport_specialist` 负责交通方案，`itinerary_planner` 负责最终行程编排。部分角色可以并行执行，最终由规划角色汇总。

多 Agent 的本质是把一个复杂任务拆给多个有明确职责、提示词、工具权限和输出 schema 的智能体协作。它主要解决这些问题：

- 复杂任务拆解：一个 Agent prompt 太长、职责太多，容易输出发散。
- 专业性隔离：不同 Agent 可以使用不同 prompt、工具、模型和温度。
- 并行提效：POI、天气、酒店、交通这类检索可以并行跑。
- 错误隔离：某个角色失败，可以降级或重试，不一定拖垮整个任务。
- 可观测性：每个 Agent 的输入、输出、耗时、失败原因可以单独记录。
- 成本优化：简单角色用便宜模型，最终汇总用强模型。

单 Agent 也可以通过 prompt 分配多个职责，但缺点是上下文很长、状态不清晰、工具权限难控、失败定位困难。多 Agent 更适合任务链长、工具多、需要并行、需要审计和可维护的场景。

### 用户量、Agent 使用量、Token 消耗和成本优化怎么讲？

如果按 TravelMind 当前仓库状态，应该诚实说它是 MVP/PoC 项目，没有真实大规模生产 DAU。可以这样回答：

> 这个项目目前主要是 MVP 和验证阶段，我不会把它包装成已经大规模商用。我们更关注链路可行性、架构可扩展性和成本模型。压测和成本估算主要围绕一次行程生成的模型调用次数、搜索调用次数、平均 token、任务耗时和失败率来做。

如果面试官要求量化，可以给可替换口径：

- 单次完整行程生成通常包含 4 到 6 个角色调用。
- 简单角色输入输出约 1k 到 3k tokens，最终 itinerary planner 可能 4k 到 10k tokens。
- 一次完整生成大概 10k 到 30k tokens，取决于天数、检索资料和输出详细程度。
- 个人开发阶段一个月 token 量可能在几十万到几百万 tokens；团队或灰度阶段按 DAU、生成次数和模型单价估算。

成本优化方案：

- 模型分层：需求解析、分类、格式修复用便宜模型；最终规划和复杂推理用强模型。
- 角色级配置：项目支持 role override，不同 Agent 可配置不同模型和 endpoint。
- 检索裁剪：只把 top N 高质量资料放进上下文，避免无意义塞满。
- 结果缓存：搜索结果、图片 prompt、部分中间结构可以按 query + destination 缓存。
- 失败重试控制：只对网络错误和可恢复解析错误重试，避免无限重试烧 token。
- 输出结构约束：用 Pydantic schema 校验，失败时只修复局部 JSON，不重跑全链路。
- 上下文压缩：历史对话和 refine 信息做摘要，只保留用户硬约束和最新变更。
- 人工确认高成本操作：图片生成、大模型长输出、批量导出前提示用户。

收益可以这样讲：AI 投入后，原来人工查资料和排行程可能需要 30 到 60 分钟，系统能在数分钟内给出初稿；人工角色从“从零写方案”变成“校对和调整方案”。如果按内部使用，效率提升可以保守说 40% 到 70%，但最终数值应以真实统计为准。

## KJ 公司

### Claude Code 的多层架构怎么理解？

Claude Code 这类 Coding Agent 可以理解为多层架构：

1. 用户意图层：理解用户要修 bug、加功能、解释代码还是跑测试。
2. 项目上下文层：读取文件、搜索引用、理解依赖、识别约束。
3. 规划层：拆任务，决定读哪些文件、改哪些模块、跑哪些验证。
4. 工具执行层：shell、文件编辑、测试、git、浏览器、MCP。
5. 代码生成层：按项目风格生成补丁。
6. 验证层：运行 lint、test、build，分析失败并迭代。
7. 安全层：沙箱、权限审批、危险命令拦截、用户变更保护。

核心不是“模型直接写代码”，而是模型和工具形成闭环：观察环境、执行动作、读取反馈、再修正。

### PS 网页版实现方案？

网页版 Photoshop 这类应用一般会用 WebAssembly + Canvas/WebGL/WebGPU + Worker 架构。核心思路：

- UI 层用 React/Vue/Svelte 管理工具栏、图层面板、属性面板。
- 渲染层用 Canvas 2D、WebGL 或 WebGPU 显示画布。
- 图像处理算法用 WASM 承载，例如滤镜、选区、变形、颜色计算。
- 大文件解析放到 Web Worker，避免阻塞主线程。
- 图层模型维护每个 layer 的 bitmap、transform、blend mode、mask。
- 操作历史用 command stack，支持 undo/redo。
- 文件导入导出通过 ArrayBuffer、Blob、File System Access API。

### Canvas 无限画布怎么实现？

无限画布不是创建一个无限大的 canvas，而是维护一个世界坐标系和视口变换：

- 画布 DOM 尺寸固定为视口大小。
- 所有图形存世界坐标，例如 `{ x, y, width, height }`。
- 通过 `scale` 和 `translate` 实现缩放平移。
- 渲染时只绘制视口内可见对象。
- 大量对象时用四叉树、R-tree 或网格索引做可见性裁剪。
- 图片或复杂节点可以分层缓存，减少每帧重绘。

示例：

```ts
type Viewport = { x: number; y: number; scale: number }

function worldToScreen(point: { x: number; y: number }, viewport: Viewport) {
  return {
    x: (point.x - viewport.x) * viewport.scale,
    y: (point.y - viewport.y) * viewport.scale
  }
}

function draw(ctx: CanvasRenderingContext2D, nodes: Node[], viewport: Viewport) {
  ctx.setTransform(viewport.scale, 0, 0, viewport.scale, -viewport.x * viewport.scale, -viewport.y * viewport.scale)
  for (const node of nodes) {
    if (!isVisible(node, viewport)) continue
    ctx.fillRect(node.x, node.y, node.width, node.height)
  }
}
```

### WebAssembly 了解吗？

了解。WASM 是一种接近原生性能的字节码格式，可以把 C/C++/Rust 等代码编译到浏览器运行。适合 CPU 密集型任务，比如图像处理、音视频编解码、加密压缩、CAD、游戏引擎、PDF 渲染等。它不能直接操作 DOM，通常通过 JS 胶水代码和 ArrayBuffer 与浏览器交互。

### Docker 和 K8s 的关系？

Docker 主要解决“如何把应用及其依赖打包成镜像并运行成容器”。K8s 解决“很多容器如何编排、调度、扩缩容、服务发现、滚动发布、故障恢复”。可以理解为 Docker 偏单机容器生命周期，K8s 偏集群级容器管理。现在 K8s 底层不一定直接用 Docker runtime，也可以用 containerd。

### 镜像、容器、挂载是什么关系？

镜像是只读模板，容器是镜像运行后的实例。容器自己的文件层是临时的，删除容器会丢失，所以持久化数据要挂载 volume 或 bind mount。

示例：

```bash
docker run -d \
  -v travelmind-storage:/app/storage \
  -p 8000:8000 \
  travelmind-api
```

TravelMind 的 Compose 里，api 和 worker 都挂载同一个 `storage-data` volume，用于 SQLite 和 PDF 导出文件共享。

### K8s 中多个服务怎么通信？

K8s 内部服务通常通过 Service DNS 通信，例如 `api.default.svc.cluster.local`。Pod 是易变的，Service 提供稳定入口和负载均衡。外部访问通过 Ingress、Gateway API 或 LoadBalancer。服务间还会配合 ConfigMap、Secret、ServiceAccount、NetworkPolicy 控制配置和权限。

### 怎么进行团队管理和推动项目进度？

我的思路是把目标拆成可验收的闭环：

- 先明确业务目标、范围、截止时间、风险。
- 拆成前端、后端、AI、数据、运维、测试等模块。
- 每个模块定义接口契约、验收标准和 owner。
- 先打通主链路，再补充边界情况和体验优化。
- 每天同步阻塞点，不把风险留到最后。
- 对 AI 项目尤其要尽早做 PoC，因为模型效果、成本和延迟都不是纯编码能保证的。

### Express 底层原理？如果自己实现怎么做？

Express 核心是 HTTP server + 中间件洋葱/队列模型 + 路由匹配。请求进来后按注册顺序执行 middleware，每个 middleware 接收 `req, res, next`，调用 `next()` 进入下一个；路由本质上是 method + path 的匹配。

简化版：

```js
const http = require("http")

function createApp() {
  const stack = []
  const app = (req, res) => {
    let index = 0
    const next = () => {
      const layer = stack[index++]
      if (!layer) return res.end("Not Found")
      if (layer.path === req.url || layer.path === "*") {
        return layer.handler(req, res, next)
      }
      next()
    }
    next()
  }
  app.use = (path, handler) => stack.push({ path, handler })
  app.listen = (...args) => http.createServer(app).listen(...args)
  return app
}
```

### 入职后如何快速上手业务？

我会按四条线并行：

- 业务线：先搞清楚用户是谁、核心流程是什么、收入或价值点在哪。
- 技术线：看架构图、启动项目、跑测试、读核心接口和数据库表。
- 人员线：找产品、后端、前端、测试、运维确认边界和协作方式。
- 交付线：先做一个低风险小需求，熟悉发布流程和代码规范。

### 职业中比较有挑战性的问题？

可以讲 AI 系统落地的挑战：AI 输出天然不稳定，业务系统又要求稳定、可追踪、可回滚。我的处理方式是把不可控的模型输出包在可控工程里：输入做结构化，输出做 schema 校验，工具调用有重试和降级，任务状态可追踪，结果保留来源和 trace，关键业务不完全依赖模型自由发挥。

## JR 公司

### AI 项目架构情况

TravelMind 的架构是 Vue3 前端 + FastAPI API + ARQ Worker + Redis 队列 + SQLAlchemy 数据层 + Docker Compose 部署。AI 部分采用内部编排抽象，不把业务直接绑死在某个框架或模型上。`AgentOrchestrator` 定义规划、资料总结、导出草稿等能力；底层可以换 stub、本地模型、OpenAI-compatible、Gemini、Claude 或 HelloAgents PoC。

### 为什么选择 LangChain / LangGraph？选型依据？

如果项目中采用 LangChain/LangGraph，我会按这个逻辑选型：

- 只是单轮问答或简单 RAG，不一定需要 LangGraph，普通服务层就够。
- 如果有多步骤、多工具、状态流转、失败恢复和人工干预，就适合 LangGraph。
- LangChain 适合快速接模型、prompt、retriever、tool、output parser。
- LangGraph 适合把 Agent 流程显式建模，支持条件分支、循环、人审节点和状态持久化。

选型看五点：团队熟悉度、框架稳定性、调试能力、是否方便替换模型、是否能和现有后端工程融合。TravelMind 目前用内部抽象而不是强绑定 LangChain，原因是 MVP 阶段希望保持轻量，模型协议和业务 schema 可控。

### 抽象通用 AI 能力模块做了什么？

通用 AI 能力可以抽象成：

- 模型配置：base_url、api_key、model、协议、超时、角色级 override。
- 统一客户端：OpenAI Responses、Chat Completions、Gemini、Claude 等协议适配。
- Prompt 管理：按角色维护 system prompt 和输出格式要求。
- 结构化输出解析：Pydantic 校验、失败修复、字段默认值。
- Tool 调用：搜索、地图、图片、导出、数据库查询。
- 任务编排：同步/异步执行、进度更新、错误记录。
- 成本治理：token 估算、缓存、模型分层、失败重试限制。

### AI 调用工具失败怎么解决？

工具失败要按类型处理：

- 参数错误：用 schema 校验，返回可读错误给模型修正。
- 网络超时：短退避重试，设置最大次数。
- 第三方服务不可用：切换备选工具，例如 GrokSearch 失败后用 Tavily 或本地 seed。
- 无结果：降级为人工链接、官方源或提示用户补充信息。
- 权限失败：不重试，提示配置 API key 或登录状态。
- 解析失败：只让模型修复结构化片段，不重跑全流程。

### RAG 流程

标准 RAG 流程是：

1. 文档采集：PDF、网页、数据库、手工上传。
2. 清洗切分：按标题、段落、token 长度切 chunk，保留 metadata。
3. 向量化：用 embedding 模型生成向量。
4. 入库：写入向量库和元数据索引。
5. 查询改写：把用户问题改写成更适合检索的 query。
6. 召回：向量检索、关键词检索、混合检索。
7. 排序去重：按相似度、时间、权威性、业务规则排序。
8. Re-rank：用交叉编码器或 LLM 判断问题与片段的相关性。
9. 生成答案：把 top chunks 和引用放入 prompt。
10. 校验输出：检查引用、格式、敏感信息和事实一致性。

### 怎么加速 RAG 检索？

- 文档预切分、预向量化，避免查询时临时处理。
- 使用 HNSW / IVF 等 ANN 索引。
- metadata filter 先过滤租户、文档类型、时间、地区。
- query cache 和 embedding cache。
- 混合检索并行跑 BM25 和向量召回。
- 限制 topK，先粗召回 50，再 re-rank 到 5 到 10。
- 热门知识做缓存或放入轻量 KV。
- 大文档按章节建父子 chunk，先召回小 chunk，再带回父段落。

### 向量库和数据量怎么讲？

TravelMind 当前代码侧更偏搜索聚合和结构化评分，没有落地独立向量库。如果被问到项目现状，可以诚实说：这个 MVP 目前没有把旅行资料沉淀成大规模向量库，检索主要来自官方 seed、GrokSearch/Tavily、小红书和用户链接。下一步如果做知识库，会优先考虑 PostgreSQL + pgvector 或 Elasticsearch/OpenSearch 混合检索。

选型依据：

- 数据量小、团队已有 PG：pgvector 成本低、事务一致、运维简单。
- 关键词和过滤强：Elasticsearch/OpenSearch 更适合 BM25、分词、复杂 filter。
- 向量规模大、低延迟：Milvus、Qdrant、Weaviate 更适合独立向量服务。

### 大模型选型逻辑

我一般按任务选模型，而不是盲目选最强模型：

- 分类、意图识别、格式修复：便宜、快、稳定的模型。
- RAG 问答：看长上下文、遵循证据、中文能力、幻觉率。
- 复杂规划：看推理能力、结构化输出稳定性。
- 代码生成：看项目上下文理解、工具使用、修复能力。
- 政府或私有化：优先国产模型、私有部署、数据不出域。

评估指标包括准确率、延迟、成本、上下文长度、结构化输出成功率、工具调用成功率、供应商稳定性、合规要求。

### 政策文件场景如何确认召回准确性？

- 数据源权威：优先政府官网、法规库、正式文件。
- metadata 完整：文件名、发文机关、文号、发布日期、有效状态。
- 检索过滤：按地区、政策类型、时间范围过滤。
- 引用强制：答案必须引用原文段落和链接。
- 多路召回：关键词 + 向量 + 文号精确匹配。
- Re-rank：提高真正回答问题的片段排名。
- 人工审核：重要政策结论进入人工复核流程。
- 答案约束：没有依据就回答“不确定/未检索到”，不能编。

### 上下文压缩策略

- 保留硬约束：日期、预算、目的地、人数、禁忌、必须去的地点。
- 摘要历史：把多轮对话压成用户偏好和已确认变更。
- 删除低价值内容：寒暄、重复内容、失败工具日志。
- 检索上下文只保留 top chunks 和关键句。
- 对结构化任务，把自然语言历史转成 JSON state。
- 压缩后做校验：检查预算、时间、地点等关键字段是否丢失。

如果模型压缩质量不稳定，可以用更强模型压缩、规则抽取兜底、字段级 diff、人审关键字段、压缩前后让模型自检，也可以把关键约束结构化存 DB，不依赖摘要文本。

### Claude Code 泄露事件、上下文治理和核心循环

如果被问源码泄露，我会谨慎回答：我了解过社区讨论和公开分析，但不会传播或依赖非授权源码。可以从产品形态推断其上下文治理：读取项目文件、搜索引用、维护任务计划、控制工具权限、压缩长历史、保留关键操作记录、在编辑后运行验证。

核心循环可以概括为：

1. 理解用户目标。
2. 搜索和读取相关文件。
3. 形成计划。
4. 调用工具执行编辑或命令。
5. 读取工具反馈。
6. 修复错误或继续下一步。
7. 运行测试/构建验证。
8. 总结变更和风险。

### 多租户 K8s 怎么部署？一个租户一个 pod 吗？

不一定。一个租户一个 Pod 隔离强，但成本和运维压力大，适合大客户、强隔离、私有化。多数 SaaS 会按共享服务部署，通过 tenant_id 做数据隔离、权限隔离、资源配额隔离；高级租户可以独立 namespace、独立数据库、独立队列或独立集群。

常见方案：

- 小客户：共享 Pod + 共享库 + tenant_id。
- 中客户：共享服务 + 独立 schema/database。
- 大客户/政府：独立 namespace 或独立集群。
- AI 任务：可按租户设置队列、并发、token 配额和限流。

## TK 公司

### 企微 H5 登录流程

企微 H5 常见流程：

1. 配置可信域名和 OAuth 回调地址。
2. 用户访问 H5，后端生成企微授权 URL。
3. 用户在企微内打开并授权，企微回调带 `code`。
4. 后端用 `code` 换取用户身份，如 `userid/open_userid`。
5. 后端绑定内部用户，签发自己的 session/JWT/cookie。
6. 前端拿到登录态，继续业务流程。

多个业务域名受限时，可以用统一认证域名做 OAuth 中转。业务域名跳到 auth 域名登录，登录完成后通过一次性 ticket 回跳业务域名，业务后端用 ticket 换 session。

### 没有设计稿怎么推进？

我会先产出低保真流程：用户角色、核心路径、页面信息结构、字段和状态。再用现有设计系统或组件库做可交互原型，找业务方快速确认。确认后再做视觉细化和异常状态。AI 可以辅助生成 PRD、页面结构、空状态文案和多版 UI 方案，但最终要由业务目标和可用性来收敛。

### H5 用户打标签、唯一 ID 和企微回调同步

用户进入页面后，优先使用后端登录态中的内部 `user_id`。未登录时可以使用匿名设备 ID，但只能作为临时 visitor_id。企微回调后，用企微 `userid/open_userid` 和内部 user_id 建绑定关系，并把匿名访问记录合并到正式用户。

用户标签可以来自：

- 注册来源、渠道、活动。
- 浏览页面、停留时长、点击按钮。
- 表单偏好、搜索词、收藏。
- 购买或转化行为。
- AI 对用户输入的兴趣分类。

### 埋点怎么做？

埋点分前端和后端。前端记录曝光、点击、输入、提交、页面停留、异常；后端记录接口耗时、状态码、业务事件、任务状态。字段包括 user_id、visitor_id、session_id、page、event_name、timestamp、device、referrer、experiment、payload。敏感字段要脱敏，不采集密码、token、身份证等。

### RAG 检索怎么做？

可以参考前面的 RAG 流程。TravelMind 当前更像“搜索增强生成”：从官方 seed、远程搜索、小红书和手工链接召回，做评分、排序、去重，再放入 Agent 规划上下文。

### DolphinScheduler 同步 MySQL IO 爆红怎么排查？

排查顺序：

- 看同步任务频率、并发数、每次扫描数据量。
- 查慢 SQL、执行计划、是否走索引。
- 看是否三表 join 造成临时表、filesort、全表扫描。
- 检查 binlog、redo log、磁盘 IOPS、buffer pool 命中率。
- 判断是读 IO 还是写 IO，是源库压力还是目标库压力。
- 增量同步用 update_time/id 游标，避免每小时全量扫。
- 大任务分批分页，控制 batch size 和 sleep。
- 必要时加只读从库、离线数仓或消息队列削峰。

### MySQL 大表优化和百万级慢插入

- 表结构：字段类型尽量小，避免大 JSON/Text 热字段。
- 索引：只建高选择性索引，避免过多二级索引拖慢插入。
- 批量插入：多行 insert，控制每批 500 到 5000。
- 分区/分表：按时间、租户或业务 key。
- 冷热分离：历史数据归档。
- 主键：用趋势递增 ID 减少页分裂，避免完全随机 UUID 做聚簇主键。
- 写入链路：异步队列削峰，失败重试。
- 参数：关注 buffer pool、redo log、flush 策略。

## YC 公司

### 数据库和缓存一致性

常见方案是 Cache Aside：

1. 读：先查缓存，未命中查 DB，再写缓存。
2. 写：先写 DB，再删除缓存。
3. 删除失败：重试、消息队列补偿、定时校验。
4. 高并发：加互斥锁防缓存击穿，热点 key 预热。

为什么写后删除而不是更新缓存？因为复杂对象容易并发覆盖，删除后下次读从 DB 重建更稳。

### 从 0 到 1 搭项目怎么设计架构？

我会先确认业务目标、用户角色、核心流程、数据模型、非功能要求。然后按分层设计：

- 前端：路由、状态管理、组件库、权限、错误处理。
- 后端：Controller/Route、Service、Repository、Domain、DTO。
- 数据：表结构、索引、迁移、事务边界。
- AI：模型配置、prompt、工具、任务队列、观测。
- 运维：环境变量、Docker、日志、监控、CI/CD。
- 质量：单测、接口测试、关键 E2E、回滚方案。

TravelMind 的现有分层就可以作为例子：web、api、worker、groksearch-bridge、packages、infra、docs。

### 门店 AI 数字化系统怎么设计？

模块拆分：

- 用户与权限：总部、区域、店长、员工。
- 门店档案：门店信息、营业时间、设备、人员。
- 商品/服务：SKU、库存、价格、套餐。
- 订单交易：收银、退款、核销、发票。
- 会员营销：标签、优惠券、积分、私域触达。
- 数据看板：营收、客流、转化、复购。
- AI 助手：经营分析、活动建议、客服问答、门店巡检总结。
- 知识库：SOP、产品手册、政策制度。

数据流：业务系统产生订单、库存、会员、行为数据，进入数据仓或业务库，AI 通过 RAG 查询 SOP 和经营数据，生成建议，关键动作仍需人工确认。

技术选型：前端 Vue/React，后端 NestJS/FastAPI/Java Spring，数据库 MySQL/PostgreSQL，缓存 Redis，队列 RabbitMQ/Kafka/BullMQ，AI 层用模型网关 + RAG + Agent 工具。

### AI 工作流、规范和 code review

我的 AI 开发流程：

- 需求阶段：让 AI 辅助拆 PRD、验收标准、风险清单。
- 设计阶段：生成接口草案、数据模型、页面结构。
- 编码阶段：让 AI 做局部实现、测试补齐、重构建议。
- 自检阶段：让 AI 做 code review，但不能替代人工 review。
- 验证阶段：跑测试、构建、接口联调、浏览器检查。

AI 编程规范：

- 不能直接提交未理解的 AI 代码。
- 必须符合项目风格和类型约束。
- 必须补关键测试或手工验证。
- 安全、权限、支付、数据删除等代码必须人工重点 review。
- prompt 和输出要保留可追踪记录，便于复盘。

### SSE 断线续传

SSE 原生支持 `Last-Event-ID`，服务端可以给每条事件带 id；客户端断线重连时浏览器会带上最后事件 ID。TravelMind 当前 `/jobs/{id}/stream` 每秒推送 job 最新状态，状态持久化在 DB，所以刷新页面后可以通过 `GET /jobs/{id}` 或重新连接 SSE 恢复状态。更完整的断点续传可以把 timeline event id 化。

后端示例：

```py
@router.get("/{job_id}/stream")
async def stream_job_endpoint(job_id: str):
    async def event_stream():
        while True:
            job = load_job(job_id)
            yield f"id: {job.updated_at.timestamp()}\n"
            yield f"data: {json.dumps(serialize_job(job))}\n\n"
            if job.status in {"completed", "failed"}:
                break
            await asyncio.sleep(1)
    return StreamingResponse(event_stream(), media_type="text/event-stream")
```

前端示例：

```ts
const source = new EventSource(`/api/v1/jobs/${jobId}/stream`, { withCredentials: true })

source.onmessage = (event) => {
  const payload = JSON.parse(event.data)
  renderProgress(payload.data.progress_percent, payload.data.stage_message)
  if (["completed", "failed"].includes(payload.data.status)) {
    source.close()
  }
}

source.onerror = () => {
  source.close()
  setTimeout(() => pollJob(jobId), 2000)
}
```

## HJ 公司

### 国内模型替代国外模型有影响吗？

有影响，但不一定不能做。影响主要在模型能力、工具生态、上下文长度、结构化输出稳定性、英文资料能力、代码能力和接口兼容性。政府项目如果要求数据不出境，可以选择国产模型、私有化部署、专有云或模型网关。工程上要做模型适配层，避免业务代码绑定某个国外接口。TravelMind 的 LLM 客户端支持 OpenAI-compatible、NewAPI、NeiAPI 这类网关，目的就是降低切换成本。

### 国内外模型/工具对比怎么做？

我会固定一批测试集：分类、RAG 问答、结构化输出、长文总结、工具调用、代码生成。每个模型跑相同输入，记录准确率、格式成功率、延迟、成本、失败率。不能只看主观效果，要有可复现 case。

### AI 效率提升多少？

我的体感是：在需求拆解、样板代码、测试补齐、文档整理上能提升 40% 到 70%；在复杂架构、疑难 bug、安全逻辑上提升没有那么夸张，可能是 10% 到 30%，因为仍然需要工程判断。AI 最大价值是缩短从 0 到 1 的时间，但最后 20% 的可靠性交付仍然靠工程能力。

### 用什么 AI 工具做规划、草图、文档和开发？

- 项目规划：ChatGPT/Claude/Codex，生成任务拆解和风险清单。
- 草图/UI：Figma + AI 插件，或用代码快速生成可交互原型。
- 文档：AI 辅助 PRD、接口文档、测试用例、发布说明。
- 开发：Codex、Claude Code、Cursor、GitHub Copilot。
- 测试：Playwright、Vitest、Pytest，再结合 AI 生成测试点。

### 全栈搭框架思路

先从业务边界和数据流出发，不先堆技术。我的顺序是：业务模块拆分、核心实体、接口契约、权限模型、数据模型、异步任务、缓存策略、错误处理、日志监控、部署和 CI。框架只是承载，关键是边界清楚、可测试、可演进。

### 传统业务系统后端分几层？

常见分层：

- Controller/API 层：参数校验、认证、响应封装。
- Service 层：业务流程、事务编排。
- Domain 层：核心业务规则。
- Repository/DAO 层：数据库访问。
- Integration 层：第三方系统、消息队列、支付、文件。
- Infrastructure 层：缓存、日志、配置、监控。

### 高并发、熔断、限流、缓存、队列

TravelMind 当前是 MVP，不是高并发项目，但架构上已有异步队列和任务状态。高并发系统我会这样做：

- 网关限流：按 IP、用户、租户、接口限流。
- 应用熔断：第三方搜索/模型失败时快速失败或降级。
- 缓存：热点配置、搜索结果、用户会话、知识库召回。
- 队列削峰：AI 生成、导出、图片处理进入队列。
- 幂等：支付、订单、任务重试必须有幂等 key。
- 监控：QPS、P95/P99、错误率、队列堆积、模型耗时。

### 没有测试岗怎么测试？

开发自己负责基本质量：单元测试覆盖核心函数，接口测试覆盖主要 API，前端关键流程用 Playwright，AI 输出用 golden cases 和 schema 校验。上线前按冒烟清单验证登录、创建、生成、导出、异常重试等核心链路。

### AI 界面测试能否覆盖点击输入提交？

可以辅助，但不能完全替代测试工程。Playwright 本身能稳定覆盖点击、输入、提交、断言；AI 可以帮忙生成测试用例、定位选择器、分析截图差异。对动态页面，可以用 AI 做视觉检查，但关键断言仍应写成确定性规则。

### 政府 50 万项目一个月交付怎么拆？

我会先做风险评估：一个月交付客户端、APP、小程序和后端，范围很紧，必须控制 MVP。流程：

- 第 1 周：冻结需求范围、原型确认、技术方案、接口和数据库设计。
- 第 2 周：核心业务闭环开发，优先登录、主流程、管理后台。
- 第 3 周：联调、权限、报表、导入导出、移动端适配。
- 第 4 周：测试修复、部署、培训、验收材料。

同时明确不做或二期做的范围，避免需求无限膨胀。AI 可用于生成原型、接口代码、测试用例、文档和验收材料。

### 资产管理系统如何利用 AI 交付？

AI 可以辅助需求梳理、表结构设计、接口生成、前端表单/列表页面生成、导入导出模板、测试用例、操作手册。资产管理本身可加入 AI 能力：自然语言查询资产、自动生成盘点报告、识别异常折旧/闲置、根据图片识别资产类别。

## FN 公司

### Vue 和 React 核心区别

Vue 是渐进式框架，模板语法和响应式系统内置，约定更多，上手快。React 更像 UI library，核心是组件和状态驱动视图，JSX 灵活，生态更自由。Vue 依赖编译器和响应式追踪做优化，React 依赖 Fiber、调度和组件重新渲染模型。

### 谁性能上限更高？

不能简单说谁绝对更高。Vue 模板编译能做静态提升、patch flag，默认性能很好；React 生态和手动优化空间大，配合 Server Components、Compiler 也在减少无效渲染。真正瓶颈通常在数据结构、渲染数量、网络、图片、状态设计，而不是框架本身。

### 最新版本在做什么？

React 近年重点是并发渲染、Server Components、Actions、React Compiler、服务端优先和减少手写 memo。Vue 3 重点是 Composition API、Proxy 响应式、编译优化、Vapor Mode 探索、更好的 TS 支持。

### 浏览器 HTTP 请求过程和缓存

流程：URL 解析、查缓存、DNS、TCP、TLS、发送请求、服务器处理、响应、浏览器解析渲染。缓存发生在浏览器 HTTP 缓存、Service Worker、DNS 缓存、CDN、代理、服务端缓存、应用内缓存。HTTP 缓存包括强缓存 `Cache-Control/Expires` 和协商缓存 `ETag/Last-Modified`。

### 印象最深项目

可以讲 TravelMind：难点在于 AI 输出不稳定，但业务要结构化行程。解决方式是：AI 角色拆分、搜索结果评分、Pydantic schema 校验、任务状态持久化、SSE 进度推送、模型协议适配、Docker Compose 一键部署。这个项目让我对“AI 能力工程化”理解更深。

### SSE 和 WebSocket

SSE 是服务端到客户端的单向文本流，基于 HTTP，自动重连，适合 AI 流式输出、任务进度、通知。WebSocket 是双向长连接，适合聊天、协同编辑、实时游戏、行情推送。TravelMind 的 job progress 用 SSE 更合适，因为前端只需要接收后端任务状态。

### AI 时代程序员价值

价值从“写多少代码”转向“定义正确问题、设计系统边界、判断 AI 输出、保证质量和交付”。AI 能提高产出速度，但架构、业务理解、安全、可维护性、调试和跨团队协作仍然是程序员核心价值。

### 编程优点和缺点

优点可以说：我比较擅长把模糊需求拆成可交付方案，能兼顾前端体验、后端接口和 AI 工程化，也重视可维护性和验证。缺点可以说：有时为了把边界想清楚，前期会花较多时间做调研；现在会通过先做最小闭环、再迭代优化来平衡速度和质量。

### 最近学什么、职业规划

最近重点学习 AI Agent、RAG、模型协议适配、MCP、前端自动化测试和云原生部署。职业规划是继续走全栈 + AI 工程方向，短期能独立负责从需求到交付的模块，中长期希望能承担 AI 应用架构和团队技术方案设计。

## XZ 公司

### AI 开发工作流、MCP、Skill

我的 AI 开发流程一般是：先让 AI 帮我梳理需求和风险，再自己确认边界；接着让 AI 阅读项目上下文、定位相关文件；实现时控制改动范围；最后跑测试和构建，让 AI 辅助分析失败。MCP 可以把外部工具标准化接入，比如浏览器、数据库、搜索、文件、设计工具。Skill 更像固化的操作手册，把某类任务的最佳实践写成可复用流程。

### 接到需求后怎么做？

我会先确认目标用户、业务价值、验收标准和截止时间，再看现有系统有没有类似功能。然后拆接口、数据、页面、权限、异常和测试点。实现上先打通主流程，再补边界和体验。交付前自己跑冒烟，准备变更说明和风险点。

### 3 到 5 年规划

我希望往全栈 + AI 应用架构方向发展。1 年内把 AI 工程化、RAG、Agent、云原生部署打牢；3 年内能负责一个完整业务线的技术方案；5 年内希望能在技术架构和团队协作上承担更大责任，既能写关键代码，也能推动项目落地。

### 工作中深刻的事

可以讲 AI 项目落地：一开始大家容易把 AI 当成“调接口生成文本”，但真正落地会遇到输出不稳定、成本高、延迟长、来源不可追溯、用户预期不一致。我学到的是必须把 AI 能力产品化、结构化、可观测化，而不是只写 prompt。

## SH 公司（前端八股）

### CSS3 常用能力

常用 flex/grid 布局、transition、animation、transform、gradient、box-shadow、filter、media query、CSS variables、sticky、object-fit、clamp、aspect-ratio 等。渐变、旋转、缩放、动画本质上分别对应 background、transform 和 keyframes。

### CSS 动画和 JS 动画

CSS 动画适合简单、声明式、可交给浏览器优化的效果，如 hover、淡入、缩放、抖动。JS 动画适合需要精确控制、物理模拟、拖拽联动、Canvas/WebGL 的场景。性能上优先使用 transform 和 opacity，因为更容易走合成层。

### Canvas 场景

Canvas 适合绘制大量图形、图表、签名、图片编辑、小游戏、粒子动画、红包/福袋动画。红包打开可以用 UI 图 + CSS/Canvas 动画组合，复杂碎片、金币、粒子用 Canvas，主体红包用图片或 DOM 更省成本。

### WebSocket 前端连接、事件约定、心跳重连

流程：创建连接、监听 open/message/error/close、发送鉴权信息或 token、按事件协议收发消息、断线后重连。

```ts
let retry = 0
let socket: WebSocket | null = null

function connect() {
  socket = new WebSocket("wss://example.com/ws")
  socket.onopen = () => {
    retry = 0
    socket?.send(JSON.stringify({ type: "auth", token: getToken() }))
  }
  socket.onmessage = (event) => {
    const message = JSON.parse(event.data)
    if (message.type === "order.updated") updateOrder(message.payload)
  }
  socket.onclose = () => {
    const delay = Math.min(30000, 1000 * 2 ** retry++)
    setTimeout(connect, delay)
  }
}
```

心跳可以客户端定时发 ping，服务端回 pong；弱网时显示“正在重连”，数据不准时显示“数据可能延迟”。连接不上可降级 HTTP 轮询，轮询频率用指数退避或根据页面可见性降低。

### ES6 常用特性

`let/const`、箭头函数、模板字符串、解构、扩展运算符、默认参数、class、module、Promise、async/await、Map/Set、Symbol、Proxy、Reflect、可选链、空值合并等。

### 柯里化

柯里化是把多参数函数转换成一系列单参数函数。

```js
const add = (a) => (b) => a + b
add(1)(2)
```

### ES5 和 ES6 构造对象

```js
// ES5
function User(name) {
  this.name = name
}
User.prototype.say = function () {
  return this.name
}

// ES6
class User2 {
  constructor(name) {
    this.name = name
  }
  say() {
    return this.name
  }
}
```

### 浏览器兼容

CSS 用 autoprefixer、postcss、兼容写法和降级样式；JS 用 Babel、core-js polyfill、browserslist；API 不支持时做 feature detection。低版本浏览器路由变了但页面不跳，可能是 history API 不支持、base 配置错误、hash/history 模式不匹配、polyfill 缺失或服务器 fallback 配置错误。Vue/React 抹平了组件层差异，但不能完全抹平浏览器 API 差异。

### Vue 2 和 Vue 3 区别

- Vue 2 使用 `Object.defineProperty`，Vue 3 使用 `Proxy`。
- Vue 3 支持 Composition API，逻辑复用更好。
- Vue 3 TS 支持更好。
- Vue 3 编译优化更强，如 patch flag、静态提升。
- Vue 3 支持 Fragment、Teleport、Suspense。

### Vue 2 / Vue 3 响应式原理

Vue 2 在初始化时遍历 data，用 `Object.defineProperty` 给属性加 getter/setter，getter 收集依赖，setter 通知 watcher 更新。数组通过重写 `push/pop/shift/unshift/splice/sort/reverse` 这些变更方法触发更新。但通过索引直接赋值、直接改 length、新增对象属性可能无法触发，需要 `Vue.set` 或 `splice`。

Vue 3 用 Proxy 代理整个对象，可以拦截 get、set、deleteProperty、has、ownKeys 等操作，对新增属性和数组索引支持更好。依赖关系通常用 `WeakMap -> Map -> Set` 存储：target 对象弱引用为 key，属性映射到 effect 集合。WeakMap 的好处是对象不用时可被垃圾回收。

### 数据变了视图没变可能原因

- Vue 2 新增属性或数组索引赋值未被响应式追踪。
- 直接修改嵌套对象但引用未变化，某些场景未触发更新。
- key 使用错误导致组件复用异常。
- 异步更新还没 flush，需要 `nextTick`。
- 状态不是响应式对象或被解构丢失响应式。
- React 场景下直接 mutation，没有 setState 或新引用。

## PY 公司

### 如何推动 AI 系统落地？

先选一个高价值、边界清楚、可评估的场景做 MVP。比如 TravelMind 先做旅行行程生成闭环，而不是泛泛做通用助手。落地步骤：业务流程拆解、数据源确认、模型选型、Prompt/Agent 原型、结构化输出、前端体验、灰度测试、效果评估、成本监控、失败兜底。

### 用户问题如何路由到 AI 系统？意图识别怎么做？

可以用规则 + 模型分类：

- 规则识别明确命令，如“生成行程”“导出 PDF”“修改预算”。
- 小模型分类意图：问答、创建、修改、搜索、闲聊、投诉。
- 根据登录态和权限决定能否访问用户数据。
- 未登录用户只允许通用查询，不访问个人行程；需要个性化时引导登录。

### 文档/PDF/课件如何切分入库审核？

- 解析：PDF 用 OCR/文本抽取，PPT 按页，Word 按标题。
- 清洗：去页眉页脚、目录噪声、重复空格。
- 切分：按章节优先，超长再按 token 滑窗。
- 元数据：来源、版本、页码、标题、权限、有效期。
- 入库：原文库 + 向量库 + 关键词索引。
- 审核：高风险知识先人工审核，通过后可检索。

### AI 输出如何保证结构化？为什么 Markdown 而不是 JSON？

结构化可以靠 JSON Schema、Pydantic、函数调用和后处理校验。JSON 适合机器消费，Markdown 适合人读和富文本展示。像 TravelMind 的行程主数据适合 JSON，因为前端要渲染字段；导出报告或用户可读内容适合 Markdown，因为层级、列表、引用更自然。

### 秒杀系统设计

架构：CDN/网关限流、活动页静态化、Redis 预扣库存、消息队列下单、MySQL 最终落库、支付异步回调。避免超卖可以用 Redis Lua 原子扣减或 MySQL 条件更新。

Redis Lua：

```lua
local stock = tonumber(redis.call("GET", KEYS[1]))
if stock == nil or stock <= 0 then
  return 0
end
redis.call("DECR", KEYS[1])
return 1
```

MySQL 安全扣减：

```sql
UPDATE sku
SET stock = stock - 1
WHERE id = ? AND stock > 0;
```

只有 affected rows = 1 才表示扣减成功。再配合唯一订单号、事务和乐观锁。

### 不用 Redis 只用 MySQL 怎么保证安全？

用条件更新 + 事务 + 唯一约束 + 合理隔离级别。库存扣减和订单创建在同一事务里，库存 SQL 带 `stock > 0`，订单表对 `user_id + sku_id + activity_id` 加唯一索引防重复抢购。缺点是并发能力不如 Redis，需要数据库扩容和排队。

### 微信支付接入、到账和队列一致性

流程：创建业务订单，调用微信预支付，前端拉起支付，微信异步回调，后端验签，查询订单确认，更新支付单和业务单，发放积分/虚拟商品。

支付用异步队列是因为回调里不适合做复杂业务，避免阻塞微信回调。队列挂掉时，支付回调结果必须先落库，队列恢复后补偿；同时定时任务主动查单，对“已支付但未发货”状态做修复。

验签流程：取微信回调头和 body，用平台证书验证签名，解密 resource，校验商户号、订单号、金额、状态，幂等更新订单。

### MCP/SKILL 如何辅助开发？

MCP 把工具标准化，比如浏览器、数据库、搜索、文件、设计工具。Skill 把固定流程沉淀成操作手册，比如“如何做代码评审”“如何生成图片”“如何安装插件”。它们能减少重复劳动，让 AI 更稳定地按团队规范工作。

### 没有产品经理怎么出原型和 PRD？

我会自己先访谈业务方，整理角色、流程、字段、权限、异常和验收标准。然后用 AI 生成 PRD 初稿和页面草图，再用前端快速做可交互原型。评审时记录变更，按优先级拆一期/二期，避免口头需求反复漂移。

## HQ 公司

### NextJS、TypeORM、Prisma

NextJS 我了解并使用过它的路由、SSR/SSG、API routes、Server Components 思路。TypeORM 和 Prisma 都是 Node 生态 ORM。TypeORM 更接近传统 ORM，装饰器、Repository、QueryBuilder 灵活，适合复杂 SQL 和已有实体模型；Prisma schema 清晰、类型生成强、开发体验好，但复杂 SQL、动态查询和某些数据库特性可能要回到 raw SQL。

### 技术选型谁决定？

通常不是单人拍脑袋。技术负责人提出方案，核心开发参与调研，结合业务周期、团队熟悉度、性能、成本、运维、风险评估，最后由技术负责人或架构评审确定。小团队可以更快，但也要留下选型依据。

### NestJS Provider 默认生命周期和单例优点

NestJS Provider 默认是单例。单例优点是节省实例创建成本、方便共享连接池和配置、状态集中。但不能在单例里放请求级可变状态，否则会串数据。需要请求级状态时用 request-scoped provider 或显式传参。

### 统一操作日志 / 监控

NestJS 可以用 Middleware、Interceptor、Guard、Exception Filter 统一处理。操作日志适合 Interceptor：记录请求用户、路径、参数摘要、耗时、状态码、错误。监控可接 Prometheus/OpenTelemetry。

### Pipe 概念

Pipe 用于参数转换和校验，在 Controller 方法执行前运行。常见场景：DTO 校验、类型转换、参数清洗、自定义业务校验。例如 `ValidationPipe` 根据 class-validator 校验 body。

### TypeORM 两种模式和 SQL 调优

TypeORM 常用 Active Record 和 Data Mapper。Active Record 是实体自己有 save/remove 方法；Data Mapper 用 Repository/EntityManager 操作实体，更适合大型项目。慢查询时开启 logging，或用 QueryBuilder 的 `getSql()` / `getQueryAndParameters()` 获取 SQL，再用 `EXPLAIN` 分析索引和扫描行数。

### PostgreSQL 物化视图

物化视图会把查询结果持久化，适合复杂报表和低频刷新高频查询场景。与普通视图不同，普通视图每次查询都执行原 SQL；物化视图需要 `REFRESH MATERIALIZED VIEW` 更新。

### MySQL 优化经验

常见做法：慢查询日志、EXPLAIN、联合索引最左前缀、覆盖索引、避免函数作用在索引列、避免 select *、分页优化、拆大事务、冷热分离。分库分表和读写分离要在数据量、并发、团队运维能力都需要时再上。

### Bull Queue 长任务会不会丢？

Bull/BullMQ 基于 Redis 持久化任务。进程崩溃或 K8s 重启时，未完成任务一般会被标记 stalled 后重新处理。要保证不丢，需要 Redis 持久化、合理 lockDuration、幂等 jobId、重试策略、死信队列和业务状态落库。

### 任务重复执行、成本优化、断点续跑

AI 长任务要用幂等 key 和中间结果缓存。比如同一个文档 embedding，按文档 hash 判断是否已处理；同一个 prompt + model + input hash 可缓存结果。断点续跑可以把任务拆成步骤，每步完成就落库，重启后从最后成功步骤继续。

```ts
const jobKey = hash({ type: "embedding", docId, contentHash, model })
await queue.add("embedding", payload, { jobId: jobKey, attempts: 3 })
```

TravelMind 的 `job_records` 保存 stage、progress、timeline，已经有任务可观测基础；如果要做强断点续跑，可以把每个 Agent role 的输出也持久化。

### AGUI 动态渲染表单/卡片

AGUI 类协议可以理解为后端通过流式事件告诉前端“现在要渲染什么 UI”。流程：

1. 后端定义事件协议，如 `text.delta`、`form.schema`、`card.update`、`tool.call`。
2. 前端建立 SSE/WebSocket 连接。
3. 收到 schema 后用组件注册表渲染表单/卡片。
4. 用户提交后把 action 发回后端。
5. 后端继续推送状态和结果。

前端边接收边渲染：

```ts
const response = await fetch("/api/stream")
const reader = response.body!.getReader()
const decoder = new TextDecoder()
let buffer = ""

while (true) {
  const { value, done } = await reader.read()
  if (done) break
  buffer += decoder.decode(value, { stream: true })
  renderDelta(buffer)
}
```

### 数据库事务是什么？项目中必须用事务的场景

事务是一组数据库操作，要么全部成功，要么全部失败，满足 ACID。TravelMind 中创建行程并写入初始任务、更新行程 itinerary 和 latest trace、支付类系统里的订单支付和发货，都需要事务。比如生成行程完成后，更新 trip 的 `itinerary_json` 和 job 的 completed 状态，应保证一致。

### LangChain 不同版本/模块区别

LangChain 近年拆成多个包：`langchain-core` 放基础抽象，`langchain-community` 放社区集成，具体供应商有独立包如 `langchain-openai`。LangGraph 是独立的图编排框架，更适合有状态 Agent。新版更强调 LCEL、Runnable、可组合链路，而不是早期重型 Chain 类。

### 多智能体动态路由

动态路由可以基于规则、模型分类或状态条件。例如用户问题包含天气就走 weather agent，包含酒店就走 hotel agent，检索结果不足就回到 search node，预算超标就走 budget repair node。LangGraph 中可以用 conditional edges；普通代码里可以用状态机。

```py
def route(state):
    if state["intent"] == "weather":
        return "weather_agent"
    if state["need_search"]:
        return "search_agent"
    return "planner_agent"
```

### 查询改写

查询改写是把用户自然语言问题改写成更适合检索的 query。作用是补充同义词、消除指代、拆分多问题、加入领域词。比如“这个政策我能不能申请”改写成“某地区 某政策 申请条件 申报对象 材料”。

### Elasticsearch + 向量库混合检索

流程：用户 query 先做分词和 embedding；ES 做 BM25 关键词召回，向量库做语义召回；合并结果，按文档 id 去重；用 RRF 或加权分融合；再用 re-ranker 精排；最后取 top chunks 生成答案。即使已经排序去重，re-rank 仍有价值，因为粗排看的是关键词/向量相似度，re-rank 更关注“这段是否真正回答这个问题”。

### 领域词典

领域词典用于提升分词和召回，比如政策文号、业务术语、景点别名、品牌名。可以用于 query rewrite、ES 自定义词典、同义词扩展、实体识别。TravelMind 中可以维护目的地、景点别名、交通词、预算词等领域词。

### Harness 相关概念

Harness 通常指测试或评估框架，也可能指 CI/CD 平台 Harness。AI 项目里 test harness 是一套固定输入、期望输出、评估指标和自动运行脚本，用于比较 prompt、模型和检索策略效果。工程里 Harness CI/CD 则用于流水线、部署、Feature Flag、回滚等。

## YU 公司

### 求职看重什么？

我看重三点：业务是否有真实价值，技术团队是否愿意把事情做扎实，以及岗位是否能让我在全栈和 AI 工程方向持续成长。薪资重要，但我更看重长期能不能积累可迁移能力。

### 开发还是管理角色？

我主要承担开发和技术推进角色，也会参与需求拆解、方案设计、进度协调和 code review。相比纯管理，我更希望保持一线工程能力，同时能承担模块 owner 或小团队技术负责人职责。

### 日常 AI 工具渠道、费用稳定性

可以按真实情况回答。建议口径：日常使用 Codex、Claude Code、Cursor、ChatGPT、Copilot 等，个人或公司账号结合；生产系统不会直接依赖个人账号，而是通过企业 API key、模型网关或私有化模型，保证稳定性、权限和审计。

### 棘手难题如何解决？

可以讲 AI 输出不稳定：我们通过结构化 schema、任务状态、检索来源评分、模型适配层、失败重试和降级方案解决。也可以讲跨端交付风险：先冻结 MVP 范围，建立接口契约和验收清单，每日同步风险。

### 技术团队规模和架构

按真实经历替换。如果没有大型团队，可以说：我参与的项目通常由前端、后端、产品/设计、测试/运维协作；小团队里角色会复用，所以我也承担接口联调、部署脚本、文档和测试工作。

### 从前端转全栈怎么学习？

我先从接口和数据库开始，理解 HTTP、认证、SQL、事务、缓存、队列，再学习后端框架分层和部署。实际项目里从简单 CRUD、登录鉴权、文件上传、异步任务做起，逐步接触 AI 服务、模型接口、Docker 和 CI。AI 工具能加快学习，但关键概念必须自己验证。

### 如何减少 AI 代码出错和重复劳动？

- 给 AI 足够上下文和明确验收标准。
- 小步生成，不一次让它改太多。
- 要求遵循项目现有风格。
- 生成后自己审查关键逻辑。
- 跑测试、类型检查和构建。
- 把常用模式沉淀成模板、脚手架、Skill。

### 项目临近交付出现风险怎么办？

先判断风险影响范围和是否阻塞验收；立即同步负责人，不隐藏问题。然后给出方案：修复、降级、延期、砍范围、灰度开关。优先保证主流程可用和数据安全，把非核心功能延后。

### 口头需求如何借助 AI 输出原型和 UI/UX？

先把口头需求转成结构化 PRD：角色、目标、页面、字段、流程、异常、验收标准。再让 AI 生成低保真页面结构和多版布局方案，用代码或 Figma 快速做可交互原型。业务方反馈后，记录变更，转成任务清单。

### AI 生成页面常见问题和优化

常见问题：视觉风格同质化、信息层级不清、卡片堆砌、移动端溢出、状态缺失、空状态和错误状态没设计、颜色对比不足、业务重点不突出。优化方式：先定用户任务和信息优先级，使用设计系统，补齐 loading/error/empty/disabled 状态，做响应式检查，用真实数据验证密度和可读性。

### 重点介绍 AI/RAG 项目

可以这样总结：

> 我做的核心 AI 项目是 TravelMind AI，面向旅行规划场景。它不是简单聊天机器人，而是把用户偏好、搜索资料、多角色 Agent 和结构化行程结合起来。知识来源包括官方旅游 seed、GrokSearch/Tavily 远程搜索、用户手动链接和可选小红书内容。检索后会做可信度、质量、时效性和广告风险评分，再交给 Agent 生成按天组织的行程。AI 输出通过 Pydantic schema 校验，任务通过 ARQ/Redis 异步执行，前端通过 SSE 获取任务进度。这个项目让我比较系统地实践了模型适配、Agent 编排、搜索增强、异步任务和前端 AI 产品体验。

### 产品用户和功能架构

面向有旅行规划需求的普通用户，也可以扩展到旅行内容运营和定制旅行顾问。功能包括账号登录、创建行程、AI 生成/修改行程、搜索资料、图片生成、PDF 导出、社区分享、LLM 设置、后台管理。

### 自身擅长环节和优势

我比较擅长把不清楚的需求拆成可实现的工程方案，尤其是前端体验、接口契约、AI 能力落地之间的衔接。除前端外，我对后端 API、数据库建模、异步任务、Docker 部署、AI/RAG/Agent 都有实践。UI/UX 方面，我能在没有设计稿时先做可用原型，并结合业务反馈快速迭代。

