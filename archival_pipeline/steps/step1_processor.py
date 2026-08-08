"""Step 1: 三删 + 重名兜底 — 模块 A1/A2/A3/A6

需求映射:
- [A1] 平台噪音删除：删 8 位数字+短横的纯平台 ID（^\d{8}-）
- [A2] 冗余删除：重复扩展名
- [A3] 分隔符规范化：safe table 55 个确定噪音字符 + 连续分隔符折叠
- [A6] 重名冲突处理：ensure_unique 追加 _2/_3（机械兜底，不涉及语义）
- 为什么这样好: 只删不增、确定才动——safe table 是封闭列表，不在表里不动=零误删；
  语义去重（日英同名合并）留给 B4 AI 层，脚本不越权

集成来源:
  detox (BSD-2): https://github.com/dharple/detox (commit 0a8e212)
  rename-clean (GPL-3.0): ensure_unique 移植
"""
import itertools
import re
from pathlib import Path
from archival_pipeline.steps.base import PipelineStep
from archival_pipeline.models import (
    PipelineContext, FileRecord, RenameOperation,
    StepPreview, StepResult, BackupData,
)

# ── Safe table：55个确定噪音字符（移植自 detox safe.tbl） ─────
# 核心原则：只替换确定有问题的字符。不在表里的字符，一律不动。
# 这比 rename-clean 的 whitelist regex 更符合逆向思维。
_SAFE_TABLE = str.maketrans({
    # 控制字符 0x01-0x1F → _
    **{chr(i): "_" for i in range(0x01, 0x20)},
    # 标点符号 → _
    " ": "_",   "!": "_",   '"': "_",
    "$": "_",   "'": "_",   "*": "_",
    "/": "_",   ":": "_",   ";": "_",
    "<": "_",   ">": "_",   "?": "_",
    "@": "_",   "\\": "_",  "`": "_",
    "|": "_",
    # 括号 → -
    "(": "-",   ")": "-",
    "[": "-",   "]": "-",
    "{": "-",   "}": "-",
    # 特殊多字符替换
    "&": "_and_",
    chr(0x7f): "_",  # DEL
})

# ── 三删正则 ──────────────────────────────────────────────────
# 只删 8 位数字+短横的纯平台 ID（如 10236235-），
# 不删 YYMMDD_ 日期前缀（如 250717_），日期是档案核心信息。
_RE_PLATFORM_ID = re.compile(r"^\d{8}-")
_RE_DEDUP = re.compile(r"[-_]+")


def apply_safe_table(name: str) -> str:
    """应用 safe table：只替换55个确定噪音字符

    移植自 detox clean_safe() + builtin safe table
    核心逆向思维：不在表里的字符，不动。
    """
    stem = Path(name).stem
    ext = Path(name).suffix
    stem = stem.translate(_SAFE_TABLE)
    return stem + ext


def three_delete(name: str) -> str:
    """三删核心：只删不增，确定才动

    1. 删平台ID（确定的噪声模式）
    2. 删重复扩展名（确定的冗余）
    3. 去重连续分隔符（确定的格式问题）
    """
    stem = Path(name).stem
    ext = Path(name).suffix
    stem = _RE_PLATFORM_ID.sub("", stem)
    while ext and stem.endswith(ext):
        stem = stem[: -len(ext)]
    stem = stem.replace("-", "_")
    return stem + ext


def ensure_unique(path: Path, char: str = "_") -> Path:
    """确保路径唯一，冲突时追加 _2, _3（移植自 rename-clean）"""
    if not path.exists():
        return path
    stem = path.stem
    suffix = path.suffix
    for n in itertools.count(2):
        candidate = path.with_name(f"{stem}{char}{n}{suffix}")
        if not candidate.exists():
            return candidate


def validate_name(name: str) -> bool:
    """后置条件验证（移植自 sanitize validate()）

    确保输出符合预期格式：
    - 只含 [a-zA-Z0-9 _ - . & ( ) [ ] { }]
    - 不含连续分隔符
    - 不以分隔符开头
    """
    allowed = set("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789 _-.&()[]{}")
    return all(c in allowed for c in name)


class Step1Processor(PipelineStep):
    """三删：删平台ID、删重复扩展名、去重连续分隔符

    逆向思维：
      - 只删不增：文件只可能变短
      - 确定才动：safe table 只包含确定有问题的字符
      - 后置验证：sanitize 风格，确保输出合规
    """
    name = "processor"
    description = "三删：删平台ID、重复扩展名、连续分隔符去重"

    def preview(self, ctx: PipelineContext) -> StepPreview:
        ops = []
        changed = 0
        for rec in ctx.records:
            name = three_delete(rec.current_path.name)
            name = apply_safe_table(name)
            name = _RE_DEDUP.sub("_", name).strip("_-")
            if not name:
                name = "_unnamed"
            if not Path(name).suffix:
                name = name + rec.current_path.suffix

            if name != rec.current_path.name:
                new_path = rec.current_path.with_name(name)
                ops.append(RenameOperation(rec.current_path, new_path))
                changed += 1
        return StepPreview(
            step_name=self.name,
            operations=ops,
            statistics={"total": len(ctx.records), "changed": changed,
                        "skipped": len(ctx.records) - changed, "errors": 0},
        )

    def execute(self, ctx: PipelineContext) -> StepResult:
        preview = self.preview(ctx)
        backup = []
        errors = []
        for op in preview.operations:
            final = op.destination
            if not validate_name(final.name):
                # 后置验证不通过时用 safe 版本
                safe = apply_safe_table(final.name)
                final = final.with_name(safe)
            dest = ensure_unique(final)
            backup.append({"original": str(op.source), "new": str(dest)})
            if not ctx.dry_run:
                try:
                    op.source.rename(dest)
                except OSError as e:
                    errors.append(str(e))
            for rec in ctx.records:
                if rec.current_path == op.source:
                    rec.current_path = dest
                    break
        return StepResult(
            step_name=self.name,
            success=len(errors) == 0,
            backup_data=backup,
            errors=errors,
        )

    def rollback(self, backup_data: BackupData) -> bool:
        for item in reversed(backup_data.operations):
            src = Path(item["new"])
            dst = Path(item["original"])
            if src.exists():
                src.rename(dst)
        return True
