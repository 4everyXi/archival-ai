---
name: structure-scan
description: "[Process] 档案化结构扫描：判断技能能否处理该目录；不能则增量扩展。触发：新目录/结构扫描/能否处理/通用性。"
license: Apache-2.0
version: 1.0.0
author: Xi
platforms: [windows, linux, macos]
metadata:
  hermes:
    tags: [process, archival, structure, coverage]
    related_skills: [ai-workbench, codegate, verification-before-completion, test-driven-development]
---

# Structure Scan — 结构扫描与通用性增量（archival-ai 子技能）

> **定位：archival-ai 的自举机制——每次档案化都是技能的增量。**
> 每次使用档案化技能前，先扫描目标目录结构，判断当前技能能否处理；
> 不能处理 → 扩展技能（覆盖本次问题 + 保留之前能力）→ 技能更通用。
> 最终：经过多次使用，档案化技能本身足够通用。

## 触发

- 用户指定**新目录**做档案化（第一次见该形态）
- 用户说「扫描/检查一下能不能处理/通用吗」
- 预览结果出现异常（如日期丢失、噪音未清、截断）——说明有未覆盖形态

## 核心流程（4 步闭环）

```
① 扫描 → ② 判断 → ③ 增量（如需要）→ ④ 审核
   ↑________________________|
   （每轮后能力矩阵 +1，技能更通用）
```

### ① 怎么扫描（机械部分：scan_structure.py）

```bash
python skills/structure-scan/scripts/scan_structure.py <目录>        # 人类画像
python skills/structure-scan/scripts/scan_structure.py <目录> --json  # AI 机器可读
```

输出**结构画像**：
- 统计：文件数 / 扩展名分布 / 最大层级
- 目录名形态：extract_date_signal 识别结果分布（single/range/none→细分：RJ/平台ID/档位/无日期）
- 文件名日期信号 + 噪音（hex/空格/全角/副本）
- **疑似缺口清单**：含数字但未识别为日期的目录名/文件名（新日期格式的信号）

### ② 怎么判断通用（AI 决策部分）

1. **对照能力覆盖矩阵**（`capability-matrix.md`）：画像里每个形态查矩阵——
   - 矩阵有该形态 → ✅ 能处理
   - 矩阵没有 → 🔴 未覆盖 → 走 ③
2. **疑似缺口逐个判断**（AI，不是脚本）：
   - `001.png`（序号）→ 非缺口（文件名序号不是日期）
   - `20260215-カチーナ`（8 位数字像日期）→ **真缺口**（新日期格式）
   - `12184175-2026-07-02`（ID+日期）→ 判断 ID 是否被正确处理
3. **判断标准**：`extract_date_signal` / `three_delete` / `find_parent_date_and_context`
   对该形态的**实际输出**是否符合预期（跑一行 python 验证，不猜）

**能处理** → 直接走正常档案化流程（--preview → 用户确认 → --execute）。
**不能处理** → 增量扩展（③）。

### ③ 怎么增加（增量扩展流程——用什么技能改代码）

**代码改动必须用**：
- **test-driven-development**：先写失败用例（RED）→ 最小实现 → 通过（GREEN）→ 重构
- **ponytail**：最小可行方案（YAGNI + stdlib 优先）——只加本次需要的能力，不过度设计
- **systematic-debugging**：先根因调查再修（复现 → 定位 → 最小修复 → 验证）

**步骤**：
1. 在 `scripts/selftest.py` 加新形态的失败用例（RED——证明缺口真实存在）
2. 最小实现（ponytail 原则：几行正则/分支，不引入新依赖）
3. 跑 selftest 全量（GREEN——新用例过 + **旧用例全过** = 保留之前能力）
4. 更新 `capability-matrix.md`（新增行 = 技能能力 +1）+ 增量扩展记录
5. 真实目录重新 `--preview` 确效（预览确认新形态正确）
6. 更新 `SKILL.md`（日期格式/目录形态描述同步）

**铁律**：
- 覆盖本次问题的同时**必须满足之前的问题**——selftest 全量回归是唯一证明
- 只加拍板范围内的（新形态是技能自身扩展，不需用户拍板；但行为变更要预览给用户看）
- 不改 audit_xi 检测器、不改已验证的旧行为

### ④ 怎么审核（用什么技能）

| 层次 | 技能 | 做什么 |
|------|------|--------|
| 代码审查 | **codegate** | 多角色审查 + 对抗辩论：新增代码的过度工程/正确性/安全 |
| 验证门禁 | **verification-before-completion** | 完成前验证契约：fresh 证据（selftest + 临时聚焦断言）|
| 结构验证 | **ai-workbench** | quick_validate / audit_xi（技能文档结构）|
| 回归 | selftest.py | 新旧用例全过 |

**审核通过标准**：selftest ALL PASS（新旧）+ 真实目录预览正确 + capability-matrix 已更新 + 代码无过度工程（codegate 通过）。

## 增量示例（历史，理解用）

| 形态 | 发现 | 扩展 | 结果 |
|------|------|------|------|
| `12184175-2026-07-02-カチーナ`（カルル 目录）| 日期在平台 ID 后识别失败 + ID 截断 | FULL 日期 search + ID 删除 + validate 校验 | `260702_カチーナ_001.png` |
| `20260215-カチーナ`（YYYYMMDD 紧凑）| 8 位日期被当 ID 删 | _YYYYMMDD_COMPACT 识别 + 8 位优先 | `260215_カチーナ_001.png` |

## 验证

- 扫描脚本自测：`python skills/structure-scan/scripts/scan_structure.py <合成目录> --json`——画像含预期形态
- 完整闭环：合成缺口目录 → 扫描发现缺口 → 扩展 → selftest 全过 → 扫描 gap_count 归零

## Common Pitfalls

| 陷阱 | 预防 |
|------|------|
| 把序号文件（001.png）当日期缺口 | 缺口判断看"数字形态像日期"（8 位/6 位连续 + 前后文），不看"含数字" |
| 扩展时破坏旧能力 | selftest 全量回归（不是只跑新用例）|
| 只加脚本不更新矩阵 | 矩阵是判断基准——每次扩展同步更新 |
| 过度设计（为假设的形态加代码）| ponytail：只加**本次真实遇到**的形态 |
