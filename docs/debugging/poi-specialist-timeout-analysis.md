# POI Specialist 超时问题分析报告

## 问题描述
Job `job_a8fe1aedd2569a45f7a0` 在执行 poi_specialist 角色时超时（242.3秒），最终导致整个行程生成失败。

## 时间线分析

### 阶段1: 工具收集（Tool Collection）
- **14:08:49** - POI specialist 开始并行工具收集
- **14:08:51** - 检测到 groksearch 提供者，选择 `web_search` 工具
- **14:10:51** - 工具收集完成，耗时 **120.048 秒**
- **结果**: `tool_result_keys: []` （**空的！**）

### 阶段2: LLM 推理（超时发生在这里）
- **14:10:51** - POI specialist 角色开始调用 LLM（mimo-v2-pro @ token-plan-cn.xiaomimimo.com）
- **输入**: 包含空的 `tool_results: {}`
- **14:14:54** - LLM 调用超时，耗时 **242.25 秒**
- **错误**: `timed out after 242.3s`

## 根本原因分析

### 1. Grok 调用成功，但返回了超大响应！

根据 API 调用记录：
```
时间: 2026-06-16 22:10:35
提供者: grok
模型: grok-4.20-multi-agent-xhigh
耗时: 102s (总计) + 76.8s
输出: 1,658,870 字符 ⚠️
Token消耗: 92,741
状态: 流式完成 ✅
```

**关键发现**: 
- POI specialist 发送的 payload 只有 **1519 字节**（日志第20行）
- Grok 却返回了 **165 万字符**的响应！
- 这个超大响应在解析或传递时失败，导致 `tool_results` 为空

### 2. 数据丢失的原因

查看代码流程：

```python
# search_connector.py: 278-283
def call_operation(self, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
    if self._config.transport == "api":
        return self._call_api_operation(name, arguments)
    if self._mcp_client is None:
        raise SearchServiceGatewayError("Search service client is not configured")
    return self._call_mcp_operation(name, arguments)  # ← 调用这里

# search_connector.py: 430-439
def _call_mcp_operation(self, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
    assert self._mcp_client is not None
    try:
        result = self._mcp_client.call_tool(name, arguments)  # ← MCP 调用
    except Exception as exc:
        raise SearchServiceGatewayError(str(exc)) from exc
    parsed = self._parse_mcp_result(result)  # ← 解析结果
    if self._config.provider == "groksearch" and name == "web_search":
        return self._maybe_enrich_groksearch_search_payload(parsed)  # ← 增强
    return parsed
```

```python
# helloagents.py: 1858-1952
def _collect_poi_tool_results(...) -> dict[str, Any]:
    # ...
    try:
        search_result = self._call_search_like_tool(client, search_tool, query, 10, role_name="poi_specialist")
    except Exception as exc:
        _LOGGER.warning("HelloAgents role=poi_specialist tool=%s failed=%s", search_tool, exc)
        return {}  # ← 如果出错，返回空字典！
    # ...
```

### 2. 为什么 Grok 会返回这么多内容？

查看搜索查询构建（helloagents.py: 1847-1852）：
```python
query_parts.append(
    "请直接综合全网信息，输出一个具名 POI 池，覆盖经典必去、古镇人文、自然风景、"
    "美食市集、咖啡餐厅、体验类和小众补充点。每个 POI 给出：名称、所在区域、类别、"
    "推荐理由、建议时段、票价或人均、评分与评论数（无据写 unknown）、预约或排队提示、来源链接。"
    "优先返回 JSON 结构，不要编造精确数字。"
)
```

**问题**:
1. 查询非常详细，要求"综合全网信息"
2. 没有限制返回的 POI 数量
3. 使用 `web_search` 而不是设定数量限制
4. Grok 可能抓取了大量网页内容并全部返回

### 3. 数据在哪个环节丢失？

**可能的问题点**:

1. **MCP 客户端缓冲区溢出**: 165万字符可能超过 HTTP 客户端的默认限制
2. **JSON 解析失败**: `_parse_mcp_result` 尝试解析超大 JSON 时失败（search_connector.py: 441-456）
3. **异常被静默捕获**: `_collect_poi_tool_results` 的 `except Exception` 捕获异常但只返回空字典（helloagents.py: 1929-1932）
4. **内存限制**: Python 进程可能因内存不足而丢弃响应
5. **超时**: 虽然 Grok 完成了，但传输 165万字符可能触发其他超时

### 3. 为什么 LLM 会超时？

当 `tool_results` 为空时，poi_specialist 提示词变成：
- 没有搜索结果
- 没有 POI 候选
- 只有用户需求和规划简报

LLM 可能：
1. 尝试凭空生成 POI 数据（需要大量推理）
2. 陷入某种生成循环
3. 模型本身响应缓慢
4. 超时设置（242秒）过长，应该更早失败

## 验证步骤

### 1. 检查是否有异常日志
```bash
grep -E "poi_specialist.*warn|poi_specialist.*error|web_search.*failed" /path/to/travelmind-api.log
```

### 2. 检查 grok 响应是否被正确接收
在 `search_connector.py` 的 `_call_mcp_operation` 方法中添加日志：
```python
def _call_mcp_operation(self, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
    result = self._mcp_client.call_tool(name, arguments)
    _LOGGER.info(f"MCP tool {name} raw result size: {len(json.dumps(result))}")  # 添加这行
    parsed = self._parse_mcp_result(result)
    _LOGGER.info(f"MCP tool {name} parsed result keys: {parsed.keys()}")  # 添加这行
    return parsed
```

### 3. 检查 JSON 解析性能
大型 JSON（165万字符）的解析可能很慢：
```python
import json
import time
start = time.time()
parsed = json.loads(large_text)  # 可能耗时数秒
print(f"Parse took {time.time() - start}s")
```

## 修复建议

### 短期修复（紧急）

1. **添加详细日志**
```python
# helloagents.py: 1928-1932
try:
    search_result = self._call_search_like_tool(client, search_tool, query, 10, role_name="poi_specialist")
    _LOGGER.info(f"POI search result keys: {search_result.keys() if isinstance(search_result, dict) else 'not a dict'}")
    _LOGGER.info(f"POI search result size: {len(json.dumps(search_result, ensure_ascii=False))}")
except Exception as exc:
    _LOGGER.error(f"HelloAgents role=poi_specialist tool={search_tool} failed: {exc}", exc_info=True)  # 添加 exc_info
    return {}
```

2. **减少 LLM 超时时间**
```python
# 当 tool_results 为空时，应该快速失败
if not tool_results:
    # 使用更短的超时（如60秒）或直接失败
    effective_timeout = 60.0
```

3. **提前检查 tool_results**
```python
# helloagents.py: 在 _run_role 之前
if role_name == "poi_specialist" and not enriched_payload.get("tool_results"):
    _LOGGER.warning("POI specialist has no tool results, skipping LLM call")
    # 返回默认结构或抛出更明确的错误
```

### 中期修复（优化）

1. **限制响应大小**
```python
# search_connector.py: _parse_mcp_result
def _parse_mcp_result(self, result: dict[str, Any] | Any) -> dict[str, Any]:
    content = result.get("content") if isinstance(result, dict) else None
    if isinstance(content, list):
        for item in content:
            if isinstance(item, dict) and item.get("type") == "text":
                text = item["text"].strip()
                if len(text) > 1_000_000:  # 限制为1MB
                    _LOGGER.warning(f"MCP result too large: {len(text)} chars, truncating")
                    text = text[:1_000_000]
                # ...
```

2. **添加重试逻辑**
```python
# 当 groksearch 返回空结果时，尝试 tavily 或其他 fallback
```

3. **优化搜索查询**
目前的查询太长（1200+ 字符），可能导致问题：
```python
# helloagents.py: 1847-1852
# 简化查询，移除过于详细的 JSON 结构要求
query_parts.append(
    "请综合全网信息，列出具名 POI，包括：名称、区域、类别、推荐理由、票价、评分。"
)
```

### 长期优化（架构）

1. **流式处理大响应**
2. **使用消息队列处理超大响应**
3. **分段请求（多次小查询 vs 一次大查询）**
4. **缓存 grok 搜索结果**

## 下一步行动

1. ✅ 添加详细日志以确认数据在哪个环节丢失
2. ⬜ 检查是否有 warning/error 日志被遗漏
3. ⬜ 测试 165万字符 JSON 的解析性能
4. ⬜ 实现 tool_results 为空时的快速失败机制
5. ⬜ 优化搜索查询长度和复杂度
