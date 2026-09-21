# LangGraph 灰度、回滚与旧运行时排空

本手册对应迁移计划 P5。灰度选择只发生在 Job 第一次执行前，结果会写入
`job_records.payload_json.workflow_provider`。重试复用该快照；已经创建的 LangGraph
`WorkflowRun` 还会固定 graph/schema 版本，不受后续环境变量变化影响。

## 配置

- `TRAVELMIND_AGENT_PROVIDER=langgraph`：让新生成和微调任务进入灰度选择。
- `TRAVELMIND_LANGGRAPH_ROLLOUT_PERCENT=0..100`：按 Job ID 的稳定哈希分桶。
- `TRAVELMIND_LANGGRAPH_ROLLOUT_FALLBACK_PROVIDER=standard`：未命中灰度桶时使用后端单模型实现。旧实现移除后的应用级回滚使用保留部署版本。

不要在同一个运行中修改 provider 或 graph version。切换配置只影响尚未执行且没有
provider 快照的新 Job。

## 放量顺序

1. 运行固定模拟回放与协议兼容测试，质量门禁必须通过。
2. 使用专用测试账号执行少量真实端点样本；记录模型、协议、延迟、费用与失败原因，不保存比较分支的行程，也不触发图片任务。
3. 将灰度从 5% 依次提高到 25%、50%、100%。每一级至少观察一个完整业务周期，核对成功率、硬约束违规、p95 延迟和费用。
4. 100% 后继续保留旧部署版本和向后兼容数据库迁移，直到回滚窗口结束。

## 固定回放与协议矩阵

回放数据位于 `apps/api/tests/fixtures/langgraph-replay-cases.json`，包含 30 个使用受控时钟的案例。直接执行 orchestrator 的脚本不会保存 Trip，也不会派发图片任务；网络调用需要命令行参数和环境变量双重确认：

```powershell
$env:TRAVELMIND_REPLAY_ALLOW_NETWORK = "1"
$env:TRAVELMIND_REPLAY_INPUT_COST_PER_MILLION = "<input-token-price>"
$env:TRAVELMIND_REPLAY_OUTPUT_COST_PER_MILLION = "<output-token-price>"
## 在仍包含旧实现的保留部署 checkout 中运行该版本的脚本；产物 provider 为 helloagents。
uv run --project apps/api python scripts/run_workflow_replay.py --provider helloagents --output <migration-checkout>/.tmp/replay/baseline.json --allow-network
## 回到迁移 checkout；保持 baseline 使用的模型环境变量不变，为旧版产物补充脱敏配置指纹。
uv run --project apps/api python scripts/stamp_workflow_replay_config.py --artifact .tmp/replay/baseline.json
## 生成 LangGraph candidate；当前脚本会自动写入配置指纹。
uv run --project apps/api python scripts/run_workflow_replay.py --provider langgraph --output .tmp/replay/candidate.json --allow-network
uv run --project apps/api python scripts/evaluate_workflow_replay.py --baseline .tmp/replay/baseline.json --candidate .tmp/replay/candidate.json --expected-baseline-provider helloagents --baseline-total-cost-usd <isolated-baseline-billing-total>
```

回放脚本通过 `LlmConfig.from_env()` 装配模型。若生产账号为搜索角色保存了独立端点或模型，
必须同时提供对应的 `TRAVELMIND_LLM_ROLE_<ROLE>_BASE_URL`、`API_KEY`、`MODEL`、
`WIRE_API` 和 `PROVIDER_PROTOCOL`，其中 `<ROLE>` 为 `POI_SPECIALIST`、
`WEATHER_SPECIALIST`、`HOTEL_SPECIALIST` 或 `TRANSPORT_SPECIALIST`。先在不调用网络的进程中
打印角色到模型的映射并与生产 `build_user_poi_role_overrides()` 结果核对；不得只设置主模型后
把所有角色隐式回退到同一模型。baseline 与 candidate 必须使用完全相同的角色映射，配置不一致的
产物只能作为诊断，不能进入质量门禁。
配置指纹覆盖六个角色的端点、凭据身份、模型、协议和 wire API，但产物只保存外层 SHA-256
与不含端点/凭据的角色模型表。评估器默认拒绝任一产物缺少指纹或两边指纹不一致；不得手工复制
另一次运行的指纹来绕过门禁。

也可以用 `--input-cost-per-million` 和 `--output-cost-per-million` 显式传入本次端点价格。
回放会汇总每个角色返回的 prompt/completion token；任一角色缺少 usage 时，该案例费用仍记为
未知，不会错误地按零成本处理。费用缺失时质量门禁默认失败；只有在验证功能而非发布决策时才可传
`--allow-missing-cost`。保留 HelloAgents 版本的 trace 没有 token usage 字段；完整 baseline 必须
在隔离账号/密钥下执行，并将提供商账单中只属于该次 30 案例运行的精确总费用通过
`--baseline-total-cost-usd` 传入。该值不能用估算值或零占位。少量真实端点预检可用 `--limit`，
完整放量判断必须覆盖全部案例。评估报告的 `cost_source` 会分别标记费用来自
`trace_usage`、`measured_total` 或仍为 `unknown`，发布证据应保留该字段。

每个 LangGraph 角色默认最多发送 2 次 HTTP 请求，POI 角色最多 1 次；请求数和实际重试数
分别写入 trace。搜索角色的共享限流排队与模型请求分别使用有界预算，两者相加形成角色总墙钟
上限；同一并行批次的角色共享端点时，排队预算至少覆盖同端点兄弟角色的最长请求预算，获锁后
仍保留本角色完整的 HTTP 重试/协议回退预算。同步传输无法保证立刻中断，但超时响应不会继续
进入结果提交。ARQ 的任务级最大尝试次数
继续构成外层恢复上限，图节点不再额外叠加默认重试。
默认配置下，普通角色跨 3 次 ARQ 尝试的理论上限是 6 次请求，POI 角色为 3 次；
已 checkpoint 的成功节点不会重跑。

首次执行的 `planning_generated_at` 固定在 Job payload 中，同一 ARQ 重试或显式 checkpoint
恢复会复用该时间和已经核验的证据。用户主动发起新的生成任务会创建新的时间指纹并重新获取
证据；日期、prompt 版本、模型标识或规范化输入变化时，旧 WorkflowRun 不允许继续恢复。

协议回归使用模拟 HTTP 端点，覆盖 Responses、Chat Completions、Gemini、Claude、
NewAPI、NeiAPI、Grok 引用及流式异常：

```powershell
uv run --project apps/api pytest apps/api/tests/test_llm_proxy.py apps/api/tests/test_llm_orchestrator.py -q
```

## 回滚演练

把 `TRAVELMIND_LANGGRAPH_ROLLOUT_PERCENT` 设为 `0` 并重启 API/worker。验证一个新 Job
使用 `standard` fallback，同时一个已存在的 LangGraph Job 仍从原 checkpoint 继续。
不要把 LangGraph checkpoint 交给旧运行时。应用级回滚必须使用保留的上一部署版本。

## 排空检查

从仓库根目录运行：

```powershell
uv run --project apps/api python scripts/audit_workflow_rollout.py --require-drained
```

命令为只读。退出码 0 表示数据库已经包含 `0005_workflow_runs`，并且没有活跃的
legacy/unknown-provider 生成或微调任务；退出码 2 表示仍有阻塞任务或 schema 尚未升级。
输出中的 `schema_ready_for_langgraph` 必须为 `true`，`schema_blockers` 必须为空。缺少
provider 快照的旧 Job 会被保守地视为阻塞。确认排空和回滚窗口结束后，才能部署已删除
旧包与旧 provider 的版本；旧部署镜像继续保留到回滚窗口结束。

## 观察指标与门槛

- 固定案例的日期、预算算术、闭馆和班次证据硬违规必须为 0。
- 生成/微调成功率与质量不得低于基线。
- 初始门槛：p95 延迟和已知调用费用相对基线均不得增加超过 10%。
- 取消任务不得提交；重复投递不得重复提交；旧任务不得覆盖新版本行程；用户状态和凭据不得串用。
