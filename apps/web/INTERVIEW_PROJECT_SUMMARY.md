# TravelMind AI 前端项目复盘（面试版）

> 更新时间：2026-03-21  
> 项目根目录：`E:	ravel`  
> 主要负责范围：`apps/web`、`packages/shared-types`

---

## 1. 项目背景与目标

TravelMind AI 是一个旅行规划类产品，目标是把“用户输入旅行偏好 -> AI 生成行程 -> 搜索补充可信信息 -> 导出 PDF”串成一个可执行的 MVP 闭环。

我在这个项目里主要负责 **前端工作台（web）建设、共享类型对齐、页面状态完善、工作台交互升级、中英文切换修复，以及前端构建稳定性修复**。

这个项目有一个比较典型的工程背景：
- 产品规划文档中最初提到的是 **Next.js** 路线；
- 但实际代码落地时，前端已经是 **Vue 3 + Vite + TypeScript + Pinia + Vue Router**；
- 所以我在实现时必须优先尊重“当前真实代码结构”，而不是照搬最初文档。

这本身就是一个很适合面试讲的点：**工程落地不一定完全等于文档设计，真正的开发工作常常是“在既有技术栈里把产品目标走通”。**

---

## 2. 我负责的核心内容

### 2.1 前端基础稳定性
我先做的是让前端从“能写页面”升级到“能稳定构建、能稳定跑业务流程”：
- 修正 workspace / tsconfig / import 问题
- 修正别名解析失败
- 修正包导出引用错误
- 修正 JSON/BOM 导致的 Vite 构建失败
- 修正局部页面语法错误
- 修正部分页面 hardcode 文案导致的语言切换失效

### 2.2 MVP 页面级体验完善
我补齐了这些核心页面的状态能力：
- 登录页：初始化态 / 提交态 / 错误态
- Trips 列表页：加载态 / 空态 / 错误态 / 重试
- 新建 Trip 页：表单校验 / 空草稿提示 / 提交态 / 错误态
- Trip 详情页：从结果页升级为“工作台”
- 导出页：任务状态 / 时间线 / 结果展示 / 异常展示

### 2.3 Trip 工作台升级
Trip 详情页不再只是“行程结果展示”，而是变成一个真正的工作台，具备：
- 当前任务状态展示
- 阶段进度（stage / stage_message / progress_percent / timeline）
- 结构化搜索结果展示
- refine UI（快捷操作 + 文本指令）
- 规划 Brief 复核视图
- 每日行程更易读的卡片式展示
- Agent trace 展示

### 2.4 共享类型对齐
在 `packages/shared-types` 中，我把前端真正依赖的数据结构收敛成统一类型，包括：
- `Trip`
- `GeneratedItinerary`
- `SearchDocument`
- `ExportJob`
- `JobTimelineEntry`
- `TripRefineInput`
- `LlmSettings`
- `SearchGeoPoint`

这样做的意义是：**前端所有复杂页面的实现，都是围绕共享 contract 展开的，而不是写一堆临时 any。**

---

## 3. 到目前为止完成的主要工作（按阶段拆解）

---

### 阶段一：让前端先“能 build、能跑”

#### 完成内容
1. 修复错误导入
   - `AppLayout.vue` 里把 `brand` 错误地从 `@travelmind/config` 引入，改成了正确的 `@travelmind/ui`

2. 修复 TypeScript 路径别名
   - `apps/web/tsconfig.json` 中补了 `baseUrl`
   - 让 `@/stores/auth`、`@/lib/api`、`@/lib/format` 这类路径可以被 `vue-tsc` 正常解析

3. 修复 JSON/BOM 问题
   - `apps/web/package.json`
   - `apps/web/tsconfig.json`
   - `packages/ui/package.json`
   - `packages/config/package.json`
   - `packages/shared-types/package.json`
   这些文件存在 UTF-8 BOM，导致 Vite 在解析配置时出现 JSON parse error

4. 完成真实构建验证
   - 最终把 `npm run build:web` 跑通
   - 也就是 `vue-tsc --noEmit && vite build` 能完整通过

#### 这个阶段体现的能力
- 我不是只会写功能，而是会优先处理 **构建链路、类型系统、路径系统、工程入口问题**。
- 这也是前端在真实项目里很重要的一点：**没有稳定构建，后面一切功能都没有意义。**

---

### 阶段二：补齐页面状态，降低“假成功”体验

#### 完成内容
我为多个核心页面增加了统一的状态处理逻辑：

1. 封装通用 `StatePanel` 组件
   - 统一承载 loading / error / empty / info 状态
   - 避免每个页面各写一套状态结构，降低重复代码

2. 登录页增强
   - 增加 session bootstrap 过程展示
   - 登录/注册提交中的按钮禁用与文案变化
   - 后端 envelope 错误信息透传到页面

3. Trips 列表页增强
   - 第一次加载时展示 loading
   - 列表为空时展示 empty state
   - 请求失败时给出 retry

4. New Trip 页增强
   - 表单最小校验
   - 空草稿提示
   - starter brief 快速恢复
   - 提交中态和失败提示

5. Export 页增强
   - job 加载态
   - 导出轮询态
   - job 失败态
   - result 缺失时的空态

#### 这个阶段体现的能力
- 我不是只关注 happy path，而是完整覆盖 **异步过程中的状态流转**。
- 面试里可以直接强调：**我做前端时非常重视页面级 loading / empty / error 状态，因为这决定了产品在真实用户手里的稳定感。**

---

### 阶段三：统一 API 调用层与错误处理

#### 完成内容
在 `apps/web/src/lib/api.ts` 中，我把 API 层做了统一封装：

1. 统一使用 `{ data, error, meta }` envelope
2. 封装 `ApiError`
   - 包含 `status`
   - 包含 `code`
   - 包含 `details`
3. 统一 `getErrorMessage()`
   - 页面不再自己各写一份 error parsing
4. 统一 `fetch(..., { credentials: "include" })`
   - 保证 cookie-based auth 能正常工作
5. 让前端调用更像业务方法，而不是散落的 fetch
   - `login`
   - `register`
   - `me`
   - `listTrips`
   - `getTrip`
   - `createTrip`
   - `updateTrip`
   - `generateTrip`
   - `search`
   - `exportPdf`
   - `getJob`
   - 后续还扩展了 `saveTripItinerary`、`refineTrip`、`getLlmSettings`、`updateLlmSettings`

#### 这个阶段体现的能力
- 我在做的是 **API contract 层抽象**，不是“每页随手 fetch 一下”。
- 这样后续如果接口字段变化，只需要改一层，而不用全项目散点修改。

---

### 阶段四：共享类型升级

#### 完成内容
我对 `packages/shared-types/src/index.ts` 做了持续增强，让前端工作台相关能力可以有稳定类型支撑。

#### 新增 / 补强的关键类型
1. `TripRefineInput`
   - 用于前端 refine 指令

2. `LlmSettings` / `LlmSettingsInput`
   - 支撑浏览器侧模型配置页面

3. `SearchGeoPoint`
   - 描述结构化坐标

4. `SearchDocument` 扩展字段
   - `place_name`
   - `category`
   - `opening_hours`
   - `price_hint`
   - `address`
   - `geo`
   - `source_type`

5. `JobTimelineEntry`
   - `recorded_at`
   - `status`
   - `stage`
   - `stage_message`
   - `progress_percent`

6. `ExportJob` 扩展字段
   - `stage`
   - `stage_message`
   - `progress_percent`
   - `timeline_json`

#### 这个阶段体现的能力
- 我不是等后端字段全量稳定才开始写前端，而是先把 **可兼容、可空态降级** 的类型结构建好。
- 这是一种很典型的中大型项目协作能力：**前端需要对“字段还没完全到位”的现实有容错设计。**

---

### 阶段五：Trip 详情页升级为“工作台”

这是整个项目里我做的最核心的一块。

#### 以前的状态
Trip 详情页原本更像一个“结果展示页”：
- 显示 trip 基本信息
- 显示 itinerary
- 提供 generate / export 按钮
- 搜索结果只展示基本字段

#### 升级后的状态
我把它升级成一个真正的 **旅行规划工作台**。

#### 新增区域 1：当前任务区（Current Job）
展示异步任务完整状态：
- job type
- stage
- progress_percent
- stage_message
- 更新时间
- progress bar
- timeline 列表

这意味着用户不再只知道“在转圈”，而是能看到任务走到了哪一阶段。

#### 新增区域 2：行程概览（Itinerary Overview）
在生成成功后，顶部增加 overview 指标：
- 总天数
- 计划点位数
- 日均预算
- 风险数

这个设计的意义是：
- 用户先扫全局，再看明细
- 不是一上来就被很长的 itinerary 明细淹没

#### 新增区域 3：Planning Brief 复核卡
把输入给规划器的 Trip brief 单独提出来，集中展示：
- 目的地
- 日期
- 预算
- 出行人数
- 节奏
- 交通方式
- 住宿偏好
- 兴趣标签

这个区域的价值是：
- 用户可以快速判断“是不是输入有问题，才导致生成结果不理想”
- 对 refine 流程特别重要

#### 新增区域 4：Refine 工作区
增加了两类 refine 输入：
1. 4 个快捷按钮
   - 压预算
   - 减少赶路
   - 更适合拍照
   - 增加深度体验
2. 文本输入框
   - 支持用户写自由指令

并且 refine 后：
- 可以走浏览器侧模型调用
- 可以回写 Trip 记录
- 可以继续查看任务状态

#### 新增区域 5：搜索 Grounding 区
在工作台里加入“结构化搜索结果展示”：
- place_name
- category
- opening_hours
- price_hint
- address
- geo
- source_type
- platform
- score reasons

这样搜索结果不再只是“标题 + 摘要 + 链接”，而是变成可用于规划判断的结构化信息源。

#### 新增区域 6：Agent Trace 区
继续保留并强化对 Agent trace 的展示：
- provider
- workflow_id
- notes
- license_notice

这个区域对于可观察性和调试非常有价值。

#### 这个阶段体现的能力
这个部分是非常适合面试展开的，因为它体现了：
- 我会把一个“结果页”改造成“工作台”
- 我能设计信息层级
- 我能处理复杂异步状态
- 我能兼顾 AI、任务系统、结构化搜索、用户交互
- 我会做“人真正能用”的前端，不只是把字段堆上去

---

### 阶段六：导出页升级

#### 完成内容
`ExportView.vue` 也做了同步升级，不再只是简单显示导出结果。

现在支持：
- job stage 展示
- progress_percent 展示
- timeline 展示
- 轮询中态
- 失败态
- result 展示
- back to trip

#### 意义
导出流程常常是异步 + 易失败的环节，如果没有足够的可见性，用户体验会很差。

---

### 阶段七：中英文切换修复与完善

这个阶段也是非常有代表性的真实项目问题。

#### 发现的问题
一开始并不是简单的“i18n.ts 有问题”，而是多种情况叠加：
1. 有些页面使用了 `useI18n`
2. 但新增的工作台区域里混入了很多 hardcoded 中英文文案
3. 看起来像“中英切换失效”，但实际问题是“切换不完整”
4. 一度还怀疑过是不是中文乱码，但最终确认更多是终端显示编码问题，而不是源码损坏

#### 我做的修复
1. 检查 `apps/web/src/lib/i18n.ts`
   - 确认中文源码本身正常
2. 清理页面中 hardcoded 文案
   - 特别是 `TripDetailView.vue`
   - 以及 `LlmDemoView.vue`
3. 让这些新增区域跟随 locale 自动切换
4. 验证 build 通过

#### 这个阶段体现的能力
- 我不是看到“中文有问题”就直接重写 i18n，而是先判断到底是：
  - 终端显示问题
  - 文案源问题
  - 组件写死文案问题
  - 构建编码问题
- 这体现的是 **定位问题而不是盲修** 的能力。

---

### 阶段八：浏览器端模型配置与模型联调辅助页

项目后续又引入了一个比较有意思的前端能力：
- 浏览器端直接配置第三方模型
- 浏览器端直接调用第三方模型
- 支持 Responses API / Chat Completions API 适配

#### 我完成的相关工作
1. Settings 页
   - 配置 `base_url`
   - 配置 `model`
   - 配置 `wire_api`
   - 配置 / 替换 `api_key`
   - 状态保存 / 读取 / 提示

2. LlmStatusNotice 组件
   - 在多个页面提示当前模型配置状态

3. LlmDemoView
   - 用于隔离测试第三方模型调用是否正常
   - 支持中英文切换
   - 修复了一个致命语法错误（缺失 `}`）

#### 这个阶段体现的能力
- 我不仅会写产品主流程，还会补齐调试工具页 / 设置页 / 可观察性页面。
- 这种“给开发和测试提高效率”的能力，在面试里也很加分。

---

### 阶段九：生成成功后的信息展示优化

在“已经能成功生成行程”的基础上，我继续优化了信息展示，不是停留在功能可用，而是进一步提升可读性。

#### 主要优化点
1. 顶部增加行程概览 summary
2. 增加 overview metrics
3. 把 Brief 独立成一个信息卡
4. 把每日 itinerary 改成更易读的时间块结构
5. 给 item 增加：
   - 时间
   - 类型 badge
   - score badge
   - 地点
   - 备注
6. 搜索结果更突出结构化字段
7. 新增 chips / badge / score chip 等样式

#### 这个阶段体现的能力
- 我不是只追求“功能完成”，而是继续提升“信息架构和视觉可读性”。
- 对面试官来说，这体现的是 **产品思维 + 交互思维 + 落地能力**。

---

## 4. 项目中遇到的难点

下面这些难点非常值得在面试中讲，因为它们都是真实项目里很常见但不简单的问题。

---

### 难点一：设计文档与真实技术栈不一致

#### 情况
- 文档里提到 Next.js
- 实际代码是 Vue 3 + Vite

#### 难点
如果不先统一认知，很容易出现：
- 实现方向跑偏
- 组件组织方式冲突
- 构建系统理解错误

#### 我是怎么处理的
- 以当前真实仓库为准
- 优先修复现有 Vue 代码链路
- 在现有技术栈中完成工作台升级

#### 面试可说法
> 这个项目一开始最大的现实问题不是业务，而是“文档和代码不一致”。我选择先以真实代码为准，把产品目标映射到 Vue 3 + Vite 现有架构里，而不是强行照搬文档里的 Next.js 设计。这让我能更快把 MVP 真正跑通。

---

### 难点二：后端字段不一定一次性全部到位

#### 情况
前端需要展示：
- job stage
- progress_percent
- timeline
- structured search fields

但后端实际可能是逐步补字段的。

#### 难点
如果前端写得太“理想化”，就会：
- 一旦缺字段直接报错
- 页面空白
- 类型系统失真

#### 我的处理方式
- 共享类型里把这些字段设计成可选 / 可空
- 页面用 `fieldValue()` / empty state / fallback label 兼容
- timeline 为空时给出明确提示
- search structured fields 缺失时展示“暂无”而不是炸页面

#### 面试可说法
> 我把前端设计成“兼容增强式”的：后端字段到位时展示完整工作台，字段没到位时也能优雅降级，不会影响主流程。

---

### 难点三：异步任务状态复杂

#### 情况
任务不是只有 `loading / success / fail`，而是还包含：
- queued
- running
- completed
- failed
- stage
- progress
- timeline

#### 难点
如果只是一个 spinner，会极大降低可用性；如果状态写乱，又容易让页面逻辑复杂、难维护。

#### 我的处理方式
- 用统一的 `JobRecord` / `ExportJob` 类型描述任务
- 把任务信息收敛到“当前任务卡 + timeline”两个区域
- 让 Trip 详情页和 Export 页复用同样的任务观察逻辑

#### 面试可说法
> 我把任务状态从“单一 loading 动画”提升成“可解释的进度流”，用户能知道任务在哪个阶段、进度大概多少、历史更新是什么，这对 AI 和导出类产品很重要。

---

### 难点四：中英文切换不是单点问题

#### 情况
语言切换问题看起来像 i18n 问题，但实际是多个层面共同造成：
- 有的文案来自 `i18n.ts`
- 有的文案是页面写死的
- 有的终端显示乱码只是编码表现问题

#### 我的处理方式
- 先确认源码是不是坏了
- 再确认是不是 hardcode 文案残留
- 最后逐页清理固定语言文本

#### 面试可说法
> 这个问题不能靠直觉修。我先排除编码问题，再定位到页面里的 hardcode 文案，最后让新增区域也全部跟随 locale 切换。这比“看起来像乱码就重写文案文件”更可靠。

---

### 难点五：要兼顾“产品可用性”和“工程稳定性”

#### 情况
如果只做功能，很快能把按钮点通；
但如果忽略构建、类型、状态、容错，后面就会反复返工。

#### 我的处理方式
- 优先打通 build
- 再补类型
- 再补状态
- 再做工作台升级
- 最后优化信息展示

#### 面试可说法
> 我这次不是从 UI 开始冲，而是先把工程地基打稳，再逐步把产品体验做起来。这种顺序能明显减少返工成本。

---

## 5. 典型 Bug 修复清单（非常适合面试举例）

下面这些都是真实修过的 bug，可以直接在面试里讲。

| Bug / 问题 | 现象 | 根因 | 修复方式 | 结果 |
|---|---|---|---|---|
| 错误导入 | `AppLayout.vue` build 报错 | `brand` 从错误包导入 | 改为从 `@travelmind/ui` 正确导入 | 构建恢复 |
| 别名解析失败 | `@/stores/auth` 等路径无法解析 | `tsconfig` 缺少 `baseUrl` | 在 `apps/web/tsconfig.json` 增加 `baseUrl` | `vue-tsc` 路径正常 |
| JSON/BOM 导致 Vite 失败 | Vite / PostCSS 解析 JSON 报错 | 多个 `package.json` / `tsconfig.json` 带 BOM | 批量去 BOM | build 恢复 |
| 部分页面语言切换无效 | 切英文/中文后仍有一半文案不变 | 页面里混入大量 hardcode 文案 | 改成跟随 locale 的 computed 文案层 | 切换完整 |
| 疑似中文乱码 | 终端里显示中文异常 | 控制台编码问题，不是源码真的坏 | 直接检查文件内容而不是只看终端 | 避免误修 |
| `LlmDemoView.vue` 语法错误 | `TS1005: '}' expected` | 少了一个 `}` | 修复函数闭合并顺手补 locale 支持 | build 恢复 |
| 行程展示太平 | 生成成功后信息很多但不好读 | 只有 summary + 列表，没有层级 | 增加 overview / brief / daily card / badges | 可读性提升 |
| 搜索结果信息太薄 | 只能看到标题和摘要 | 结构化字段没有完整展示 | 展示 `place_name/category/opening_hours/...` | 结果更适合决策 |
| 异步任务不可解释 | 用户只看到按钮 loading | 缺少任务阶段信息 | 展示 stage/progress/timeline | 任务过程可观察 |

---

## 6. 这个项目里我体现出来的能力

### 6.1 工程能力
- 能快速修复构建链路问题
- 能处理 tsconfig / workspace / imports / encoding / build tooling
- 能做共享类型抽象
- 能搭建可维护 API 层

### 6.2 产品能力
- 能把“结果页”改造成“工作台”
- 能设计信息层级，而不是简单堆字段
- 能覆盖异步流程中的用户感知问题

### 6.3 协作能力
- 在后端字段不完全稳定时，做前端可兼容实现
- 不依赖“理想条件齐备”才开始开发
- 能围绕现有 contract 快速迭代

### 6.4 调试与排障能力
- 不盲修
- 能区分：构建问题 / 类型问题 / 运行时问题 / 编码问题 / 文案问题
- 能从“现象 -> 根因 -> 修复 -> 验证”完整闭环

---

## 7. 面试中可直接复述的项目亮点

下面这几段话可以直接当口述素材。

### 亮点 1：把 Trip 详情页做成工作台
> 我在这个项目里做的最核心的一件事，是把原本偏结果展示的 Trip 详情页升级成真正的工作台。现在它能展示异步任务进度、timeline、规划 brief、结构化搜索结果和 refine 入口，用户可以在同一个页面里完成观察、调整和继续生成，而不是在多个页面之间跳来跳去。

### 亮点 2：前端先把工程稳定住
> 我先修了构建链路和类型系统问题，比如错误导入、tsconfig 别名、BOM 导致的 Vite 失败等。因为我认为前端开发不是先把页面画出来，而是先让项目处于可稳定迭代的状态，否则后面每加一个功能都可能返工。

### 亮点 3：处理中英文切换问题不是简单换文案
> 这个项目的语言切换问题一开始看起来像乱码，但后来发现实际是页面里混有大量 hardcode 文案。我先排除了编码问题，再定位具体页面，把新增工作台区域也改成跟随 locale 切换，这样最终修的是根因，不是表象。

### 亮点 4：做了结构化展示而不是只堆字段
> 行程生成成功之后，我没有停留在“能显示出来”这个层面，而是进一步优化了信息展示，比如增加 overview 指标、daily card、评分 badge、结构化搜索字段区块，让信息更适合用户快速理解和继续决策。

---

## 8. 如果面试官追问“你最大的收获是什么？”

可以这样回答：

> 这个项目让我很深刻地体会到，前端开发的价值不只是把页面做出来，而是要把工程稳定性、接口契约、异步状态、信息层级和用户决策路径一起考虑。真正能提升产品质量的，往往不是单一大功能，而是把很多看似细碎的问题——比如构建链路、状态降级、语言切换、信息可读性——一个个处理干净。

---

## 9. 当前项目状态（可对外表述）

到目前为止，前端已经具备：
- 稳定构建能力（`npm run build:web` 通过）
- 完整的登录 / Trips / New Trip / Trip Detail / Export / Settings / Demo 路由
- 工作台化的 Trip 详情页
- 结构化搜索结果展示
- refine UI
- job timeline / progress 展示
- 中英文切换
- 浏览器端模型配置与辅助测试页

如果对外一句话总结：

> 我把 TravelMind AI 的前端从“能打开几个页面”升级成了“能稳定构建、能走通主流程、能解释任务状态、能支持继续优化决策”的工作台产品雏形。

---

## 10. 可继续优化的方向（面试加分项）

如果面试官问“你接下来还会怎么做”，可以回答：

1. 进一步拆分 Trip 工作台的子组件，降低 `TripDetailView.vue` 的复杂度
2. 给 timeline 增加阶段 icon / 明确状态映射
3. 给搜索结果增加排序、筛选、收藏
4. 给 itinerary item 增加编辑能力，而不仅仅是 refine
5. 把部分页面文案进一步收敛到统一 i18n 文件，减少局部 computed 文案对象
6. 为关键工作台流程补 E2E 测试
7. 为 job 与 search contract 增加更严格的 contract test

---

## 11. 一句话版本（适合简历 / 自我介绍）

> 负责 TravelMind AI 前端工作台建设，完成构建链路修复、共享类型对齐、页面状态完善、Trip 工作台升级、异步任务进度展示、结构化搜索结果展示、Refine UI、中英文切换修复与信息展示优化，最终将前端提升为可稳定构建、可完整演示、可继续扩展的 MVP 工作台。
