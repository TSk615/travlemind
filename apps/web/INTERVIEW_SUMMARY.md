# TravelMind AI 前端阶段性工作总结（面试版）

> 写入时间：2026-03-21  
> 项目根目录：`E:\travel`  
> 本次总结覆盖范围：**前端工作台升级 + LLM 配置与浏览器直连模型方案 + 相关问题排查与修复**

---

## 1. 项目背景与我的职责

我负责的是 **TravelMind AI 的前端工作台**，核心目标不是单纯把页面做“好看”，而是把原本偏结果展示型的页面，升级成真正可操作、可观察、可调试、可扩展的 **旅行规划工作台（workbench）**。

我的工作主要集中在以下两个方向：

1. **Trip 详情页工作台化**
   - 把原来的 Trip 详情页从“结果展示页”升级为“工作台视图”
   - 展示异步任务状态、阶段进度、timeline、结构化搜索结果、refine UI
   - 让生成、refine、导出都处于同一套工作流心智模型下

2. **LLM 配置与模型联调前端化**
   - 增加模型设置入口与设置页面
   - 增加模型状态提示，让用户知道当前到底是“真实模型”还是“fallback / stub”
   - 演进出一套 **浏览器直连第三方模型 + 后端 relay/proxy** 的前端方案
   - 提供独立的 LLM Demo/Test Bench 页面，方便联调第三方模型接口

---

## 2. 到目前为止完成的核心工作

---

### 2.1 Trip 详情页升级为“工作台”

#### 目标
原始 Trip 详情页更像是一个静态结果页：
- 展示 Trip 基本信息
- 如果有 itinerary 就展示 itinerary
- 如果要生成或导出，只是简单发请求然后看结果

我把它升级成了一个 **可操作的工作台页面**，具备下面几类能力：

#### 已完成的能力

##### 1）任务状态与进度可视化
在 `TripDetailView.vue` 中增加并统一展示：
- `stage`
- `stage_message`
- `progress_percent`
- `timeline_json`

前端不仅展示当前任务状态，还增加了：
- 当前 job 卡片
- 进度条
- timeline 列表
- 时间戳
- 状态 pill
- 失败态 / 空态 / 轮询态

这样用户不再只是“点一下生成然后等”，而是能明确知道：
- 当前卡在哪个阶段
- 后端是否真的在推进
- 最近一次更新时间是什么
- 失败发生在哪个环节

##### 2）统一 generate / refine / export 三类任务体验
我把三类操作在前端统一成同一套工作流：
- `trip.generate`
- `trip.refine`
- `export.pdf`

统一点包括：
- 都展示 job 状态
- 都支持轮询
- 都走同样的状态区域
- 都在 timeline 中可解释
- 错误信息都能落在页面内，而不是只出现在 console

##### 3）结果区从“粗略文本”升级为“结构化阅读”
搜索结果展示从只有标题/摘要，升级成结构化卡片，展示：
- `place_name`
- `category`
- `opening_hours`
- `price_hint`
- `address`
- `geo`
- `source_type`

这样做的意义是：
- 前端不再只是“把后端搜索结果 dump 出来”
- 而是把数据转换成真正对旅行规划有用的上下文信息
- 这也为后续 prompt grounding、planner explainability、结构化排序打下基础

##### 4）新增 refine UI
在 Trip 工作台中新增了 refine 能力，包括：
- 4 个快捷 refine 操作：
  - 压预算
  - 减少赶路
  - 更适合拍照
  - 增加深度体验
- 自定义 refine 文本输入框
- 提交后刷新结果 / 更新任务状态

这部分很关键，因为它把“生成一次结果”升级为“结果可迭代优化”，从产品体验上更接近真正的 AI workbench。

##### 5）新增 planning brief / itinerary 概览视图
当前 Trip 工作台不仅看结果，也能回看输入：
- destination
- dates
- budget
- travelers
- pace
- transport
- accommodation
- interests

同时我还补了 itinerary overview：
- 总天数
- 计划 stops 数量
- 平均日预算
- 风险条数

这类信息对用户判断“计划是否靠谱”很重要，也方便面试里强调你理解 **输入-推理-输出闭环**。

---

### 2.2 Export 页升级为任务进度页

`ExportView.vue` 之前更偏结果页，我把它补成了完整的任务状态页，增加：
- stage
- progress
- timeline
- result payload 显示
- 失败态 / 刷新失败态

这样 Trip 工作台跳转到 Export 页时，用户体验是连续的，不会断掉上下文。

---

### 2.3 共享类型与 API 封装升级

为了支撑工作台化，我同步升级了：

#### `packages/shared-types/src/index.ts`
补充/完善了：
- `TripRefineInput`
- `JobTimelineEntry`
- `ExportJob` 的进度字段
- `LlmSettings`
- `LlmSettingsInput`
- `LlmWireApi`

这样做的价值是：
- 前后端字段语义更清晰
- Vue 页面不再靠 `any` 硬写
- 避免页面层和接口层发生静默漂移

#### `apps/web/src/lib/api.ts`
统一补齐并整理了：
- Trip 获取/更新/生成/refine
- Search
- Export
- Job detail
- LLM settings
- 保存 itinerary 回写接口

同时保留了统一的 `request<T>()` 封装，继续使用 envelope 响应结构，降低了页面层复杂度。

---

### 2.4 增加 LLM 设置入口和设置页

#### 入口设计
我在顶部导航 `AppLayout.vue` 中加入了：
- `/settings`
- 文案：`Model settings / 模型设置`

同时在 Trip 相关页面增加了统一的状态提示组件，用户也可以从页面内直接跳转到设置页。

#### 设置页能力
在 `SettingsView.vue` 中完成了：
- `base_url`
- `api_key`
- `model`
- `wire_api`（Responses API / Chat Completions API）

并处理了：
- 初始加载
- 读取失败
- 保存失败
- 保存成功
- 空状态
- 重新加载
- API Key 默认 `password` 输入
- 已保存 key 只显示 masked 值，不回显完整密钥

---

### 2.5 模型状态提示：真实模型 vs fallback/stub

新增了共享组件：
- `apps/web/src/components/LlmStatusNotice.vue`

这个组件会在 Trip 相关页面统一提示当前模型状态：
- 已配置模型：提示会调用真实模型
- 未配置：提示当前仍是 fallback / 本地未配置状态

目前这个提示已经接入：
- `TripsView.vue`
- `NewTripView.vue`
- `TripDetailView.vue`
- `SettingsView.vue`

这件事非常重要，因为它解决了一个典型 AI 产品问题：

> 用户并不知道“现在到底是真的在调用模型，还是只是 demo / fallback”。

通过这个统一提示，前端把系统运行模式明确可视化了。

---

### 2.6 模型配置方案的演进：从“后端 settings API”转向“浏览器本地配置 + relay”

这是项目中一个非常值得面试讲的点。

#### 最初目标
最开始的需求更偏向：
- 前端通过后端 settings API 存储 LLM 配置
- 后端作为单一可信配置中心

#### 实际演进
随着项目推进，当前前端已经演进到更适合联调的方案：

- LLM 配置保存在浏览器本地（`localStorage`）
- 前端通过 `llmSettings.ts` 管理运行时模型配置
- 生成 / refine 在浏览器侧直接组织 prompt
- 通过 `/api/v1/llm/proxy` 走后端 relay 转发到第三方模型

#### 这套方案的优点
1. **联调速度快**：不必等待完整后端设置持久化流程
2. **前端可自助测试**：一个浏览器就能换模型、换 base_url、换 API 格式
3. **便于验证第三方兼容性**：特别适合 OpenAI-compatible / 非官方兼容接口
4. **安全边界相对可控**：虽然 key 在浏览器端，但真实请求仍通过 relay，可用于测试和内部工作台

#### 这套方案的代价
1. 不是最终生产级多端同步配置方案
2. 配置仅存在当前浏览器
3. 需要清晰地向用户解释：这是浏览器本地配置，不是服务端统一配置

这正好是一个很好的面试回答点：

> “我没有死守最初方案，而是根据当前后端能力和联调效率做了架构调整，用更低耦合的方式先让产品跑起来。”

---

### 2.7 浏览器端 planner / refine 能力

在 `apps/web/src/lib/browserPlanner.ts` 中，我完成了浏览器侧规划与 refine 的核心逻辑：

#### 主要能力
- 把 Trip、search grounding、refine instruction 组装成 prompt 输入
- 支持两类第三方兼容接口：
  - `responses`
  - `chat_completions`
- 解析 JSON 响应
- 兼容 SSE 流式返回
- 把模型返回的 JSON 转成：
  - `GeneratedItinerary`
  - `AgentRunTrace`
- 再把结果回写到后端 Trip 记录

#### 这部分的产品价值
这意味着前端不再只是“发一个后端生成任务”，而是具备了：
- prompt 组织能力
- 结构化解析能力
- 模型接口兼容能力
- itinerary 数据落库的闭环能力

这是一种更强的“前端工作台”角色，而不是简单 CRUD 页面。

---

### 2.8 新增 LLM Demo / Test Bench 页面

新增页面：
- `apps/web/src/views/LlmDemoView.vue`

这个页面是独立于 Trip 工作流的测试台，用于：
- 直接测试第三方模型接口是否可用
- 测试 `responses` / `chat_completions` 两种 wire format
- 查看 raw request / raw response
- 查看 SSE 返回文本解析是否正常

这个页面对工程效率帮助非常大，因为它把“模型接不通”问题和“Trip 规划逻辑”问题分离了。

也就是说，出现问题时我能快速判断：
- 是模型接口本身的问题
- 是 relay 问题
- 是 prompt 问题
- 还是 itinerary JSON 解析问题

这属于典型的 **调试面板 / 测试工具化思路**，面试里很好讲。

---

## 3. 主要修改文件（按职责分类）

### 3.1 视图层
- `apps/web/src/views/TripDetailView.vue`
- `apps/web/src/views/ExportView.vue`
- `apps/web/src/views/TripsView.vue`
- `apps/web/src/views/NewTripView.vue`
- `apps/web/src/views/SettingsView.vue`
- `apps/web/src/views/LlmDemoView.vue`

### 3.2 组件层
- `apps/web/src/components/AppLayout.vue`
- `apps/web/src/components/LlmStatusNotice.vue`

### 3.3 状态层
- `apps/web/src/stores/llmSettings.ts`

### 3.4 接口与类型层
- `apps/web/src/lib/api.ts`
- `apps/web/src/lib/browserPlanner.ts`
- `packages/shared-types/src/index.ts`

### 3.5 样式与路由层
- `apps/web/src/router.ts`
- `apps/web/src/styles.css`

---

## 4. 项目中遇到的难点

这部分建议你面试时重点讲，因为它比“我做了哪些页面”更能体现工程能力。

---

### 难点 1：从“结果页”升级到“工作台”，不是简单加几个组件

表面上看只是页面改版，但实际问题是：

- 页面要同时承载输入、过程、输出
- 要统一 generate/refine/export 三类异步流程
- 要兼容后端字段不全时的空态
- 要保证用户不需要理解后端内部结构，也能看懂任务推进逻辑

#### 我的处理方式
- 以“工作台”而不是“详情页”的视角重构布局
- 拆成：
  - 概览区
  - 模型状态区
  - 当前任务区
  - timeline 区
  - itinerary 区
  - search grounding 区
  - refine 操作区
- 把状态、进度、错误、空态全部前置可视化

这其实是一次 **产品心智模型重构**，不只是 UI 重排。

---

### 难点 2：前后端契约在演进，前端不能被动等待

最开始的需求是：
- settings 通过后端 API 存储和读取

但项目实际演进后，当前前端采用的是：
- 浏览器本地配置
- 通过 relay 走第三方模型

#### 真正的难点
前端不能因为后端尚未完全就绪就停住，必须做到：
- 类型先定义好
- 空态先兼容
- 当前能跑的链路先跑起来
- 后续切回服务端持久化时改动成本尽量低

#### 我的处理方式
- 先把 `shared-types` 设计好
- 把模型配置抽成 store
- 页面只依赖 store 的 `settings / isConfigured / resolvedConfig`
- 这样未来无论底层是：
  - `localStorage`
  - 后端 settings API
  - 混合方案
  页面层都不用大改

这体现的是 **架构缓冲层设计**。

---

### 难点 3：第三方模型接口兼容性不稳定

不同第三方兼容接口通常会有差异：
- 有的支持 `/responses`
- 有的只支持 `/chat/completions`
- 有的返回 JSON
- 有的返回 SSE
- 有的字段命名不同

#### 我的处理方式
在前端抽象出 `wire_api`：
- `responses`
- `chat_completions`

同时在 `browserPlanner.ts` 和 `LlmDemoView.vue` 中分别处理：
- JSON 返回提取
- SSE 返回提取
- 错误消息提取
- 无文本输出的保护性报错

这能显著降低“第三方接口看起来兼容，其实细节不兼容”带来的排查成本。

---

### 难点 4：浏览器侧直接调用模型时，如何兼顾安全与效率

如果前端直接持有 API Key，会带来安全和部署上的顾虑；但如果完全依赖后端，又会拖慢联调效率。

#### 我的权衡方式
当前采用的是：
- 配置保存在浏览器本地
- 实际请求仍通过 `/api/v1/llm/proxy` relay
- 用于工作台和联调，而不是一开始就假设它是最终生产态

这个方案的价值在于：
- 前端调试效率高
- relay 仍提供一层中间控制
- 未来可以渐进迁移到真正的服务端配置中心

这类“先跑通、再收敛”的工程决策，在面试里是加分项。

---

### 难点 5：中英文切换必须持续可用

项目已有中英文切换能力，所以新增区域不能只写死英文。

#### 我做了什么
- 新增页面和组件都继续使用 `useI18n()`
- 一些新增区块采用前端本地 `computed copy` 方式管理中英文文案
- 保证新增状态提示、设置页、工作台文案在切换语言时同步变化

#### 真实难点
不是“有没有翻译”，而是：
- 在高频演进下，如何不让 i18n 成为迭代阻力
- 如何在没有完整翻译后台的情况下仍然快速交付

---

### 难点 6：Windows + Vite/esbuild 构建环境问题

构建时遇到了典型的环境级问题：

- 在当前沙箱环境里，`vite build` / `esbuild` 拉起子进程会报 `spawn EPERM`

#### 表现
- 代码本身可能没问题
- 但 build 在沙箱内失败
- 容易误判为代码错误

#### 我的处理方式
- 先判断错误栈，确认问题来自 `esbuild` 子进程权限
- 再在沙箱外重跑 build 做真实验证
- 最终确认当前前端构建通过

这个问题很适合面试里讲“我怎么区分代码问题和环境问题”。

---

## 5. 出现过的 bug 与修复方式

这一节建议你在面试时当成“调试案例库”。

---

### Bug 1：Vue 模板里把 `<textarea />` 写成自闭合，导致模板问题

#### 问题来源
在快速重构页面时，曾出现：
- `<textarea ... />`

但在 Vue / HTML 语义里，`textarea` 不应该自闭合。

#### 风险
- 模板编译异常
- 页面渲染不稳定
- 构建可能失败

#### 修复
全部改成显式闭合：
- `<textarea ...></textarea>`

#### 面试可讲点
这是个典型的“小语法错误引发大问题”的案例，说明前端重构时要特别注意模板语义，而不只是 TS 逻辑。

---

### Bug 2：PowerShell 批量写文件时，把字面量 `` `r`n `` 写进了源码

#### 问题来源
在 Windows PowerShell 环境下使用字符串替换/写文件时，曾把 `` `r`n `` 当普通文本写进文件，导致源码里出现：
- 非法 import 拼接
- 模板中混入奇怪字符
- Vue 文件被污染

#### 风险
- 文件表面看起来像“只多了个换行”，实际上会直接导致源码不可用
- 这种错误不一定第一眼能看出来

#### 修复方式
- 不做局部脆弱替换
- 直接把受污染文件整文件重写成干净版本
- 重跑构建验证

#### 面试价值
这个案例能体现：
- 我知道什么时候应该“精修补丁”
- 什么时候应该“整体重写，快速恢复到可信状态”

---

### Bug 3：TripDetailView 在多次迭代后局部逻辑漂移，最终通过整文件重构修正

#### 具体问题
Trip 工作台经过多轮需求变化后，出现过：
- import 依赖不一致
- 状态逻辑插入位置不稳定
- 页面中混入过时实现
- 条件分支不再完全匹配当前产品方案

#### 修复方式
我最终采用：
- 重新梳理 TripDetailView 的职责边界
- 保留已验证的功能点
- 按“模型状态 / brief / job / itinerary / search / refine”重新组织结构
- 整文件重写，减少局部 patch 累积带来的技术债

#### 收获
对复杂页面来说，**持续 patch 并不总是最优解**，在一定阶段做一次“结构性回正”反而更稳。

---

### Bug 4：构建失败但其实不是代码 bug，而是环境权限 bug

#### 现象
- `npm run build --workspace @travelmind/web` 在沙箱内报 `spawn EPERM`

#### 真正原因
- `vite` / `esbuild` 在当前环境中无法正常拉起 worker 子进程

#### 修复方式
- 识别为环境权限问题
- 申请在沙箱外重跑
- 在沙箱外确认 build 通过

#### 面试价值
能体现你不是“盲改代码直到不报错”，而是会先定位问题层级。

---

### Bug 5：模型状态与实际运行模式容易不一致，必须做统一状态收敛

#### 问题
如果每个页面都自己判断“是否配置模型”，会出现：
- 某页提示已配置
- 某页提示未配置
- 某页读取的是旧值

#### 修复方式
- 抽离 `llmSettings` store
- 统一由 store 负责：
  - 读取本地配置
  - 计算 `configured`
  - 生成 masked key
  - 暴露 `resolvedConfig`
- 页面只消费 store，不自行拼判断逻辑

#### 收获
统一状态源是前端复杂工作台的基础，不然越往后越容易出现“同一事实多个版本”。

---

### Bug 6：用户刚创建 Trip 后，不清楚下一步应该做什么

#### 问题
在 Trip 创建完成跳转到详情页后，用户可能会误以为：
- itinerary 已自动生成
- 或者不知道应该点击什么

#### 修复方式
- `NewTripView.vue` 在创建成功后带上 `query: { entry: "create" }`
- `TripDetailView.vue` 根据 `route.query.entry` 展示“下一步先生成第一版行程”的提示卡

#### 价值
这不是底层 bug，但属于 **用户流程 bug / 产品引导 bug**，修复后能明显提升工作流清晰度。

---

## 6. 当前架构上的关键设计决策

这一部分很适合面试时回答“你为什么这么做”。

### 决策 1：状态统一收敛到 store，而不是散落在页面里
- `auth.ts` 管登录态
- `locale.ts` 管语言态
- `llmSettings.ts` 管模型配置与运行模式

**原因：** 避免同一事实在多个页面重复计算。

---

### 决策 2：页面只消费“业务状态”，不直接关心底层存储细节
比如：
- 页面不关心配置来自 localStorage 还是未来的 settings API
- 只关心 `isConfigured`、`settings`、`resolvedConfig`

**原因：** 降低未来迁移成本。

---

### 决策 3：把 LLM 调试工具独立成 demo 页
- `LlmDemoView.vue` 与 Trip 工作流隔离

**原因：** 把“模型接不通”和“planner 逻辑错误”分开排查。

---

### 决策 4：把复杂页面做成“工作台”，而不是只堆按钮和结果
Trip 工作台里同时呈现：
- 输入 brief
- 模型状态
- 当前 job
- timeline
- itinerary
- grounding results
- refine 操作

**原因：** AI 产品的关键不是只展示最终文本，而是让用户理解和控制生成过程。

---

## 7. 最新构建与验证结果

### 最新构建结论
已验证：
- `npm run build --workspace @travelmind/web` **通过**

### 说明
在当前开发环境中：
- 沙箱内构建可能因为 `vite/esbuild spawn EPERM` 失败
- 但在沙箱外执行时，当前版本构建已通过

### 当前前端状态
到目前为止，前端已经具备：
- Trip 工作台
- 异步任务进度展示
- refine 交互
- 结构化搜索结果展示
- Export 任务页
- 模型状态提示
- 浏览器本地 LLM 配置页
- 第三方模型测试页
- 浏览器侧 planner/refine 调用链路

---

## 8. 面试时可以重点强调的能力点

### 8.1 产品理解
我做的不是单页 UI，而是把“旅行规划工作流”产品化：
- 输入 → 生成 → refine → 导出 → 联调模型

### 8.2 工程化能力
- 抽象 shared types
- 统一 API 层
- 做状态收敛
- 管理复杂页面结构
- 保持 build 稳定

### 8.3 调试能力
我处理过：
- 模板错误
- 文件污染
- 环境权限问题
- 页面状态漂移
- 接口兼容问题
- 模型响应解析问题

### 8.4 架构权衡能力
我能根据项目现状做取舍：
- 一开始按后端 settings API 思路设计
- 后续根据实际联调效率，演进到浏览器本地配置 + relay
- 同时保留未来迁移空间

### 8.5 AI 产品落地能力
不是只会“接一个 LLM 接口”，而是把模型真正放进业务工作流里：
- 配置
- 状态提示
- prompt 组织
- 结果解析
- 回写数据
- 错误处理
- 联调面板

---

## 9. 如果面试官追问“下一步你会怎么做”

可以回答：

1. 把浏览器本地 LLM 配置迁移到真正的服务端 settings API
2. 增加模型调用日志和 prompt trace，提升可观测性
3. 给 refine 增加 scope/day 粒度选择
4. 把 grounding results 与 itinerary item 做更强关联
5. 给 browserPlanner 增加 schema 校验和自动修复策略
6. 让 Trip 工作台支持对比“原计划 vs refine 后计划”
7. 给导出增加更多 artifact 元信息和重试入口

---

## 10. 一句话总结（适合面试开场）

我在这个项目里做的核心事情，是把 TravelMind AI 的前端从“能展示结果的页面”，升级成了一个真正可运行、可解释、可配置、可联调的 **AI 旅行规划工作台**；同时在后端能力尚不完全稳定的情况下，设计并落地了一套 **浏览器本地配置 + relay + 第三方模型测试台** 的前端方案，并处理了多个真实的模板、构建、状态同步和接口兼容问题。
