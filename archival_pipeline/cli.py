"""统一 CLI 入口 — 模块 A 的默认路径 + 快速模式 + 安全网命令

需求映射:
- [模块组合] 默认只注册结构步骤（step1+step2）；--translate 才启用 B5 缓存引擎
- [四不原则] --preview 先出变更清单，--execute 才执行，--rollback 可逆
- 为什么这样好: 默认路径不含翻译脚本=智能体优先在代码层落地；翻译由 AI 完成，脚本不越权
"""
import argparse
import datetime
import hashlib
import json
import sys
import tempfile
from pathlib import Path
from archival_pipeline.pipeline import Pipeline
from archival_pipeline.preview import render
from archival_pipeline.backup import save_backup, rollback_all


def _auto_backup_dir() -> Path:
    """自动备份目录（f2 思路：平台临时目录，防污染 target 目录）"""
    d = Path(tempfile.gettempdir()) / "archival-ai-backups"
    d.mkdir(exist_ok=True)
    return d


def _target_hash(target: Path) -> str:
    """target 路径 hash（备份文件命名，f2 用 cwd 路径 MD5 思路）"""
    return hashlib.md5(str(target.resolve()).encode("utf-8")).hexdigest()[:10]


def _find_auto_backups(target: Path) -> list[Path]:
    """找 target 对应的自动备份（按时间排序，最新优先）"""
    h = _target_hash(target)
    d = _auto_backup_dir()
    if not d.exists():
        return []
    return sorted(d.glob(f"{h}-*.json"))


def flatten(target: Path, mode: str = "all", changed_files: set | None = None):
    """平铺：把子目录里的文件移到根目录（可选仅移动已归档文件）

    每个文件独立 try/except：单个文件失败不中断其余，逐个报错并汇总，
    避免一处失败导致整个平铺中断且无任何错误反馈。
    """
    moved = 0
    errors = []
    for p in sorted(target.rglob("*"), key=lambda x: len(str(x)), reverse=True):
        if p.is_file() and p.parent != target:
            if mode == "archived" and changed_files is not None:
                if p not in changed_files:
                    continue
            dest = target / p.name
            if dest.exists():
                stem = dest.stem
                ext = dest.suffix
                n = 2
                while (target / f"{stem}_{n}{ext}").exists():
                    n += 1
                dest = target / f"{stem}_{n}{ext}"
            try:
                p.rename(dest)
                moved += 1
                print(f"  {p.name}")
            except OSError as e:
                errors.append(f"{p.name}: {e}")
    for p in sorted(target.rglob("*"), key=lambda x: len(str(x)), reverse=True):
        if p.is_dir() and p != target:
            try:
                p.rmdir()
            except OSError:
                pass
    if errors:
        print(f"⚠ 平铺有 {len(errors)} 个文件失败（未中断其余）:")
        for e in errors:
            print(f"  ⚠ {e}")
    print(f"\n平铺完成: {moved} 个文件移到根目录")


def gen_translation_list(target: Path) -> None:
    """生成翻译工作区：<目标>\\_translation\\ + 文件三件套 + 目录三件套

    文件（原名/路径/译名）：只含文件名无路径——AI/用户手动翻译产译名清单（同序）。
    目录（目录原名/目录路径/目录译名）：翻译目录名用（如平台ID+日文作品名目录）。
    """
    ws = target / "_translation"
    ws.mkdir(exist_ok=True)
    # 与 pipeline 同一扫描排除规则（preview_* + _translation）
    items = []  # (原名, 相对路径)
    for p in sorted(target.rglob("*")):
        if not p.is_file():
            continue
        if p.name.startswith("preview_"):
            continue
        if "_translation" in p.relative_to(target).parts:
            continue
        rel = str(p.relative_to(target)).replace("\\", "/")
        items.append((p.name, rel))
    names = [n for n, _ in items]
    paths = [r for _, r in items]
    (ws / "原名清单.txt").write_text("\n".join(names) + "\n", encoding="utf-8")
    (ws / "路径清单.txt").write_text("\n".join(paths) + "\n", encoding="utf-8")
    # 三件套一次生成：译名清单（空占位——AI 通过原名/路径清单生成；已存在则保留）
    # ponytail: AI 已填充的译名不清空——gen 只负责"补缺失"
    trans_file = ws / "译名清单.txt"
    if not trans_file.exists():
        trans_file.write_text("", encoding="utf-8")
        trans_status = "（空占位——待 AI 通过原名/路径清单生成）"
    else:
        trans_status = "（已存在——保留不覆盖）"
    # 目录名清单（同序三件套：目录原名/目录路径/目录译名——翻译目录用）
    dirs = sorted(d for d in target.iterdir() if d.is_dir() and d.name != "_translation")
    dir_names = [d.name for d in dirs]
    dir_paths = [d.relative_to(target).as_posix() for d in dirs]
    (ws / "目录原名清单.txt").write_text("\n".join(dir_names) + "\n", encoding="utf-8")
    (ws / "目录路径清单.txt").write_text("\n".join(dir_paths) + "\n", encoding="utf-8")
    dir_trans_file = ws / "目录译名清单.txt"
    if not dir_trans_file.exists():
        dir_trans_file.write_text("", encoding="utf-8")
        dir_trans_status = "（空占位——待 AI 生成）"
    else:
        dir_trans_status = "（已存在——保留不覆盖）"

    print(f"翻译工作区已生成: {ws}")
    print(f"  原名清单.txt（{len(names)} 个文件）+ 路径清单.txt + 译名清单.txt{trans_status}")
    print(f"  目录原名清单.txt（{len(dir_names)} 个目录）+ 目录路径清单.txt + 目录译名清单.txt{dir_trans_status}")
    print(f"路径清单（{len(paths)} 行，与原名清单同序一一对应）: {ws / '路径清单.txt'}")


def apply_dir_translation(target: Path, translated_file: Path,
                          preview: bool = False, execute: bool = False) -> None:
    """目录名翻译应用：目录译名清单（同序配 目录原名/路径清单）→ 预览/重命名 + 备份

    三件套同序配对（一起生成才对应）：目录原名清单[i] / 目录路径清单[i] / 译名清单[i]——
    路径定位目录 + 原名校验（防 AI 幻觉/文件变动）→ 重命名 + save_backup（回滚通用）。
    翻译目标重名 → A6 兜底（ensure_unique _2，与文件翻译一致）。
    # ponytail: 不走 pipeline（step3）——目录不在 records 范围（_init_records 只收文件），
    # 独立命令更简单；备份/原名校验/A6 与 step3 同模式（保持一致）。
    """
    ws = target / "_translation"
    dir_orig = [l.rstrip() for l in (ws / "目录原名清单.txt").read_text(encoding="utf-8").splitlines() if l.strip()]
    dir_paths = [l.rstrip() for l in (ws / "目录路径清单.txt").read_text(encoding="utf-8").splitlines() if l.strip()]
    translated = [l.rstrip() for l in translated_file.read_text(encoding="utf-8").splitlines() if l.strip()]
    if not (len(dir_orig) == len(dir_paths) == len(translated)):
        print(f"三件套行数不一致: 目录原名 {len(dir_orig)} / 路径 {len(dir_paths)} / 译名 {len(translated)}")
        return

    changed, errors = 0, []
    ops = []  # [(old_path, new_name)]——仅校验通过的变更
    for orig, rel, trans in zip(dir_orig, dir_paths, translated):
        d = target / rel
        # 路径定位 + 原名校验（防 AI 幻觉改名/执行前目录变动）——失败跳过不执行
        if not d.exists():
            errors.append(f"目录不存在: {rel}")
            continue
        if d.name != orig:
            errors.append(f"原名校验失败: {rel}（清单 {orig} vs 实际 {d.name}）")
            continue
        if trans != orig:
            ops.append((d, trans))
            changed += 1

    if errors:
        print(f"检测到 {len(errors)} 个错误（已跳过，不会执行）:")
        for e in errors:
            print(f"  ⚠ {e}")
    print(f"共 {len(dir_orig)} 个目录，{changed} 个变更，{len(dir_orig) - changed} 个无变化")

    if preview:
        for d, trans in ops:
            print(f"  {d.relative_to(target)}  →  {trans}")
        print("[预览模式——未执行]")
        return

    if execute:
        from archival_pipeline.backup import save_backup
        # 先备份后改名（与 step1/step3 同模式——回滚通用，不区分模块）
        # 备份文件路径 = _auto_backup_dir()/hash-step-时间戳.json（复用 cli 自动备份命名）
        backup = [{"original": str(d), "new": str(d.with_name(trans))} for d, trans in ops]
        if backup:
            backup_file = _auto_backup_dir() / (
                f"{_target_hash(target)}-dir_translate-"
                f"{datetime.datetime.now():%Y%m%d%H%M%S}.json"
            )
            save_backup(backup, backup_file, "dir_translate")
            print(f"备份已保存: {backup_file}")
        for d, trans in ops:
            dest = d.with_name(trans)
            if dest.exists():  # A6 兜底：目标重名 → 追加 _2/_3（与文件 ensure_unique 一致）
                # ponytail: 目录名含点（如 `.psd` 伪扩展名）时按"扩展名"拆——`春ちゃん.psd` → `春ちゃん_2.psd`
                stem, sfx = trans.rsplit(".", 1) if "." in trans else (trans, "")
                n = 2
                while dest.exists():
                    dest = d.with_name(f"{stem}_{n}{'.' + sfx if sfx else ''}")
                    n += 1
            d.rename(dest)
        print("完成")


def main():
    """CLI 入口：预览/执行/回滚/残留检测

    默认路径 = 结构处理（step1+step2）；--translate 才启用快速模式缓存翻译。
    """
    parser = argparse.ArgumentParser(description="archival_Super — 档案化管线统一入口")
    parser.add_argument("target", nargs="?", help="目标目录")
    parser.add_argument("--preview", metavar="FILE", nargs="?", const="",
                        help="生成预览文件到目标目录（默认 preview_<时间戳>.txt；可指定相对/绝对路径）")
    parser.add_argument("--format", choices=["json", "txt"], default="txt", help="预览输出格式")
    parser.add_argument("--dual", action="store_true",
                        help="txt 预览双版本：对照版 + 纯净版（仅修改后文件名，preview_<时间戳>_clean.txt）")
    parser.add_argument("--full", action="store_true", help="完整列表模式：显示全部文件原名+译名")
    parser.add_argument("--execute", action="store_true", help="执行重命名")
    parser.add_argument("--backup", metavar="PREFIX", help="备份文件前缀")
    parser.add_argument("--rollback", metavar="FILE", nargs="*", help="从备份回滚（无参数时自动找最近自动备份）")
    parser.add_argument("--config", help="配置文件")
    parser.add_argument("--translate", choices=["table"], nargs="?",
                        const="table", help="快速模式缓存翻译（B5）")
    parser.add_argument("--step-config", metavar="KEY=VALUE", action="append", help="步骤配置")
    parser.add_argument("--apply-translation", metavar="MAPPING_JSON",
                        help="翻译应用：AI 产出的翻译映射（对照组 json）→ 执行/预览 + 备份")
    parser.add_argument("--apply-dir-translation", metavar="TRANSLATED_LIST",
                        help="目录名翻译应用：目录译名清单.txt（同序配 目录原名/路径清单）→ 重命名 + 备份")
    parser.add_argument("--gen-translation-list", action="store_true",
                        help="生成翻译工作区：创建 <目标>\\_translation\\ + 原名清单.txt（仅文件名，无路径）")
    parser.add_argument("--template", metavar="FORMAT", help="命名模板")
    parser.add_argument("--flatten", choices=["all", "archived"], nargs="?", const="all", help="平铺")
    args = parser.parse_args()

    if args.rollback is not None:
        if args.rollback:
            success = rollback_all(args.rollback)
        else:
            # 自动回滚：找 temp 自动备份目录中匹配 target 的备份（f2 undo 思路）
            backups = _find_auto_backups(Path(args.target).resolve() if args.target else Path.cwd())
            if not backups:
                print("未找到自动备份（需先 --execute 或显式 --backup）", file=sys.stderr)
                sys.exit(1)
            print(f"回滚 {len(backups)} 个自动备份: {[b.name for b in backups]}")
            success = rollback_all(backups)
        sys.exit(0 if success else 1)

    if not args.target:
        parser.error("目标目录是必需的")

    target = Path(args.target).resolve()
    config = {}
    if args.config:
        config = json.loads(Path(args.config).read_text(encoding="utf-8"))

    step_configs: dict[str, dict] = {}
    if args.step_config:
        for sc in args.step_config:
            if "=" not in sc:
                continue
            key, value = sc.split("=", 1)
            parts = key.split(".", 1)
            if len(parts) == 2:
                step_name, step_key = parts
                step_configs.setdefault(step_name, {})[step_key] = value

    # flatten 必须与 --execute 一起才能实际执行，
    # 单独使用或只给 --preview 时只生成预览不动文件。
    if args.flatten and not args.execute and not args.preview:
        flatten(target, args.flatten)
        return

    if args.gen_translation_list:
        gen_translation_list(target)
        return

    if args.apply_dir_translation:
        apply_dir_translation(target, Path(args.apply_dir_translation),
                              preview=args.preview is not None, execute=args.execute)
        return

    p = Pipeline(target, config=config, step_configs=step_configs, dry_run=not args.execute)

    if args.translate:
        from archival_pipeline.steps.step0_translator import Step0Translator
        if "translator" not in step_configs:
            step_configs["translator"] = {}
        step_configs["translator"]["engine"] = args.translate
        p.context.step_configs = step_configs
        p.register(Step0Translator())

    # 默认只注册结构步骤（A 模块）。翻译由 AI 完成；--translate 才启用缓存引擎。
    if args.apply_translation:
        # 模块 B 执行端：翻译应用 = 纯翻译（只注册 step3，不重跑 step1/step2）——
        # 模块 A 已由 --execute 完成；若重跑结构步骤会把原名清洗（如空格→_），
        # 导致译名清单的 original（原名清单快照）与清洗后文件名不匹配、翻译被跳过。
        from archival_pipeline.steps.step3_translate_apply import Step3TranslateApply
        p.register(Step3TranslateApply(mapping_file=args.apply_translation))
    else:
        from archival_pipeline.steps.step1_processor import Step1Processor
        from archival_pipeline.steps.step2_inherit_prefix import Step2InheritPrefix
        p.register(Step1Processor())
        p.register(Step2InheritPrefix())

    if args.template:
        if "inherit_prefix" not in step_configs:
            step_configs["inherit_prefix"] = {}
        step_configs["inherit_prefix"]["template"] = args.template
        p.context.step_configs = step_configs

    if not args.execute:
        result = p.preview()
        if args.full:
            from archival_pipeline.models import RenameOperation as RO
            import copy
            # 用 pipeline 的 records（原始路径）重建 original→final 对照。
            # ⚠️ 链式解析：final_operations 含中间态 op（step1: 原名→中间名, step2: 中间名→最终名），
            #    直接 get(src) 只解析一步会显示中间结果（如 2096f222_0zenra→0zenra 而非 231127_0zenra）
            #    必须沿 op 链走到终点（2026-08-08 真实目录分析发现的显示 bug）
            ops_by_source = {str(op.source): str(op.destination) for op in result.final_operations}

            def _resolve(src: str) -> str:
                """链式解析：原名 → 最终名（沿 op 链走到尽头，防循环）"""
                seen = set()
                cur = src
                while cur in ops_by_source and cur not in seen:
                    seen.add(cur)
                    cur = ops_by_source[cur]
                return cur

            full_ops = []
            for rec in p.context.records:
                src = str(rec.original_path)
                dst = _resolve(src)
                full_ops.append(RO(source=rec.original_path, destination=Path(dst)))
            full_result = copy.copy(result)
            full_result.final_operations = full_ops
            # Recalculate statistics
            changed = sum(1 for op in full_ops if op.source.name != op.destination.name)
            full_result.statistics = {
                "total": len(full_ops),
                "changed": changed,
                "skipped": len(full_ops) - changed,
                "errors": 0,
            }
            result = full_result

        output = render(args.format, result)
        if args.preview is not None:
            # 默认在目标目录下生成人类预览（preview_<时间戳>.txt）——方便用户就地查看判断
            preview_path = (Path(args.preview) if args.preview
                            else Path(f"preview_{datetime.datetime.now():%Y%m%d_%H%M%S}.txt"))
            if not preview_path.is_absolute():
                preview_path = target / preview_path
                # 防污染警告：非 preview_ 前缀的相对路径文件会被下次扫描处理
                if not preview_path.name.startswith("preview_"):
                    print(f"⚠ 提示: '{preview_path.name}' 不以 preview_ 开头，"
                          f"下次执行会被扫描处理；建议 --preview 默认名或绝对路径", file=sys.stderr)
            preview_path.write_text(output, encoding="utf-8")
            # 双版本：对照版 + 纯净版（仅修改后文件名，含相对路径）
            if args.dual and args.format == "txt":
                clean_output = render("txt-clean", result)
                clean_path = preview_path.with_name(
                    preview_path.stem + "_clean" + preview_path.suffix)
                clean_path.write_text(clean_output, encoding="utf-8")
                print(f"纯净版已保存: {clean_path}")
            print(f"预览已保存: {preview_path}")
        else:
            print(output)
        return

    result = p.run()
    # 自动落盘备份（f2 思路：每次操作自动 JSON 备份到平台临时目录，可随时 undo）
    saved = []
    for sr in result.steps:
        if not sr.backup_data:
            continue
        if args.backup:
            backup_file = Path(f"{args.backup}_{sr.step_name}.json")
            if not backup_file.is_absolute():
                backup_file = target / backup_file
        else:
            backup_file = _auto_backup_dir() / (
                f"{_target_hash(target)}-{sr.step_name}-"
                f"{datetime.datetime.now():%Y%m%d%H%M%S}.json"
            )
        save_backup(sr.backup_data, backup_file, sr.step_name)
        saved.append(str(backup_file))
    if saved:
        print(f"备份已保存: {', '.join(saved)}")
    if result.statistics.get("errors", 0) > 0:
        print(f"执行含错误: {result.statistics}", file=sys.stderr)

    if args.flatten:
        flatten(target, args.flatten)

    print("完成")


if __name__ == "__main__":
    main()
