"""统一 CLI 入口 — 模块 A 的默认路径 + 快速模式 + 安全网命令

需求映射:
- [模块组合] 默认只注册结构步骤（step1+step2）；--translate 才启用 B5 缓存引擎
- [四不原则] --preview 先出变更清单，--execute 才执行，--rollback 可逆
- 为什么这样好: 默认路径不含翻译脚本=智能体优先在代码层落地；翻译由 AI 完成，脚本不越权
"""
import argparse
import json
import sys
from pathlib import Path
from archival_pipeline.pipeline import Pipeline
from archival_pipeline.preview import render
from archival_pipeline.backup import save_backup, rollback_all


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


def main():
    """CLI 入口：预览/执行/回滚/残留检测

    默认路径 = 结构处理（step1+step2）；--translate 才启用快速模式缓存翻译。
    """
    parser = argparse.ArgumentParser(description="archival_Super — 档案化管线统一入口")
    parser.add_argument("target", nargs="?", help="目标目录")
    parser.add_argument("--preview", metavar="FILE", help="生成预览文件")
    parser.add_argument("--format", choices=["json", "txt"], default="txt", help="预览输出格式")
    parser.add_argument("--full", action="store_true", help="完整列表模式：显示全部文件原名+译名")
    parser.add_argument("--execute", action="store_true", help="执行重命名")
    parser.add_argument("--backup", metavar="PREFIX", help="备份文件前缀")
    parser.add_argument("--rollback", metavar="FILE", nargs="+", help="从备份回滚")
    parser.add_argument("--config", help="配置文件")
    parser.add_argument("--translate", choices=["table"], nargs="?",
                        const="table", help="快速模式：常用词缓存翻译（AI 翻译不走此选项）")
    parser.add_argument("--step-config", metavar="KEY=VALUE", action="append", help="步骤配置")
    parser.add_argument("--template", metavar="FORMAT", help="命名模板")
    parser.add_argument("--flatten", choices=["all", "archived"], nargs="?", const="all", help="平铺")
    args = parser.parse_args()

    if args.rollback:
        success = rollback_all(args.rollback)
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

    p = Pipeline(target, config=config, step_configs=step_configs, dry_run=not args.execute)

    if args.translate:
        from archival_pipeline.steps.step0_translator import Step0Translator
        if "translator" not in step_configs:
            step_configs["translator"] = {}
        step_configs["translator"]["engine"] = args.translate
        p.context.step_configs = step_configs
        p.register(Step0Translator())

    # 默认只注册结构步骤（A 模块）。翻译由 AI 完成；--translate 才启用缓存引擎。
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
            # Use pipeline's records (original paths) instead of re-scanning disk
            ops_by_source = {str(op.source): str(op.destination) for op in result.final_operations}
            full_ops = []
            for rec in p.context.records:
                src = str(rec.original_path)
                dst = ops_by_source.get(src, src)
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
        if args.preview:
            preview_path = Path(args.preview)
            if not preview_path.is_absolute():
                preview_path = target / preview_path
            preview_path.write_text(output, encoding="utf-8")
            print(f"预览已保存: {preview_path}")
        else:
            print(output)
        return

    result = p.run()
    if args.backup:
        for sr in result.steps:
            if sr.backup_data:
                backup_file = Path(f"{args.backup}_{sr.step_name}.json")
                if not backup_file.is_absolute():
                    backup_file = target / backup_file
                save_backup(sr.backup_data, backup_file, sr.step_name)
                print(f"备份已保存: {backup_file}")

    if args.flatten:
        flatten(target, args.flatten)

    print("完成")


if __name__ == "__main__":
    main()
