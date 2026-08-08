---
name: repo-port
description: "找现成方案/开源库：引入依赖、复用仓库能力的 USE/ADAPT/EXTRACT/IGNORE 决策。"
license: Apache-2.0
version: 2.1.0
author: Xi
platforms: [windows, linux, macos]
metadata:
  category: methodology
  tags: [meta, repo-port, capability-sourcing, mature-solution-first]
---

# Repo-Port — 外部能力采购系统（通用架构迁移治理）

> **不是** GitHub 推荐工具 / 代码搬运工具 / 架构收藏夹。
> **是** 外部能力采购系统：输入"我缺什么能力"，输出"这个能力是否存在、谁解决、为什么可信、应该如何采用、是否破坏现有系统、如何长期维护"。

## 任务开始时先过这道闸（Auto-Gate，2026-08-08 新增）

**任何任务的开头，先问 3 个问题**（不是等任务失败后才想起 repo-port）：

```
1. 这个任务需要"能力"吗？（要做某事/要某功能/要某库）
   ├── 不需要 → 继续正常流程
   └── 需要 ↓
2. 这个能力世界上可能已经有现成的吗？
   ├── 完全不可能（全新领域/纯业务逻辑）→ 原创，记入"已查无方案"
   └── 可能 ↓
3. 走 repo-port 决策链：
   search（找候选）→ explore（探索）→ intelligence（理解）
   → USE/ADAPT/EXTRACT/IGNORE（决策）→ extraction（提取）
```

**触发信号（出现任一即自动介入）**：
- "我要实现 X" → 先查"有没有现成的 X"
- "要不要用/引入 Y 库" → 走决策链
- "这个功能自己写还是用现成的" → 走决策链
- "找开源项目/工具做 Z" → search
- "X 库的 Y 能力能复用到我这边吗" → intelligence + 决策
- 任何"卡住/反复试/不确定" → **说明还没查够，立即转向探索**（反模式红线）

**为什么前置**：个人用户最大限制是维护时间，不是写码能力。
先查现成方案的成本（几分钟搜索）远低于自造的长期维护成本（永远的技术债）。
这是"成熟方案优先"原则的落地闸门——**默认先查，原创必须证明查过**。

## Mature Solution First Principle（成熟方案优先原则，最高防线）

**如果一个问题已经有成熟、活跃、边界匹配的解决方案，默认优先使用，而不是重新实现。**

但注意：
- 不是"看到优秀项目必须使用"
- 必须**证明**：①它解决我的问题 ②边界匹配 ③维护成本合理 —— 才使用

**个人用户默认策略（2026-08-01 强化 + 边界条件）**：
- **成熟仓库 + 问题边界匹配 → 直接 USE 是默认**（不是 ADAPT）
- **成熟但边界不匹配 → IGNORE**（Kubernetes/LangGraph 很成熟，个人用户边界不匹配 → 不引入）
- 原因：个人最大的限制不是代码能力，而是**维护时间有限 / 调试能力有限 / 上游更新跟踪困难 / 容易创造自己的技术债**
- 反模式："AgentChat 解决网页 AI Agent → 我读源码抽 receipt 自己写 Hermes 版本" ❌ 错误方向（除非边界无法嵌入）

### Adapter Principle（适配层原则，2026-08-01 升级为最高原则之一）

**判断任何中间层是否合理的唯一标准**：

> 这个中间层是在**隐藏复杂度**，还是**增加复杂度**？

| 类型 | 例子 | 判定 |
|------|------|------|
| **必要基础设施边界** | 10 个模型供应商（不同协议/参数/鉴权/streaming）→ LiteLLM → 统一 OpenAI 接口 | ✅ 隐藏复杂度（供应商碎片化是天然问题，LiteLLM 已解决 → USE）|
| **必要能力恢复层** | 模型输出格式不稳 → ClawRouter | ✅ 隐藏复杂度 |
| **危险的自制 wrapper** | 已有完整 AgentChat → 自己写 Hermes Receipt Wrapper | ❌ 增加复杂度（原仓库已是完整产品，重新实现已有能力）|

**关键区分**：LiteLLM 不是"为用别人项目多加的转接"——它是**已验证的必要抽象边界**（供应商碎片化天然存在，LiteLLM 降低系统复杂度 → USE）。完整案例 → `reference/examples.md` 案例 1。

**注意**：ADAPT 成立必须证明**能力契约一致但实现环境完全不兼容**（如 AgentChat receipt 依赖 Node/CDP/browser worker，我的环境是 Python/API/tool call）——否则就是"重新实现已有能力"。

### 个人用户决策顺序（升级版）

```
发现成熟仓库
    ↓
能直接用？
    ├── 是 → USE（默认！）
    └── 否 ↓
只是接口不同？
    ├── 是 → DEPENDENCY / Adapter（如 LiteLLM 统一多供应商）
    └── 否 ↓
环境完全不同？
    ├── 是 → ADAPT（如 AgentChat：浏览器环境 vs API 环境）
    └── 否 ↓
IGNORE
```

**反模式（血泪教训）**：先手动试错，试不动了才去查。判断标准：**如果某个问题让我"卡住/反复试/不确定"，说明我还没查够**——立即停下转向探索。

## 六阶段流程

```
1. Discovery            → 找到可能解决问题的仓库
2. Capability Extraction → 它到底提供什么能力
3. Usage Validation     → 它应该如何被使用（L1-L5）
4. Adoption Decision    → 为什么用/为什么不用原仓库（五级）
5. Integration Validation → 如何进入现有系统（不破坏）
6. Continuous Evolution → 未来如何替换/升级
```

## 决策链（含代码质量审核层，2026-08-08 补）

> ⚠️ **关键补丁**：决策链不能止于"用途理解"（repository-intelligence 的 Capability Model），
> 必须加**代码质量审核**（codegate）——否则 star 数会误导决策（6.5k★ 可能是烂代码，
> 500★ 可能干净利落）。**代码质量是决策输入，不是可选项。**

```
repository-search（发现候选）
  → repo-explorer（克隆+扫描+走读）
  → repository-intelligence（用途层：Capability Model——它解决什么问题）
  → ★ codegate（质量层：它实现得好不好？过度工程吗？值不值得借鉴？）★ 必经
  → repo-port 决策（USE/ADAPT/EXTRACT/IGNORE，基于 用途+质量 双重证据）
  → repository-extraction（提取，带 Source Lock）
```

**codegate 在决策中的角色**（不是审核"我们的代码"，是审核**候选仓库的代码**）：
- `ponytail-audit` → 候选仓库是否堆复杂度（过度工程 → 降级 IGNORE/EXTRACT）
- `multi-role-review` → 安全/正确性/性能/可读性五视角（质量问题 → 影响 USE 决策）
- `adversarial-debate` → 对"这模块做得对不对/值不值得"存疑时的对抗验证
- 结论写入决策理由："质量审核发现 X → 影响决策 Y"

### 能力边界（2026-08-08 定稿，防"加载=获得能力"幻觉）

**repo/技能本身不是全栈工程师——它只是说明文本 + 检查清单，不包含任何"代码/编程/审核"能力。**

- 加载 codegate = 获得**审核清单**（哪些视角、查什么、怎么判），**不是**获得审核能力
- 真正的审核由 **agent 主动执行**：读代码 → 应用清单 → 判断——这是模型推理 + 方法论（验证匹配形态/证据优先/注释即检验）
- "★ codegate 必经"的语义 = **agent 必须主动过质量审核层**，不是"加载了就有"
- 技能无法阻止跳过它（实测：EXTRACT 未过审就执行，技能不会拦截）——靠 agent 自律 + 用户监督
- 文档把"路由到 X"写成"获得能力"= 过度承诺（原 repo 同病：SKILL.md 是说明文本，不是工程师）

**触发信号（进入 codegate 的条件）**：
- 决策前一律快速过 ponytail-audit（最小成本，全量跳过有风险）
- USE 决策前必须 multi-role-review（要全量采用，必须先审质量）
- 任何"这个思路值得借鉴吗/大神为什么这样想"→ adversarial-debate + multi-role-review

### 理解 vs 审核：边界（2026-08-08 定稿，防混淆）

**审核 ≠ 理解。审核预设理解，但永远不等于理解。**

| | 理解（Understand） | 审核（Review/Audit） |
|---|---|---|
| 动作 | **吸收**：它做什么、为什么这么做 | **评判**：做得好不好、过度工程吗 |
| 产出 | 能力模型、结构图、大神思路复述 | **Findings 问题清单**、质量判定、风险 |
| 问题 | "它怎么想的？" | "它想得对不对？" |
| 负责 | repo-explorer + repository-intelligence | **codegate** |
| 结束状态 | 我**知道**了 | 我**判断**了 |

**"大神为什么这样想"属于理解层**（走读源码/文档/commit 历史推理设计意图）；
**审核层验证"这个思路是否成立"**（挑盲区、找过度工程、挑战假设）。

**两个坑**：
- ❌ 把审核当理解 → codegate 直接审没走读过的仓库 → findings 全凭猜测（空审）
- ❌ 把理解当审核 → intelligence 说"很完善"就 USE → 没评估质量（盲信）

**链条语义**：先理解透（吸收）→ 再审核狠（评判）→ 最后决策（两者合并，缺一不可）。

---

## 1. Discovery（发现）

根据**能力缺口**找候选仓库（不是"它牛不牛"）：
- 官方仓库 / 官方 issue / 社区仓库 / 社区 issue / 大神方案 / 大型配置
- 多源交叉验证
- 路由：`skills/repository-search/SKILL.md`

## 2. Capability Extraction（能力提取）

理解仓库 → 结构化能力模型：
- 路由：`skills/repository-intelligence/SKILL.md`
- 输出：`capability-records/<repo>/discovery.md`

## 3. Usage Validation（使用方式验证）

**目的**：避免"看起来正确"的架构幻觉——看到优秀组件就抽能力硬塞进自己的架构，破坏原设计边界。

**核心问题**：这个项目真正解决什么问题？它应该作为系统中的什么角色存在？

### 六层验证模型

| 层 | 回答 | 证据源 |
|----|------|--------|
| L1 作者设计意图 | 作者想解决什么？定位/类型/明确不负责什么 | README / docs / examples / architecture / issues |
| L2 源码边界 | 它实际上是什么？（入口→核心模块→调用方向→数据流）| 源码（README 可能说谎，源码不会）|
| L3 社区真实使用 | 用户实际上怎么用？| issues 问题类型 / PR 贡献方向 / forks |
| L4 高质量组合方式 | 成熟用户如何组合？边界在哪？| 大神架构 / 主流 stack |
| **L5 反事实验证** | 删除/故障/替换/泄漏它，系统会怎样？| 冲突测试（见下）|
| **L6 Context Fit** | 它为什么适合我的场景？| context-fit.md（见下）|

**L3 判读**：issues 全是 add provider/fix selector → 核心是 provider 生态；全是 routing 算法 → 核心是 router。

### L6 场景适配（Personal Context Fit，2026-08-01 强化）

**能力存在 ≠ 场景适合。** 尤其个人用户 ≠ 企业架构：

| 维度 | 企业 | 个人 |
|------|------|------|
| 成本模型 | 100 人维护，目标稳定 10 年 | 自己维护，目标最大能力/最低复杂度 |
| 引入门槛 | 成熟/合规/可审计 | **能修/能跑/不折腾** |
| 错误模式 | 引入不足 | **照搬大厂方案**（K8s+LangGraph+Temporal+Kafka = 每天维护 30 分钟只换 5% 收益 → 应 IGNORE）|

**Personal Context Fit 五维**：
| 维度 | 核心问题 |
|------|---------|
| Technical Fit | 技术栈/架构是否匹配？|
| Cost Fit | 引入成本 vs 收益？|
| **Maintenance Fit** | **坏了我能修吗？** 不能修 → 慎用（个人无团队兜底）|
| Skill Fit | 我是否有能力维护/扩展？|
| Evolution Fit | 升级路径清晰吗？锁死风险？|

### L5 反事实验证（新增，2026-08-01）

作者可能错、社区可能错、明星项目可能错——必须反事实测试：

| 测试 | 方法 | 结论判定 |
|------|------|---------|
| 删除测试 | 删除后**原设计目标是否还能成立**（不是"系统还能启动"）| 目标消失=基础设施（如删 LiteLLM：启动 OK 但多模型统一入口❌）；目标仍在=增强/插件 |
| 故障注入 | 它失败时拖垮系统吗？| 增强失败→系统降级✅；增强失败→系统死亡❌（位置错误）|
| 替换测试 | 存在同层替代吗？| 换掉架构不变=能力层；换掉需重构=基础抽象 |
| 边界泄漏 | 它做不属于自己的事吗？| 数据库存数据≠业务决策；Router 选目标≠执行任务 |
| 组合证明 | 为什么大神同时用多个？| A 输出→是否成为 B 输入（模型→Recovery→Verification 三层不同问题）|

## 4. Adoption Decision（采用决策）+ Integration Mode（集成方式）

**核心问题：为什么不用原仓库？** —— 不能"看到优点就自己写"。

### 4a. Adoption Decision（采用什么）

| 决策 | 含义 | 条件 |
|------|------|------|
| **USE** | 采用该项目作为系统组件解决我的问题 | 成熟 + 问题边界匹配 + 维护成本合理 |
| **ADAPT** | 保留能力契约，替换实现 | 思想正确但实现耦合原环境（无法直接复用）|
| **EXTRACT** | 只学习思想/算法 | 能力是通用模式，无需代码依赖 |
| **IGNORE** | 不采用 | 场景不匹配 / 维护成本 > 收益 |

### 4b. Integration Mode（怎么集成）—— 与 4a 正交

**USE 之后如何集成**是独立维度（避免 LiteLLM 被误分类为"DEPENDENCY 不是 USE"）：

| 模式 | 含义 | 例子 |
|------|------|------|
| **embedded dependency** | pip/npm 依赖嵌入 | LiteLLM(pip) / ClawRouter(npm) |
| **external service** | 独立服务运行 | PostgreSQL / Chat2API(GUI) |
| **sidecar** | 旁路进程 | ClawRouter(localhost:8402) |
| **wrapper** | 薄封装调用 | validate-config 调官方命令 |
| **extracted concept** | 只取思想不取代码 | Adaptive fallback |

**组合规则**：`Adoption: USE` + `Integration: embedded dependency`（LiteLLM）；`Adoption: USE` + `Integration: external service`（PostgreSQL）。**二者不冲突，是正交维度。**

### ADAPT 第二门槛（2026-08-01 强化，防滑向重新发明）

ADAPT 前必须**全部满足**：
1. ✅ 原仓库能力匹配（解决我的 Gap）
2. ✅ 不能直接运行（环境/接口不兼容）
3. ✅ **不存在更小的成熟替代**（先查 OpenTelemetry/Langfuse/agent observability 等是否已解决 execution evidence——不能证明"没有替代"就自造 receipt）
4. ✅ 自己实现范围 ≤ 原能力契约（不扩大，只替换实现边界）

**反模式**：证明"AgentChat 不适合"后直接自造 receipt——**必须再证明"没有更小成熟替代"**，否则就是重新发明已有能力。

**反模式（ADAPT 滥用）**：见 `reference/examples.md` 案例 2（"AgentChat 有 receipt → 我喜欢 → 我写一个 = ADAPT" ❌ 错误）。

**判断链（统一，从 Gap 出发）**：
```
发现候选方案
    ↓
它是否解决我的 Gap？
    ├── 否 → IGNORE（问题都不匹配，谈何采用）
    └── 是 ↓
它是否已经是完整产品？且我的问题边界 = 它的设计边界？
    ├── 是 → USE（默认！）
    └── 否 ↓
只是接口/协议不同？
    ├── 是 → DEPENDENCY / Adapter（如 LiteLLM 统一多供应商）
    └── 否 ↓
环境是否完全冲突？（能力契约一致，实现不兼容）
    ├── 是 → ADAPT（环境完全冲突）
    └── 否 ↓
只学习思想/算法？
    ├── 是 → EXTRACT
    └── 否 → IGNORE
```
**⚠️ IGNORE 分支必须自查（v2.5 测试发现）**：即使 IGNORE，也要问"**是否存在可 EXTRACT 的思想/算法**"（如 LangGraph×个人：框架过重 IGNORE，但 DAG+仲裁思想可提取）——防止"整体不用"时丢失可复用的局部思想。

## 5. Integration Validation（集成验证）

如何进入现有系统且不破坏：
- 反向冲突测试（职责重叠 / 依赖方向 / 失败隔离 / 替换测试）
- 输出：`capability-records/<repo>/integration.md`（Original Purpose / Boundary / Conflict / Placement / Failure Isolation / Community Pattern / Adoption Decision）

## 6. Continuous Evolution（持续演进）

- 组件替换/升级路径（如官方功能发布后迁移自研过渡件）
- 周期性重新验证（反代/模型生态变化快）
- 能力缺口列表更新

---

## Capability Gap Mapping（能力缺口映射，通用）

**任何项目先问"我缺什么"，不是"这个仓库有什么"。**

```
需求/GAP → 寻找候选 → 能力验证 → 采用决策 → 集成
```

- 每个项目维护自己的能力矩阵 + 缺口列表（G001/G002/...）
- 发现仓库时：先问"它解决哪个 Gap"，不解决任何 Gap → IGNORE（再强也不引入）
- **具体项目的矩阵/缺口/审计是实例**，放各项目自己的技能/记录，不污染本方法论

## 快速导航

| 需求 | 操作 |
|------|------|
| 使用子技能 `repository-extraction` | skills/repository-extraction/SKILL.md — 基于 Capability Model 提取可复用能力 |
| 使用子技能 `repository-intelligence` | skills/repository-intelligence/SKILL.md — 理解陌生仓库，输出结构化能力模型 |
| 使用子技能 `repository-search` | skills/repository-search/SKILL.md — 根据能力需求发现候选仓库 |
| 参考 mistakes | reference\mistakes.md |
| 参考 tool-routing | reference\tool-routing.md |
| 参考 integration 模板 | reference\integration-template.md |
| 参考 validation 模板 | reference\validation-template.md |
| 参考 context-fit 模板 | reference\context-fit-template.md |
| 参考 decision 模板 | reference\decision-template.md |
| 运行 port-repo | scripts\port-repo.js |

## 阅读指南

### 参考文档 (5 个)

- `reference\mistakes.md` — mistakes
- `reference\tool-routing.md` — tool-routing
- `reference\integration-template.md` — integration.md 融合证明模板（L4 + 冲突测试）
- `reference\validation-template.md` — validation.md 运行验证模板（L5）
- `reference\context-fit-template.md` — context-fit.md 场景适配模板

### 脚本工具 (1 个)

- `scripts\port-repo.js` — port-repo

## 子技能一览

| 子技能 | 路径 | 用途 |
|--------|------|------|
| repository-search | `skills/repository-search/` | 根据能力需求发现候选仓库 |
| repository-intelligence | `skills/repository-intelligence/` | 理解陌生仓库，输出结构化能力模型 |
| repository-extraction | `skills/repository-extraction/` | 基于 Capability Model 提取可复用能力（✅ 已实现 2026-08-08：COPY 模式 + Source Lock + 3 脚本） |
| repo-explorer | `skills/repo-explorer/` | **执行层**：完整克隆+扫描+源码走读（补齐 extraction 之前的探索缺口） |

**探索流程**：repository-search（发现）→ **repo-explorer（克隆/扫描/走读，执行层）** → repository-intelligence（能力模型）→ 本技能决策 → repository-extraction（提取）。

## 防污染长期规则（2026-08-01 定稿，防止 repo-port 滑回项目案例库）

**repo-port 目录只允许放方法**：

```
repo-port/
├── SKILL.md            # 方法（规则/流程/判断模型/模板）
├── reference/
│   ├── examples.md     # 方法案例（演示"怎么用方法"，不是具体项目矩阵）
│   └── *-template.md   # 模板
└── capability-records/ # 能力记录（仓库发现/验证/决策的流程示范，非能力矩阵）
```

**禁止**：
- ❌ repo-port 里放任何具体项目的**能力矩阵**（Hermes/OpenClaw/Codex/xxx 的 9 项能力、缺口列表、采用清单）
- ❌ examples/ 慢慢累积成"项目案例库"（每分析一个仓库就往里塞案例）

**项目矩阵必须放对应技能目录**：
```
<项目技能名>/capability-map.md  # 每个项目的矩阵各归其位
```
（如 ai-api-gateway 的能力矩阵放 ai-api-gateway 技能内，repo-port 不持有）

**判断标准**：repo-port 出现"具体项目名 + 能力清单"结构 = 污染信号，立即外移。

## Decision Confidence（决策置信度，v2.5 增强）

证据不足时**不允许假装确定**——决策必须标注置信度：

| 置信度 | 条件 | 处理 |
|--------|------|------|
| **High** | L1-L6 全部完成 | 可执行决策（USE/ADAPT/...）|
| **Medium** | L1-L4 完成（未跑 L5/L6）| 有条件决策：标注"待 L5/L6 验证"，先做研究不动手 |
| **Low** | 只有 README/简介 | **禁止决策**：标记"需深入"（L2 源码/L3 社区），回 Discovery |

**规则**：`Low` 不允许输出 USE/ADAPT/IGNORE 终局结论——那是在假装确定。输出应为"证据不足，下一步 L2 源码验证"。

---

## 技能组文件清单

### 子技能 SKILL.md (3 个)

- `skills/repository-extraction\SKILL.md`
- `skills/repository-intelligence\SKILL.md`
- `skills/repository-search\SKILL.md`

### 参考文档 (7 个)

- `reference\mistakes.md`
- `reference\tool-routing.md`
- `reference\integration-template.md`
- `reference\validation-template.md`
- `reference\context-fit-template.md`
- `reference\decision-template.md`
- `reference\examples.md`（方法案例，非项目矩阵）

### 脚本工具 (1 个)

- `scripts\port-repo.js`

### 其他文件 (29 个)
> 数量较多（29个），详细列表略。

## QA Gate

- [ ] 仓库 URL/path 有效且可访问
- [ ] 理解深度(1-3)已明确指定
- [ ] 能力模型输出符合 Capability Model Schema
- [ ] **六层验证完成（L1-L6）**：作者意图 / 源码边界 / 社区使用 / 组合方式 / 反事实验证 / Context Fit
- [ ] **五级决策明确**：USE / DEPENDENCY / ADAPT / EXTRACT / IGNORE
- [ ] **为什么不用原仓库已回答**（ADAPT/EXTRACT 必须证明环境不兼容，decision.md 落盘）
- [ ] **Adapter Principle 通过**：中间层是隐藏复杂度（合理）还是增加复杂度（危险的自制 wrapper）？
- [ ] **个人默认策略遵守**：成熟仓库 + 边界匹配 → USE 默认；成熟但边界不匹配 → IGNORE；ADAPT 必须证明环境不兼容
- [ ] integration.md 融合证明已生成（冲突测试通过）
- [ ] 能力缺口匹配（解决哪个 Gap）已明确
- [ ] Source Lock 已执行（如适用）

## Gotchas

| 陷阱 | 后果 | 预防 |
|------|------|------|
| 不做 Source Lock 直接提取 | 版本漂移，代码不一致 | 提取前必须执行 Source Lock |
| 理解深度设太高 | token 浪费，信息过载 | 从 depth=1 开始，按需加深 |
| 跳过复用价值判断 | 集成无用代码 | 必须回答"这个能力值得复用吗？" |
| 忽略许可证检查 | 法律风险 | 提取前检查 LICENSE 文件 |
| 直接修改源码而非提取 | 破坏原始仓库 | 用提取技能，不改原仓库 |
| **看到优点就自己写** | 违反 Mature Solution First | 先证明"为什么不用原仓库" |
| **只读文档不运行验证** | 文档与实际不符 | 必须 L5 运行验证（V1-V5）|
| **能力强≠场景适合** | 引入错位组件 | 必须 context-fit 验证 |
| **方法论被项目案例污染** | repo-port 变成项目说明书 | 案例放各自技能，方法论保持通用 |

## Anti-Patterns

| 反模式 | 正确做法 |
|--------|---------|
| 自己实现已有能力 | 先用 repo-port 搜索现成方案 |
| 复制整个仓库 | 只提取需要的能力模块 |
| 不检查依赖就集成 | 分析依赖关系再决定 |
| 跳过理解直接提取 | 先用 repository-intelligence 理解 |
| 把 repo-port 当"推荐系统" | 它是"采购系统"：按缺口找方案 |
| 把 repo-port 当"Hermes 说明书" | 方法通用，案例放各项目记录 |
