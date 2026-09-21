# LangGraph 迁移验证记录（2026-09-20）

分支：`codex/langchain-migration`

本记录对应 `langchain-migration-plan-2026-09-20.md` 的 P0–P5。代码层迁移与旧运行时清理
已经完成；生产放量仍须完成本文末尾的外部环境门禁。

## 已完成范围

- 生成与微调统一使用后端 LangGraph 工作流；浏览器编排器已删除。
- 六角色生成图、微调图、一次修复、证据核验与结果装配已经接入中立业务核心。
- 业务 Pydantic Schema 已从编排核心提取到 `services/planning/role_models.py`，API 探针、
  脚本与测试均改用中立模块；角色输入压缩位于 `services/planning/payloads.py`，POI 探针
  不再实例化编排核心或调用其私有实现；结果转换、地图关联及最终 trace 装配已提取到
  `services/planning/result_builder.py`，工作流不再承载产品模型转换算法。
- `WorkflowRun`、SQLite/PostgreSQL checkpointer、恢复指纹、取消、重试预算、版本冲突与幂等提交已经落地。
- HTTP 请求总数和跨重试/协议回退的总截止时间在角色级硬限制；生产环境和 ARQ 模式使用
  Redis 共享端点/凭据限流，本地 inline 模式在进程内共享。取消在模型请求前再次检查。
- 搜索角色的共享限流排队预算与获锁后的请求预算分开计算，并共同形成有界的角色墙钟上限；
  同一并行批次共享端点时，兄弟角色排队不会再吞掉后续角色的完整请求预算。最终 planner/refiner
  使用 300 秒最小请求预算和 420 秒上限，以覆盖真实端点上的长结构化行程输出。
- PostgreSQL checkpointer 初始化使用数据库 advisory lock，避免多个 Worker 首次启动时并发执行
  checkpoint schema migration；Compose 显式给 API/worker 注入同一个 PostgreSQL checkpoint URL，
  生产配置拒绝 SQLite 等进程本地 checkpoint 存储。
- trace 持久化角色请求标识、端点、协议、耗时、usage、实际重试/请求次数与缓存复用；
  恢复时按稳定 request ID 标记复用节点。失败调用保留原始异常类型供任务重试分类，并把
  脱敏 request ID、耗时、usage、实际重试/请求次数写入角色失败日志。回放脚本可按显式
  token 单价计算已知费用，缺少 usage 时保持未知。
- 首次生成/微调时间固定写入 Job payload，ARQ 自动重试和手动生成恢复复用相同时间，避免
  时间漂移改变 input fingerprint；用户主动创建的新 Job 则重新获取证据。
- 微调 scope/day_index 组合在 HTTP 路由与工作流入口双层校验，旧任务载荷或内部调用无法
  绕过范围约束后再触发模型请求。
- 恢复绑定会同时校验用户、行程和执行记录关联；跨用户复用已知 `run_id` 会被拒绝。
- provider 灰度按 Job ID 稳定分桶，任务首次执行后固定 provider；双向灰度切换不会改变已有
  Job 快照，已有 `WorkflowRun` 的 provider 优先于冲突的 Job 快照；回滚使用 `standard` 或保留部署版本。
- 30 组受控时钟回放、协议矩阵和质量/延迟/费用门禁已经实现；门禁默认要求
  `retained-deployment` baseline 与 `langgraph` candidate，拒绝混合 provider 结果；
  baseline/candidate 还必须携带一致的脱敏配置指纹，覆盖六角色端点、凭据身份、模型、协议及
  wire API，防止不同角色路由的结果被错误比较；
  `day_plan` 案例会拒绝旧 scope 值，并把目标日之外的任何改动计为硬违规。保留
  HelloAgents trace 没有 token usage 时，发布门禁只接受显式提供的隔离账单总费用，仍不会
  把缺失费用当成零。
- `hello-agents` 包、旧 orchestrator/LLM adapter、旧 prompt 模块、浏览器 planner 与旧专用脚本已经删除。
- API 与 worker 锁文件均已移除 `hello-agents` 及其不再需要的传递依赖。

历史数据兼容性仍刻意保留：旧 provider 值会归一化到 `langgraph`，旧 trace 可在 UI 中读取；
prompt 版本和部分日志事件继续使用原有字符串，因为它们参与 checkpoint 指纹或运维查询。
这些字符串不代表旧包仍在运行。

## 本分支验证结果

| 检查 | 结果 |
| --- | --- |
| API 全量测试 | `311 passed`（连接隔离的 PostgreSQL 16 测试库，无跳过项） |
| PostgreSQL Alembic 升降级与 checkpoint 跨连接恢复 | `3 passed` |
| SQLite 空库/旧库升级及 `0005` 降级重升 | 通过 |
| 现有 SQLite 用户库备份、`0004` → `0005` 与排空审计 | 完整性正常、schema 就绪、无阻塞 Job/Run |
| LangGraph、共享限流、恢复、存储与灰度定向测试 | `38 passed` |
| 前端单元测试 | `10 passed` |
| 前端生成/微调与鉴权 E2E（Chromium） | `4 passed` |
| 前端生产构建（`vue-tsc` + Vite） | 通过 |
| API 源码与测试 `compileall` | 通过 |
| API/worker `uv lock` 与 `uv sync --locked` | 通过 |
| worker 启动恢复、心跳、任务执行及 ARQ 重试映射烟测 | `4 passed` |
| 安装环境中 `hello_agents` 模块不存在 | 通过 |
| Windows 本地启动脚本语法解析 | 通过 |
| 正确生产角色映射的 LangGraph 真实端点单例预检 | `1/1` 成功、零硬违规，约 `440.3s` |
| 同配置保留部署单例对照 | `helloagents` 角色执行 `RuntimeError`，约 `378.3s`；非认证、配额、限流、超时或网络错误 |
| 本次限流/截止时间修复定向测试 | `64 passed` |
| 本次修复后的 API 本地全量回归 | `314 passed`（连接隔离的 PostgreSQL 16 测试库，无跳过项） |

本次使用隔离的 Docker PostgreSQL 16 测试库设置 `TRAVELMIND_TEST_POSTGRES_URL`，完成
upgrade → downgrade → upgrade，并验证 LangGraph checkpoint 跨 PostgreSQL 连接恢复且不重跑
已成功节点。首次运行发现 advisory lock 查询触发的 SQLAlchemy 2 隐式事务会包住 Alembic
迁移，导致连接关闭时回滚 DDL；迁移环境现已在加锁后显式提交，并在解锁后结束事务。

## 发布前必须完成的外部门禁

1. 在目标数据库先执行迁移，再运行
   `scripts/audit_workflow_rollout.py --require-drained`。必须得到
   `schema_ready_for_langgraph=true`、空 `schema_blockers`，且没有 legacy/unknown 阻塞任务。
2. 使用专用测试凭据运行少量真实 Responses、Chat/Gemini/Claude/NewAPI/NeiAPI/Grok 样本，
   再以保留部署生成的 baseline 执行完整 30 案例质量门禁。2026-09-21 已使用原项目最近一套
   完整生产角色映射完成 1 条 LangGraph 真实端点预检；完整协议样本、同配置保留部署 baseline、
   30 条 candidate 和精确费用对比仍未完成。同案例的保留部署单例在角色执行阶段失败，已作为
   baseline 诊断保留，但单例不能替代完整 baseline。只配置主模型、导致所有角色回退到同一模型的
   早期诊断结果已标记为无效，不作为发布证据。
3. 完成上述门禁后再逐级放量 5% → 25% → 50% → 100%，并按 runbook 观察成功率、硬约束、
   p95 延迟和费用。

2026-09-21 经用户明确授权，先使用 SQLite 在线备份保存本机持久化数据库，再将原库从
`0004_search_role_models` 升级到 `0005_workflow_runs`。升级后 `PRAGMA integrity_check` 返回
`ok`，`workflow_runs` 与 `job_records.workflow_run_id` 均存在；排空审计得到
`schema_ready_for_langgraph=true`、空 `schema_blockers`、零阻塞 Job/Run 和
`safe_to_remove_legacy_runtime=true`。备份保留在忽略的运行时目录中，没有纳入 Git。
