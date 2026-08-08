"""Step 2: 日期提取与上下文继承 — 模块 A4/A5

需求映射:
- [A4] 日期提取与统一：任意名称（目录/文件）提取日期信号——具体日期 / 日期范围 / 无
- [A5] 目录上下文继承：父目录名（无日期部分）作前缀，保留档案上下文
- 为什么这样好: 只从已有信息提取、不新增语义（逆向思维）；mtime 回退是正向操作默认关闭，
  需显式启用——符合"只删不增、确定才动"原则

日期继承完备规则（v2，覆盖所有组合）:
  P1 文件自身有具体日期  → 用文件日期（最高：文件自己的信号最可信）
  P2 文件自身有日期范围  → 用范围起点
  P3 父目录链中第一个具体日期 → 用它（具体优先于范围；跳过无日期目录）
  P4 父目录链中第一个日期范围 → 用范围起点
  P5 全部无日期 → 不加前缀

  排序原则: ① 文件信号 > 目录信号（靠近文件优先）；② 具体日期 > 日期范围
  排除规则: RJ 编号 / 平台标记(价格) / 歧义格式(MM-DD) 不识别为日期
  幂等性: 已带 YYMMDD 前缀的文件跳过（重复运行不变）

集成自 filebatch-prefixer (MIT):
  Source: https://github.com/rishabh-panda/filebatch-prefixer (commit 314f96e)
"""
import calendar
import re
from datetime import datetime
from pathlib import Path
from archival_pipeline.steps.base import PipelineStep
from archival_pipeline.models import (
    PipelineContext, RenameOperation,
    StepPreview, StepResult, BackupData,
)

# ── 排除模式 ─────────────────────────────────────────────────
_RJ_PATTERN = re.compile(r"^RJ\d+", re.IGNORECASE)
# 纯数字/短横目录（平台 ID 等，不是日期也不是上下文）
_PURE_NUMERIC_DIR = re.compile(r"^[\d\-_]{2,8}$")
# 平台档位标记 (fantia500)/(fanbox500)/patreon/ci-en/gumroad（A5 清理）
_RE_TIER_TAG = re.compile(
    r"\(?(?:fantia|fanbox|patreon|ci[-_]?en|gumroad)\s*\d*\)?", re.IGNORECASE,
)

# ── 日期范围模式（两个日期，取起点） ────────────────────────
_RANGE_FULL = re.compile(
    r"((?:19|20)\d{2}[-/_](?:0[1-9]|1[012])[-/_](?:0[1-9]|[12]\d|3[01]))"
    r"\s*[-~～_/]\s*"
    r"((?:19|20)\d{2}[-/_](?:0[1-9]|1[012])[-/_](?:0[1-9]|[12]\d|3[01]))"
)
_RANGE_YYMMDD = re.compile(r"(\d{6})\s*[-~～_/]\s*(\d{6})")
_RANGE_MONTH = re.compile(
    r"((?:19|20)\d{2}[._](?:0[1-9]|1[012]))\s*[-~～_/]\s*((?:19|20)\d{2}[._](?:0[1-9]|1[012]))"
)

# ── 具体日期模式 ─────────────────────────────────────────────
_DATE_FULL_SEP = re.compile(
    r"(?:19|20)\d{2}[-/_](?:0[1-9]|1[012])[-/_](?:0[1-9]|[12]\d|3[01])"
)
_DATE_YEAR_MONTH_DOT = re.compile(
    r"(?:19|20)\d{2}[._](?:0[1-9]|1[012])(?:[._](?:0[1-9]|[12]\d|3[01]))?"
)
# 6位数字开头 + 后面不是数字：`250714_`、`220208haru_ki`（数字后跟字母=作者命名，仍算日期）。
# 放宽自 `(?:_|$)`（数字后只能是下划线/结尾）——真实文件常见 6位日期+字母组合
_YYMMDD_HEAD = re.compile(r"^(\d{6})(?![0-9])")


def _validate_date(s: str) -> bool:
    """YYMMDD 合法性校验（含真实月天数）——防误判纯数字 ID/非法日期（2月30日）为日期"""
    if len(s) != 6 or not s.isdigit():
        return False
    y, m, d = int(s[:2]), int(s[2:4]), int(s[4:6])
    if not (1 <= m <= 12 and 1 <= d <= 31):
        return False
    return d <= calendar.monthrange(2000 + y, m)[1]


def _full_to_yymmdd(s: str) -> str:
    """'2022-02-15' / '2022.02.15' / '2022/02/15' → '220215'"""
    parts = re.split(r"[-/._]", s)
    return parts[0][2:] + parts[1] + parts[2]


def _month_to_yymm(s: str) -> str:
    """'2025.09' → '2509'"""
    parts = re.split(r"[._]", s)
    return parts[0][2:] + parts[1]


def extract_date_signal(name: str) -> tuple[str, str | None]:
    """提取日期信号：具体日期 / 日期范围（返回起点）/ 无

    返回 ("single"|"range"|"none", yymmdd)
    - "single": 具体日期（YYMMDD / YYYY-MM-DD / YYYY.MM 月精度）
    - "range":  日期范围（取起点，如 231127-260607 → 231127）
    - "none":   无日期（RJ 编号、平台标记、纯数字 ID 等）
    """
    if _RJ_PATTERN.match(name):
        return ("none", None)
    # 范围优先（范围包含两个日期，先于具体识别）
    m = _RANGE_FULL.search(name)
    if m:
        return ("range", _full_to_yymmdd(m.group(1)))
    m = _RANGE_YYMMDD.search(name)
    if m and _validate_date(m.group(1)):
        return ("range", m.group(1))
    m = _RANGE_MONTH.search(name)
    if m:
        return ("range", _month_to_yymm(m.group(1)))
    # 具体日期
    m = _YYMMDD_HEAD.match(name)
    if m and _validate_date(m.group(1)):
        return ("single", m.group(1))
    m = _DATE_FULL_SEP.match(name)
    if m:
        return ("single", _full_to_yymmdd(m.group(0)))
    m = _DATE_YEAR_MONTH_DOT.match(name)
    if m:
        return ("single", _month_to_yymm(m.group(0)))
    return ("none", None)



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
    """从父目录链找日期（P3 具体优先，P4 范围兜底）和上下文

    遍历父目录链（近→远）:
      第一遍: 找第一个具体日期目录 → 用它（具体优先于范围）
      第二遍: 没找到具体 → 找第一个日期范围目录 → 用起点
      都没有 → 无日期

    上下文 = 日期源之下（文件之上）的无日期目录名（反转成根→近顺序）。
    全部无日期时，上下文 = 所有无日期目录（保留档案层级）。

    例: path=2025.09.7z/Furina-芙宁娜/芙芙.mp4
      1. 检查 Furina-芙宁娜 → 无日期，记录为上下文
      2. 检查 2025.09.7z → 日期 2509（月精度），停止
      返回 ('2509', 'Furina-芙宁娜')
    """
    # 父目录链（近→远）
    chain: list[Path] = []
    parent = path.parent
    while parent != target_dir and parent != parent.parent:
        chain.append(parent)
        parent = parent.parent

    def _context_below(idx: int) -> str:
        """收集 chain[0..idx-1]（日期源之下）的无日期目录作为上下文"""
        parts = []
        for p in chain[:idx]:
            t, _ = extract_date_signal(p.name)
            if (t == "none"
                    and not _PURE_NUMERIC_DIR.match(p.name)
                    and not _RJ_PATTERN.match(p.name)):
                # A5: 清理平台档位标记 (fantia500)/(fanbox500)
                name = _RE_TIER_TAG.sub("", p.name).strip("()[] _-")
                if name:
                    parts.append(name)
        parts.reverse()
        return "_".join(parts)

    # 第一遍: 最近的具体日期
    for i, p in enumerate(chain):
        t, d = extract_date_signal(p.name)
        if t == "single":
            return d, _context_below(i)
    # 第二遍: 最近的范围（起点）
    for i, p in enumerate(chain):
        t, d = extract_date_signal(p.name)
        if t == "range":
            return d, _context_below(i)
    # 无日期: 全部无日期目录作上下文（清理档位标记）
    parts = []
    for p in reversed(chain):
        if not _PURE_NUMERIC_DIR.match(p.name):
            name = _RE_TIER_TAG.sub("", p.name).strip("()[] _-")
            if name:
                parts.append(name)
    return None, "_".join(parts)


def compute_prefix(file_path: Path, target_dir: Path, allow_mtime: bool = False) -> str:
    """计算文件应有的前缀

    逆向模式（默认）:
      - 文件自身有具体日期 → 保留（幂等，不继承）
      - 文件自身有日期范围 → 用起点
      - 从父目录继承日期（P3 具体优先 / P4 范围起点）
      - 全部无日期 → 不加前缀

    正向模式（allow_mtime=True）:
      - 父目录无日期时，用文件 mtime 作为回退
      - ⚠️ 这是正向操作（增加内容），应明确标识
    """
    f_type, f_date = extract_date_signal(file_path.stem)
    if f_type == "single":
        return ""
    if f_type == "range":
        return f_date + "_"
    date, context = find_parent_date_and_context(file_path, target_dir)
    if not date and allow_mtime:
        date = get_date_prefix_from_mtime(file_path)
    parts = []
    if date:
        parts.append(date)
    if context:
        parts.append(context)
    return "_".join(parts) + "_" if parts else ""


class Step2InheritPrefix(PipelineStep):
    """日期继承：文件/父目录日期提取 + 上下文前缀

    完备规则见模块 docstring（P1-P5）。
    """

    name = "inherit_prefix"
    description = "日期继承：文件/父目录日期/范围提取作为前缀"
    allow_mtime: bool = False

    def preview(self, ctx: PipelineContext) -> StepPreview:
        """预览：P1-P5 日期继承（文件日期>目录具体>范围起点）+ context 前缀"""
        step_cfg = ctx.step_configs.get(self.name, {})
        allow_mtime = step_cfg.get("allow_mtime", self.allow_mtime)
        template = step_cfg.get("template", None)

        ops = []
        changed = 0
        for i, rec in enumerate(ctx.records):
            f_type, f_date = extract_date_signal(rec.current_path.stem)
            if f_type == "single":
                continue  # 文件已带具体日期，幂等跳过
            if f_type == "range":
                date, context = f_date, ""  # 文件带范围 → 起点，不继承目录
            else:
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
                    # 模板引擎不可用（依赖缺失）→ 该文件不处理，静默跳过（安全：宁可不改不错改）
                    new_name = None
            else:
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
