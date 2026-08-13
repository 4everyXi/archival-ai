"""Step 1: 结构清洗 — 模块 A1/A2/A3/A6

需求映射:
- [A1] 平台噪音删除: 平台ID(8位非日期数字)/hex hash/域名标签/平台名前缀/URL编码；
       内容标记白名单（[2D动画][有修正] 等）保留——是档案核心信息，不是噪音
- [A2] 冗余删除: 重复扩展名、下载副本后缀 (1)/- Copy/副本
- [A3] 分隔符规范化: 全角→半角、零宽字符删除、safe table（确定噪音字符）、连续分隔符折叠
- [A6] 重名冲突处理: ensure_unique 追加 _2/_3（机械兜底，不涉及语义）
- 为什么这样好: 只删不增、确定才动——每个删除模式都是确定性噪音；
  语义判断（重复词/日英同名/乱码）留给 B4 AI 层，脚本不越权

集成来源:
  detox (BSD-2): https://github.com/dharple/detox (commit 0a8e212)
  rename-clean (GPL-3.0): ensure_unique 移植
"""
import itertools
import re
import unicodedata
from pathlib import Path
from archival_pipeline.steps.base import PipelineStep
from archival_pipeline.models import (
    PipelineContext, RenameOperation,
    StepPreview, StepResult, BackupData,
)

# ── A1: 平台噪音模式 ──────────────────────────────────────────
# 域名广告标签（[www.xxx.com]）——只删这类；[2D动画][有修正] 等内容标记保留
_RE_DOMAIN_TAG = re.compile(
    r"\[[^\[\]]*\.(?:com|net|org|tv|cc|me|xyz|info|site|top)[^\[\]]*\]",
    re.IGNORECASE,
)
# 平台名前缀（twitter/pixiv/youtube/yt/ig/fb/tiktok/patreon/gumroad）
_RE_PLATFORM_PREFIX = re.compile(
    r"^(?:twitter_video_|twitter_|pixiv_|youtube_|yt_|ig_|fb_|tiktok_|patreon_|gumroad_)",
    re.IGNORECASE,
)
# hex hash（8-32 位，含至少一个 a-f；全数字走 _RE_NUMERIC_ID 判定）
_RE_HEX_HASH = re.compile(r"^([0-9a-f]{8,32})[_-]")
# 纯数字 ID（8 位+；YYYYMMDD 日期由 _is_valid_yyyymmdd 豁免）
_RE_NUMERIC_ID = re.compile(r"^(\d{8,})[_-]")
# 平台档位标记 (fantia500)/(fanbox500)/patreon/ci-en/gumroad——平台结构，不是档案信息
_RE_TIER_TAG = re.compile(
    r"\(?(?:fantia|fanbox|patreon|ci[-_]?en|gumroad)\s*\d*\)?", re.IGNORECASE,
)
# URL 编码残留 %20 / %E3%81%82
_RE_URL_ENC = re.compile(r"%[0-9A-Fa-f]{2}")

# ── A2: 冗余删除 ──────────────────────────────────────────────
# 下载副本后缀: xxx(1).mp4 / xxx - Copy / xxx_copy / xxx副本 / xxx- 副本 (2)
_RE_COPY_PAREN = re.compile(r"\((\d+)\)$")
_RE_COPY_SUFFIX = re.compile(r"(?:[ _-]+)?(?:copy)[ _-]*$", re.IGNORECASE)
_RE_COPY_CN = re.compile(r"(?:[ _-]+)?副本(?:[ _-]*\(\d+\))?[ _-]*$")

# ── A3: 全角→半角 / 零宽 / safe table ────────────────────────
_FULLWIDTH_TO_HALFWIDTH = str.maketrans(
    "０１２３４５６７８９"
    "ＡＢＣＤＥＦＧＨＩＪＫＬＭＮＯＰＱＲＳＴＵＶＷＸＹＺ"
    "ａｂｃｄｅｆｇｈｉｊｋｌｍｎｏｐｑｒｓｔｕｖｗｘｙｚ"
    "！＂＃＄％＆＇（）＊＋，－．／：；＜＝＞？＠［＼］＾＿｀｛｜｝～　",
    "0123456789"
    "ABCDEFGHIJKLMNOPQRSTUVWXYZ"
    "abcdefghijklmnopqrstuvwxyz"
    "!\"#$%&'()*+,-./:;<=>?@[\\]^_`{|}~ ",
)
# 零宽/不可见字符（复制粘贴残留，确定噪音）：零宽空格/连接符/软连字符/BOM
_ZERO_WIDTH = "\u200b\u200c\u200d\u00ad\ufeff"

# Safe table: 确定噪音字符（移植自 detox safe.tbl）
# 核心原则：只替换确定有问题的字符。不在表里的字符，一律不动。
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
    # 日文名字分隔中点 → _（A3 统一分隔符；语义翻译后由 AI 重建）
    "・": "_",
    # 括号 → -
    "(": "-",   ")": "-",
    "[": "-",   "]": "-",
    "{": "-",   "}": "-",
    # 特殊多字符替换
    "&": "_and_",
    chr(0x7f): "_",  # DEL
})

# ── 三删正则（兼容保留） ───────────────────────────────────────
_RE_DEDUP = re.compile(r"[-_]+")


def _is_valid_yyyymmdd(s: str) -> bool:
    """YYYYMMDD 合法日期判定（区分日期与平台 ID）"""
    if len(s) != 8 or not s.isdigit():
        return False
    y, m, d = int(s[:4]), int(s[4:6]), int(s[6:8])
    return 1900 <= y <= 2099 and 1 <= m <= 12 and 1 <= d <= 31


def _is_hex(s: str) -> bool:
    """是否 hex 串（全 hex 且含至少一个字母）——区分 hash 与纯数字 ID"""
    return bool(re.fullmatch(r"[0-9a-fA-F]+", s)) and re.search(r"[a-fA-F]", s)


# v2 补全: 分辨率标准化（源: reverse_archival_processor_v2._normalize_resolution）
# 数字边界 (?<!\d)/(?!\d) 防止误匹配日期范围（231127_260607 的 1127_2606 非分辨率）
_RESOLUTION_PATTERN = re.compile(r"(?<!\d)(\d{3,4})[x×_](\d{3,4})(?!\d)")
_KNOWN_RESOLUTIONS = {
    (1920, 1080): "1080p", (1280, 720): "720p", (3840, 2160): "4K",
    (2560, 1440): "1440p", (640, 480): "480p", (320, 240): "240p",
}


def _normalize_resolution(stem: str) -> str:
    """标准化分辨率：1920x1080 / 1280_720 → 1080p / 720p（已知表 + 高度兜底）

    机械确定（宽×高映射），真实目录高频（jururiDF1_1280_720 等）。
    """
    def _repl(m: "re.Match") -> str:
        w, h = int(m.group(1)), int(m.group(2))
        if (w, h) in _KNOWN_RESOLUTIONS:
            return _KNOWN_RESOLUTIONS[(w, h)]
        return f"{h}p" if h > 0 else m.group(0)

    return _RESOLUTION_PATTERN.sub(_repl, stem)


def apply_safe_table(name: str) -> str:
    """应用 safe table：只替换确定噪音字符

    移植自 detox clean_safe() + builtin safe table
    核心逆向思维：不在表里的字符，不动。
    """
    stem = Path(name).stem
    ext = Path(name).suffix
    stem = stem.translate(_SAFE_TABLE)
    return stem + ext


def three_delete(name: str) -> str:
    """结构清洗主链（A1+A2+A3+A5档位），只删不增，确定才动

    顺序（依赖关系）:
      1. 全角→半角（先转，后续匹配基于半角）
      2. 删零宽字符（不可见噪音）
      3. 删域名标签 [www.xxx.com]（内容标记 [2D动画] 保留）
      4. 删平台名前缀 twitter_/pixiv_/yt_...
      5. 删平台 ID（8位+数字，YYYYMMDD 日期豁免）
      6. 删 hex hash（含字母的 8-32 位串）
      7. 删平台档位标记 (fantia500)
      8. 删副本后缀 (1)/- Copy/副本
      9. 删 URL 编码 %XX
      10. 删重复扩展名
      11. 统一分隔符
    """
    stem = Path(name).stem
    ext = Path(name).suffix
    # A3: NFC 归一化（macOS NFD 与 Windows NFC 字节不同→同名共存；pathvalidate normalize 思想）
    stem = unicodedata.normalize("NFC", stem)
    # D7: 全角数字紧贴半角数字 → 插 _（`１1920` → `1_1920`，防转换后合并成歧义数字 11920）
    stem = re.sub(r"([０-９])(?=[0-9])", r"\1_", stem)
    stem = re.sub(r"([0-9])(?=[０-９])", r"\1_", stem)
    # A3: 全角→半角
    stem = stem.translate(_FULLWIDTH_TO_HALFWIDTH)
    # A3: 零宽字符
    stem = stem.translate(str.maketrans("", "", _ZERO_WIDTH))
    # A1: 域名标签
    stem = _RE_DOMAIN_TAG.sub("", stem)
    # A1: 平台名前缀
    stem = _RE_PLATFORM_PREFIX.sub("", stem)
    # A1: 平台 ID（日期豁免）
    m = _RE_NUMERIC_ID.match(stem)
    if m and not _is_valid_yyyymmdd(m.group(1)):
        stem = stem[m.end():]
    # A1: hex hash
    m = _RE_HEX_HASH.match(stem)
    if m and _is_hex(m.group(1)):
        stem = stem[m.end():]
    # A5: 平台档位标记
    stem = _RE_TIER_TAG.sub("", stem)
    # A2: 副本后缀
    stem = _RE_COPY_PAREN.sub("", stem)
    stem = _RE_COPY_SUFFIX.sub("", stem)
    stem = _RE_COPY_CN.sub("", stem)
    # A1: URL 编码
    stem = _RE_URL_ENC.sub("_", stem)
    # A2: 重复扩展名
    while ext and stem.endswith(ext):
        stem = stem[: -len(ext)]
    # A3: 统一分隔符（空格/半角连字符/日文名字中点 → _）
    stem = stem.replace(" ", "_").replace("-", "_").replace("・", "_")
    # D8 修正: 非扩展名点号统一为 _，但数字间小数点豁免（RIFE4.0 版本号保留；
    #          juri_kijoui.48fps 点前是字母仍转 _）
    stem = re.sub(r"\.(?![0-9])", "_", stem)
    stem = re.sub(r"(?<![0-9])\.", "_", stem)
    # v2 补全: 分辨率标准化（1920x1080→1080p，源: _normalize_resolution）
    stem = _normalize_resolution(stem)
    # v2 补全: 折叠连续分隔符 + 去首尾（detox clean_wipeup 思想；xxx__yyy → xxx_yyy）
    stem = re.sub(r"_{2,}", "_", stem).strip("_")
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
    """后置条件验证：文件名是否可作为合法文件名落盘

    只检查两类真正会导致 rename 失败的问题：
      1. Windows 非法字符（\\ / : * ? " < > |）——win32 下无法作为文件名
      2. 空名 / 纯分隔符名

    边界：中文/日文/全角字符都是合法文件名，不在检查范围（它们由
    conflict_detector 的 FORBIDDEN_CHARS 与 Windows 文件系统自然校验，
    无需在此预设 ASCII 白名单）。
    """
    if not name or name.strip() == "":
        return False
    # 只查 Windows 保留字符 + 控制字符（中文/日文/全角都是合法文件名）
    if re.search(r'[\\/:*?"<>|\x00-\x1f]', name):
        return False
    return True


def _sanitize_forbidden(name: str) -> str:
    """最小化替换 Windows 非法字符（execute 降级路径用）

    只替换真正会导致 rename 失败的字符为 "_"，其余（含中文/日文/
    方括号内容标记）一律原样保留。方括号 [ ] 是 Windows 合法字符，
    也是内容标记（[2D动画]）的载体，不得当作噪音处理。
    """
    return re.sub(r'[\\/:*?"<>|\x00-\x1f]', "_", name)


class Step1Processor(PipelineStep):
    """结构清洗：平台噪音/冗余/分隔符/重名兜底

    逆向思维：
      - 只删不增：文件只可能变短
      - 确定才动：每个删除模式都是确定性噪音
      - 内容标记保留：方括号标签（体裁/修正状态）是档案信息
      - 后置验证：sanitize 风格，确保输出合规
    """

    name = "processor"
    description = "结构清洗：平台噪音(hex/ID/域名)/副本后缀/全角分隔符/重名兜底"

    def preview(self, ctx: PipelineContext) -> StepPreview:
        ops = []
        changed = 0
        for rec in ctx.records:
            name = three_delete(rec.current_path.name)
            # three_delete 已做分隔符规范化（空格/连字符/中点→_）；此处不再调用
            # apply_safe_table——它的方括号/圆括号→"-" 映射会把内容标记
            # "[2D动画]" 的 [ ] 也当噪音转掉。真正的 Windows 非法字符由
            # conflict_detector(FORBIDDEN_CHARS) 与 execute 的 validate_name +
            # _sanitize_forbidden 把关，无需在此再 safe 一遍。
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
                # 后置验证不通过（真·Windows 非法字符）时才救——且只做"字符级最小替换"，
                # 不复用 apply_safe_table（它会把合法的 "[2D动画]" 内容标记也转成 "-"，
                # 那是 bug #1 的连带伤害源）。这里只替换真正非法的字符为 "_"。
                final = final.with_name(_sanitize_forbidden(final.name))
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
