# 开发说明

## 从哪里开始

- [项目中文首页](../README.md)：功能、体验地址、技术栈和本地启动摘要。
- [完整本地运行指南](local-development.md)：离线演示、真实模型、Worker 和 Docker Compose。
- [系统架构](architecture.md)、[接口概览](api-overview.md)：理解前后端分工与任务流程。

## 本地默认行为

- API 默认数据库为 `storage/travelmind.db`（SQLite）。
- 任务默认使用 `inline` 模式；配置 `TRAVELMIND_QUEUE_MODE=arq` 后需启动 Redis 和 Worker。
- 导出文件写入 `storage/exports`；不要提交数据库、私人导出和真实账户信息。
- 建议先用 `TRAVELMIND_AGENT_PROVIDER=stub` 跑通流程，再配置真实模型和搜索服务。离线示例不代表真实模型生成质量。

## 常用检查

```powershell
npm run test:web:unit
npm run build:web
npm run test:web:e2e
uv run --project apps/api pytest apps/api/tests -q
```

PostgreSQL 专项需单独提供 `TRAVELMIND_TEST_POSTGRES_URL`。测试迁移循环可能清空测试库，只能指向独立测试数据库，不能指向生产业务库。

## 部署与发布

当前线上采用 VPS 容器部署：Web、API、Worker、PostgreSQL、Redis 和搜索桥接按各自边界运行，具体见 [部署运维](vps-deployment.md)。也可根据自身环境选择其他容器平台，不代表本项目同时部署在所有平台。

发布前应运行 LangGraph 回放质量检查和任务排空审计，保留上一版本作为回退点。前端和后端可分别更新；推送 GitHub 代码不会自动保证线上页面已经切换。

## 公开账户与本地实验

公开账户仅有共享的 5 次生成额度，维护方式见 [体验账户说明](public-demo.md)。未完成实验应与可发布版本隔离，不要把临时输出、供应商原始响应、日志、API Key 或私钥提交到仓库。
