"""archival-ai 自检：验证默认路径/快速模式/统计/冲突检测/回滚闭环。

运行: python scripts/selftest.py
"""
import shutil
import sys
import tempfile
from pathlib import Path

SKILL_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SKILL_ROOT))


def make_tree(base: Path):
    (base / "10003844-2025-06-04-キャラ名").mkdir(parents=True)
    (base / "10003844-2025-06-04-キャラ名" / "G36_01.mp4").write_text("x", encoding="utf-8")
    (base / "250717_素材_Colored_ver.mp4").write_text("x", encoding="utf-8")
    (base / "10221804-2025-07-14-モブ差分" / "jpeg" / "500").mkdir(parents=True)
    (base / "10221804-2025-07-14-モブ差分" / "jpeg" / "500" / "001.jpeg").write_text("x", encoding="utf-8")


def test_default_no_translate(tmp: Path):
    """默认路径只做结构：Colored 保持原文，翻译不走脚本"""
    from archival_pipeline.pipeline import Pipeline
    from archival_pipeline.steps.step1_processor import Step1Processor
    from archival_pipeline.steps.step2_inherit_prefix import Step2InheritPrefix

    p = Pipeline(tmp)
    p.register(Step1Processor())
    p.register(Step2InheritPrefix())
    res = p.preview()
    for op in res.final_operations:
        assert "着色版" not in op.destination.name, f"默认路径误翻译: {op}"
    assert res.statistics["total"] == 3, f"total 应为 3，实际 {res.statistics}"


def test_translate_only_explicit(tmp: Path):
    """快速模式（显式 --translate）才走缓存翻译"""
    from archival_pipeline.pipeline import Pipeline
    from archival_pipeline.steps.step0_translator import Step0Translator

    p = Pipeline(tmp)
    p.register(Step0Translator())
    res = p.preview()
    translated = [op for op in res.final_operations
                  if "着色版" in op.destination.name]
    assert translated, "快速模式应翻译 Colored→着色版"


def test_conflict_detector_blocks():
    """冲突检测：Windows 保留字符应产生 error"""
    from archival_pipeline.steps.conflict_detector import check_conflicts, has_errors

    findings = check_conflicts([(Path("a.txt"), Path("b:bad.txt"))])
    assert has_errors(findings), "FORBIDDEN_CHARS 应产生 error"


def test_full_cycle(tmp: Path):
    """执行→备份→回滚 全链路（强断言：被改名文件必须恢复原名）"""
    from archival_pipeline.backup import rollback_all, save_backup
    from archival_pipeline.pipeline import Pipeline
    from archival_pipeline.steps.step1_processor import Step1Processor
    from archival_pipeline.steps.step2_inherit_prefix import Step2InheritPrefix

    p = Pipeline(tmp, dry_run=False)
    p.register(Step1Processor())
    p.register(Step2InheritPrefix())
    res = p.run()
    assert res.statistics["errors"] == 0, f"执行有错误: {res.statistics}"
    backups = []
    for sr in res.steps:
        if sr.backup_data:
            backups.append(save_backup(
                sr.backup_data, tmp / f"backup_{sr.step_name}.json",
                step_name=sr.step_name))
    assert backups, "应生成备份"
    # 执行后原名已被改（前缀继承生效）
    assert not (tmp / "10003844-2025-06-04-キャラ名" / "G36_01.mp4").exists(), \
        "执行后 G36_01.mp4 应已被改名前缀继承"
    rollback_all(backups)
    # 强断言：被改名的文件回滚后恢复原名
    assert (tmp / "250717_素材_Colored_ver.mp4").exists(), "回滚后原文件应恢复"
    assert (tmp / "10003844-2025-06-04-キャラ名" / "G36_01.mp4").exists(), \
        "回滚后 G36_01.mp4 应恢复原名"
    assert (tmp / "10221804-2025-07-14-モブ差分" / "jpeg" / "500" / "001.jpeg").exists(), \
        "回滚后 001.jpeg 应恢复原名"


def main():
    tmp = Path(tempfile.mkdtemp(prefix="archival_ai_selftest_"))
    try:
        make_tree(tmp)
        test_default_no_translate(tmp)
        test_translate_only_explicit(tmp)
        test_conflict_detector_blocks()
        test_full_cycle(tmp)
        print("ALL PASS — 默认路径/快速模式/统计/冲突检测/回滚闭环 全部正确")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    main()
