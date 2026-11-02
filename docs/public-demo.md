# 公开体验账户与生成额度

## 体验者

地址和公开登录信息见 [README](../README.md#在线体验--5-次行程生成)。所有访客共享 **总计 5 次**，不是每人 5 次、也不是每天 5 次。余额以 `/api/v1/me` 的 `generation_quota` 为准。

表单创建草稿、查看行程和下载自己的导出文件不消耗生成次数。`trip.generate`（包括手动重试）及 `trip.refine` 创建新任务时各扣 1 次；相同账户 / 类型 / 幂等键重放不重复扣减。失败和取消不自动返还；任务内部自动重试不产生新额度消费。额度用尽后后端返回 HTTP 403、`generation_quota_exhausted`，但可继续浏览历史行程。

公开数据可被其他访客查看、编辑或删除。不要输入个人信息或自有服务密钥。独立模型 / 搜索 / 生图测试、主动补图、引导式 AI 对话、社区写入、账户外部绑定和模型配置修改均不可用，避免绕过行程额度调用付费服务。

## 维护者：显式创建，不随启动重置

先迁移数据库，再在**目标环境**执行：

```powershell
$env:TRAVELMIND_DEMO_PASSWORD="TravelMind-Demo-2026!"
uv run --project apps/api python -m travelmind_api.provision_demo `
  --email demo@travelmind.example `
  --copy-settings-from-email YOUR_CONFIGURED_ACCOUNT_EMAIL
Remove-Item Env:TRAVELMIND_DEMO_PASSWORD
```

Linux / 容器中使用等价的环境变量和 `python -m travelmind_api.provision_demo`。源账户需要已配置有效的规划模型。CLI 只复制规划、研究和搜索配置，不复制管理员权限、图片生成服务、其他用户数据或外部绑定。服务密钥留在目标数据库，受现有凭据加密机制保护；不要提交源账户密码或配置。

- 首次创建：新账户 + `generation_quotas` 行，`generation_limit=5`、`used=0`，在同一事务提交。
- 已存在的体验账户：只返回当前余额，不改密码、不覆盖服务配置、不恢复额度。
- 已存在但不是体验账户、密码不匹配或邮箱属于管理员：拒绝操作。
- 未提供密码：失败退出，不创建账户。
- 这不是匿名注册奖励；普通账户没有该额度行，行为保持不变。

不要把公开邮箱列入 `TRAVELMIND_ADMIN_EMAILS`。修改管理员邮箱配置前应检查是否与公开账户冲突。

## 实现与一致性

Alembic `0006_generation_quotas` 新建独立表，外键关联账户而不是行程。创建付费任务时先锁定账户的额度行，再检查幂等键、条件扣减、写入任务；任务和消费共同提交 / 回滚。兼容 SQLite 与 PostgreSQL，多进程竞争不能超过额度。同一请求复用已存在任务不会重复扣费；`commit=False` 调用由外层事务负责提交。

后端权限检查基于数据库额度标记，而不是前端按钮、邮箱字符串或客户端参数。`GET /settings/llm` 仅供读取已配置状态，公开账户不返回任何密钥片段。线上新版页面横幅展示共享余额和隐私提示，也可直接从 `/me` 查看余额。

## 发布检查

1. 备份生产 PostgreSQL；确认无正在运行的行程任务后迁移 / 更新 API 和 Worker。
2. 显式创建体验账户，检查不是管理员、模型配置有效、余额为 5。
3. 验证登录、`/me`、配置只读及绕过接口被拒绝，**不要用公开账户跑验收生成消耗体验额度**。
4. 再将账户信息放到公开 README。5 次 / 并发 / 耗尽验证使用测试数据库，不直接在生产中重置。
5. 额度不会自动补充。需要追加试用时由维护者另行决定，不通过重复部署或重新登录发放。
