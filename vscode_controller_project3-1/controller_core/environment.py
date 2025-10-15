"""環境與路徑相關的共用設定。"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Iterable

logger = logging.getLogger(__name__)

CONFIG_DIR = Path.home() / ".ai_controller_v5"
CONFIG_FILE = CONFIG_DIR / "config.json"
SCREENSHOT_DIR = CONFIG_DIR / "screenshots"
LOG_DIR = CONFIG_DIR / "logs"
PROJECTS_DIR = CONFIG_DIR / "projects"
CONVERSATIONS_DIR = CONFIG_DIR / "conversations"
PROJECT_LIST_FILE = CONFIG_DIR / "project_list.json"
ERROR_REPORTS_DIR = CONFIG_DIR / "error_reports"


def iter_required_directories() -> Iterable[Path]:
    """回傳應存在的必要目錄列表。"""
    return (
        CONFIG_DIR,
        SCREENSHOT_DIR,
        LOG_DIR,
        PROJECTS_DIR,
        CONVERSATIONS_DIR,
        ERROR_REPORTS_DIR,
    )


def ensure_directories() -> None:
    """確保所有必要的目錄均已建立。"""
    for directory in iter_required_directories():
        try:
            directory.mkdir(parents=True, exist_ok=True)
            logger.info("目錄已準備: %s", directory)
        except Exception as exc:  # pragma: no cover - 防止啟動時靜默失敗
            logger.error("無法創建目錄 %s: %s", directory, exc)
            raise RuntimeError(f"無法創建必要的目錄: {directory}") from exc
