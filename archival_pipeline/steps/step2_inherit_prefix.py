"""Step 2: 日期提取与上下文继承 — 模块 A4/A5

需求映射:
- [A4] 日期提取与统一：多格式日期 → YYMMDD；文件自带日期优先（幂等，重复运行不变）
- [A5] 目录上下文继承：父目录名（无日期部分）作前缀，保留档案上下文
- 为什么这样好: 只从已有信息提取、不新增语义（逆向思维）；mtime 回退是正向操作默认关闭，
  需显式启用——符合"只删不增、确定才动"原则

集成自 filebatch-prefixer (MIT):
  Source: https://github.com/rishabh-panda/filebatch-prefixer (commit 314f96e)
"""
import re
from datetime import datetime
from pathlib import Path
from archival_pipeline.steps.base import PipelineStep
from archival_pipeline.models import (
    PipelineContext, FileRecord, RenameOperation,
    StepPreview, StepResult, BackupData, FileMetadata,
)

# 日期模式
_DATE_FULL_SEP = re.compile(
    r"(?:19|20)\d{2}[-/_](?:0[1-9]|1[012])[-/_](?:0[1-9]|[12]\d|3[01])"
)
_DATE_YEAR_MONTH_DOT = re.compile(
    r"(?:19|20)\d{2}[._](?:0[1-9]|1[012])(?:[._](?:0[1-9]|[12]\d|3[01]))?"
)
_YYMMDD_HEAD = re.compile(r"^(\d{6})(?:_|$)")


def _validate_date(s: str) -> bool:
    if len(s) != 6 or not s.isdigit():
        return False
    m, d = int(s[2:4]), int(s[4:6])
    return 1 <= m <= 12 and 1 <= d <= 31


def extract_date_from_dirname(name: str) -> str | None:
    """从目录名提取日期"""
    m = _YYMMDD_HEAD.match(name)
    if m and _validate_date(m.group(1)):
        return m.group(1)
    m = _DATE_FULL_SEP.match(name)
    if m:
        g = m.group(0)
        return g[2:4] + g[5:7] + g[8:10]
    m = _DATE_YEAR_MONTH_DOT.match(name)
    if m:
        parts = re.split(r"[._]", m.group(0))
        if len(parts) >= 2:
            return parts[0][2:] + parts[1]
    return None


def get_date_prefix_from_mtime(file_path: Path) -> str | None:
    """从文件修改时间提取 yymmdd（集成自 filebatch-prefixer）"""
    try:
        ts = file_path.stat().st_mtime
        return datetime.fromtimestamp(ts).strftime("%y%m%d")
    except (OSError, ValueError):
        return None


def find_parent_date_and_context(
    path: Path, target_dir: Path,
) -> tuple[str | None, str]:
    """从父目录链找日期和上下文

    遍历父目录链，收集所有无日期的目录名作为上下文，
    遇到第一个有日期的目录时停止，用它的日期作为前缀。

    例: path=2025.09.7z/Furina-芙宁娜/芙芙.mp4
      1. 检查 Furina-芙宁娜 → 无日期，记录为上下文
      2. 检查 2025.09.7z → 日期 2509，停止
      返回 ('2509', 'Furina-芙宁娜')
    """
    contexts: list[str] = []
    parent = path.parent
    while parent != target_dir and parent != parent.parent:
        context = parent.name
        date = extract_date_from_dirname(context)
        if date:
            # 去掉日期部分作为当前目录的上下文
            rest = context
            for pat in [_DATE_FULL_SEP, _DATE_YEAR_MONTH_DOT]:
                m = pat.match(rest)
                if m:
                    rest = rest[m.end():].lstrip("-_ .")
                    break
            if rest and re.match(r"^[a-zA-Z0-9]{1,4}$", rest):
                rest = ""
            if rest:
                contexts.insert(0, rest)
            # 反转：按根目录到文件的顺序排列
            contexts.reverse()
            full_context = "_".join(contexts) if contexts else ""
            return date, full_context
        else:
            # 无日期的目录，记作上下文
            if context and not re.match(r"^[\d\-_]{2,8}$", context):
                contexts.append(context)
        parent = parent.parent

    # 没找到任何日期
    contexts.reverse()
    return None, "_".join(contexts) if contexts else ""


def compute_prefix(file_path: Path, target_dir: Path, allow_mtime: bool = False) -> str:
    """计算文件应有的前缀

    逆向模式（默认）：
      - 从父目录继承日期（纯机械，不增语义）
      - 文件自身已有日期 → 跳过（幂等性）
      - 父目录无日期 → 不加前缀

    正向模式（allow_mtime=True）：
      - 父目录无日期时，用文件 mtime 作为回退
      - ⚠️ 这是正向操作（增加内容），应明确标识
    """
    stem = file_path.stem
    if _YYMMDD_HEAD.match(stem) and _validate_date(stem[:6]):
        return ""
    date, context = find_parent_date_and_context(file_path, target_dir)
    # mtime 回退是正向操作，默认不启用
    if not date and allow_mtime:
        date = get_date_prefix_from_mtime(file_path)
    parts = []
    if date:
        parts.append(date)
    if context:
        parts.append(context)
    return "_".join(parts) + "_" if parts else ""


class Step2InheritPrefix(PipelineStep):
    """日期继承：从父目录提取日期和上下文作为文件名前缀

    逆向模式：
      - 只从父目录提取已有的日期信息，不新增内容
      - 文件自身有日期 → 跳过（幂等性）
      - 父目录无日期 → 不加前缀

    正向扩展（allow_mtime）：
      - 允许用文件修改时间作为日期回退
      - ⚠️ 这是正向操作，仅在明确指定时启用
    """
    name = "inherit_prefix"
    description = "日期继承：从父目录提取日期/上下文作为前缀"
    allow_mtime: bool = False

    def preview(self, ctx: PipelineContext) -> StepPreview:
        step_cfg = ctx.step_configs.get(self.name, {})
        allow_mtime = step_cfg.get("allow_mtime", self.allow_mtime)
        template = step_cfg.get("template", None)

        ops = []
        changed = 0
        for i, rec in enumerate(ctx.records):
            date, context = find_parent_date_and_context(
                rec.current_path, ctx.target_dir)
            if not date and allow_mtime:
                date = get_date_prefix_from_mtime(rec.current_path)

            if template:
                # 自定义模板（从 bulk-rename-py TokenProcessor 复制）
                try:
                    from archival_pipeline.external.token_processor import TokenProcessor
                    # 预替换 {context}，因为 TokenProcessor 不支持
                    filled = template.replace("{context}", context or "")
                    new_name = TokenProcessor.apply_name_mask(
                        mask=filled,
                        oname=rec.current_path.stem,
                        ext=rec.current_path.suffix,
                        counter=str(i + 1).zfill(3),
                        date_str=date or "",
                        time_str="",
                    )
                except ImportError:
                    new_name = None
            else:
                # 默认: {date}_{context}_{name}{ext}
                stem = rec.current_path.stem
                if _YYMMDD_HEAD.match(stem) and _validate_date(stem[:6]):
                    continue  # 文件已有日期前缀，跳过
                parts = [p for p in [date, context] if p]
                prefix = "_".join(parts) + "_" if parts else ""
                new_name = prefix + rec.current_path.name if prefix else None

            if new_name and new_name != rec.current_path.name:
                new_path = rec.current_path.with_name(new_name)
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
            backup.append({"original": str(op.source), "new": str(op.destination)})
            if not ctx.dry_run:
                try:
                    op.source.rename(op.destination)
                except OSError as e:
                    errors.append(str(e))
            for rec in ctx.records:
                if rec.current_path == op.source:
                    rec.current_path = op.destination
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
