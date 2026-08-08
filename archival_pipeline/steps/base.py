"""PipelineStep 抽象基类 — 每步三分离协议

需求映射:
- [模块化] preview（只读生成预览）/ execute（执行改 records）/ rollback（接收快照回滚）
- 为什么这样好: preview 与 execute 分离保证预览零副作用（幂等）；rollback 接收快照
  而非 ctx，因为回滚时 ctx 已被后续步骤改变——这是安全网可靠性的关键
"""
from abc import ABC, abstractmethod
from archival_pipeline.models import (
    PipelineContext, StepPreview, StepResult, BackupData,
)


class PipelineStep(ABC):
    """每个管线步骤实现此抽象类"""
    name: str = ""
    description: str = ""

    @abstractmethod
    def preview(self, ctx: PipelineContext) -> StepPreview:
        """生成当前步骤的预览（只读）"""

    @abstractmethod
    def execute(self, ctx: PipelineContext) -> StepResult:
        """执行当前步骤，修改 ctx.records"""

    @abstractmethod
    def rollback(self, backup_data: BackupData) -> bool:
        """回滚当前步骤，接收备份数据"""
