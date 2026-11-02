# 文档导航

主入口：[项目 README](../README.md)。以下按阅读目的组织；带日期的文件是当时的开发 / 验收记录，不应视为当前产品承诺。

[本次公开体验发布记录](public-release-2026-11-02.md)

## 先了解项目

- [架构](architecture.md)：系统边界、数据流与服务拆分。
- [API 概览](api-overview.md)：认证、行程、异步任务和导出接口。
- [开发指南](development.md)、[本地启动 / Compose](local-development.md)。
- [LangGraph 迁移验证](langgraph-migration-verification-2026-09-20.md)。

## 体验和部署

- [公开体验账户与 5 次额度](public-demo.md)。
- [生产部署说明](public-demo.md#发布检查)。
- [LangGraph 发布 / 回退](langgraph-rollout-runbook.md)。
- [GrokSearch 部署](groksearch-bridge-deploy.md)、[本地准备](groksearch-local-setup.md)。
- [可选小红书采集服务](xhs-crawler-deploy.md)：公开体验账户不开放绑定。

## 专项实现与历史记录

- [迁移方案](langchain-migration-plan-2026-09-20.md)、[迁移验收](langgraph-migration-verification-2026-09-20.md)。
- `change-records/`、`debugging/`、`runbooks/`：供追溯实现决策和验收边界。
- 尚未提交的图片、规划和自适应微调实验保留在本地，不随本次公开体验发布。

## 未上线实验

自适应微调系列文档是离线 / 独立测试环境中的实验记录。功能默认关闭，生产环境强制不启用；请勿根据实验文档宣称线上可用。开发原始输出不随仓库发布。
