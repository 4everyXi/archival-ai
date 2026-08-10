#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""残留检测 — 后置验证层

需求映射:
- [验证层] 翻译/精修完成后检测：假名残留 / 日语汉字残留（240+ Shinjitai 对照）/ 中英混排
- 为什么这样好: 验证是后置检查不是前置替代——AI 自由翻译后由它兜住机械层面的遗漏；
  机械检测（残留）适合脚本，语义质量（自然度/基调）由六维盲评负责，两者不混淆
"""

"""
翻译质量检查器 — 检查日语残留、截断、分隔符等

用法:
  python scripts/check_translation.py "目标目录"
  python scripts/check_translation.py "目标目录" --verbose
"""
import argparse
import re
import sys
from pathlib import Path

# ============================================================
# 日语专用汉字 → 简体中文 对照表
# 这些 Kanji 在日语是常用字，但简体中文使用不同的字形
# 如果文件名中出现了左侧的日语汉字，说明翻译遗漏
# ============================================================
JP_ONLY_KANJI_MAP = {
    "変": "变", "態": "态", "遊": "游", "恥": "耻",
    "圧": "压", "拡": "扩", "図": "图", "団": "团",
    "対": "对", "収": "收", "処": "处", "続": "续",
    "軽": "轻", "転": "转", "関": "关", "険": "险",
    "験": "验", "権": "权", "済": "济", "沢": "泽",
    "読": "读", "辺": "边", "選": "选", "雑": "杂",
    "蔵": "藏", "豊": "丰", "歳": "岁", "戯": "戏",
    "捗": "步", "渋": "涩", "壊": "坏", "戻": "回",
    "録": "录", "絵": "绘", "訳": "译", "薬": "药",
    "覧": "览", "歯": "齿", "齢": "龄", "顕": "显",
    "黙": "默", "膚": "肤",
    "靈": "灵", "懷": "怀", "擔": "担", "覺": "觉",
    "學": "学", "悅": "悦", "虛": "虚", "轉": "转",
    "遲": "迟", "關": "关", "嚴": "严", "亞": "亚",
    "惡": "恶", "禮": "礼", "殘": "残", "盜": "盗",
    "歷": "历", "曆": "历", "豐": "丰", "獸": "兽",
    "並": "并", "眞": "真", "敎": "教",
    "髪": "发", "體": "体", "廣": "广", "圍": "围",
    "亂": "乱", "爭": "争", "爲": "为", "狀": "状",
    "單": "单", "雙": "双", "萬": "万", "對": "对",
    "應": "应", "歸": "归", "當": "当", "畫": "画",
    "會": "会", "從": "从", "條": "条", "備": "备",
    "盡": "尽", "進": "进", "達": "达", "過": "过",
    "隨": "随", "隱": "隐", "樣": "样", "縣": "县",
    "黨": "党", "傳": "传", "價": "价", "權": "权",
    "護": "护", "讀": "读", "萬": "万", "總": "总",
    "專": "专", "業": "业", "東": "东", "樂": "乐",
    "氣": "气", "發": "发", "電": "电", "當": "当",
    "頭": "头", "體": "体", "學": "学", "國": "国",
    "會": "会", "開": "开", "場": "场", "樓": "楼",
    "點": "点", "時": "时", "書": "书", "長": "长",
    "門": "门", "間": "间", "關": "关",
}

_JP_KANJI_PATTERN = re.compile(
    "[" + "".join(re.escape(c) for c in JP_ONLY_KANJI_MAP.keys()) + "]"
)


def _check_jp_kanji(name):
    """检查文件名中是否包含日语专用汉字（Shinjitai/旧字体）。"""
    found = []
    for m in _JP_KANJI_PATTERN.finditer(name):
        c = m.group()
        cn = JP_ONLY_KANJI_MAP.get(c, "?")
        found.append(f"{c}(应→{cn})")
    return found


def _check_list_mode(list_file: Path) -> None:
    """清单模式：校验译名清单.txt（应用前必跑——不合格不许应用）

    检查：①假名残留 ②英文残留（白名单外）③下划线复合词残留 ④单字书面词
    白名单（保留类——本次经验提取）：
      - 作者名（jururi/juri/ruri——检索锚点）
      - 技术规格（fps/RIFE/4x/1080p/720p/480p/1700p/4K/8K）
      - 社区通用（NTR/MMD/VR/3D/2D/CG/OF）
      - 系列代号（zzz/z02 类——数字组合）
      - 素材名段（D3——\d{5,6}[a-z] 开头的素材日+素材名）
      - 版本标记（a/b/s 单字母）
    """
    KEEP_EN = {  # 英文白名单（保留类 token）
        "fps", "FPS", "RIFE", "4x", "4X", "NTR", "MMD", "VR", "3D", "2D", "CG", "OF",
        "sample", "SAMPLE", "Timeline", "flow", "qq", "PKR", "kijoui", "kijouiB",
        "kijouiR", "Rkijoui", "mzg", "mzgs", "magL", "hdk", "hdkk", "L", "S", "SS",
        "thina", "aloe", "marimeia", "irikuro", "peko", "aquasZ", "z", "zzz", "z02",
        "Timelinelow", "s", "Z",  # Timeline 系列/小写版本标记 s/大写系列代号 Z
        # 作者名（检索锚点）
        "jururi", "juri", "ruri",
    }
    lines = [l.rstrip() for l in list_file.read_text(encoding="utf-8").splitlines() if l.strip()]
    issues = {"假名残留": [], "英文残留（白名单外）": [], "下划线复合词残留": [], "单字书面词": []}
    for line in lines:
        stem = line.rsplit(".", 1)[0] if "." in line else line
        # ① 假名残留
        kana = re.findall(r"[ぁ-んァ-ヶー]+", stem)
        if kana:
            issues["假名残留"].append((line, kana))
        # ② 英文残留（白名单外）——素材日段（\d{5,}[a-z]）后的 token 豁免（D3 素材名延续）
        eng = []
        in_material = False
        for tok in stem.split("_"):
            if re.fullmatch(r"\d{5,}[a-z]+\d*", tok):
                in_material = True  # 素材日+素材名段开始——后续英文全部豁免（D3）
                continue
            if in_material:
                continue
            if not re.fullmatch(r"[A-Za-z]+", tok):
                continue
            if tok in KEEP_EN or re.fullmatch(r"[ab]", tok):
                continue
            eng.append(tok)
        if eng:
            issues["英文残留（白名单外）"].append((line, eng))
        # ③ 下划线复合词残留（英文_英文——ha_to/bunny_suits 类——整段理解不该出现）
        comp = re.findall(r"(?<![0-9])\b[a-z]+_[a-z]+\b", stem)
        comp = [c for c in comp if not any(p in KEEP_EN for p in c.split("_"))]
        if comp:
            issues["下划线复合词残留"].append((line, comp))
        # ④ 单字书面词（性/桌/爱 单字——按基调选口语双字）
        single = re.findall(r"_(?:性|桌|爱|操|幼|裸)_", f"_{stem}_")
        if single:
            issues["单字书面词"].append((line, single))

    total_problems = sum(len(v) for v in issues.values())
    print(f"清单: {list_file}")
    print(f"行数: {len(lines)} / 问题: {total_problems}")
    if total_problems == 0:
        print("✅ 译名完成标准校验通过——可以应用")
        return
    for k, v in issues.items():
        if not v:
            continue
        print(f"\n⚠️ [{k}] {len(v)} 处")
        for line, detail in v[:8]:
            print(f"    {line}  ({detail})")
        if len(v) > 8:
            print(f"    ... 还有 {len(v)-8} 处")
    print("\n❌ 校验未通过——修复后再应用（AI 逐条精修）")


def main():
    parser = argparse.ArgumentParser(description="检查翻译质量")
    parser.add_argument("target", nargs="?", help="目标目录（默认当前目录）")
    parser.add_argument("--list", dest="list_file", metavar="译名清单.txt",
                        help="清单模式：校验译名清单（应用前——假名/英文白名单/复合词/单字词）")
    parser.add_argument("--verbose", "-v", action="store_true", help="详细输出")
    args = parser.parse_args()

    if args.list_file:
        _check_list_mode(Path(args.list_file))
        return

    root = Path(args.target).resolve() if args.target else Path.cwd()
    if not root.exists():
        print(f"❌ 目录不存在: {root}")
        sys.exit(1)

    print("=" * 80)
    print("检查翻译质量")
    print("=" * 80)

    issues = []
    total = 0

    for item in sorted(root.rglob("*")):
        name = item.stem if item.is_file() else item.name
        if not name:
            continue
        total += 1

        # 检查1: 日语残留（平假名/片假名）
        jp_remain = re.findall(r"[ぁ-んァ-ヶー]+", name)
        if jp_remain:
            issues.append(("日语残留（假名）", name, jp_remain))

        # 检查2: 日语专用汉字残留（Shinjitai/旧字体）
        jp_kanji_found = _check_jp_kanji(name)
        if jp_kanji_found:
            issues.append(("日语汉字残留", name, jp_kanji_found))

        # 检查3: 中英混排（单个字母紧邻汉字）
        if re.search(r"[a-zA-Z][\u4e00-\u9fff]|[\u4e00-\u9fff][a-zA-Z]", name):
            issues.append(("中英混排", name, []))

        # 检查4: 全角空格
        if "\u3000" in name:
            issues.append(("全角空格", name, []))

        # 检查5: 连续重复词
        if re.search(r"(.{2,})\\1", name):
            issues.append(("可能重复", name, []))

        # 检查6: 创作者名误翻译 — 使用硬编码已知列表
        creator_patterns = ["じゅるり"]
        for cp in creator_patterns:
            if cp in name:
                issues.append(("创作者名残留", name, [cp]))

        # 检查7: 截断检测 — 字母紧贴汉字（排除合法标记）
        trunc1 = re.search(r"(?<![a-zA-Z0-9])[a-zA-Z][\u4e00-\u9fff]", name)
        trunc2 = re.search(r"[\u4e00-\u9fff][a-zA-Z](?![a-zA-Z])", name)
        if trunc1 and not re.search(r'(?:1080|720|2160|4)[pＰkＫ\u4e00-\u9fff]|p完|p高|p低', name):
            issues.append(("截断(字母+汉字)", name, []))
        if trunc2 and not re.search(r'[\u4e00-\u9fff][A-Z][^a-zA-Z]|骑乘位[ABCR]|版本[ABCD]|[位版][A-D]', name):
            issues.append(("截断(汉字+字母)", name, []))

        # 检查8: RJ码/DLsite码
        if re.search(r"RJ\d{5,}", name, re.IGNORECASE):
            issues.append(("DLsite码", name, []))

        # 检查9: 价格元数据残留
        if re.search(r"\(\d+\)", name):
            issues.append(("价格元数据", name, []))

        # 检查10: 全角英数字
        if re.search(r"[Ａ-Ｚａ-ｚ０-９]", name):
            issues.append(("全角英数字", name, []))

    # ── 统计 ──
    print(f"\n总项目数: {total}")
    print(f"问题数: {len(issues)}")

    if not issues:
        print("\n✅ 翻译质量检查通过")
        return

    # ── 按类型分组输出 ──
    issue_types = {}
    for issue_type, name, detail in issues:
        if issue_type not in issue_types:
            issue_types[issue_type] = []
        issue_types[issue_type].append((name, detail))

    for issue_type, items in sorted(issue_types.items()):
        print(f"\n⚠️  [{issue_type}] {len(items)} 处")
        for name, detail in items[:10]:
            if detail:
                print(f"    {name}  ({detail})")
            else:
                print(f"    {name}")
        if len(items) > 10:
            print(f"    ... 还有 {len(items)-10} 处")

    # ── 综合建议 ──
    if "日语汉字残留" in issue_types:
        print(f"\n💡 日语汉字残留说明：")
        print(f"    这些是日语专用汉字（Shinjitai），在中文有对应的简体写法。")
        print(f"    例如：変→变、態→态、遊→游。说明逆向翻译映射表没有覆盖这些词。")
        print(f"    处理方式：① 补充映射表后重新运行逆向翻译  ② 执行正向AI精修")

    # 详细模式: 列出目录结构
    if args.verbose:
        print("\n" + "=" * 80)
        print("目录结构:")
        for d in sorted(root.iterdir()):
            if d.is_dir():
                print(f"  📂 {d.name}")


if __name__ == "__main__":
    main()
