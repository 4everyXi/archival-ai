# archival-ai 能力地图（repo-port 产出）

> 项目矩阵归属本技能目录（repo-port 防污染规则：项目矩阵各归其位，repo-port 只放方法）
> 生成：2026-08-08 · repo-port 能力盘点 · 代码走读 + codegate 全栈审查后

## 〇、定位声明（最重要）

**archival-ai 是一个 Agent 能力（skill）——使用方是 AI 模型（agent），不是给用户手敲的 CLI。**

- **执行主体**：agent。语义判断（翻译/去重/边界）由 agent 逐条理解；脚本只是 agent 的机械工具层（安全网）。
- **调用方式**：agent 加载本技能（skill_view）→ 读 SKILL.md 认知框架 → 按需调用包内工具。
- **不是**：给用户敲的命令行工具（CLI 是 agent 内部执行通道，不是面向用户的交付物）；也不是给 Python 代码 import 的库（跨技能复用走技能路由，不走 import）。
- **核心范式**：AI 决定 → 用户确认 → 脚本执行 → 备份兜底（agent-first-design）。

## 〇·一、设计思路来源（大神方案追溯）

| 来源 | 贡献思路 | 在本技能中的体现 |
|------|---------|-----------------|
| **repo-port**（能力采购系统） | 成熟方案优先：不重复造轮子，先查现成工具；Source Lock 追溯来源 | 集成 detox（BSD-2）/ rename-clean（GPL-3.0）/ filebatch-prefixer（MIT）/ bulk-rename-py，代码内均有"集成自 X (license) + commit"注释（Source Lock 精神） |
| **web-tool-router**（工具路由） | 按任务类型分诊到正确工具通道：机械任务走脚本/API，语义任务走 AI/浏览器兜底 | 模块 A（机械→脚本通道）vs 模块 B（语义→AI 通道）的分诊；agent 判断任务类型→选择工具；快速模式=脚本通道（缓存），精品模式=AI 通道（默认） |
| agent-first-design | 智能体优先：AI 决定、用户确认、脚本执行、备份兜底 | 全部设计基石（SKILL.md 范式声明） |

> 路由思想核心：**同一种任务，通道选择由 agent 判断**——机械的走脚本（快、确定、可回滚），语义的走 AI（理解、判断、搜索），安全永远在执行层。

## 一、能力模型（Capability Model）—— agent 的工具箱

| 工具 | 入口 API | 形态 | 依赖 | agent 何时用 |
|------|---------|------|------|------------|
| 文件名结构清洗（三删+全角+副本） | `step1.three_delete(name)` | 纯函数 | stdlib | 机械噪音清理（A 模块） |
| 日期信号识别（具体/范围/无） | `step2.extract_date_signal(name)` | 纯函数 | stdlib | 日期继承判断（A4） |
| 日期继承（P1-P5 + 日历校验） | `step2.find_parent_date_and_context` / `compute_prefix` | 纯函数 | stdlib | 层级归档（A4/A5） |
| 备份/回滚安全网 | `backup.save_backup` / `rollback_all` | 独立模块 | stdlib | 任何批量修改前/后（安全层） |
| 重命名冲突检测（7 类+拓扑排序） | `conflict_detector.check_conflicts` / `RenameSolver` | 纯函数 | stdlib | 执行前拦截危险操作（安全层） |
| 预览确认（json/txt 双格式） | `preview.render` | 模块 | stdlib | 变更清单给用户确认（确认层） |
| 残留检测（假名/汉字） | `scripts/check_translation.py` | 脚本 | stdlib | 翻译后置验证（验证层） |
| 译名缓存（560 条词条库） | `translator/cache.py` | 数据 | stdlib | 快速模式机械替换（B5 缓存） |

**共性**：纯 stdlib、无外部依赖——agent 在任何环境都能调。**分层**：机械层（A）/ 语义层（agent 自己）/ 安全层（备份回滚冲突）/ 验证层（残留检测）。

## 二、复用决策（repo-port 五级决策）

| 工具/能力 | 决策 | 依据 |
|----------|------|------|
| 三删清洗 / 日期信号 / 备份回滚 / 冲突检测 | **USE-in-place + EXTRACT 思想** | 机械工具内聚于本包；思想（安全网模式/只删不增/数据清洗标准）已沉淀进 ai-workbench `ai-native-skill-methodology.md` |
| 日期继承 / 预览确认 | USE-in-place | 场景较特定；复用价值在方法论层（已沉淀） |
| 残留检测 / 译名缓存 | IGNORE（留在技能内） | 翻译领域特定数据/逻辑 |

**为什么不提取为独立仓库（repo-port 最高防线：Personal Context Fit）**：
- 维护负担：拆库 = 多倍维护（个人用户最大限制是维护时间）
- 能修/不折腾：工具已在 archival-ai 内聚且纯 stdlib
- 定位不匹配：agent 技能是"认知框架 + 工具集"，拆成库反而破坏形态

## 三、跨技能复用（agent 视角）

**使用方是 agent，复用 = 技能路由 + 方法论引用，不是代码 import：**

```
其他 agent 遇到"文件整理/批量重命名/归档"类任务
  → ask-matt 路由 → 加载 archival-ai（skill_view）
  → 读 SKILL.md 认知框架（A/B 模块、P1-P5、反模式）
  → 按需调用包内工具（three_delete / extract_date_signal / backup...）
```

- **路由**：`ask-matt`（整理类请求 → archival-ai）
- **方法论**：ai-workbench `references/ai-native-skill-methodology.md`（跨技能共享的判断标准，agent 读它学"怎么做才算好"）
- **不复制**：其他技能不复制 archival-ai 的代码/数据（缓存词条库留在本包）

## 四、L5 反事实验证（删掉会怎样）

| 工具 | 删除后果 | 结论 |
|------|---------|------|
| three_delete | agent 需手工做机械清洗 | 保留（机械层） |
| extract_date_signal | 日期识别需 agent 手工解析 | 保留（机械层） |
| backup/rollback | 安全网缺失（agent 自由决策失去兜底） | 保留（基础设施） |
| check_conflicts | 危险重命名无拦截 | 保留（基础设施） |

## 五、持续演进

- 新机械能力（如 NFC 归一化）→ 先在本包实现，再判断是否提升为共享方法论
- 方法论层更新 → ai-workbench `ai-native-skill-methodology.md`（本地图不重复沉淀思想）
- 周期复查：Xi 技能组新增"整理类"技能时，检查应路由到本技能还是自建（默认路由）
