"""结构扫描 — 输出目录结构画像（子技能 structure-scan 的机械部分）

用途: 每次档案化任务先扫描目标目录，输出结构画像 + 疑似缺口清单——
AI 对照 capability-matrix.md 判断技能是否通用（能否处理该目录形态）。

输出（txt 人类 / json AI）:
  1. 统计: 文件数 / 扩展名分布 / 目录层级
  2. 目录名形态: 每个目录名的日期识别结果 / 档位 / 平台 ID / RJ / 标题 / 无日期
  3. 文件名形态: 日期格式分布 / hex / 空格 / 全角 / 副本后缀
  4. 疑似缺口: 含数字但未识别为日期的目录名/文件名（可能是未支持的日期格式）
     —— 这是"结构不够通用"的信号，AI 判断是否真缺口

用法:
  python scripts/scan_structure.py <目录> [--json]
"""
import json
import re
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))  # scripts → structure-scan → skills → 技能根

from archival_pipeline.steps.step2_inherit_prefix import extract_date_signal
from archival_pipeline.steps.step1_processor import three_delete, _is_hex

# 疑似缺口: 含数字但 extract_date_signal 返回 none（可能是新日期格式）
_DIGITY = re.compile(r"\d")
_FULL_DATE = re.compile(r"(?:19|20)\d{2}[-/_](?:0[1-9]|1[012])[-/_](?:0[1-9]|[12]\d|3[01])")


def scan(target: Path) -> dict:
    """扫描目录，返回结构画像"""
    files = [p for p in target.rglob("*") if p.is_file()]
    files = [p for p in files if not p.name.startswith("preview_")]

    # 1. 统计
    ext_counter: Counter = Counter()
    for f in files:
        ext_counter[f.suffix.lower() or "(无扩展名)"] += 1

    # 目录层级（相对 target 的最大深度）
    max_depth = 0
    for f in files:
        depth = len(f.relative_to(target).parts) - 1  # 减文件本身
        max_depth = max(max_depth, depth)

    # 2. 目录名形态
    dirs = sorted({f.parent for f in files} | {f.parent.parent for f in files if f.parent != target})
    dir_signal: Counter = Counter()
    dir_samples: dict = {}
    for d in dirs:
        name = d.name
        t, date = extract_date_signal(name)
        label = t if t != "none" else _classify_none(name)
        dir_signal[label] += 1
        dir_samples.setdefault(label, name)

    # 3. 文件名形态
    file_date_signal: Counter = Counter()
    hex_count = 0
    space_count = 0
    fullwidth_count = 0
    copy_suffix_count = 0
    for f in files:
        stem = f.stem
        t, _ = extract_date_signal(stem)
        file_date_signal[t] += 1
        # hex hash（step1 会删的 8 位 hex）
        parts = stem.split("_")
        if parts and _is_hex(parts[0]):
            hex_count += 1
        if " " in stem:
            space_count += 1
        if re.search(r"[０-９Ａ-Ｚａ-ｚ]", stem):
            fullwidth_count += 1
        if re.search(r"\(1\)|- ?Copy|副本", stem):
            copy_suffix_count += 1

    # 4. 疑似缺口: 含数字但未识别为日期（目录名 + 文件名）
    gaps = []
    for d in sorted(dirs):
        name = d.name
        if _DIGITY.search(name) and extract_date_signal(name)[0] == "none":
            gaps.append({"type": "目录", "name": name,
                         "why": _gap_reason(name)})
    for f in files:
        name = f.stem
        if _DIGITY.search(name) and extract_date_signal(name)[0] == "none":
            gaps.append({"type": "文件", "name": f.name,
                         "why": _gap_reason(name)})

    return {
        "target": str(target),
        "statistics": {
            "files": len(files),
            "extensions": dict(ext_counter.most_common(10)),
            "max_depth": max_depth,
            "dirs": len(dirs),
        },
        "dir_signal": dict(dir_signal.most_common()),
        "dir_samples": dir_samples,
        "file_signal": dict(file_date_signal),
        "noise": {
            "hex_hash": hex_count,
            "space": space_count,
            "fullwidth": fullwidth_count,
            "copy_suffix": copy_suffix_count,
        },
        "gaps": gaps[:30],  # 疑似缺口（含数字未识别为日期）
        "gap_count": len(gaps),
    }


def _classify_none(name: str) -> str:
    """none 目录名的细分（帮助判断形态）"""
    if re.match(r"^RJ\d+", name, re.IGNORECASE):
        return "RJ编号"
    if re.fullmatch(r"\d{8}", name[:8]) if len(name) >= 8 else False:
        return "平台ID"
    if re.search(r"\(?(?:fantia|fanbox|patreon)\d*\)?", name, re.IGNORECASE):
        return "档位目录"
    if _DIGITY.search(name):
        return "含数字(非日期)"
    return "无日期"

def _gap_reason(name: str) -> str:
    """疑似缺口的原因说明（供 AI 判断是否真缺口）"""
    if _FULL_DATE.search(name):
        return "含 YYYY-MM-DD 但未被识别"
    m = re.search(r"(\d{6,8})", name)
    if m:
        return f"含 {len(m.group(1))} 位数字 {m.group(1)}（可能是未支持的日期格式）"
    return "含数字但形态不明"


def render_txt(data: dict) -> str:
    """人类可读画像"""
    lines = [f"结构画像: {data['target']}",
             f"  文件 {data['statistics']['files']} 个 / 扩展名 {data['statistics']['extensions']}"
             f" / 最大层级 {data['statistics']['max_depth']}"]
    lines.append(f"\n目录名形态（extract_date_signal 识别）:")
    for k, v in data["dir_signal"].items():
        sample = data["dir_samples"].get(k, "")
        lines.append(f"  {k}: {v} 个  (例: {sample})")
    lines.append(f"\n文件名日期信号: {data['file_signal']}")
    lines.append(f"噪音: hex {data['noise']['hex_hash']} / 空格 {data['noise']['space']}"
                 f" / 全角 {data['noise']['fullwidth']} / 副本 {data['noise']['copy_suffix']}")
    lines.append(f"\n疑似缺口 {data['gap_count']} 个（含数字未识别为日期——可能是不支持的日期格式）:")
    for g in data["gaps"][:15]:
        lines.append(f"  [{g['type']}] {g['name']}  ← {g['why']}")
    if data["gap_count"] > 15:
        lines.append(f"  ... 共 {data['gap_count']} 个")
    return "\n".join(lines)


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)
    target = Path(sys.argv[1])
    if not target.is_dir():
        print(f"目录不存在: {target}", file=sys.stderr)
        sys.exit(1)
    data = scan(target)
    if "--json" in sys.argv:
        print(json.dumps(data, ensure_ascii=False, indent=2))
    else:
        print(render_txt(data))


if __name__ == "__main__":
    main()
