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
    moved = 0
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
            p.rename(dest)
            moved += 1
            print(f"  {p.name}")
    for p in sorted(target.rglob("*"), key=lambda x: len(str(x)), reverse=True):
        if p.is_dir() and p != target:
            try:
                p.rmdir()
            except OSError:
                pass
    print(f"\n平铺完成: {moved} 个文件移到根目录")


def gen_translation_list(target: Path) -> None:
    """生成翻译工作区：创建 <目标>\\_translation\\ + 原名清单.txt + 路径清单.txt

    文档①（用户拍板设计）：只包含所有文件的原名，**不含任何路径**——
    AI/用户基于它逐条手动翻译，产出译名清单（同序一一对应）。

    路径清单.txt：与原名清单**一起生成、同序一一对应**（第 N 行 = 第 N 个原名的
    相对路径）——AI 拿到译名后按路径定位文件重命名（原名无路径无法定位）。
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
    print(f"翻译工作区已创建: {ws}")
    print(f"原名清单（{len(names)} 个文件，仅文件名无路径）: {ws / '原名清单.txt'}")
    print(f"路径清单（{len(paths)} 行，与原名清单同序一一对应）: {ws / '路径清单.txt'}")


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
