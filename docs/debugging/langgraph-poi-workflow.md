# LangGraph POI 工作流调试

本指南用于当前 `LangGraphOrchestrator` + `RoleInvoker` 实现。旧 `helloagents.py` 已删除，
不要再按旧文件行号或旧运行时入口排查。

## 首先确认执行路径

1. Job 的 `payload_json.workflow_provider` 应为 `langgraph`。
2. Job 日志应依次出现 `langgraph_role_started`，随后是
   `langgraph_role_completed` 或 `langgraph_role_failed`。
3. POI 节点完成后，trace 中应有 `poi_specialist`，并记录 endpoint、model、耗时、
   `request_count`、`retry_count` 和已知 usage。
4. 恢复执行时，已经从 checkpoint 复用的角色会标记 `cache_reused=true`。

```powershell
$latestLog = Get-ChildItem E:\travel\logs\jobs\*.jsonl |
  Sort-Object LastWriteTime -Descending |
  Select-Object -First 1

Get-Content $latestLog |
  Select-String 'langgraph_role_started|langgraph_role_completed|langgraph_role_failed'
```

## POI 证据路径

- 原生搜索模型：POI 角色直接使用模型搜索能力，不重复调用 MCP 搜索。
- 普通模型：`PlanningCore` 通过现有 `ConfiguredSearchGateway` 收集、压缩证据后交给角色。
- 地图关联、营业日核验、预算和时间线检查仍是确定性 Python 逻辑，不由模型自行决定。

部分低层工具日志仍保留 `helloagents_` 前缀，目的是兼容既有运维查询和历史 checkpoint
指纹；它们是事件兼容标识，不代表旧包或旧 orchestrator 仍在运行。

## 超时、重试和并发

- POI 角色最多发送 1 次 HTTP 请求；其他角色默认最多 2 次。
- 角色截止时间覆盖预处理、共享限流等待、HTTP 重试和协议回退。
- ARQ 模式按 endpoint、协议和凭据身份使用 Redis 共享锁；inline 模式使用进程共享锁。
- 同步传输不能保证在取消瞬间中断，但请求返回后会重新检查截止时间与取消状态，
  超时或取消结果不会进入最终提交。

出现失败时先比较 `request_count` 与 `retry_count`：前者是实际出站请求总数，后者仅统计
真正发出的重试请求。`LlmRequestBudgetExceeded` 表示请求次数已耗尽；
`LlmRequestDeadlineExceeded` 表示角色总截止时间已耗尽。

## 本地验证

协议与预算回归不需要真实凭据：

```powershell
uv run --project apps/api pytest `
  apps/api/tests/test_llm_proxy.py `
  apps/api/tests/test_llm_concurrency.py `
  apps/api/tests/test_langgraph_migration.py -q
```

真实端点只使用专用测试账号，并按
[`langgraph-rollout-runbook.md`](E:/travel/docs/langgraph-rollout-runbook.md) 的网络双重确认、
token 单价和小样本限制执行。不要把 API key 或完整模型输入写进 checkpoint 或调试文档。
