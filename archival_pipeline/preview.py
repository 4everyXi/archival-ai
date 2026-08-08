"""预览生成 — 变更清单必须先给用户看

需求映射:
- [四不原则] 不跳过预览：json（AI 读）/ txt（人看）双格式
- [统计正确] 基于最终状态：total=文件数，changed=原路径≠最终路径的文件数
- 为什么这样好: 档案化不可逆，预览确认是用户最终裁判权的落点
"""
import json
import datetime
import shutil
from pathlib import Path
from archival_pipeline.models import PipelineResult

_formatters: dict[str, type] = {}
_PREVIEW_LIMIT = 5  # 同级目录最多保留预览文件数


def register_format(name: str, formatter_cls: type):
    _formatters[name] = formatter_cls


def render(name: str, result: PipelineResult) -> str:
    """按格式名（json/txt）渲染预览结果——格式注册表分发"""
    cls = _formatters.get(name)
    if not cls:
        raise ValueError(f"Unknown format: {name}")
    return cls().render(result)


def manage_preview_files(target_dir: Path):
    """预览文件管理：超过 5 个时移入 previews/ 子目录"""
    preview_files = sorted([
        p for p in target_dir.iterdir()
        if p.is_file() and p.name.startswith("preview_")
    ])
    if len(preview_files) <= _PREVIEW_LIMIT:
        return
    previews_dir = target_dir / "previews"
    previews_dir.mkdir(exist_ok=True)
    for pf in preview_files:
        dest = previews_dir / pf.name
        if not dest.exists():
            shutil.move(str(pf), str(dest))


class JsonFormatter:
    """JSON 格式预览——机器可读（AI 后续处理用）"""

    format_name = "json"

    def render(self, result: PipelineResult) -> str:
        """渲染为 JSON：原始路径/新路径对照 + 统计 + 步骤清单"""
        data = {
            "file_renames": {
                "original_paths": [str(op.source) for op in result.final_operations],
                "new_paths": [str(op.destination) for op in result.final_operations],
            },
            "statistics": result.statistics,
            "steps": [s.step_name for s in result.steps],
            "timestamp": datetime.datetime.now().isoformat(),
        }
        return json.dumps(data, ensure_ascii=False, indent=2)


class TextFormatter:
    """TXT 格式预览——人类可读，只显示文件名对照，不显示完整路径"""

    format_name = "txt"

    def render(self, result: PipelineResult) -> str:
        """渲染为 TXT：文件对照清单（只显示文件名）+ 统计"""
        lines = []
        stats = result.statistics
        total = stats.get("total", 0)
        changed = stats.get("changed", 0)

        lines.append(f"共 {total} 个文件，{changed} 个变更\n")

        if not result.final_operations:
            lines.append("（无变更）\n")
            return "".join(lines)

        for op in result.final_operations:
            src = op.source.name
            dst = op.destination.name
            if src == dst:
                lines.append(f"  {src}  ->  {dst}\n")
            else:
                lines.append(f"  {src}\n")
                lines.append(f"  -> {dst}\n")

        return "".join(lines)


register_format("json", JsonFormatter)
register_format("txt", TextFormatter)
