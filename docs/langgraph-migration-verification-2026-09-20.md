# LangGraph 迁移验证记录（2026-09-20）

分支：`codex/langchain-migration`

本记录对应 `langchain-migration-plan-2026-09-20.md` 的 P0–P5。代码层迁移与旧运行时清理
已经完成；生产放量仍须完成本文末尾的外部环境门禁。

## 已完成范围

- 生成与微调统一使用后端 LangGraph 工作流；浏览器编排器已删除。
- 六角色生成图、微调图、一次修复、证据核验与结果装配已经接入中立业务核心。
- 业务 Pydantic Schema 已从编排核心提取到 `services/planning/role_models.py`，API 探针、
  脚本与测试均改用中立模块；结果转换、地图关联及最终 trace 装配已提取到
  `services/planning/result_builder.py`，工作流不再承载产品模型转换算法。
- `WorkflowRun`、SQLite/PostgreSQL checkpointer、恢复指纹、取消、重试预算、版本冲突与幂等提交已经落地。
- HTTP 请求总数和跨重试/协议回退的总截止时间在角色级硬限制；生产环境和 ARQ 模式使用
  Redis 共享端点/凭据限流，本地 inline 模式在进程内共享。取消在模型请求前再次检查。
- PostgreSQL checkpointer 初始化使用数据库 advisory lock，避免多个 Worker 首次启动时并发执行
  checkpoint schema migration；Compose 显式给 API/worker 注入同一个 PostgreSQL checkpoint URL，
  生产配置拒绝 SQLite 等进程本地 checkpoint 存储。
- trace 持久化角色请求标识、端点、协议、耗时、usage、实际重试/请求次数与缓存复用；
  恢复时按稳定 request ID 标记复用节点。回放脚本可按显式 token 单价计算已知费用，
  缺少 usage 时保持未知。
- 首次生成/微调时间固定写入 Job payload，ARQ 自动重试和手动生成恢复复用相同时间，避免
  时间漂移改变 input fingerprint；用户主动创建的新 Job 则重新获取证据。
- 恢复绑定会同时校验用户、行程和执行记录关联；跨用户复用已知 `run_id` 会被拒绝。
- provider 灰度按 Job ID 稳定分桶，任务首次执行后固定 provider；回滚使用 `standard` 或保留部署版本。
- 30 组受控时钟回放、协议矩阵和质量/延迟/费用门禁已经实现。
- `hello-agents` 包、旧 orchestrator/LLM adapter、旧 prompt 模块、浏览器 planner 与旧专用脚本已经删除。
- API 与 worker 锁文件均已移除 `hello-agents` 及其不再需要的传递依赖。

历史数据兼容性仍刻意保留：旧 provider 值会归一化到 `langgraph`，旧 trace 可在 UI 中读取；
prompt 版本和部分日志事件继续使用原有字符串，因为它们参与 checkpoint 指纹或运维查询。
这些字符串不代表旧包仍在运行。

## 本分支验证结果

| 检查 | 结果 |
| --- | --- |
| API 全量测试 | `290 passed, 2 skipped`（本机无 PostgreSQL） |
| SQLite 空库/旧库升级及 `0005` 降级重升 | 通过 |
| 请求预算/截止时间、共享限流、恢复与 LangGraph 定向测试 | `61 passed` |
| 前端单元测试 | `10 passed` |
| 前端生成/微调与鉴权 E2E（Chromium） | `4 passed` |
| 前端生产构建（`vue-tsc` + Vite） | 通过 |
| API 源码与测试 `compileall` | 通过 |
| API/worker `uv lock` 与 `uv sync --locked` | 通过 |
| worker 导入及函数注册 | 通过 |
| 安装环境中 `hello_agents` 模块不存在 | 通过 |
| Windows 本地启动脚本语法解析 | 通过 |

API 全量测试中两个跳过项是 PostgreSQL Alembic 循环与 PostgreSQL LangGraph checkpoint
跨连接恢复测试：本机未配置 `TRAVELMIND_TEST_POSTGRES_URL`，Docker daemon 与本地 5432
端口也未运行。GitHub Actions 的 API job 已配置 PostgreSQL 16 service 和该环境变量，因此
这两项属于 CI 强制门禁，而不是永久跳过测试。

## 发布前必须完成的外部门禁

1. 在一次性 PostgreSQL 测试库设置 `TRAVELMIND_TEST_POSTGRES_URL`，运行
   `apps/api/tests/test_postgres_migrations.py`，确认迁移头为 `0005_workflow_runs`，完成
   upgrade → downgrade → upgrade，并验证 LangGraph checkpoint 跨 PostgreSQL 连接恢复且不重跑
   已成功节点。
2. 在目标数据库先执行迁移，再运行
   `scripts/audit_workflow_rollout.py --require-drained`。必须得到
   `schema_ready_for_langgraph=true`、空 `schema_blockers`，且没有 legacy/unknown 阻塞任务。
3. 使用专用测试凭据运行少量真实 Responses、Chat/Gemini/Claude/NewAPI/NeiAPI/Grok 样本，
   再以保留部署生成的 baseline 执行完整 30 案例质量门禁。当前工作区未配置模型凭据，
   因而没有伪造这项结果。
4. 完成上述门禁后再逐级放量 5% → 25% → 50% → 100%，并按 runbook 观察成功率、硬约束、
   p95 延迟和费用。

本机现有持久化 SQLite 数据库仍停留在 `0005` 之前。只读排空审计显示没有活跃任务，
但因缺少 `workflow_runs` 和 `job_records.workflow_run_id` 而返回不安全；验证过程没有擅自迁移
这份用户数据。
