"""预览生成 — 变更清单必须先给用户看

需求映射:
- [四不原则] 不跳过预览：json（AI 读）/ txt（人看）双格式
- [统计正确] 基于最终状态：total=文件数，changed=原路径≠最终路径的文件数
- 为什么这样好: 档案化不可逆，预览确认是用户最终裁判权的落点
"""
import json
import datetime
from pathlib import Path
from archival_pipeline.models import PipelineResult

_formatters: dict[str, type] = {}


def register_format(name: str, formatter_cls: type):
    _formatters[name] = formatter_cls


def render(name: str, result: PipelineResult) -> str:
    """按格式名（json/txt）渲染预览结果——格式注册表分发"""
    cls = _formatters.get(name)
    if not cls:
        raise ValueError(f"Unknown format: {name}")
    return cls().render(result)



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
        """渲染为 TXT：全量文件对照（变更 + 无变化清单）+ 统计

        人类预览必须每个文件都有交代——无变化本身是信息（已符合需求/无需处理，
        而非被漏掉）。分组：变更显示源→目标对照，无变化显示清单。
        """
        lines = []
        stats = result.statistics
        total = stats.get("total", 0)
        changed = stats.get("changed", 0)
        skipped = stats.get("skipped", 0)

        lines.append(f"共 {total} 个文件，{changed} 个变更，{skipped} 个无变化\n")

        if not result.final_operations:
            lines.append("（无文件）\n")
            return "".join(lines)

        # 相对被执行目录的完整路径（保留全部层级：日期继承来源/档位/目录结构），
        # 去掉重复的盘符+根前缀——人类判断需求只需看 target 内部的相对结构
        def _rel(p: Path) -> str:
            try:
                return str(p.relative_to(result.target_dir))
            except ValueError:
                return str(p)  # 目标目录外（防御）

        changed_ops = [op for op in result.final_operations if op.source != op.destination]
        unchanged = [op.source for op in result.final_operations if op.source == op.destination]

        if changed_ops:
            lines.append(f"\n[{changed} 个变更]\n")
            for op in changed_ops:
                lines.append(f"  {_rel(op.source)}\n")
                lines.append(f"  -> {_rel(op.destination)}\n")

        if unchanged:
            lines.append(f"\n[{skipped} 个无变化]（已确认无需处理，非漏掉）\n")
            for p in unchanged:
                lines.append(f"  {_rel(p)}\n")

        return "".join(lines)


class CleanTextFormatter:
    """纯净版 TXT 预览——只显示修改后的文件名（含相对路径），无源→目标对照

    用途: 用户直接看"最终会变成什么样"——不带对照噪音，方便扫读/复制最终名。
    """

    format_name = "txt-clean"

    def render(self, result: PipelineResult) -> str:
        """渲染为 TXT 纯净版：仅修改后文件名清单 + 统计"""
        lines = []
        stats = result.statistics
        total = stats.get("total", 0)
        changed = stats.get("changed", 0)
        skipped = stats.get("skipped", 0)

        lines.append(f"共 {total} 个文件，{changed} 个变更，{skipped} 个无变化\n")
        lines.append(f"\n[{changed} 个变更后文件名]（纯净版：仅修改后文件，含相对路径）\n")

        if not result.final_operations:
            lines.append("（无文件）\n")
            return "".join(lines)

        def _rel(p: Path) -> str:
            try:
                return str(p.relative_to(result.target_dir))
            except ValueError:
                return str(p)  # 目标目录外（防御）

        for op in result.final_operations:
            if op.source != op.destination:
                lines.append(f"  {_rel(op.destination)}\n")

        return "".join(lines)


register_format("json", JsonFormatter)
register_format("txt", TextFormatter)
register_format("txt-clean", CleanTextFormatter)
