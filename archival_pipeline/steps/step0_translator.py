"""Step 0: 翻译（快速模式专用）——常用词缓存替换

仅作为快速模式的缓存引擎：用已确认译名（DEFAULT_TRANSLATIONS）做机械替换。
精品模式（默认）的翻译由 AI 完成，不经过本步骤。

映射表定位：已确认译名缓存，不是翻译引擎。AI 永远是最终裁判。
"""

from pathlib import Path

from archival_pipeline.models import (
    PipelineContext, StepPreview, StepResult, BackupData, RenameOperation,
)
from archival_pipeline.steps.base import PipelineStep
from archival_pipeline.translator.cache import DEFAULT_TRANSLATIONS

# 按长度降序预排序一次（长词优先匹配防截断），避免每次调用重复排序
_SORTED = sorted(DEFAULT_TRANSLATIONS, key=lambda x: -len(x[0]))


def translate_by_cache(name: str, mappings: list[tuple[str, str]] | None = None) -> str | None:
    """常用词缓存替换：只替换已知词，不猜未知词。返回 None 表示无变化。"""
    stem = Path(name).stem
    ext = Path(name).suffix
    result = stem
    for jp, cn in (mappings or _SORTED):
        if jp in result:
            result = result.replace(jp, cn)
    return result + ext if result != stem else None


class Step0Translator(PipelineStep):
    """翻译（快速模式）：常用词缓存替换"""

    name = "translator"
    description = "翻译（快速模式）：常用词缓存替换"

    def preview(self, ctx: PipelineContext) -> StepPreview:
        mappings = ctx.step_configs.get(self.name, {}).get("mappings")
        ops = []
        changed = 0
        for rec in ctx.records:
            new_name = translate_by_cache(rec.current_path.name, mappings)
            if new_name and new_name != rec.current_path.name:
                ops.append(RenameOperation(
                    rec.current_path, rec.current_path.with_name(new_name)))
                changed += 1
        return StepPreview(
            step_name=self.name, operations=ops,
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
            step_name=self.name, success=len(errors) == 0,
            backup_data=backup, errors=errors,
        )

    def rollback(self, backup_data: BackupData) -> bool:
        for item in reversed(backup_data.operations):
            src = Path(item["new"])
            dst = Path(item["original"])
            if src.exists():
                src.rename(dst)
        return True
