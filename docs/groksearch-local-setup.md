# GrokSearch 本地配置与 Exa 搜索兜底

TravelMind 通过 GrokSearch bridge 调用搜索服务。生产环境使用 `inprocess` 模式：Grok 正常且返回可用来源时优先使用 Grok；Grok 报错、超时、空回复或缺少可用来源时，自动调用 Exa。这个机制是**搜索兜底**，不是行程规划模型的替代品，也不保证规划模型一定输出合法行程。

## 一键准备

在仓库根目录执行：

```powershell
.\scripts\setup-groksearch-local.ps1 -PrintEnvTemplate
```

脚本安装 bridge 依赖与上游 GrokSearch、检查命令及鉴权。仅检查可加 `-CheckOnly`，重装上游可加 `-ForceReinstall`。

## 私密环境变量

在本地根目录 `.env` 配置；服务器配置在 `/opt/travelmind/shared/providers.env`（仅服务端可读）。下面全部是占位符，**不要提交真实密钥**：

```env
TRAVELMIND_GROKSEARCH_RUNNER_MODE=inprocess
TRAVELMIND_GROKSEARCH_COMMAND=grok-search
TRAVELMIND_GROKSEARCH_BRIDGE_API_KEY=replace-with-your-bridge-key
TRAVELMIND_GROKSEARCH_BRIDGE_BASE_URL=http://127.0.0.1:8085/mcp
TRAVELMIND_GROKSEARCH_BRIDGE_TIMEOUT_SECONDS=75
TRAVELMIND_SEARCH_SERVICE_PROVIDER=groksearch
TRAVELMIND_SEARCH_SERVICE_TRANSPORT=mcp
GROK_API_URL=
GROK_API_KEY=
GROK_MODEL=Web/grok-chat-fast
GROK_WIRE_API=chat_completions
EXA_API_KEY=
TRAVELMIND_GROKSEARCH_PRIMARY_TIMEOUT_SECONDS=40
TAVILY_ENABLED=true
TAVILY_API_KEY=
TAVILY_API_URL=
FIRECRAWL_API_KEY=
FIRECRAWL_API_URL=
```

上游也支持 `GUDA_API_KEY` 配置。Exa Key 只给 bridge 使用，不放进网页、公开 README 或客户端设置。

## 兜底边界

- Grok 主搜索默认最多等待 **40 秒**；Grok 与额外来源的整体等待最多 **45 秒**，避免一个分支卡住拖死整次查询。
- Exa 另有 **12 秒**硬超时，使用官方 `https://api.exa.ai/search`，返回标题、链接与正文摘要。外层工具超时应至少为 75 秒。
- Exa 来源与原有 Tavily / Firecrawl 来源按链接去重，并写回原 `session_id` 缓存；`get_sources` 仍可读取完整来源。不会把 Exa 网页摘要伪装成 Grok 的回答。
- Grok 成功且有来源时不调用 Exa，不额外消耗 Exa 额度。
- Exa 也失败时，优先保留已获得的其他来源；所有来源都不可用则返回明确的 `search_unavailable`，不能假装搜索成功。
- 用户取消任务时不再启动兜底；并发请求的故障状态相互隔离。日志不记录 Key 或上游原始异常正文。
- 以上自动兜底安装在 bridge 的 **inprocess** 入口；`stdio` 模式直接运行上游程序，不具备这层包装。

## 启动与测试

```powershell
uv run --project apps/groksearch-bridge uvicorn travelmind_groksearch_bridge.main:app --host 127.0.0.1 --port 8085
uv run --project apps/api uvicorn travelmind_api.main:app --host 127.0.0.1 --port 8000
uv run --project apps/worker python -m travelmind_worker.worker
uv run --project apps/groksearch-bridge pytest apps/groksearch-bridge/tests
```

自动化测试使用假 Key / 模拟 HTTP，不会扣真实模型或搜索额度。覆盖 Grok 超时/异常/空结果、Exa 接管、缓存与去重、双服务失败、取消以及并发隔离。**自动化通过不等同于真实第三方服务或完整行程生成验收通过。**
