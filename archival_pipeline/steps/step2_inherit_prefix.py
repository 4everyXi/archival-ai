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
from archival_pipeline.steps.step1_processor import _ZERO_WIDTH

# ── 排除模式 ─────────────────────────────────────────────────
_RJ_PATTERN = re.compile(r"^RJ\d+", re.IGNORECASE)
# 纯数字/短横目录（平台 ID 等，不是日期也不是上下文）
_PURE_NUMERIC_DIR = re.compile(r"^[\d\-_]{2,8}$")
# 平台档位标记 (fantia500)/(fanbox500)/(0)/(500)/patreon/ci-en/gumroad（A5 清理）
# ⚠️ 裸数字只匹配括号内（\(\d+\)）——否则误删 RJ01606066 的作品号、scene01 的序号
_RE_TIER_TAG = re.compile(
    r"\(?(?:fantia|fanbox|patreon|ci[-_]?en|gumroad)\s*\d*\)?|\(\d+\)", re.IGNORECASE,
)
# YYYYMMDD 紧凑格式（20260215 → 260215）——区分平台 ID（8 位非日期）与 8 位日期
_YYYYMMDD_COMPACT = re.compile(r"(?:19|20)\d{2}(?:0[1-9]|1[012])(?:0[1-9]|[12]\d|3[01])")

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
# 6位数字开头：`250714_`、`220208haru_ki`、`2203126kiri_kij`（6位日期后跟字母/数字/序号，
# 如素材日期 220312 + 序号 6）。放宽自 `(?![0-9])`（数字后只能是字母）——文件日期最优先原则：
# 文件本身包含的日期（哪怕后跟序号）优先于目录日期；非法日期由 _validate_date 兜底拒绝
_YYMMDD_HEAD = re.compile(r"^(\d{6})")


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
    # FULL 日期（YYYY-MM-DD）search：可在平台 ID 后（12184175-2026-07-02-カチーナ → 2026-07-02）
    m = _DATE_FULL_SEP.search(name)
    if m:
        return ("single", _full_to_yymmdd(m.group(0)))
    # YYYYMMDD 紧凑（20260215 → 260215）——8 位完整格式优先于 6 位 YYMMDD
    # （20100228 的 201002 恰好是合法 YYMMDD，但 8 位整体语义是 2010-02-28）
    m = _YYYYMMDD_COMPACT.match(name)
    if m:
        d = m.group(0)
        return ("single", d[2:4] + d[4:6] + d[6:8])
    m = _YYMMDD_HEAD.match(name)
    if m and _validate_date(m.group(1)):
        return ("single", m.group(1))
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

    上下文（A5 全链继承，用户拍板 2026-08-08）:
      继承父目录链上**所有**目录名（target 下第一级 → 文件父目录），
      越靠近根目录的目录被越多文件继承。
      每个目录名: 去日期部分（日期已由 A4 提取前置，不重复）→
      去档位标记 → 去伪扩展名 → 去符号噪音；剩余非空则进 context，根→近顺序。
      RJ 编号/纯数字目录不再排除（RJ 是作品标识，属于档案上下文）。

    例: 2022-02-15-報いを受ける春ちゃん.psd/200609haru1.psd
      → 日期 220215（P3）+ context '報いを受ける春ちゃん'
      → 220215_報いを受ける春ちゃん_200609haru1.psd
    """
    # 父目录链（近→远）
    chain: list[Path] = []
    parent = path.parent
    while parent != target_dir and parent != parent.parent:
        chain.append(parent)
        parent = parent.parent

    def _clean_context_name(name: str) -> str:
        """A5 全链继承的目录名处理：去平台 ID/日期/档位/伪扩展名/符号噪音

        不全角转半角（避免 ？→? 非法字符；全角字符 Windows 合法）。
        """
        n = name
        # 去开头平台 ID（8 位数字，fantia/fanbox 作品号——A1 平台 ID 规则：
        # 8 位非日期数字是平台 ID；8 位合法日期（YYYYMMDD/YYYY-MM-DD）豁免）
        if re.fullmatch(r"\d{8}", n[:8]) and not _YYYYMMDD_COMPACT.fullmatch(n[:8]):
            n = re.sub(r"^\d{8}(?:[-_ ]|$)", "", n)
        # 去日期部分（从开头匹配的日期格式去掉；YYMMDD 需 _validate_date 校验，
        # 防止 12184175 的 121841（非法日期）被当日期截断）
        for pat in (_RANGE_FULL, _RANGE_YYMMDD, _RANGE_MONTH,
                    _YYMMDD_HEAD, _DATE_FULL_SEP, _YYYYMMDD_COMPACT,
                    _DATE_YEAR_MONTH_DOT):
            m = pat.match(n)
            if not m:
                continue
            # 仅 YYMMDD 需要合法性校验（其余正则已限定合法范围）
            if pat is _YYMMDD_HEAD and not _validate_date(m.group(1)):
                continue
            n = n[m.end():]
            break
        n = n.lstrip("-_~ ～. ")
        # 去档位标记（含裸数字 (0)/(500)）
        n = _RE_TIER_TAG.sub("", n)
        # 去伪扩展名（目录名里的 .psd 等——目录不是文件，扩展名无档案语义）
        if "." in n:
            stem = Path(n).stem
            n = stem if stem else n
        # 零宽删除、连续分隔折叠、去首尾
        n = n.translate(str.maketrans("", "", _ZERO_WIDTH))
        n = re.sub(r"_+", "_", n).strip(" _-·")
        # 纯数字/纯符号剩余（档位目录 0/500、2022-02-22! 的 !、期数残留）→
        # 平台结构数字无独立档案语义，丢弃；有字母/日文才保留（RJ01606066、scene01_LOOP）
        if not re.search(r"[A-Za-z\u4e00-\u9fffぁ-んァ-ヶ]", n):
            return ""
        return n

    def _context_all() -> str:
        """全链继承：所有父目录名（去日期/档位/伪扩展名后剩余）作 context，根→近"""
        parts = []
        for p in chain:
            c = _clean_context_name(p.name)
            if c:
                parts.append(c)
        parts.reverse()  # 根→近
        return "_".join(parts)

    # 第一遍: 最近的具体日期
    for i, p in enumerate(chain):
        t, d = extract_date_signal(p.name)
        if t == "single":
            return d, _context_all()
    # 第二遍: 最近的范围（起点）
    for i, p in enumerate(chain):
        t, d = extract_date_signal(p.name)
        if t == "range":
            return d, _context_all()
    # 无日期
    return None, _context_all()


def compute_prefix(file_path: Path, target_dir: Path, allow_mtime: bool = False) -> str:
    """计算文件应有的前缀

    逆向模式（默认）:
      - 文件自身有日期 + 父目录有日期 → 目录发布日优先（素材复用场景：
        200609haru1 在 220215 目录 → 220215_200609haru1，素材日期保留在原名）
      - 文件自身有日期 + 无目录日期 → 文件日期即档案日期（幂等）
      - 从父目录继承日期（P3 具体优先 / P4 范围起点）
      - 全部无日期 → 不加前缀

    正向模式（allow_mtime=True）:
      - 父目录无日期时，用文件 mtime 作为回退
      - ⚠️ 这是正向操作（增加内容），应明确标识
    """
    f_type, f_date = extract_date_signal(file_path.stem)
    if f_type == "single":
        # D3 修正：目录发布日优先——文件自带日期（素材日）≠ 目录日期时用目录日期作前缀
        # （素材日期保留在原名）；context 全链继承（作品名/标题/RJ 等）
        parent_date, parent_ctx = find_parent_date_and_context(file_path, target_dir)
        if parent_date:
            if file_path.stem.startswith(parent_date):
                return ""
            parts = [parent_date]
            if parent_ctx:
                parts.append(parent_ctx)
            return "_".join(parts) + "_"
        return ""
    if f_type == "range":
        # 文件自带日期范围 → 起点（文件自身日期信号最强，不继承目录）
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
                # D3 修正：目录发布日优先——文件自带日期（素材日）≠ 目录日期时
                # 用目录日期作前缀（素材日期保留在原名）；context 全链继承
                parent_date, parent_ctx = find_parent_date_and_context(
                    rec.current_path, ctx.target_dir)
                if parent_date:
                    if rec.current_path.stem.startswith(parent_date):
                        continue  # 已对齐目录日期，幂等
                    date, context = parent_date, parent_ctx
                else:
                    continue  # 无目录日期：文件日期即档案日期，幂等
            elif f_type == "range":
                # 文件自带日期范围 → 起点（文件自身日期信号最强，不继承目录）
                date, context = f_date, ""
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
