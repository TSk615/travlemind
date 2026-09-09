# Grok POI 轻量版改动测试指南

## 改动已完成

已应用 5 处轻量版改动到代码中,文件均已保存到 `E:\travel`:

1. ✅ `apps/api/src/travelmind_api/agents/helloagents.py` - GrokSearch answer 分支 + 回落逻辑
2. ✅ `apps/api/src/travelmind_api/prompts/roles/helloagents.py` - prompt 从「发现」改为「整理」
3. ✅ stub 候选 POI 已禁用
4. ✅ 新增可观测性日志事件 `helloagents_poi_answer_received`
5. ✅ 编译验证通过

## 测试目标

验证:
- POI specialist 不再超时(之前 242s)
- Grok `answer` 工具能直接综合出结构化 POI 池(`poi_source=grok_answer`)
- mimo 作为 JSON 规整器(而非 POI 发现者)能正常工作
- 回落路径(`web_search`+crawl)在 answer 失败时正常触发

## 在本地 Host 环境测试

### 方式 1: API + curl 触发(推荐)

#### 1. 启动 API server

```powershell
cd E:\travel
$env:TRAVELMIND_LLM_BASE_URL="https://token-plan-cn.xiaomimimo.com/v1"
$env:TRAVELMIND_LLM_API_KEY="你的 API key"
$env:TRAVELMIND_LLM_MODEL="mimo-v2-pro"
$env:TRAVELMIND_SEARCH_PROVIDER="groksearch"
$env:TRAVELMIND_SEARCH_MCP_SERVER_NAME="groksearch"
$env:TRAVELMIND_MAPS_PROVIDER="stub"

uv run --project apps/api uvicorn travelmind_api.main:app --reload --host 127.0.0.1 --port 8000
```

#### 2. 创建测试 trip (新开一个 PowerShell 窗口)

```powershell
# 先注册/登录获取 token (如果还没有)
curl -X POST http://127.0.0.1:8000/auth/register `
  -H "Content-Type: application/json" `
  -d '{"email":"test@example.com","password":"test123456","name":"Test User"}'

# 登录获取 token
$response = curl -X POST http://127.0.0.1:8000/auth/login `
  -H "Content-Type: application/json" `
  -d '{"email":"test@example.com","password":"test123456"}' | ConvertFrom-Json

$token = $response.data.access_token

# 创建 trip
$tripResponse = curl -X POST http://127.0.0.1:8000/trips `
  -H "Authorization: Bearer $token" `
  -H "Content-Type: application/json" `
  -d '{
    "title": "广州出发去大理",
    "origin": "广州",
    "destination": "大理",
    "start_date": "2026-06-10",
    "end_date": "2026-06-14",
    "budget": 6800,
    "travelers": 2,
    "interests": ["美食", "城市漫步", "海边风景"],
    "accommodation_preference": "靠近市区、方便步行觅食的酒店",
    "pace": "balanced",
    "transport_mode": "rail"
  }' | ConvertFrom-Json

$tripId = $tripResponse.data.id
Write-Host "Trip ID: $tripId"

# 触发生成
curl -X POST "http://127.0.0.1:8000/trips/$tripId/generate" `
  -H "Authorization: Bearer $token"
```

#### 3. 查看生成日志

```powershell
# 等待任务完成(约 3-5 分钟)
Start-Sleep -Seconds 180

# 找到最新的 job log
Get-ChildItem E:\travel\logs\jobs\job_*.jsonl | Sort-Object LastWriteTime -Descending | Select-Object -First 1
```

### 方式 2: 直接用 Python 脚本

如果本地环境有完整依赖,可以直接运行:

```powershell
cd E:\travel
$env:TRAVELMIND_LLM_BASE_URL="https://token-plan-cn.xiaomimimo.com/v1"
$env:TRAVELMIND_LLM_API_KEY="你的 API key"
$env:TRAVELMIND_SEARCH_PROVIDER="groksearch"

uv run --project apps/api python scripts/debug/test_grok_poi_generation.py
```

## 验证要点

### 1. 检查 poi_specialist 是否走 answer 路径

```powershell
$latestLog = Get-ChildItem E:\travel\logs\jobs\job_*.jsonl | Sort-Object LastWriteTime -Descending | Select-Object -First 1
Get-Content $latestLog | Select-String "helloagents_poi_answer_received"
```

如果看到这个事件,说明 Grok answer 路径成功触发。

### 2. 检查 poi_source

```powershell
Get-Content $latestLog | Select-String "poi_source"
```

期望看到:
- `"poi_source": "grok_answer"` — answer 路径成功
- `"poi_source": "web_search_crawl"` — 回落到 web_search 路径

### 3. 检查 poi_specialist 耗时

```powershell
Get-Content $latestLog | Select-String "poi_specialist.*elapsed"
```

应该远低于之前的 242s。

### 4. 检查 featured_poi_count

```powershell
Get-Content $latestLog | Select-String "featured_poi_count"
```

应该 > 0,说明 POI 池被成功提取并规整。

### 5. 完整 output_snapshot

```powershell
# 提取 poi_specialist 的 output_snapshot
Get-Content $latestLog | Select-String "helloagents_poi_specialist_output_snapshot" | ConvertFrom-Json | ConvertTo-Json -Depth 10
```

## 预期结果

**成功场景**:
- ✅ poi_specialist 耗时 < 120s (不再超时)
- ✅ 日志中出现 `helloagents_poi_answer_received` 事件
- ✅ `poi_source=grok_answer`
- ✅ `featured_poi_count` > 5
- ✅ 生成的行程包含具名 POI(不是 "Stub POI for 大理")

**回落场景**(如果 Grok answer 调用失败):
- ✅ 自动回落到 `web_search`+crawl 路径
- ✅ `poi_source=web_search_crawl`
- ✅ 仍能生成完整行程

## 对比参考

之前失败的 job: `E:\travel\logs\jobs\job_637b7132ccd938bae4d2.jsonl`
- poi_specialist 超时 242.3s
- candidate_pois 全是 stub 数据
- role_failed: timeout

新的生成应该完全避免这些问题。

## 遇到问题

如果测试遇到问题,收集以下信息:

1. 最新 job log 完整内容
2. API server 控制台输出
3. `helloagents_poi_answer_received` 事件是否出现
4. poi_specialist 的 input_snapshot 和 output_snapshot

把这些信息发给我,我继续分析。
