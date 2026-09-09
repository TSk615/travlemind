你的 POI specialist 超时了，但工具调用**其实成功了**（走的是 `web_search + crawl` 回落路径），只是 **Grok answer 路径没触发**。

## 问题诊断

从日志看：
- ✅ 工具调用成功（耗时 139s）
- ✅ 拿到了 search/crawl 结果（`tool_result_keys` 有 7 个字段）
- ❌ **没有** `helloagents_poi_answer_received` 事件 → answer 路径没走
- ❌ mimo 等待 LLM 响应超时 242s → 可能是拿到的 tool_results 太大或格式有问题

## 可能原因

### 1. GrokSearch MCP 没提供 `answer` 工具

代码优先级：`("web_search", "answer", "search")`

如果 `available_tools` 里有 `web_search` 但没有 `answer`，就会选 `web_search` 而不是 `answer`。

**验证方法**：检查 GrokSearch Bridge 是否正常启动并暴露了 `answer` 工具。

```powershell
# 测试 GrokSearch Bridge 工具列表
curl http://127.0.0.1:8085/mcp/list-tools

# 或者看 Bridge 启动日志，应该显示注册了哪些工具
```

期望看到类似：
```json
{
  "tools": [
    {"name": "web_search", ...},
    {"name": "answer", ...},
    {"name": "web_fetch", ...},
    ...
  ]
}
```

### 2. `answer` 工具调用失败被静默吞掉

看代码 1878-1905 行，如果 `answer_tool == "answer"` 但调用时抛异常，会 `_LOGGER.warning` 后直接进入回落路径。

但日志里**没有**任何 warning，说明：
- 要么 `answer_tool` 根本不是 `"answer"`（选了 `web_search`）
- 要么代码根本没进入 answer 分支（`_is_groksearch_provider` 返回 False）

### 3. Search provider 配置不对

检查环境变量：
```powershell
# 确认这些变量设对了
$env:TRAVELMIND_SEARCH_PROVIDER
$env:TRAVELMIND_SEARCH_MCP_SERVER_NAME
```

应该是：
```
TRAVELMIND_SEARCH_PROVIDER=groksearch
TRAVELMIND_SEARCH_MCP_SERVER_NAME=groksearch
```

如果是其他值（比如 `stub`），`_is_groksearch_provider` 会返回 False，永远不会尝试 answer。

## 建议操作

### 方案 1: 加详细日志确认问题（推荐）

我给代码加几行调试日志，重新跑一次，看：
1. `_is_groksearch_provider` 返回什么
2. `available_tools` 里有哪些工具
3. `_pick_search_tool` 选中了什么工具

要我加吗？

### 方案 2: 直接检查 GrokSearch Bridge

```powershell
# 窗口 1: 重启 Bridge，看启动日志
cd E:\travel
uv run --project apps/groksearch-bridge uvicorn travelmind_groksearch_bridge.main:app --host 127.0.0.1 --port 8085

# 窗口 2: 测试工具列表
curl http://127.0.0.1:8085/health
curl http://127.0.0.1:8085/mcp/list-tools
```

把输出发给我。

### 方案 3: 检查 API 启动时的环境变量

API server 启动日志里应该有 search provider 配置的输出。找一下有没有类似：
```
INFO: Search provider: groksearch
INFO: MCP server: groksearch
```

## 关于 242s 超时

即使走回落路径（web_search+crawl）也不应该让 mimo 超时。可能是：
- crawl 返回的网页内容太大（几十 MB），mimo 处理不过来
- 网络问题导致 crawl 卡住
- mimo API 本身慢

要我先加日志诊断，还是你直接检查 Bridge？
