# LangGraph 灰度、回滚与旧运行时排空

本手册对应迁移计划 P5。灰度选择只发生在 Job 第一次执行前，结果会写入
`job_records.payload_json.workflow_provider`。重试复用该快照；已经创建的 LangGraph
`WorkflowRun` 还会固定 graph/schema 版本，不受后续环境变量变化影响。

## 配置

- `TRAVELMIND_AGENT_PROVIDER=langgraph`：让新生成和微调任务进入灰度选择。
- `TRAVELMIND_LANGGRAPH_ROLLOUT_PERCENT=0..100`：按 Job ID 的稳定哈希分桶。
- `TRAVELMIND_LANGGRAPH_ROLLOUT_FALLBACK_PROVIDER=helloagents|standard`：未命中灰度桶时使用的迁移期后备实现。

不要在同一个运行中修改 provider 或 graph version。切换配置只影响尚未执行且没有
provider 快照的新 Job。

## 放量顺序

1. 运行固定模拟回放与协议兼容测试，质量门禁必须通过。
2. 使用专用测试账号执行少量真实端点样本；记录模型、协议、延迟、费用与失败原因，不保存比较分支的行程，也不触发图片任务。
3. 将灰度从 5% 依次提高到 25%、50%、100%。每一级至少观察一个完整业务周期，核对成功率、硬约束违规、p95 延迟和费用。
4. 100% 后继续保留旧部署版本和向后兼容数据库迁移，直到回滚窗口结束。

## 回滚演练

把 `TRAVELMIND_LANGGRAPH_ROLLOUT_PERCENT` 设为 `0` 并重启 API/worker。验证一个新 Job
使用 fallback provider，同时一个已存在的 LangGraph Job 仍从原 checkpoint 继续。
不要把 LangGraph checkpoint 交给旧运行时。旧实现从当前代码移除后，应用回滚必须使用
保留的上一部署版本。

## 排空检查

从仓库根目录运行：

```powershell
uv run --project apps/api python scripts/audit_workflow_rollout.py --require-drained
```

命令为只读。退出码 0 表示没有活跃的 legacy/unknown-provider 生成或微调任务；退出码 2
表示仍有阻塞任务。缺少 provider 快照的旧 Job 会被保守地视为阻塞。确认排空和回滚窗口结束后，才能删除旧包、旧 provider 和旧部署镜像。

## 观察指标与门槛

- 固定案例的日期、预算算术、闭馆和班次证据硬违规必须为 0。
- 生成/微调成功率与质量不得低于基线。
- 初始门槛：p95 延迟和已知调用费用相对基线均不得增加超过 10%。
- 取消任务不得提交；重复投递不得重复提交；旧任务不得覆盖新版本行程；用户状态和凭据不得串用。
