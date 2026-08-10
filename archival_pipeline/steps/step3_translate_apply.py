"""Step3 TranslateApply — 翻译应用（模块 B 的执行端 + 安全网）

设计（用户拍板）:
- 翻译 = 逐文件对照组：AI 产出「翻译映射」json（original 未译原名 + translated 译后名
  放在一起）——AI 生成时可看对照，精修时也读同一映射判断问题（对照组反馈循环）
- 本步骤只做机械执行：读映射 → 匹配当前文件 → 重命名 + 备份 —— AI 负责判断，
  脚本负责安全（与模块 A 同一备份/回滚机制——回滚是通用的，不区分模块）
- 回滚 = --rollback 按时间轴找最近备份（含翻译备份），反向恢复

映射 json 格式（AI 产出）:
[
  {"path": "相对路径/原名", "original": "当前文件名", "translated": "翻译后文件名"},
  ...
]
- translated == original 表示该文件不翻译（对照组全量列出，AI 可审计）
- path 相对 target 目录（用于定位文件）；original 用于匹配当前名（防 AI 幻觉错名）

需求映射:
- [范式] AI 决定（翻译什么/怎么翻）→ 脚本执行（应用+备份）→ 备份兜底
- [通用回滚] 与 step1/step2 同一 BackupData 格式（original/new），--rollback 统一恢复
"""
import json
from pathlib import Path

from archival_pipeline.models import (
    PipelineContext, RenameOperation, StepPreview, StepResult, BackupData,
)
from archival_pipeline.steps.base import PipelineStep


class Step3TranslateApply(PipelineStep):
    """翻译应用：读 AI 产出的翻译映射 → 匹配文件 → 重命名（自动备份）"""

    name = "translate_apply"
    description = "翻译应用：AI 翻译映射（原名→译名）批量重命名，自动备份"

    def __init__(self, mapping_file: str | Path | None = None):
        self.mapping_file = Path(mapping_file) if mapping_file else None

    def _load_mapping(self) -> list[dict]:
        """读取翻译映射（两种形态）:
        1. json 对照组（AI 产出）：[{path, original, translated}]
        2. txt 同序译名清单（手动翻译文档②）：每行一个译名，与
           _translation/原名清单.txt 按行一一对应（第 N 行译名 = 第 N 个原名的译名）
        """
        if not self.mapping_file or not self.mapping_file.exists():
            return []
        sfx = self.mapping_file.suffix.lower()
        if sfx == ".json":
            data = json.loads(self.mapping_file.read_text(encoding="utf-8"))
            return data if isinstance(data, list) else []
        if sfx == ".txt":
            # 同序译名清单（文档③）：配 _translation/原名清单.txt + 路径清单.txt
            # 三份同序一一对应（一起生成）——第 N 行：原名=清单①[N]、路径=清单②[N]、
            # 译名=清单③[N]。路径用于定位文件，原名用于校验（防 AI 幻觉/文件变动）。
            ws = self.mapping_file.parent
            orig_file = ws / "原名清单.txt"
            path_file = ws / "路径清单.txt"
            if not orig_file.exists() or not path_file.exists():
                return []
            originals = [l.rstrip("\r\n") for l in orig_file.read_text(encoding="utf-8").splitlines() if l.strip()]
            paths = [l.rstrip("\r\n") for l in path_file.read_text(encoding="utf-8").splitlines() if l.strip()]
            translated = [l.rstrip("\r\n") for l in self.mapping_file.read_text(encoding="utf-8").splitlines() if l.strip()]
            mapping = []
            for i, orig in enumerate(originals):
                mapping.append({
                    "path": paths[i] if i < len(paths) else "",
                    "original": orig,
                    "translated": translated[i] if i < len(translated) else orig,
                })
            return mapping
        return []

    def preview(self, ctx: PipelineContext) -> StepPreview:
        """预览：映射项（translated != original）→ RenameOperation（原名→译名）"""
        ops = []
        changed = 0
        errors = []
        # 建立 相对路径 → 当前文件 索引（相对 target）
        records_by_rel = {}
        for rec in ctx.records:
            rel = str(rec.current_path.relative_to(ctx.target_dir)).replace("\\", "/")
            records_by_rel.setdefault(rel, []).append(rec)

        for item in self._load_mapping():
            path = item.get("path", "")
            original = item.get("original", "")
            translated = item.get("translated", "")
            if not original:
                continue
            if path:
                # json 模式：按相对路径精确匹配
                recs = records_by_rel.get(path, [])
                if not recs:
                    errors.append(f"映射路径未匹配: {path}")
                    continue
                rec = recs[0]
                if rec.current_path.name != original:
                    errors.append(f"原名不匹配（AI 幻觉或文件已变）: {path} 期望 {original} 实际 {rec.current_path.name}")
                    continue
                if translated and translated != original:
                    new_path = rec.current_path.with_name(translated)
                    ops.append(RenameOperation(rec.current_path, new_path))
                    changed += 1
            else:
                # txt 模式（文档②同序译名清单）：按原名匹配——同名文件全部应用同译名
                matches = [rec for rec in ctx.records if rec.current_path.name == original]
                if not matches:
                    errors.append(f"原名未匹配: {original}")
                    continue
                if translated and translated != original:
                    for rec in matches:
                        new_path = rec.current_path.with_name(translated)
                        ops.append(RenameOperation(rec.current_path, new_path))
                        changed += 1

        self._last_errors = errors  # 供 execute 读取（StepPreview 无 errors 字段）
        return StepPreview(
            step_name=self.name,
            operations=ops,
            statistics={
                "total": len(self._load_mapping()),
                "changed": changed,
                "skipped": len(self._load_mapping()) - changed,
                "errors": len(errors),
            },
        )

    def execute(self, ctx: PipelineContext) -> StepResult:
        """执行：重命名 + 备份（original/new 与模块 A 同格式，回滚通用）"""
        preview = self.preview(ctx)
        backup = []
        errors = list(getattr(self, "_last_errors", []) or [])
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
        """回滚：反向恢复（译名 → 原名）——与模块 A 同一机制"""
        for item in reversed(backup_data.operations):
            src = Path(item["new"])
            dst = Path(item["original"])
            if src.exists():
                src.rename(dst)
        return True
