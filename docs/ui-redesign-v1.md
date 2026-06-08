# TravelMind UI 重构方案 v1（完善版）

## 0. 设计哲学

**"治愈旅感 AI"** — 三层视觉语言的精确配比：

| 层级 | 风格来源 | 占比 | 职责 |
|------|----------|------|------|
| 底色层 | 日系清新 + 吉卜力温暖 | 70% | 页面背景、留白、文字排版、信息卡片 |
| 触感层 | Soft UI（新拟态） | 20% | 按钮、输入框、可交互元素的凹凸质感 |
| 点睛层 | Y2K 虹彩 | 10% | AI 状态、生成动效、CTA 高光、模式切换 |

核心原则：
- 留白即呼吸 — 模块间距不低于 24px，主内容区最大宽度 1200px
- 一页一焦点 — 每屏只有一个视觉重心
- AI 是配角 — 虹彩高光只服务于"正在发生的 AI 行为"，静态信息保持温和
- 装饰克制 — 每页最多 1 个手绘线稿 + 1 种微纹理，禁止满屏插画

---

## 1. 设计 Token 体系

### 1.1 色彩

```css
:root {
  /* === 基础色（日系清新底色）=== */
  --tm-paper: #F6F2EB;        /* 主背景：温暖米纸 */
  --tm-mist: #EEF1EC;         /* 次背景：薄雾绿灰 */
  --tm-snow: #FDFCFA;         /* 卡片/面板底色 */
  --tm-moss: #5D7A63;         /* 主色调：苔藓绿 */
  --tm-tea: #2B2A28;          /* 正文墨色 */
  --tm-clay: #C98F6B;         /* 暖色点缀：陶土橙 */
  --tm-stone: #8A8580;        /* 辅助灰：石色 */

  /* === AI 虹彩点缀（仅 10-15% 面积）=== */
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
- `moss` 替代现有 `#0f5e3c`，饱和度降低使整体更柔和，用于主按钮、链接、进度条
- `clay` 继承现有 `warm` 角色，用于 kicker 标签、次要强调、hover 状态
- `aurora-*` 三色仅用于：AI 生成中的边框渐变、模式切换的激活态、CTA 按钮的微光
- 禁止将 aurora 色用作大面积背景或文字颜色

### 1.2 圆角与边框

```css
:root {
  --tm-radius-sm: 8px;       /* chip、badge */
  --tm-radius-md: 12px;      /* 输入框、小卡片 */
  --tm-radius-lg: 16px;      /* 标准卡片 */
  --tm-radius-xl: 24px;      /* 大面板、模态框 */
  --tm-radius-2xl: 32px;     /* Hero 区域 */
  --tm-radius-full: 999px;   /* 胶囊按钮 */

  --tm-border-hairline: 1px solid rgba(43, 42, 40, 0.06);
  --tm-border-subtle: 1px solid rgba(43, 42, 40, 0.10);
  --tm-border-visible: 1px solid rgba(43, 42, 40, 0.16);
}
```

### 1.3 阴影（Soft UI 双套系统）

```css
:root {
  /* Raised（凸起）— 按钮默认态、卡片悬浮 */
  --tm-shadow-raised-sm: 4px 4px 8px rgba(166, 158, 146, 0.15),
                         -2px -2px 6px rgba(255, 255, 255, 0.7);
  --tm-shadow-raised-md: 6px 6px 16px rgba(166, 158, 146, 0.18),
                         -4px -4px 12px rgba(255, 255, 255, 0.8);
  --tm-shadow-raised-lg: 12px 12px 32px rgba(166, 158, 146, 0.12),
                         -6px -6px 20px rgba(255, 255, 255, 0.9);

  /* Inset（凹陷）— 输入框、进度槽、toggle 凹槽 */
  --tm-shadow-inset-sm: inset 2px 2px 4px rgba(166, 158, 146, 0.12),
                        inset -1px -1px 3px rgba(255, 255, 255, 0.5);
  --tm-shadow-inset-md: inset 3px 3px 8px rgba(166, 158, 146, 0.15),
                        inset -2px -2px 6px rgba(255, 255, 255, 0.6);

  /* Float（浮层）— 下拉菜单、tooltip、模态 */
  --tm-shadow-float: 0 8px 32px rgba(43, 42, 40, 0.08),
                     0 2px 8px rgba(43, 42, 40, 0.04);
}
```

Soft UI 使用边界：
- 只在 `paper` 或 `mist` 背景上使用 raised/inset 阴影，深色背景上退化为普通投影
- 按钮 `:active` 态从 raised 切换到 inset，模拟物理按压
- 输入框默认 inset，`:focus` 时加 moss 色 ring 但保留 inset 底
- 卡片不使用 Soft UI 阴影，保持传统轻投影（避免页面过于"鼓包"）

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
- `display` 仅用于 Hero 大标题和页面级标题（h1），营造"书卷气"
- `body` 用于所有正文、按钮、表单标签
- `mono` 用于预算数字、日期、API 状态码等数据类信息
- 中文标题行高 1.2，正文行高 1.6；英文可适当收紧

### 1.5 间距系统

基于 4px 基准的 8 级阶梯：4 / 8 / 12 / 16 / 24 / 32 / 48 / 64 / 80px

关键约束：
- 卡片内边距统一 24px（移动端 16px）
- 模块间距统一 24px（桌面端可放大到 32px）
- 页面级区块间距 48-64px
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
- L4 AI 专属（虹彩扫光/脉冲/粒子）：2-4s 循环，仅在 AI 活跃时播放

`prefers-reduced-motion` 下：L1-L3 时长归零（瞬切），L4 完全禁用

---

## 2. 组件视觉规范

### 2.1 按钮系统

| 变体 | 场景 | 视觉 |
|------|------|------|
| Primary | 主 CTA（创建行程、生成） | moss 实色底 + raised 阴影，hover 时微上浮 |
| Secondary | 次要操作（清空、返回） | snow 底 + hairline 边框 + raised-sm |
| Ghost | 内联操作（查看详情） | 透明底，hover 时显示 mist 背景 |
| AI CTA | AI 生成/对话发送 | moss 底 + aurora 渐变边框微光环绕 |
| Danger | 删除、取消 | error 色底，仅在确认态显示 |

按钮交互态：
- `:hover` — translateY(-1px) + shadow 加深
- `:active` — translateY(0) + 切换到 inset 阴影（按压感）
- `:focus-visible` — 2px moss ring，offset 2px
- `:disabled` — opacity 0.5，去除阴影，cursor not-allowed

### 2.2 输入框

所有输入框统一为"浅色凹陷"风格：
- 默认：snow 背景 + inset-sm 阴影 + radius-md
- `:hover`：背景微亮到 #FFFFFF
- `:focus`：保留 inset 底 + 外加 `0 0 0 3px rgba(93, 122, 99, 0.12)` ring
- 错误态：ring 变为 error 色，底部出现错误文案
- 标签使用 body 字体 700 weight，text-sm

### 2.3 卡片

三种卡片层级：
- **信息卡**（trip-card, day-card）：snow 底 + hairline 边框 + shadow-float 的 0.3x 版本
- **操作卡**（metric-card, quick-action）：mist 底 + subtle 边框，hover 时提升为 snow + raised-sm
- **高亮卡**（AI 结果、highlight）：渐变底 `linear-gradient(135deg, rgba(93,122,99,0.08), rgba(201,143,107,0.06))` + subtle 边框

### 2.4 导航栏（Topbar）

从当前"胶囊按钮堆砌"改为"旅行画框"式：
- 容器：snow 底 + radius-2xl + shadow-float，不再使用 backdrop-filter（性能考虑）
- 品牌区：保留 brand-mark 但改为 moss 渐变圆角方块 + 衬线体品牌名
- 导航项：去掉胶囊边框，改为纯文字 + 底部 2px 细线指示激活态
- 激活态：文字变 moss 色 + 底部细线 + 微弱的 moss 背景晕染
- 语言切换：缩小为图标级 toggle，不再占据显眼位置
- 移动端：折叠为汉堡菜单 + 底部 sheet

### 2.5 StatusPill（保留 props，升级视觉）

- 去掉现有的纯色块背景，改为更柔和的色调
- 使用语义色的 8% 透明度做背景 + 对应前景色文字
- 加 1px 同色系 12% 透明度边框
- 圆角改为 radius-sm（8px），不再用 full pill

### 2.6 AI 状态指示器（新增组件）

当 AI 正在工作时的统一视觉语言：
- 边框：1px 渐变边框，aurora-cyan → aurora-lilac → aurora-rose 循环
- 脉冲：边框上叠加一个 4px 宽的高光点沿边框运动（3s 一圈）
- 进度条：底色 mist，填充使用 aurora 三色渐变
- 文字状态：stone 色 + 呼吸闪烁（opacity 0.6 ↔ 1.0）

适用场景：NewTrip 对话模式的输入框、TripDetail 生成中的面板边框、Job 进行中的 timeline 卡片

---

## 3. 页面重构详案

### 3.1 AppLayout（母版）

**现状问题：**
- topbar 使用 grid 三栏但在中等屏幕下导航项挤压
- 背景 job banner 视觉权重过高，与内容区竞争注意力
- 缺少全局的页面过渡动效

**改造方案：**

```
┌─────────────────────────────────────────────────────┐
│  [Brand]     Home  Trips  Community  AI Images  [⚙] │  ← 画框式顶栏
├─────────────────────────────────────────────────────┤
│  ┌─ Background Job (条件显示) ──────────────────┐   │  ← 收缩为 toast 条
│  │  🔄 行程生成中... 3/5 步骤        [查看 →]   │   │
│  └──────────────────────────────────────────────┘   │
│                                                     │
│              [ 页面内容区 ]                          │  ← max-width: 1200px
│              route-view with transition              │
│                                                     │
└─────────────────────────────────────────────────────┘
```

关键改动：
- topbar 改为 flexbox 单行，导航居中，品牌左对齐，工具右对齐
- background-job-banner 收缩为 48px 高的 toast 条，使用 info 语义色
- 页面内容区加 `max-width: 1200px; margin: 0 auto; padding: 0 24px`
- 路由切换加 fade + translateY(8px) 过渡

### 3.2 首页（HomeView）

**现状问题：**
- Hero 区是功能介绍卡片，缺乏品牌叙事和情感共鸣
- highlight-card 列表式罗列功能点，没有视觉层次
- 整体像"功能说明书"而非"旅行灵感入口"

**改造方案：**

```
┌─────────────────────────────────────────────────────┐
│                                                     │
│     ✦ TravelMind AI                                 │
│                                                     │
│     让每一次出发                                     │  ← 衬线体大标题
│     都有迹可循                                       │     text-4xl, moss 色
│                                                     │
│     从灵感碎片到可执行的旅行计划，                    │  ← stone 色副标题
│     AI 帮你把"想去"变成"出发"。                      │
│                                                     │
│     [ 开始规划 ]  [ 浏览社区灵感 ]                   │  ← Primary + Ghost
│                                                     │
│  ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─   │
│                                                     │
│  ┌──────────┐  ┌──────────┐  ┌──────────┐          │
│  │ 🗺 智能   │  │ 📋 结构化 │  │ 📤 一键   │          │  ← 三列能力卡
│  │ 行程规划  │  │ 信息采集  │  │ 导出分享  │          │     hover 时微上浮
│  │          │  │          │  │          │          │
│  │ 简短描述  │  │ 简短描述  │  │ 简短描述  │          │
│  └──────────┘  └──────────┘  └──────────┘          │
│                                                     │
│  ┌─ 装饰 ─────────────────────────────────────────┐ │
│  │  右下角：一枝手绘植物线稿（SVG, opacity 0.06）  │ │
│  │  背景：paper 底 + 左上角 moss 径向渐变 3% 透明  │ │
│  └────────────────────────────────────────────────┘ │
└─────────────────────────────────────────────────────┘
```

关键改动：
- Hero 改为全宽叙事区，不再左右分栏
- 标题使用 `font-display`（衬线体），正文使用 `font-body`
- 去掉 highlight-card 的列表，改为底部三列能力卡（简洁图标 + 一句话）
- CTA 区只保留 2 个按钮，主次分明
- 背景装饰：仅一个低透明度 SVG 线稿 + 微弱径向渐变

### 3.3 NewTrip（行程意图采集工作台）

**现状问题：**
- 表单和对话模式切换不够直观，两种模式视觉差异不足
- 表单字段平铺，缺乏分组和进度感
- 对话模式的 AI 气泡和用户气泡区分不明显
- 右侧摘要缺少"完成度"引导

**改造方案：**

```
┌─────────────────────────────────────────────────────────────────┐
│  ┌─ 情绪 Hero ───────────────────────────────────────────────┐  │
│  │  新建行程 · 整理你的旅行意图                               │  │
│  │  [ 📝 表单模式 ]  [ 💬 对话模式 ]  ← Soft UI toggle       │  │
│  └───────────────────────────────────────────────────────────┘  │
│                                                                 │
│  ┌─ 主操作区 (左 60%) ──────┐  ┌─ 草稿摘要 (右 40%) ────────┐  │
│  │                          │  │                             │  │
│  │  [表单模式时]             │  │  完成度 ████████░░ 75%     │  │
│  │  ┌─ 基础行程 ──────────┐ │  │                             │  │
│  │  │ 标题 / 出发地 / 目的 │ │  │  ✓ 目的地：汕头             │  │
│  │  │ 地 / 日期           │ │  │  ✓ 日期：4.14-4.18          │  │
│  │  └─────────────────────┘ │  │  ✓ 预算：¥6,800             │  │
│  │  ┌─ 预算与人数 ────────┐ │  │  ○ 住宿偏好：未填           │  │
│  │  │ 预算 / 人数 / 节奏  │ │  │  ○ 兴趣标签：未填           │  │
│  │  └─────────────────────┘ │  │                             │  │
│  │  ┌─ 偏好风格 ──────────┐ │  │  ─────────────────────────  │  │
│  │  │ 兴趣 / 交通 / 节奏  │ │  │  💡 推荐下一步：            │  │
│  │  └─────────────────────┘ │  │  补充住宿偏好可让 AI 生成   │  │
│  │  ┌─ 住宿需求 ──────────┐ │  │  更精准的方案               │  │
│  │  │ 住宿类型偏好        │ │  │                             │  │
│  │  └─────────────────────┘ │  │  [ 直接创建也可以 ]         │  │
│  │                          │  └─────────────────────────────┘  │
│  │  [对话模式时]             │                                   │
│  │  ┌─ AI 对话区 ─────────┐ │  ← 虹彩边框（AI 活跃时）        │
│  │  │ 🤖 Assistant 气泡   │ │                                   │
│  │  │    (mist 底 + 左对齐)│ │                                   │
│  │  │ 👤 User 气泡        │ │                                   │
│  │  │    (snow 底 + 右对齐)│ │                                   │
│  │  │                     │ │                                   │
│  │  │ ┌─ 输入框 ────────┐ │ │                                   │
│  │  │ │ [aurora 边框]    │ │ │                                   │
│  │  │ └─────────────────┘ │ │                                   │
│  │  └─────────────────────┘ │                                   │
│  └──────────────────────────┘                                   │
│                                                                 │
│  ┌─ Action Rail ────────────────────────────────────────────┐   │
│  │  [示例草稿]  [清空]           [创建行程]  [创建并生成 ✦]  │   │
│  └──────────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────────┘
```

关键改动：
- 顶部情绪 Hero 精简为一行标题 + 模式 toggle（Soft UI 凹凸切换）
- 表单按逻辑分 4 组，每组有折叠标题，输入框统一 inset 风格
- 对话区独立使用 AI 视觉语言：虹彩边框 + 渐变状态条
- 气泡区分：Assistant 用 mist 底 + 左对齐 + moss 色名字标签；User 用 snow 底 + 右对齐
- 右侧 sticky 摘要新增：进度条 + 已填/未填清单 + 智能建议
- 底部 action rail 固定在视口底部（移动端）或内容底部（桌面端）
- 按钮主次：Ghost（示例/清空）→ Secondary（创建）→ AI CTA（创建并生成）

### 3.4 TripDetail（结果解读与再规划工作台）

**现状问题：**
- 信息密度高但缺乏层次，用户不知道先看什么
- AI 生成状态和普通信息卡视觉权重相同
- 长列表缺乏锚点导航
- 操作按钮散落各处

**改造方案：**

```
┌─────────────────────────────────────────────────────────────────┐
│  ┌─ 概览摘要条 ─────────────────────────────────────────────┐   │
│  │  🗺 汕头美食之旅  ·  4天3夜  ·  ¥6,800  ·  2人           │   │
│  │  [completed ●]  生成于 2026-04-10                         │   │
│  └──────────────────────────────────────────────────────────┘   │
│                                                                 │
│  ┌─ 锚点导航 ──────────────────────────────────────────────┐    │
│  │  [概览]  [行程]  [搜索资料]  [社区]  [优化]  [导出]      │    │
│  └─────────────────────────────────────────────────────────┘    │
│                                                                 │
│  ┌─ 核心指标网格 ───────────────────────────────────────────┐   │
│  │  ┌────────┐ ┌────────┐ ┌────────┐ ┌────────┐            │   │
│  │  │ 总预算  │ │ 天数   │ │ 景点数  │ │ 风险项  │            │   │
│  │  │ ¥6,800 │ │ 4 天   │ │ 12 个  │ │ 2 项   │            │   │
│  │  └────────┘ └────────┘ └────────┘ └────────┘            │   │
│  └──────────────────────────────────────────────────────────┘   │
│                                                                 │
│  ┌─ 行程时间线 ────────────────────────────────────────────┐    │
│  │  Day 1 · 4月14日 · 抵达与老城探索                        │    │
│  │  ├─ 09:00  高铁抵达汕头站                                │    │
│  │  ├─ 10:30  入住酒店                                      │    │
│  │  └─ 14:00  老城区漫步                                    │    │
│  │                                                          │    │
│  │  Day 2 · 4月15日 · 美食深度游                            │    │
│  │  ├─ ...                                                  │    │
│  └─────────────────────────────────────────────────────────┘    │
│                                                                 │
│  ┌─ AI 操作面板（生成/优化时显示虹彩边框）─────────────────┐    │
│  │  Quick Refine: [输入优化指令...]        [提交优化 ✦]     │    │
│  └─────────────────────────────────────────────────────────┘    │
└─────────────────────────────────────────────────────────────────┘
```

关键改动：
- 顶部新增"概览摘要条"：一行展示核心信息（目的地、天数、预算、状态）
- 新增锚点导航条（sticky），解决长页面定位问题
- 核心指标改为 4 列网格，使用 mono 字体突出数字
- 行程时间线改为左侧时间轴样式（竖线 + 节点），替代现有平铺卡片
- AI 操作面板（生成/refine/导出）统一使用同一套视觉：
  - 静态时：普通 panel 样式
  - AI 活跃时：虹彩边框 + 脉冲动效 + 进度条
  - 完成时：moss 色 success 边框闪现后恢复普通
- 搜索资料、社区发布、导出等次要功能收入对应锚点区域，不在首屏争夺注意力

---

## 4. 装饰语言规范

### 4.1 允许的装饰元素

| 类型 | 规格 | 使用限制 |
|------|------|----------|
| 手绘线稿 | SVG，stroke-only，1-2px 线宽 | 每页最多 1 个，opacity ≤ 0.06 |
| 微纹理噪点 | SVG filter 或 CSS noise | 每页最多 1 种，opacity ≤ 0.03 |
| 径向渐变 | moss/clay 色，3-5% 透明度 | 仅用于页面背景角落 |
| AI 光晕 | aurora 三色径向渐变 | 仅用于 AI CTA 按钮背后，半径 ≤ 120px |

### 4.2 禁止的装饰元素

- 厚重描边（> 2px）
- 廉价玻璃拟态（高模糊 + 高饱和度边框）
- Y2K 金属质感大面积底色
- 满屏插画或照片背景
- 动态粒子/星空等重性能装饰
- 多于 2 种渐变叠加

### 4.3 AI 视觉语言的边界

AI 虹彩效果只在以下场景出现：
1. AI 正在生成/处理中 — 边框渐变动画
2. 模式切换 toggle 的激活态 — 微弱渐变背景
3. "创建并生成"等 AI CTA 按钮 — 按钮边缘微光
4. 生成完成瞬间 — 0.5s 的 aurora 闪烁后消失

其他所有场景（信息展示、表单填写、列表浏览）保持温和中性。

---

## 5. 响应式策略

### 5.1 断点

```css
/* 移动端优先 */
--breakpoint-sm: 640px;   /* 大手机横屏 */
--breakpoint-md: 768px;   /* 平板竖屏 */
--breakpoint-lg: 1024px;  /* 平板横屏/小笔记本 */
--breakpoint-xl: 1280px;  /* 标准桌面 */
```

### 5.2 各页面响应式要点

**AppLayout：**
- < 768px：topbar 折叠为 logo + 汉堡菜单，导航移入底部 sheet
- < 768px：background-job-banner 变为顶部固定 toast

**NewTrip：**
- < 1024px：右侧摘要从 sticky 侧栏变为顶部可折叠摘要条
- < 768px：表单分组改为手风琴（accordion），一次展开一组
- < 768px：action rail 固定在视口底部

**TripDetail：**
- < 1024px：核心指标从 4 列变 2 列
- < 768px：锚点导航变为水平滚动 tab bar
- < 768px：时间线取消左侧时间轴，改为卡片堆叠

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
- 设置 `prefix: 'tw-'` 避免与现有类名冲突
- 新组件优先用 Tailwind，旧组件保持现有 CSS 不动
- 通过 CSS 变量桥接：Tailwind 的 `theme.extend.colors` 引用 `var(--tm-*)`

### 7.2 迁移步骤

**Phase 1（本次 v1）：**
1. 新建 `apps/web/src/tokens.css` — 所有新 token 定义
2. 安装配置 Tailwind，确保 build 通过
3. 重写 AppLayout（topbar + content wrapper）
4. 重写 HomeView
5. 重写 NewTripView
6. 重写 TripDetailView 的概览区和锚点导航
7. 升级 StatusPill、StatePanel 视觉（保留 props）

**Phase 2（后续）：**
- TripDetail 完整重构（时间线、搜索、社区、导出区）
- CommunityFeedView / CommunityPostDetailView
- AIImageStudioView
- 旧 CSS 逐步清理

### 7.3 文件结构变更

```
apps/web/src/
├── styles/
│   ├── tokens.css          ← 新：所有设计 token
│   ├── base.css            ← 新：reset + 全局基础样式
│   ├── components.css      ← 新：通用组件样式（按钮、卡片等）
│   ├── utilities.css       ← 新：少量自定义 utility
│   └── legacy.css          ← 重命名现有 styles.css，逐步缩减
├── components/
│   ├── ui/                 ← 新：基础 UI 组件目录
│   │   ├── TmButton.vue
│   │   ├── TmInput.vue
│   │   ├── TmCard.vue
│   │   ├── TmAuroraFrame.vue  ← AI 虹彩边框组件
│   │   └── TmProgressRing.vue
│   ├── AppLayout.vue       ← 重写
│   ├── StatePanel.vue      ← 视觉升级
│   └── StatusPill.vue      ← 视觉升级
└── views/
    ├── HomeView.vue        ← 重写
    ├── NewTripView.vue     ← 重写
    └── TripDetailView.vue  ← 部分重写
```

### 7.4 关键约束

- 不修改 `packages/shared-types`、后端接口、路由结构
- 现有组件的 props/events 接口不变，只改内部模板和样式
- `packages/ui` 的 `styles.css` 同步更新 token（保持两处一致）
- Tailwind 的 `@layer` 确保不污染旧样式的优先级
- 构建产物体积增量控制在 < 30KB gzip

---

## 8. 测试计划

### 8.1 视觉回归

| 页面 | 390px | 768px | 1280px | 状态覆盖 |
|------|-------|-------|--------|----------|
| Home | ✓ | ✓ | ✓ | — |
| NewTrip | ✓ | ✓ | ✓ | form/chat/loading/error/empty/ready |
| TripDetail | ✓ | ✓ | ✓ | no-itinerary/generating/completed/exporting/published |
| AppLayout | ✓ | ✓ | ✓ | with-job/without-job |

### 8.2 交互测试

- 键盘 Tab 顺序在所有页面连贯
- focus-visible ring 在所有可交互元素上可见
- 按钮 disabled 态视觉明确且不可点击
- 表单验证错误态有明确视觉反馈
- 对话模式输入框在 AI 处理中显示 loading 态
- 模式切换（form ↔ chat）过渡流畅

### 8.3 性能基线

- Lighthouse Performance ≥ 90（桌面端）
- LCP < 2.5s
- CLS < 0.1
- 无 layout shift 由 Tailwind 引入
- backdrop-filter 使用量减少（仅保留模态遮罩）

### 8.4 工程验证

- `pnpm run build --filter @travelmind/web` 通过
- 旧页面（Settings、Export、LlmDemo）样式无变化
- CSS 变量在所有目标浏览器（Chrome 90+, Safari 15+, Firefox 90+）正常工作
- Tailwind purge 正确，无未使用样式残留

---

## 9. 与原方案的差异说明

| 原方案点 | 完善后调整 | 原因 |
|----------|-----------|------|
| 引入 Tailwind | 加 `prefix: 'tw-'` + `@layer` 隔离 | 现有 CSS 类名多，避免冲突 |
| 顶栏"旅行画框" | 去掉 backdrop-filter，改为实色底 | 性能考虑，blur 在低端设备卡顿 |
| 字体 Noto Serif SC | 仅用于 h1 级标题 | 衬线体大面积使用会降低可读性 |
| Soft UI 全局 | 限定为按钮和输入框 | 卡片用 Soft UI 会导致页面"鼓包感"过重 |
| Y2K 10-15% | 精确定义 4 个使用场景 | 避免执行时边界模糊导致滥用 |
| 右侧摘要 | 新增完成度进度条 + 智能建议 | 解决"用户不知道何时可以创建"的问题 |
| TripDetail 长列表 | 新增锚点导航 + 概览摘要条 | 解决信息密度高但无主次的核心问题 |
| 装饰语言 | 量化限制（opacity、数量、尺寸） | 避免"克制"变成主观判断 |

---

## 10. 假设与边界

- v1 不做全站翻新，社区和 AI 生图页继承新 token 但不重画布局
- v1 不引入重资产插画，装饰以 CSS/SVG 为主
- 语言切换保留中英双语，所有新结构兼容 i18n 文案长度差异
- 不引入第三方组件库（如 Headless UI），保持现有纯手写组件的控制力
- 暗色模式不在 v1 范围内，但 token 结构预留 `@media (prefers-color-scheme: dark)` 扩展点
- 移动端适配以"可用"为标准，不做独立的移动端设计稿