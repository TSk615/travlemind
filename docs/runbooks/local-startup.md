# 后端启动命令速查

## 1. 环境变量配置

在 `E:\travel\.env` 文件中添加(如果文件不存在就创建):

```env
# === LLM 配置 ===
TRAVELMIND_LLM_BASE_URL=https://token-plan-cn.xiaomimimo.com/v1
TRAVELMIND_LLM_API_KEY=你的 mimo API key
TRAVELMIND_LLM_MODEL=mimo-v2-pro

# === GrokSearch 配置 ===
TRAVELMIND_GROKSEARCH_COMMAND=grok-search
TRAVELMIND_GROKSEARCH_BRIDGE_API_KEY=change-this-bridge-key
TRAVELMIND_GROKSEARCH_BRIDGE_BASE_URL=http://127.0.0.1:8085/mcp
TRAVELMIND_GROKSEARCH_BRIDGE_TIMEOUT_SECONDS=30
TRAVELMIND_SEARCH_PROVIDER=groksearch
TRAVELMIND_SEARCH_MCP_SERVER_NAME=groksearch

# === Grok API 密钥(至少配一个) ===
GUDA_API_KEY=你的 GUDA API key (如果有)
GROK_API_KEY=你的 Grok API key (如果有)
GROK_API_URL=https://api.x.ai/v1
GROK_MODEL=Web/grok-chat-fast

# === Tavily 搜索(可选) ===
TAVILY_ENABLED=true
TAVILY_API_KEY=你的 Tavily API key (如果有)

# === Maps Provider ===
TRAVELMIND_MAPS_PROVIDER=stub
```

## 2. GrokSearch 初始化(首次使用)

```powershell
cd E:\travel
.\scripts\setup-groksearch-local.ps1 -PrintEnvTemplate
```

这个脚本会:
- 安装 groksearch-bridge 依赖
- 安装上游 GrokSearch (GuDaStudio/GrokSearch@grok-with-tavily)
- 验证 `grok-search` 命令可用
- 检查必需的 API keys

## 3. 启动服务(3个窗口)

### 窗口 1: GrokSearch Bridge

```powershell
cd E:\travel
uv run --project apps/groksearch-bridge uvicorn travelmind_groksearch_bridge.main:app --host 127.0.0.1 --port 8085
```

**验证**: 访问 http://127.0.0.1:8085/health 应该返回 OK

### 窗口 2: API Server

```powershell
cd E:\travel
uv run --project apps/api uvicorn travelmind_api.main:app --reload --host 127.0.0.1 --port 8000
```

**验证**: 访问 http://127.0.0.1:8000/health 应该返回健康状态

### 窗口 3: Worker(可选,如果要异步执行)

```powershell
cd E:\travel
$env:TRAVELMIND_REDIS_URL="redis://127.0.0.1:6379/0"
uv run --project apps/worker python -m travelmind_worker.worker
```

**注意**: Worker 需要 Redis,如果没装 Redis 可以跳过这步,API 会同步执行任务。

## 4. 快速测试 GrokSearch

```powershell
# 测试 bridge 是否能调用 Grok
curl http://127.0.0.1:8085/mcp/test-search
```

## 常见问题

### Q: GUDA_API_KEY 和 GROK_API_KEY 有什么区别?

- **GUDA_API_KEY**: GuDa Studio 提供的 Grok API 代理服务密钥
- **GROK_API_KEY**: X.AI 官方 Grok API 密钥

至少配置一个即可,GrokSearch 会优先使用 GUDA。

### Q: 为什么需要 GrokSearch Bridge?

因为 TravelMind API 通过 MCP 协议调用搜索工具,Bridge 把上游 GrokSearch CLI 暴露为 MCP server。

### Q: 没有 Grok API key 怎么办?

可以临时用 stub 模式测试其他逻辑:

```env
TRAVELMIND_SEARCH_PROVIDER=stub
```

但这样 POI specialist 拿到的搜索结果是假数据。

### Q: 启动报错 "grok-search command not found"

运行初始化脚本:
```powershell
.\scripts\setup-groksearch-local.ps1
```

### Q: 我只想测试后端,不关心 Web 前端

只启动窗口 1(Bridge) 和窗口 2(API) 即可,然后用 curl/Postman 调用 API。

## 5. 验证完整流程

```powershell
# 注册用户
curl -X POST http://127.0.0.1:8000/auth/register `
  -H "Content-Type: application/json" `
  -d '{"email":"test@example.com","password":"test123456","name":"Test"}'

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
    "title": "广州去大理测试",
    "origin": "广州",
    "destination": "大理",
    "start_date": "2026-06-10",
    "end_date": "2026-06-14",
    "budget": 6800,
    "travelers": 2,
    "interests": ["美食", "城市漫步", "海边风景"],
    "accommodation_preference": "靠近市区",
    "pace": "balanced",
    "transport_mode": "rail"
  }' | ConvertFrom-Json

$tripId = $tripResponse.data.id

# 触发生成
curl -X POST "http://127.0.0.1:8000/trips/$tripId/generate" `
  -H "Authorization: Bearer $token"

# 查看最新日志
Start-Sleep -Seconds 180
Get-ChildItem E:\travel\logs\jobs\*.jsonl | Sort-Object LastWriteTime -Descending | Select-Object -First 1 | Get-Content | Select-String "langgraph_role_started|langgraph_role_completed|langgraph_role_failed"
```
