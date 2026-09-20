# LangGraph 迁移验证记录（2026-09-20）

分支：`codex/langchain-migration`

本记录对应 `langchain-migration-plan-2026-09-20.md` 的 P0–P5。代码层迁移与旧运行时清理
已经完成；生产放量仍须完成本文末尾的外部环境门禁。

## 已完成范围

- 生成与微调统一使用后端 LangGraph 工作流；浏览器编排器已删除。
- 六角色生成图、微调图、一次修复、证据核验与结果装配已经接入中立业务核心。
- `WorkflowRun`、SQLite/PostgreSQL checkpointer、恢复指纹、取消、重试预算、版本冲突与幂等提交已经落地。
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
| API 全量测试 | `276 passed, 1 skipped` |
| SQLite 空库/旧库升级及 `0005` 降级重升 | 通过 |
| LangGraph、rollout、迁移和 orchestrator 定向测试 | `71 passed, 1 skipped` |
| 前端单元测试 | `10 passed` |
| 前端生产构建（`vue-tsc` + Vite） | 通过 |
| API 源码与测试 `compileall` | 通过 |
| API/worker `uv lock` 与 `uv sync --locked` | 通过 |
| worker 导入及函数注册 | 通过 |
| 安装环境中 `hello_agents` 模块不存在 | 通过 |
| Windows 本地启动脚本语法解析 | 通过 |

API 全量测试中唯一跳过项是 PostgreSQL 迁移测试：本机未配置
`TRAVELMIND_TEST_POSTGRES_URL`，Docker daemon 与本地 5432 端口也未运行。

## 发布前必须完成的外部门禁

1. 在一次性 PostgreSQL 测试库设置 `TRAVELMIND_TEST_POSTGRES_URL`，运行
   `apps/api/tests/test_postgres_migrations.py`，确认迁移头为 `0005_workflow_runs`，并完成
   upgrade → downgrade → upgrade。
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
