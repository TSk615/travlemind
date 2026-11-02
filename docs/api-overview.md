# 接口概览

业务 JSON 接口通常使用以下统一响应结构；事件流和文件下载等接口返回对应内容：

```json
{
  "data": {},
  "error": null,
  "meta": {}
}
```

## 登录与认证

- `POST /api/v1/auth/register`
- `POST /api/v1/auth/login`
- `POST /api/v1/auth/refresh`
- `POST /api/v1/auth/logout`
- `GET /api/v1/me`

## 外部账户绑定

- `GET /api/v1/account/xhs/status`
- `POST /api/v1/account/xhs/bind`
- `GET /api/v1/account/xhs/bind/{bind_id}`
- `DELETE /api/v1/account/xhs/bind`

## 行程管理与生成

- `POST /api/v1/trips`
- `GET /api/v1/trips`
- `GET /api/v1/trips/{id}`
- `PATCH /api/v1/trips/{id}`
- `DELETE /api/v1/trips/{id}`
- `PUT /api/v1/trips/{id}/itinerary`
- `POST /api/v1/trips/intake/chat`
- `POST /api/v1/trips/{id}/generate`
- `POST /api/v1/trips/{id}/refine`
- `POST /api/v1/trips/{id}/images/enrich`

## 搜索、导出与异步任务

- `POST /api/v1/search`
- `POST /api/v1/exports`
- `POST /api/v1/exports/pdf`
- `GET /api/v1/jobs/{id}`
- `GET /api/v1/jobs/{id}/stream`
- `POST /api/v1/jobs/{id}/retry`：从检查点重试失败的行程生成任务。
- `POST /api/v1/jobs/{id}/cancel`：取消任务。

## 模型与运行配置

- `GET /api/v1/settings/llm`
- `PUT /api/v1/settings/llm`

## 模型及搜索调试工具

- `POST /api/v1/llm/proxy`
- `POST /api/v1/llm/models`
- `POST /api/v1/llm/test`
- `POST /api/v1/llm/search-proxy`
- `POST /api/v1/llm/search-images-proxy`
- `POST /api/v1/llm/tavily-images-proxy`
- `POST /api/v1/llm/xhs-images-proxy`

## 图片管理与生成

- `POST /api/v1/images/prompts/compose`
- `POST /api/v1/images/generate`
- `GET /api/v1/images`
- `GET /api/v1/images/feed`
- `GET /api/v1/images/prompt-trends`
- `GET /api/v1/images/{generation_id}`
- `PATCH /api/v1/images/{generation_id}`
- `POST /api/v1/images/{generation_id}/remix`

## 攻略社区

- `GET /api/v1/posts`
- `GET /api/v1/posts/{post_id}`
- `POST /api/v1/posts`
- `PATCH /api/v1/posts/{post_id}`
- `POST /api/v1/posts/{post_id}/refresh-from-trip`
- `DELETE /api/v1/posts/{post_id}`

## 公开体验账户说明

登录后访问 `GET /api/v1/me` 可取得当前账户信息。公开体验账户返回以下额度字段，数值以实时响应为准：

```json
{
  "generation_quota": {
    "limit": 5,
    "used": 0,
    "remaining": 5
  }
}
```

所有访客共享这 5 次额度。生成、重新生成、AI 调整和手动失败重试创建有效新任务时预占次数，最终失败自动退回且同一任务只退一次；日期校验不通过不建任务、不扣次；幂等请求复用已有任务不重复扣减。额度用尽返回 HTTP 403 和 `generation_quota_exhausted`。

公开账户不允许修改模型配置、访问管理员接口、绑定外部账户或直接使用独立模型 / 搜索 / 生图调试接口。受限请求返回 HTTP 403，具体错误代码和说明见响应的 `error` 字段。

完整规则见 [公开体验账户与额度](public-demo.md)。涉及写操作的浏览器请求还需遵守部署环境的 Cookie、Origin 与 CSRF 检查，不能只凭一个前端按钮判断接口权限。
