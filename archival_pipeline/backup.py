"""备份/回滚 — 安全网核心

需求映射:
- [范式] 安全放执行层：操作前 JSON 备份，rollback_all 统一回滚
- [四不原则] 不覆盖备份：每次操作独立备份文件
- 为什么这样好: 备份是 AI 自由决策的兜底——AI 判断错了可一键恢复，无需用规则限制 AI
"""
import json
import datetime
import logging
from pathlib import Path
from archival_pipeline.models import BackupData

logger = logging.getLogger("ArchivalBackup")


def save_backup(backup_data: list[dict], filepath: str | Path,
                step_name: str = "") -> Path:
    data = {
        "step_name": step_name,
        "timestamp": datetime.datetime.now().isoformat(),
        "operations": backup_data,
    }
    fp = Path(filepath)
    fp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    return fp


def load_backup(filepath: str | Path) -> BackupData:
    data = json.loads(Path(filepath).read_text(encoding="utf-8"))
    return BackupData(
        step_name=data.get("step_name", ""),
        timestamp=data.get("timestamp", ""),
        operations=data.get("operations", []),
    )


def rollback_all(backup_files: list[str | Path]) -> bool:
    """回滚所有备份文件（逆序：后执行的先回滚，恢复执行前状态）

    返回 True 仅当全部回滚成功；部分失败时返回 False 并记 logger，
    供上游据此报告"回滚不完整"而非静默吞掉失败。
    """
    success = True
    failed = []  # 逐个失败项，供上游报明细
    for bf in reversed(backup_files):
        try:
            data = load_backup(bf)
            for item in reversed(data.operations):
                src = Path(item["new"])
                dst = Path(item["original"])
                if src.exists():
                    src.rename(dst)
        except Exception as e:
            logger.error("回滚失败: %s: %s", bf, e)
            failed.append(str(bf))
            success = False
    if failed:
        logger.error("回滚不完整：%d 个备份失败：%s", len(failed), ", ".join(failed))
    return success
