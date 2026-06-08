# TravelMind UI 重构方案 v4（终版）

## 0. 设计哲学与架构总纲

**"治愈旅感 AI"** — 三层视觉语言 × 三层工程架构

### 视觉语言配比

| 层级 | 风格来源 | 占比 | 职责 |
|------|----------|------|------|
| 底色层 | 日系清新 + 吉卜力温暖 | 70% | 页面背景、留白、文字排版、信息卡片 |
| 触感层 | Soft UI（新拟态） | 20% | 按钮、输入框、分段切换、进度槽 |
| 点睛层 | Y2K 虹彩 | 10% | AI 状态、生成动效、CTA 高光、模式切换 |

### 工程架构三层

| 层级 | 内容 | 产出 |
|------|------|------|
| Design Tokens | CSS 变量作为单一事实源 | `tokens.css` |
| Component Primitives | 自有轻量组件层（不引入第三方库） | `components/ui/*.vue` |
| Page Skeletons | 四种复用模式组合成页面 | 各 View 文件 |

### 核心原则

- 留白即呼吸 — 模块间距不低于 24px，主内容区最大宽度 1280px
- 一页一焦点 — 每屏只有一个视觉重心
- AI 是配角 — 虹彩高光只服务于"正在发生的 AI 行为"，静态信息保持温和
- 装饰克制 — 每页最多 1 个手绘线稿 + 1 种微纹理，禁止满屏插画
- 组件自治 — 每个组件只关心自己的视觉变体，页面只负责编排

---

## 1. Design Token 体系

### 1.1 色彩

```css
:root {
  /* === 基础色（日系清新底色）=== */
  --tm-paper: #F6F2EB;        /* 主背景：温暖米纸 */
  --tm-mist: #EEF1EC;         /* 次背景：薄雾绿灰 */
  --tm-snow: #FDFCFA;         /* 卡片/面板底色 */
  --tm-moss: #5D7A63;         /* 主色调：苔藓绿（替代现有 #0f5e3c） */
  --tm-tea: #2B2A28;          /* 正文墨色（替代现有 --tm-ink） */
  --tm-clay: #C98F6B;         /* 暖色点缀：陶土橙（替代现有 --tm-warm） */
  --tm-stone: #8A8580;        /* 辅助灰：石色（替代现有 --tm-muted） */

  /* === AI 虹彩点缀（仅 10% 面积）=== */
  --tm-aurora-cyan: #7FE4E3;
  --tm-aurora-lilac: #C6B7FF;
  --tm-aurora-rose: #F4C2D7;

  /* === 语义色 === */
  --tm-success: #5D7A63;
  --tm-warning: #D4A054;
  --tm-error: #C75B4A;
  --tm-info: #6B9DAD;
}
```

色彩使用规则：
- `paper/mist/snow` 构成背景三阶，从页面底 → 区域底 → 卡片底逐层提亮
- `moss` 用于主按钮、链接、进度条、focus ring
- `clay` 用于 kicker 标签、次要强调、hover 状态
- `aurora-*` 三色仅用于：AI 生成中的边框渐变、模式切换激活态、AI CTA 微光、完成闪现
- 禁止将 aurora 色用作大面积背景或文字颜色

### 1.2 圆角与边框

```css
:root {
  --tm-radius-sm: 8px;       /* chip、badge、StatusPill */
  --tm-radius-md: 12px;      /* 输入框、小卡片 */
  --tm-radius-lg: 16px;      /* 标准卡片 */
  --tm-radius-xl: 24px;      /* 大面板、模态框 */
  --tm-radius-2xl: 32px;     /* Hero 区域 */
  --tm-radius-full: 999px;   /* 胶囊按钮（仅保留在语言切换等小控件） */

  --tm-border-hairline: 1px solid rgba(43, 42, 40, 0.06);
  --tm-border-subtle: 1px solid rgba(43, 42, 40, 0.10);
  --tm-border-visible: 1px solid rgba(43, 42, 40, 0.16);
}
```

### 1.3 阴影（Soft UI 双套系统）

```css
:root {
  /* Raised（凸起）— 按钮默认态 */
  --tm-shadow-raised-sm: 4px 4px 8px rgba(166, 158, 146, 0.15),
                         -2px -2px 6px rgba(255, 255, 255, 0.7);
  --tm-shadow-raised-md: 6px 6px 16px rgba(166, 158, 146, 0.18),
                         -4px -4px 12px rgba(255, 255, 255, 0.8);

  /* Inset（凹陷）— 输入框、进度槽、toggle 凹槽 */
  --tm-shadow-inset-sm: inset 2px 2px 4px rgba(166, 158, 146, 0.12),
                        inset -1px -1px 3px rgba(255, 255, 255, 0.5);
  --tm-shadow-inset-md: inset 3px 3px 8px rgba(166, 158, 146, 0.15),
                        inset -2px -2px 6px rgba(255, 255, 255, 0.6);

  /* Float（浮层）— 下拉菜单、tooltip、模态 */
  --tm-shadow-float: 0 8px 32px rgba(43, 42, 40, 0.08),
                     0 2px 8px rgba(43, 42, 40, 0.04);

  /* Card（卡片）— 信息卡片的轻投影 */
  --tm-shadow-card: 0 2px 8px rgba(43, 42, 40, 0.04),
                    0 1px 3px rgba(43, 42, 40, 0.03);
}
```

Soft UI 使用边界：
- 只在 `paper` 或 `mist` 背景上使用 raised/inset 阴影
- 按钮 `:active` 态从 raised 切换到 inset（按压感）
- 输入框默认 inset，`:focus` 时加 moss 色 ring 但保留 inset 底
- 卡片不使用 Soft UI 阴影，保持 `shadow-card` 轻投影

### 1.4 字体

```css
:root {
  --tm-font-display: "Noto Serif SC", "Songti SC", "Source Han Serif CN", serif;
  --tm-font-body: "PingFang SC", "Microsoft YaHei", system-ui, sans-serif;
  --tm-font-mono: "JetBrains Mono", "Fira Code", "SF Mono", monospace;

  --tm-text-xs: 0.75rem;     /* 12px */
  --tm-text-sm: 0.875rem;    /* 14px */
  --tm-text-base: 1rem;      /* 16px */
  --tm-text-lg: 1.125rem;    /* 18px */
  --tm-text-xl: 1.5rem;      /* 24px */
  --tm-text-2xl: 2rem;       /* 32px */
  --tm-text-3xl: 2.75rem;    /* 44px */
  --tm-text-4xl: 3.5rem;     /* 56px */

  --tm-leading-tight: 1.2;
  --tm-leading-normal: 1.6;
  --tm-leading-relaxed: 1.8;
}
```

字体使用规则：
- `display`（衬线体）仅用于 Hero 大标题和 h1，营造"书卷气"
- `body` 用于所有正文、按钮、表单标签
- `mono` 用于预算数字、日期、指标数据

### 1.5 间距系统

基于 4px 基准的 8 级阶梯：`4 / 8 / 12 / 16 / 24 / 32 / 48 / 64 / 80px`

关键约束：
- 卡片内边距统一 24px（移动端 16px）
- 模块间距统一 24px（桌面端可放大到 32px）
- 页面级区块间距 48–64px
- 表单字段间距 16px，分组间距 32px

### 1.6 动效

```css
:root {
  --tm-ease-out: cubic-bezier(0.16, 1, 0.3, 1);
  --tm-ease-in-out: cubic-bezier(0.4, 0, 0.2, 1);
  --tm-duration-fast: 150ms;
  --tm-duration-normal: 250ms;
  --tm-duration-slow: 400ms;
}
```

动效分级：
- L1 微交互（hover/focus/press）：150ms ease-out，仅 transform + opacity
- L2 状态切换（展开/折叠/tab 切换）：250ms ease-in-out
- L3 页面过渡（路由切换）：400ms，fade + subtle slide
- L4 AI 专属（虹彩扫光/脉冲）：2–4s 循环，仅在 AI 活跃时播放

`prefers-reduced-motion` 下：L1–L3 时长归零（瞬切），L4 完全禁用

---

## 2. 组件体系

### 2.1 基础组件清单

| 组件 | 职责 | Soft UI | Aurora |
|------|------|---------|--------|
| `TmButton` | 主次 CTA，5 种变体 | ✓ raised/inset | 仅 AI CTA 变体 |
| `TmIconButton` | 图标操作按钮 | ✓ raised-sm | ✗ |
| `TmSegmentedSwitch` | 模式切换（form/chat） | ✓ 凹槽 + 凸起滑块 | 激活态微光 |
| `TmField` | 单行输入 + label + hint + error | ✓ inset | ✗ |
| `TmTextarea` | 多行输入 | ✓ inset | 对话模式边框 |
| `TmSelect` | 下拉选择 | ✓ inset | ✗ |
| `TmFieldGroup` | 表单分组容器（折叠标题） | ✗ | ✗ |
| `TmInlineHint` | 字段下方说明/错误文案 | ✗ | ✗ |
| `TmCard` | 通用信息卡片 | ✗ shadow-card | ✗ |
| `TmSection` | 页面区块容器 | ✗ | ✗ |
| `TmMetricCard` | 数据指标卡（数字突出） | ✗ | ✗ |
| `TmStatePanel` | 状态面板（升级现有 StatePanel） | ✗ | AI 活跃时边框 |
| `TmStatusPill` | 状态标签（升级现有 StatusPill） | ✗ | ✗ |
| `TmAuroraPanel` | AI 高亮容器（生成/refine/导出共用） | ✗ | ✓ 边框+脉冲 |
| `TmProgressTrack` | 进度条/完成度 | ✓ inset 槽 | 填充渐变 |
| `TmAnchorNav` | sticky 锚点导航条 | ✗ | ✗ |
| `TmToast` | 轻量通知条（背景任务） | ✗ | ✗ |

### 2.2 四种复用模式

**AppShell Pattern（母版）**
- 顶部画框式导航 + 内容容器 + 背景任务 toast
- 适用：全局 AppLayout

**Workbench Pattern（工作台）**
- 主编辑区（左 60%）+ sticky 摘要区（右 40%）+ 底部 action rail
- 适用：NewTrip

**List-Detail Pattern（列表详情）**
- 锚点导航 + 分区内容块 + 各区独立操作
- 适用：TripDetail

**Narrative Hero Pattern（叙事引导）**
- 全宽情绪区 + 衬线体大标题 + 简洁 CTA
- 适用：Home 首屏、NewTrip 顶部

### 2.3 视觉分工规则

| 场景 | 允许的视觉层 |
|------|-------------|
| 普通信息卡片 | paper/mist/snow + hairline + shadow-card |
| 按钮、输入框、分段切换、进度槽 | Soft UI raised/inset |
| AI 正在生成/处理中 | TmAuroraPanel 边框渐变动画 |
| 模式切换 toggle 激活态 | 微弱 aurora 渐变背景 |
| AI CTA 按钮 | moss 底 + aurora 边缘微光 |
| 生成完成瞬间 | 0.5s aurora 闪烁后消失 |
| 其他所有场景 | 温和中性，无 aurora |

### 2.4 按钮系统详细规范

| 变体 | 场景 | 视觉 |
|------|------|------|
| Primary | 主 CTA（创建行程、生成） | moss 实色底 + raised 阴影，hover 微上浮 |
| Secondary | 次要操作（清空、返回） | snow 底 + hairline 边框 + raised-sm |
| Ghost | 内联操作（查看详情） | 透明底，hover 时显示 mist 背景 |
| AI CTA | AI 生成/对话发送 | moss 底 + aurora 渐变边框微光 |
| Danger | 删除、取消 | error 色底，仅在确认态显示 |

交互态：
- `:hover` — translateY(-1px) + shadow 加深
- `:active` — translateY(0) + 切换到 inset 阴影
- `:focus-visible` — 2px moss ring，offset 2px
- `:disabled` — opacity 0.5，去除阴影

### 2.5 输入框统一规范

所有输入框为"浅色凹陷"风格：
- 默认：snow 背景 + inset-sm 阴影 + radius-md
- `:hover`：背景微亮到 #FFFFFF
- `:focus`：保留 inset 底 + 外加 `0 0 0 3px rgba(93, 122, 99, 0.12)` ring
- 错误态：ring 变为 error 色，底部出现错误文案（TmInlineHint）
- 标签：body 字体 700 weight，text-sm

### 2.6 卡片三层级

- **信息卡**（trip-card, day-card）：snow 底 + hairline + shadow-card
- **操作卡**（metric-card, quick-action）：mist 底 + subtle 边框，hover 提升为 snow + raised-sm
- **高亮卡**（AI 结果）：渐变底 `linear-gradient(135deg, rgba(93,122,99,0.08), rgba(201,143,107,0.06))` + subtle 边框

### 2.7 StatusPill 升级（保留现有 props）

- 去掉纯色块背景，改为语义色 8% 透明度背景 + 对应前景色文字
- 加 1px 同色系 12% 透明度边框
- 圆角改为 radius-sm（8px），不再用 full pill

### 2.8 AI 状态指示器（TmAuroraPanel）

当 AI 正在工作时的统一视觉：
- 边框：1px 渐变边框，aurora-cyan → aurora-lilac → aurora-rose 循环
- 脉冲：边框上叠加 4px 高光点沿边框运动（3s 一圈）
- 进度条：底色 mist，填充使用 aurora 三色渐变
- 文字状态：stone 色 + 呼吸闪烁（opacity 0.6 ↔ 1.0）

适用场景：NewTrip 对话输入框、TripDetail 生成面板、Job 进行中的 timeline

---

## 3. 页面重构详案

### 3.1 AppLayout（母版 — AppShell Pattern）

**现状问题：**
- topbar 使用 grid 三栏，中等屏幕下导航项挤压
- 所有导航做成胶囊按钮，视觉噪音大
- background-job-banner 视觉权重过高，与内容区竞争
- 使用 backdrop-filter 性能差
- 缺少全局路由过渡动效

**改造方案：**

```
┌─────────────────────────────────────────────────────────────┐
│  [TM Brand]     Home  Trips  NewTrip  Community  Images  [⚙]│  ← 画框式顶栏
├─────────────────────────────────────────────────────────────┤
│  ┌─ Background Task Toast (条件显示) ─────────────────────┐  │
│  │  🔄 行程生成中... 3/5        [查看 →]                  │  │
│  └────────────────────────────────────────────────────────┘  │
│                                                              │
│              [ 页面内容区 max-width: 1280px ]                 │
│              route-view with fade+slide transition            │
│                                                              │
└──────────────────────────────────────────────────────────────┘
```

关键改动：
- topbar 从 grid 三栏改为 flexbox 单行：品牌左对齐、导航居中、工具右对齐
- 导航项去掉胶囊边框，改为纯文字 + 底部 2px 细线指示激活态
- 激活态：文字变 moss 色 + 底部细线 + 微弱 moss 背景晕染
- 语言切换缩小为图标级 toggle
- 去掉 backdrop-filter，改为 snow 实色底 + radius-2xl + shadow-float
- background-job-banner 收缩为 48px 高 TmToast 条，info 语义色
- 内容区 `max-width: 1280px; margin: 0 auto; padding: 0 24px`
- 路由切换加 fade + translateY(8px) 过渡（L3 动效）

### 3.2 Home（品牌叙事首页 — Narrative Hero Pattern）

**现状问题：**
- Hero 区是功能介绍卡片左右分栏，缺乏品牌叙事
- highlight-card 列表式罗列功能点，没有视觉层次
- 整体像"功能说明书"而非"旅行灵感入口"

**改造方案：**

```
┌─────────────────────────────────────────────────────────────┐
│                                                             │
│     ✦ TravelMind AI                                         │
│                                                             │
│     让每一次出发                                             │  ← 衬线体 text-4xl
│     都有迹可循                                               │     moss 色
│                                                             │
│     从灵感碎片到可执行的旅行计划，                            │  ← stone 色副标题
│     AI 帮你把"想去"变成"出发"。                              │
│                                                             │
│     [ 开始规划 ]  [ 浏览社区灵感 ]                           │  ← Primary + Ghost
│                                                             │
│  ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─   │
│                                                             │
│  ┌──────────┐  ┌──────────┐  ┌──────────┐                  │
│  │ 🗺 智能   │  │ 📋 结构化 │  │ 📤 一键   │                  │  ← 三列能力卡
│  │ 行程规划  │  │ 信息采集  │  │ 导出分享  │                  │     hover 微上浮
│  │          │  │          │  │          │                  │
│  │ 简短描述  │  │ 简短描述  │  │ 简短描述  │                  │
│  └──────────┘  └──────────┘  └──────────┘                  │
│                                                             │
│  ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─   │
│                                                             │
│  "灵感 → 采集 → 规划 → 出发"  流程口号带                     │  ← stone 色小字
│                                                             │
│  ┌─────────────────────────────────────────────────────┐    │
│  │  准备好了？  [ 创建第一个行程 ✦ ]                     │    │  ← 收尾 CTA
│  └─────────────────────────────────────────────────────┘    │
│                                                             │
│  装饰：右下角一枝手绘植物线稿 SVG (opacity 0.06)             │
│  背景：paper 底 + 左上角 moss 径向渐变 3% 透明               │
└─────────────────────────────────────────────────────────────┘
```

关键改动：
- 从左右分栏改为全宽叙事流：Hero → 能力卡 → 流程带 → 收尾 CTA
- 标题使用 `font-display`（衬线体），正文使用 `font-body`
- 去掉 highlight-card 列表，改为底部三列能力卡（简洁图标 + 一句话）
- 新增流程口号带和收尾 CTA，形成完整叙事闭环
- 保留旅行气质和留白，不做重营销落地页

### 3.3 NewTrip（意图采集工作台 — Workbench Pattern）

**现状问题：**
- 表单和对话模式切换不够直观，视觉差异不足
- 表单字段平铺在 2 列 grid 中，缺乏分组和进度感
- 对话模式 AI/用户气泡仅靠 `border-style:dashed` 区分
- 右侧摘要缺少"完成度"引导，用户不知道何时可以创建
- 底部操作按钮层级不清

**改造方案：**

```
┌─────────────────────────────────────────────────────────────────┐
│  ┌─ 情绪 Hero ───────────────────────────────────────────────┐  │
│  │  新建行程 · 整理你的旅行意图                               │  │
│  │  [ 📝 表单模式 | 💬 对话模式 ]  ← TmSegmentedSwitch       │  │
│  └───────────────────────────────────────────────────────────┘  │
│                                                                 │
│  ┌─ 主操作区 (左 60%) ──────────┐  ┌─ 草稿摘要 (右 40%) ────┐  │
│  │                              │  │                         │  │
│  │  [表单模式]                   │  │  完成度 ████████░░ 75% │  │
│  │  ┌─ 行程基础 (TmFieldGroup) ┐│  │                         │  │
│  │  │ 标题 / 出发地 / 目的地    ││  │  ✓ 目的地：汕头         │  │
│  │  │ 开始日期 / 结束日期       ││  │  ✓ 日期：4.14-4.18      │  │
│  │  └──────────────────────────┘│  │  ✓ 预算：¥6,800         │  │
│  │  ┌─ 预算与人数 ─────────────┐│  │  ○ 住宿偏好：未填       │  │
│  │  │ 预算 / 人数              ││  │  ○ 兴趣标签：未填       │  │
│  │  └──────────────────────────┘│  │                         │  │
│  │  ┌─ 节奏与交通 ─────────────┐│  │  ─────────────────────  │  │
│  │  │ 节奏 / 交通方式          ││  │  💡 推荐下一步：        │  │
│  │  └──────────────────────────┘│  │  补充住宿偏好可让 AI    │  │
│  │  ┌─ 偏好与住宿 ─────────────┐│  │  生成更精准的方案       │  │
│  │  │ 兴趣 / 住宿类型偏好      ││  │                         │  │
│  │  └──────────────────────────┘│  │  [ 直接创建也可以 ]     │  │
│  │                              │  └─────────────────────────┘  │
│  │  [对话模式]                   │                               │
│  │  ┌─ TmAuroraPanel ─────────┐ │  ← AI 活跃时虹彩边框         │
│  │  │ 🤖 助手气泡 (mist底+左) │ │                               │
│  │  │ 👤 用户气泡 (snow底+右) │ │                               │
│  │  │ ┌─ 输入框 ────────────┐ │ │                               │
│  │  │ │ aurora 边框 + inset  │ │ │                               │
│  │  │ └─────────────────────┘ │ │                               │
│  │  │ [状态条：正在思考...]    │ │                               │
│  │  └─────────────────────────┘ │                               │
│  └──────────────────────────────┘                               │
│                                                                 │
│  ┌─ Action Rail ────────────────────────────────────────────┐   │
│  │  [示例草稿]  [清空]           [创建行程]  [创建并生成 ✦]  │   │
│  │   Ghost       Ghost           Secondary    AI CTA         │   │
│  └──────────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────────┘
```

关键改动：
- 顶部情绪 Hero 精简为一行标题 + TmSegmentedSwitch（Soft UI 凹凸切换）
- 表单从 2 列 grid 平铺改为 4 组 TmFieldGroup，每组有折叠标题
- 对话区使用 TmAuroraPanel 包裹，AI 活跃时虹彩边框
- 气泡区分明确：Assistant = mist 底 + 左对齐 + moss 名字标签；User = snow 底 + 右对齐
- 右侧 sticky 摘要新增：TmProgressTrack 完成度 + 已填/未填清单 + 智能建议 + 缺失项
- 底部 action rail 统一承载所有操作，按钮主次分明
- 移动端 < 1024px：右侧摘要变为顶部可折叠摘要条

### 3.4 TripDetail（结果解读工作台 — List-Detail Pattern）

**现状问题：**
- 2430 行巨型组件，信息密度高但缺乏层次
- 所有模块同权竞争首屏注意力
- AI 生成状态和普通信息卡视觉权重相同
- 长页面缺乏锚点导航
- refine、generate、export、image enrich 各自一套视觉风格

**改造方案：**

```
┌─────────────────────────────────────────────────────────────────┐
│  ┌─ 概览摘要条 ─────────────────────────────────────────────┐   │
│  │  🗺 汕头美食之旅  ·  4天3夜  ·  ¥6,800  ·  2人           │   │
│  │  [completed ●]  生成于 2026-04-10                         │   │
│  └──────────────────────────────────────────────────────────┘   │
│                                                                 │
│  ┌─ TmAnchorNav (sticky) ──────────────────────────────────┐    │
│  │  [概览]  [行程]  [搜索资料]  [社区]  [优化]  [导出]      │    │
│  └─────────────────────────────────────────────────────────┘    │
│                                                                 │
│  ┌─ 核心指标网格 (TmMetricCard × 4) ───────────────────────┐   │
│  │  ┌────────┐ ┌────────┐ ┌────────┐ ┌────────┐            │   │
│  │  │ 总预算  │ │ 天数   │ │ 景点数  │ │ 风险项  │            │   │
│  │  │ ¥6,800 │ │ 4 天   │ │ 12 个  │ │ 2 项   │            │   │
│  │  │ (mono) │ │ (mono) │ │ (mono) │ │ (mono) │            │   │
│  │  └────────┘ └────────┘ └────────┘ └────────┘            │   │
│  └──────────────────────────────────────────────────────────┘   │
│                                                                 │
│  ┌─ 行程时间线 ────────────────────────────────────────────┐    │
│  │  Day 1 · 4月14日 · 抵达与老城探索                        │    │
│  │  │                                                       │    │
│  │  ├─ 09:00  高铁抵达汕头站                                │    │
│  │  ├─ 10:30  入住酒店                                      │    │
│  │  └─ 14:00  老城区漫步                                    │    │
│  │                                                          │    │
│  │  Day 2 · 4月15日 · 美食深度游                            │    │
│  │  ├─ ...                                                  │    │
│  └─────────────────────────────────────────────────────────┘    │
│                                                                 │
│  ┌─ AI 操作面板 (TmAuroraPanel — 所有 AI 操作共用) ────────┐    │
│  │  Quick Refine: [输入优化指令...]        [提交优化 ✦]     │    │
│  │  ─────────────────────────────────────────────────────   │    │
│  │  [导出 PDF]  [重新生成]  [图片增强]                       │    │
│  │                                                          │    │
│  │  静态时：普通 panel                                       │    │
│  │  AI 活跃时：虹彩边框 + 脉冲 + 进度条                     │    │
│  │  完成时：moss success 边框闪现后恢复                      │    │
│  └─────────────────────────────────────────────────────────┘    │
└─────────────────────────────────────────────────────────────────┘
```

关键改动：
- 首屏只保留概览摘要条 + 核心指标 + 当前任务态
- 新增 TmAnchorNav（sticky），分为概览/行程/搜索资料/社区/优化/导出
- 核心指标改为 4 列 TmMetricCard 网格，mono 字体突出数字
- 行程从平铺卡片改为时间轴/日程块结构（左侧竖线 + 节点）
- 搜索资料改为更清晰的 list-detail 卡组
- refine、generate、export、image enrich 共享同一个 TmAuroraPanel
- 次要功能收入对应锚点区域，不在首屏争夺注意力

### 3.5 次级页面策略

Community、AI Images、Settings、Export 本轮不重画布局，只继承：
- 新 token（色彩、圆角、阴影、字体）
- 新按钮样式（TmButton 变体）
- 新卡片样式（shadow-card 替代 backdrop-filter）
- 新 StatusPill / StatePanel 视觉

避免全站视觉撕裂，同时控制改动范围。

---

## 4. 装饰语言规范

### 4.1 允许的装饰元素

| 类型 | 规格 | 使用限制 |
|------|------|----------|
| 手绘线稿 | SVG，stroke-only，1–2px 线宽 | 每页最多 1 个，opacity ≤ 0.06 |
| 微纹理噪点 | SVG filter 或 CSS noise | 每页最多 1 种，opacity ≤ 0.03 |
| 径向渐变 | moss/clay 色，3–5% 透明度 | 仅用于页面背景角落 |
| AI 光晕 | aurora 三色径向渐变 | 仅用于 AI CTA 按钮背后，半径 ≤ 120px |

### 4.2 禁止的装饰元素

- 厚重描边（> 2px）
- 廉价玻璃拟态（高模糊 + 高饱和度边框）
- Y2K 金属质感大面积底色
- 满屏插画或照片背景
- 动态粒子/星空等重性能装饰
- 多于 2 种渐变叠加
- backdrop-filter（性能考虑，全面移除）

### 4.3 AI 视觉语言的边界

AI 虹彩效果只在以下 4 个场景出现：
1. AI 正在生成/处理中 — TmAuroraPanel 边框渐变动画
2. 模式切换 toggle 的激活态 — 微弱渐变背景
3. "创建并生成"等 AI CTA 按钮 — 按钮边缘微光
4. 生成完成瞬间 — 0.5s aurora 闪烁后消失

其他所有场景保持温和中性。

---

## 5. 响应式策略

### 5.1 断点

```css
--breakpoint-sm: 640px;   /* 大手机横屏 */
--breakpoint-md: 768px;   /* 平板竖屏 */
--breakpoint-lg: 1024px;  /* 平板横屏/小笔记本 */
--breakpoint-xl: 1280px;  /* 标准桌面 */
```

### 5.2 各页面响应式要点

**AppLayout：**
- < 768px：topbar 折叠为 logo + 汉堡菜单，导航移入底部 sheet
- < 768px：TmToast 变为顶部固定窄条

**Home：**
- < 768px：三列能力卡变为单列堆叠
- < 640px：Hero 标题降为 text-2xl

**NewTrip：**
- < 1024px：右侧摘要从 sticky 侧栏变为顶部可折叠摘要条
- < 768px：表单分组改为手风琴（accordion），一次展开一组
- < 768px：action rail 固定在视口底部

**TripDetail：**
- < 1024px：核心指标从 4 列变 2 列
- < 768px：TmAnchorNav 变为水平滚动 tab bar
- < 768px：时间线取消左侧竖线，改为卡片堆叠

---

## 6. 可访问性要求

- 所有文本对比度 ≥ 4.5:1（WCAG AA）
- aurora 色不单独用作信息传达色，必须搭配文字或图标
- focus-visible ring 统一为 2px moss 色 + 2px offset
- 按钮最小触控区域 44×44px
- 表单错误信息使用 `aria-describedby` 关联
- AI 状态变化使用 `aria-live="polite"` 通知屏幕阅读器
- 所有动效遵守 `prefers-reduced-motion`
- 颜色不作为唯一的状态区分手段（StatusPill 同时使用颜色 + 文字）

---

## 7. 技术实现路径

### 7.1 引入 Tailwind（渐进式）

```bash
# 在 apps/web 中安装
pnpm add -D tailwindcss @tailwindcss/vite
```

Tailwind 配置策略：
- 使用 `@theme` 将所有 CSS 变量映射为 Tailwind token
- 设置 `prefix: 'tw-'` 避免与现有类名冲突（现有 `.nav-link`、`.panel`、`.field` 等大量无前缀类）
- 新组件优先用 Tailwind，旧组件保持现有 CSS 不动
- 通过 CSS 变量桥接：Tailwind 的 `theme.extend.colors` 引用 `var(--tm-*)`
- 使用 `@layer` 确保不污染旧样式优先级

### 7.2 文件结构变更

```
apps/web/src/
├── styles/
│   ├── tokens.css          ← 新：所有设计 token（单一事实源）
│   ├── base.css            ← 新：reset + 全局基础样式
│   ├── components.css      ← 新：通用组件样式
│   ├── utilities.css       ← 新：少量自定义 utility
│   └── legacy.css          ← 重命名现有 styles.css，逐步缩减
├── components/
│   ├── ui/                 ← 新：基础 UI 组件目录
│   │   ├── TmButton.vue
│   │   ├── TmIconButton.vue
│   │   ├── TmSegmentedSwitch.vue
│   │   ├── TmField.vue
│   │   ├── TmTextarea.vue
│   │   ├── TmSelect.vue
│   │   ├── TmFieldGroup.vue
│   │   ├── TmInlineHint.vue
│   │   ├── TmCard.vue
│   │   ├── TmSection.vue
│   │   ├── TmMetricCard.vue
│   │   ├── TmAuroraPanel.vue
│   │   ├── TmProgressTrack.vue
│   │   ├── TmAnchorNav.vue
│   │   └── TmToast.vue
│   ├── AppLayout.vue       ← 重写（AppShell Pattern）
│   ├── StatePanel.vue      ← 视觉升级（保留 props/events）
│   ├── StatusPill.vue      ← 视觉升级（保留 props/events）
│   └── LlmStatusNotice.vue ← 保持不动
└── views/
    ├── HomeView.vue        ← 重写（Narrative Hero Pattern）
    ├── NewTripView.vue     ← 重写（Workbench Pattern）
    ├── TripDetailView.vue  ← 重构信息层级（List-Detail Pattern）
    ├── TripsView.vue       ← 继承新 token，不重画
    ├── CommunityFeedView.vue       ← 继承新 token
    ├── CommunityPostDetailView.vue ← 继承新 token
    ├── AIImageStudioView.vue       ← 继承新 token
    ├── ExportView.vue              ← 继承新 token
    ├── SettingsView.vue            ← 继承新 token
    └── LoginView.vue               ← 继承新 token
```

### 7.3 实施顺序（推荐）

**Phase 1：基础设施**
1. 新建 `styles/tokens.css`，定义所有新 token
2. 新建 `styles/base.css`，全局 reset 和基础排版
3. 安装配置 Tailwind（prefix + @layer），确保 build 通过
4. 将现有 `styles.css` 重命名为 `legacy.css`，在 main.ts 中两者并存
5. 同步更新 `packages/ui/src/styles.css` 中的 token

**Phase 2：组件层**
6. 实现 TmButton（5 种变体）
7. 实现 TmField / TmTextarea / TmSelect / TmFieldGroup / TmInlineHint
8. 实现 TmCard / TmSection / TmMetricCard
9. 实现 TmSegmentedSwitch / TmProgressTrack
10. 实现 TmAuroraPanel / TmToast / TmAnchorNav
11. 升级 StatePanel / StatusPill 视觉（保留 props）

**Phase 3：页面重构**
12. 重写 AppLayout（定下母版节奏）
13. 重写 HomeView
14. 重写 NewTripView
15. 重构 TripDetailView（信息重排 + 锚点化 + 共享 AI 面板）

**Phase 4：收尾**
16. 次级页面继承新 token（替换旧变量引用）
17. 逐步清理 legacy.css 中不再使用的样式
18. 视觉回归测试

### 7.4 关键约束

- 不修改 `packages/shared-types`、后端接口、路由结构
- 现有组件的 props/events 接口不变，只改内部模板和样式
- `packages/ui` 的 `styles.css` 同步更新 token（保持两处一致）
- Tailwind 的 `@layer` 确保不污染旧样式的优先级
- 构建产物体积增量控制在 < 30KB gzip
- 不引入完整第三方组件库，保持自有轻量组件层
- 不做深色模式（token 结构预留扩展点）
- 不引入重插画资源

---

## 8. 测试计划

### 8.1 视觉回归

| 页面 | 390px | 768px | 1280px | 状态覆盖 |
|------|-------|-------|--------|----------|
| Home | ✓ | ✓ | ✓ | — |
| NewTrip | ✓ | ✓ | ✓ | form/chat/loading/error/empty/ready |
| TripDetail | ✓ | ✓ | ✓ | no-itinerary/generating/completed/exporting/published/stale |
| AppLayout | ✓ | ✓ | ✓ | with-job/without-job |

### 8.2 交互一致性

- 按钮 hover/active/focus 在所有变体上行为一致
- 表单错误态有明确视觉反馈（TmInlineHint + error ring）
- TmSegmentedSwitch 切换过渡流畅
- TmAnchorNav sticky 定位在滚动时稳定
- TmAuroraPanel 在 AI 活跃/静态/完成三态间正确切换
- 键盘 Tab 顺序在所有页面连贯
- focus-visible ring 在所有可交互元素上可见

### 8.3 性能基线

- Lighthouse Performance ≥ 90（桌面端）
- LCP < 2.5s
- CLS < 0.1
- 无 backdrop-filter 使用（全面移除）
- 无 layout shift 由 Tailwind 引入

### 8.4 工程验证

- `pnpm run build --filter @travelmind/web` 通过
- 旧页面（Settings、Export、LlmDemo）样式无变化
- CSS 变量在目标浏览器（Chrome 90+, Safari 15+, Firefox 90+）正常
- Tailwind purge 正确，无未使用样式残留
- 新旧样式不互相污染

---

## 9. 设计参考与灵感来源

组件结构参考了以下方向（吸收模式，不照搬视觉）：
- **响应式导航**：画框式 topbar + 移动端底部 sheet
- **卡片网格**：能力卡、指标卡的统一间距和 hover 行为
- **多步表单**：TmFieldGroup 折叠分组 + 进度引导
- **列表详情**：TripDetail 的锚点导航 + 分区内容
- **数据面板**：TmMetricCard 的数字突出 + 语义色标注
- **App Shell**：顶部导航 + 内容容器 + toast 通知的经典结构

参考资源：
- https://www.stylekit.top/en/tailwind-ui-prompts
- https://www.stylekit.top/en/ui-prompts

---

## 10. 假设与边界

- 本次以"工作台优先"为范围边界：AppLayout + Home + NewTrip + TripDetail
- 不做全站一次性翻新，次级页面只继承 token
- 不引入完整第三方组件库（如 Headless UI），保持 Vue 现有页面的控制力
- 不做深色模式，不引入重插画资源
- 每页最多 1 个低透明 SVG 线稿装饰
- 语言切换保留中英双语，所有新结构兼容 i18n 文案长度差异
- 移动端适配以"可用"为标准，不做独立移动端设计稿
- 不改后端接口、不改路由、不改 `shared-types` 业务契约

---

## 11. 与前版差异总结

| 维度 | v1 | v3 | v4 终版 |
|------|----|----|---------|
| 架构 | Token + 页面 | Token + 组件 + 页面骨架 | 三层架构 + 四种复用模式 |
| 组件 | 仅列出视觉规范 | 命名组件清单 | 完整组件表 + props 约束 + 视觉分工矩阵 |
| 页面 | 4 页详细 wireframe | 4 页改动描述 | 4 页 wireframe + 现有代码对照 + 改动清单 |
| Tailwind | 引入 | 渐进引入+前缀 | prefix + @layer + 变量桥接 + 旧样式隔离 |
| backdrop-filter | 保留在模态遮罩 | 未提及 | 全面移除（性能考虑） |
| 实施顺序 | 7 步线性 | 4 步分层 | 4 Phase 18 步，依赖关系明确 |
| 次级页面 | 后续处理 | 只继承 token | 只继承 token + 明确不重画布局 |
| 内容宽度 | 1200px | 1200–1280px | 统一 1280px |
| 组件灵感 | 未提及 | stylekit.top 参考 | 明确吸收 5 种模式，不照搬视觉 |
