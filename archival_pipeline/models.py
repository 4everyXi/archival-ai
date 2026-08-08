"""数据模型 — 贯穿管线的文件记录与结果类型

需求映射:
- [链式预览] FileRecord.original_path 不变 + current_path 每步更新，支撑多步骤链式传递
- [执行层安全] StepResult.backup_data 携带每步备份，rollback 接收 BackupData 快照而非 ctx
- 为什么这样好: 回滚时 ctx 已被后续步骤改变，快照才是真相（v2 架构设计的关键决策）
"""
from dataclasses import dataclass, field
from pathlib import Path
from typing import TypedDict, NotRequired


class FileMetadata(TypedDict, total=False):
    """文件元数据，TypedDict 约束 key"""
    extracted_date: str
    parent_context: str
    platform_ids: list[str]
    warnings: list[str]


@dataclass
class FileRecord:
    """贯穿整个管线的文件记录"""
    original_path: Path
    current_path: Path
    metadata: FileMetadata = field(default_factory=dict)


@dataclass
class PipelineContext:
    """管线上下文，所有步骤共享"""
    target_dir: Path
    config: dict = field(default_factory=dict)
    step_configs: dict[str, dict] = field(default_factory=dict)
    dry_run: bool = True
    records: list[FileRecord] = field(default_factory=list)
    step_results: dict[str, "StepResult"] = field(default_factory=dict)


@dataclass
class RenameOperation:
    """一次重命名操作"""
    source: Path
    destination: Path


@dataclass
class StepPreview:
    """单个步骤的预览结果"""
    step_name: str
    operations: list[RenameOperation] = field(default_factory=list)
    statistics: dict = field(default_factory=lambda: {
        "total": 0, "changed": 0, "skipped": 0, "errors": 0
    })


@dataclass
class StepResult:
    """单个步骤的执行结果"""
    step_name: str
    success: bool = True
    backup_data: list[dict] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)


@dataclass
class BackupData:
    """回滚用的备份数据"""
    step_name: str
    timestamp: str = ""
    operations: list[dict] = field(default_factory=list)


@dataclass
class PipelineResult:
    """完整管线的执行结果"""
    steps: list[StepResult] = field(default_factory=list)
    final_operations: list[RenameOperation] = field(default_factory=list)
    statistics: dict = field(default_factory=dict)
    target_dir: Path | None = None
