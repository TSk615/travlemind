# 系统架构

## 整体结构

- **前端**：`apps/web` 是 Vue 3 单页应用，直接调用 FastAPI 接口，提供首页、旅行空间、行程详情、模型设置和攻略社区。
- **接口服务**：FastAPI 负责认证、账户绑定、行程、搜索、图片、社区、运行配置、任务生命周期及导出接口。
- **异步任务**：ARQ Worker 处理行程生成、AI 调整、图片补全、生图和 PDF 导出。生产使用 Redis 队列；本地开发和测试可使用 `inline` 模式。
- **数据库**：生产使用 PostgreSQL；本地可用同一套 SQLAlchemy 模型连接 SQLite。数据库结构由 Alembic 迁移管理。
- **公开体验额度**：独立记录体验账户的生成上限与已用次数，通过事务和条件更新避免并发超额；不依赖浏览器状态或行程数量。

## AI 工作流

- `AgentOrchestrator` 是规划、来源摘要和导出草稿的内部接口。
- `StubOrchestrator` 用于离线测试和本地启动，不调用真实付费模型。
- `LangGraphOrchestrator` 实现可持久化的多角色流程，协调景点、天气、住宿、交通与规划任务，使用已配置的模型和搜索服务。
- 工作流检查点独立持久化，支持任务中断后的恢复；多进程部署需共用 PostgreSQL 检查点存储。
- `standard` 是标准单模型实现，可作为回退路径。原 HelloAgents 包已不再是运行时依赖，历史记录仍可阅读。
- 模型配置按账户保存，通过 `/api/v1/settings/llm` 读取和更新。客户端按配置接入 Responses、兼容 Chat Completions、Gemini、Claude、NewAPI 和 NeiAPI 类端点。

## 搜索与来源

- 来源包括内置官方信息、用户链接、已配置的远程搜索以及可选的小红书内容补充。
- 远程搜索支持通过 MCP 桥接的 GrokSearch 和直接调用 API 的 Tavily。
- 搜索结果包含 `ScoreBreakdown`，表示可信度、质量、时效、广告因素与综合分数。当前排序包含启发式规则，不应当作对真实信息准确性的保证。
- 模型输出、参考预算及第三方信息需要在出行前核验，本项目不提供实时票务、库存或支付能力。

## 前端与视觉资产

- Vite 入口为 `apps/web/src/main.ts`；共享视觉变量位于 `apps/web/src/styles/tokens.css` 和 `packages/ui/src/styles.css`。
- 门户首页、旅行空间与行程流视图使用 TypeScript / Vue 实现，支持移动端布局和减少动画偏好。
- 图片与字体随项目本地提供；装饰图是 AI 氛围视觉，不是目的地实拍证明。行程照片是否展示以实际返回数据和检查结果为准。
- 开发用行程预览路由只在开发模式注册，不进入生产路由。
- `apps/web/src/**/*.js` 中的生成文件或历史产物被忽略，不属于当前 TypeScript 构建入口。

## 发布边界

前端、API、Worker 和搜索桥接可分别发布。一次代码推送不等于所有线上容器自动更新；发布后需要核对实际镜像、页面资源和健康状态。自适应微调实验未纳入生产能力承诺。

相关入口：[本地启动](local-development.md) · [接口概览](api-overview.md) · [体验额度](public-demo.md) · [部署运维](vps-deployment.md)。
