#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""冲突检测 — 执行层安全网（模块 A 执行前自动调用）

需求映射:
- [执行层安全] pipeline.run() 每步执行前 check_conflicts，error 阻断，warning 提示
- [Windows 安全] 保留字符/保留名/尾随字符/MAX_PATH 检测——中文文件名场景极易踩雷
- 为什么这样好: 安全放在执行层而非决策层——AI 只管判断好坏，脚本保证操作本身安全；
  纯函数无状态、可独立测试（selftest 已覆盖）

来源: brename (chain/case collision) + F2 (windows safety) + rnr (RenameSolver)
检测类型: TARGET_EXISTS / CHAIN_COLLISION / CASE_COLLISION / FORBIDDEN_TRAIL /
          FORBIDDEN_CHARS / EMPTY_TARGET / PATH_TOO_LONG / SOURCE_MISSING
"""

from __future__ import annotations
import logging

import enum
import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable


# ── Windows保留字符和名称 ──
WINDOWS_FORBIDDEN_CHARS: re.Pattern[str] = re.compile(r'[\\\\/:*?"<>|]')
WINDOWS_RESERVED_NAMES: frozenset[str] = frozenset({
    'CON', 'PRN', 'AUX', 'NUL',
    'COM1', 'COM2', 'COM3', 'COM4', 'COM5', 'COM6', 'COM7', 'COM8', 'COM9',
    'LPT1', 'LPT2', 'LPT3', 'LPT4', 'LPT5', 'LPT6', 'LPT7', 'LPT8', 'LPT9',
})
MAX_PATH_LIMIT: int = 260

logger = logging.getLogger("ConflictDetector")


class ConflictType(enum.Enum):
    TARGET_EXISTS = '目标文件已存在'
    CHAIN_COLLISION = '链式覆盖'
    CASE_COLLISION = '大小写碰撞'
    FORBIDDEN_TRAIL = 'Windows禁止尾随字符'
    FORBIDDEN_CHARS = 'Windows保留字符'
    EMPTY_TARGET = '目标路径为空'
    PATH_TOO_LONG = '路径超过MAX_PATH限制'
    SOURCE_MISSING = '源文件不存在'


@dataclass(frozen=True)
class ConflictFinding:
    """一个冲突发现。"""
    type: ConflictType
    old_path: Path
    new_path: Path
    severity: str  # 'error' | 'warning'
    message: str


def check_conflicts(changes: Iterable[tuple[Path, Path]]) -> list[ConflictFinding]:
    """
    检测 rename 操作集合中的所有冲突。

    Args:
        changes: (旧路径, 新路径) 的可迭代对象

    Returns:
        冲突发现列表。空 = 安全执行。
    """
    changes_list = list(changes)
    if not changes_list:
        logger.info("No changes to detect")
        return []
    findings: list[ConflictFinding] = []
    seen_lower: dict[str, Path] = {}       # lower(new) → old 用于大小写检测
    final_new: set[Path] = set()            # 所有最终新路径
    change_map: dict[Path, Path] = {}       # old → new 映射

    for old, new in changes_list:
        change_map[old] = new

    # ── 1. SOURCE_MISSING ──
    for old, new in changes_list:
        if not old.exists():
            findings.append(ConflictFinding(
                type=ConflictType.SOURCE_MISSING,
                old_path=old, new_path=new, severity='error',
                message=f'源文件不存在: {old}'
            ))

    # ── 2. EMPTY_TARGET ──
    for old, new in changes_list:
        if not new.name or new.name.strip() == '':
            findings.append(ConflictFinding(
                type=ConflictType.EMPTY_TARGET,
                old_path=old, new_path=new, severity='error',
                message=f'目标路径为空: {old} → (空)'
            ))

    # ── 3. FORBIDDEN_TRAIL ──
    for old, new in changes_list:
        name = new.name
        if name.endswith((' ', '.')):
            findings.append(ConflictFinding(
                type=ConflictType.FORBIDDEN_TRAIL,
                old_path=old, new_path=new, severity='error',
                message=f'Windows禁止尾随字符: "{name}" 以空格/句点结尾'
            ))

    # ── 4. FORBIDDEN_CHARS ──
    for old, new in changes_list:
        if WINDOWS_FORBIDDEN_CHARS.search(new.name):
            findings.append(ConflictFinding(
                type=ConflictType.FORBIDDEN_CHARS,
                old_path=old, new_path=new, severity='error',
                message=f'Windows保留字符: "{new.name}"'
            ))

    # ── 5. RESERVED_NAMES ──
    for old, new in changes_list:
        stem = new.stem.upper()
        if stem in WINDOWS_RESERVED_NAMES:
            findings.append(ConflictFinding(
                type=ConflictType.FORBIDDEN_CHARS,
                old_path=old, new_path=new, severity='error',
                message=f'Windows保留名称: "{stem}"'
            ))

    # ── 6. PATH_TOO_LONG ──
    for old, new in changes_list:
        if len(str(new)) > MAX_PATH_LIMIT:
            findings.append(ConflictFinding(
                type=ConflictType.PATH_TOO_LONG,
                old_path=old, new_path=new, severity='warning',
                message=f'路径超过{MAX_PATH_LIMIT}字符: {len(str(new))}字符'
            ))

    # ── 7. TARGET_EXISTS：最终状态检测 ──
    # 收集所有最终新路径（排除链中作为中间源文件的路径）
    all_new: set[Path] = set()
    new_to_old: dict[Path, Path] = {}
    for old, new in changes_list:
        all_new.add(new)
        new_to_old[new] = old

    # 如果是链中的中间节点（B 既是 A的目标又是 C的来源），不算TARGET_EXISTS
    intermediate_targets: set[Path] = set()
    for old, new in changes_list:
        if old in all_new:
            intermediate_targets.add(old)

        all_sources = {o for o, _ in changes_list}
    for old, new in changes_list:
        if new in intermediate_targets:
            continue  # 链式节点，由CHAIN_COLLISION处理
        if new in all_sources:
            continue  # 源文件也会被rename，不算已存在
        if new.exists():
            findings.append(ConflictFinding(
                type=ConflictType.TARGET_EXISTS,
                old_path=old, new_path=new, severity='error',
                message=f'目标文件已存在: {new}'
            ))

    # ── 8. CHAIN_COLLISION ──
    for old, new in changes_list:
        if old in all_new:
            # old 也被其他操作作为目标 → 链
            source_of_old = new_to_old.get(old)
            if source_of_old:
                findings.append(ConflictFinding(
                    type=ConflictType.CHAIN_COLLISION,
                    old_path=source_of_old, new_path=old, severity='warning',
                    message=f'链式覆盖: {source_of_old.name} → {old.name} → {new.name}'
                ))

    # ── 9. CASE_COLLISION ──
    for old, new in changes_list:
        key = str(new).lower()
        if key in seen_lower:
            other = seen_lower[key]
            if other != old:
                findings.append(ConflictFinding(
                    type=ConflictType.CASE_COLLISION,
                    old_path=old, new_path=new, severity='error',
                    message=f'大小写碰撞: {old.name} 与 {other.name} 都→ "{new.name}"'
                ))
        else:
            seen_lower[key] = old

    if findings:
        errs = sum(1 for f in findings if f.severity == "error")
        warns = sum(1 for f in findings if f.severity == "warning")
        logger.warning(f"Detected {len(findings)} conflicts ({errs} errors, {warns} warnings)")
    else:
        logger.info("No conflicts - clean")
    return findings


def has_errors(findings: list[ConflictFinding]) -> bool:
    """检查是否有需要阻塞的错误。"""
    return any(f.severity == 'error' for f in findings)


def format_findings(findings: list[ConflictFinding]) -> str:
    """格式化冲突发现为可读字符串。"""
    if not findings:
        return '✓ 未检测到冲突'

    lines: list[str] = []
    for f in findings:
        tag = '[错误]' if f.severity == 'error' else '[警告]'
        lines.append(f'{tag} {f.message}')
    return '\\n'.join(lines)


# ── RenameSolver (rnr solver.rs 移植) ──


# RenameSolver (rnr solver.rs: topological sort + revert)

class RenameSolver:
    """重命名排序器. 拓扑排序 + bottom-up + revert. 纯函数无状态."""

    @staticmethod
    def solve_operations(plan):
        """返回有序操作列表 (深到浅/链式解析)."""
        if not plan:
            return []
        rm = {}  # target -> source
        for s, t in plan:
            if t in rm:
                raise ValueError("Duplicate target: %s" % t)
            rm[t] = s

        dm = {}
        for t in rm:
            dm.setdefault(len(t.parts), []).append(t)

        out = []
        all_t = set(rm)
        for depth in sorted(dm, reverse=True):
            nc, cf = [], []
            for t in dm[depth]:
                s = rm[t]
                (cf if s in all_t else nc).append(t)
                if t.exists() and not any(s == t for s, _ in plan):
                    raise FileExistsError("Target exists not in plan: %s" % t)
            for t in nc:
                out.append((rm[t], t))
            if cf:
                out.extend(RenameSolver._resolve(cf, rm))
        return out

    @staticmethod
    def _resolve(cf, rm):
        """Kahn拓扑排序."""
        cs = set(cf)
        deg = {t: 0 for t in cf}
        adj = {}
        for t in cf:
            s = rm[t]
            if s in rm and s in cs:
                adj.setdefault(s, []).append(t)
                deg[t] = 1
        q = [t for t in cf if deg.get(t, 0) == 0]
        r = []
        while q:
            n = q.pop(0)
            r.append(n)
            for nb in adj.get(n, []):
                deg[nb] -= 1
                if deg[nb] == 0:
                    q.append(nb)
        if len(r) != len(cf):
            rem = [t for t in cf if t not in r]
            raise ValueError("Rename cycle: " + ", ".join(rm[t].name + "->" + t.name for t in rem))
        r.reverse()
        return [(rm[t], t) for t in r]

    @staticmethod
    def revert_operations(ops):
        """回滚: 反转 + 交换."""
        return [(t, s) for s, t in reversed(ops)]

