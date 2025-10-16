"""核心設定與共用資源。"""
from __future__ import annotations

import logging
from pathlib import Path

# ================================
# 日誌設定
# ================================
logging.basicConfig(
    level=logging.INFO,
    format='[%(asctime)s] %(levelname)s: %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)

logger = logging.getLogger("ai_controller")

# ================================
# 路徑常數
# ================================
HOST = '127.0.0.1'
PORT = 5001

CONFIG_DIR = Path.home() / '.ai_controller_v5'
CONFIG_FILE = CONFIG_DIR / 'config.json'
SCREENSHOT_DIR = CONFIG_DIR / 'screenshots'
LOG_DIR = CONFIG_DIR / 'logs'
PROJECTS_DIR = CONFIG_DIR / 'projects'
CONVERSATIONS_DIR = CONFIG_DIR / 'conversations'
PROJECT_LIST_FILE = CONFIG_DIR / 'project_list.json'
ERROR_REPORTS_DIR = CONFIG_DIR / 'error_reports'

_DIRECTORIES = [
    CONFIG_DIR,
    SCREENSHOT_DIR,
    LOG_DIR,
    PROJECTS_DIR,
    CONVERSATIONS_DIR,
    ERROR_REPORTS_DIR,
]


def ensure_directories() -> None:
    """確保所有必要目錄存在。"""
    for directory in _DIRECTORIES:
        try:
            directory.mkdir(parents=True, exist_ok=True)
            logger.info("目錄已準備: %s", directory)
        except Exception as exc:  # pragma: no cover - 防禦性處理
            logger.error("無法創建目錄 %s: %s", directory, exc)
            raise RuntimeError(f"無法創建必要的目錄: {directory}") from exc


# 初始化目錄
ensure_directories()

__all__ = [
    'logger',
    'HOST',
    'PORT',
    'CONFIG_DIR',
    'CONFIG_FILE',
    'SCREENSHOT_DIR',
    'LOG_DIR',
    'PROJECTS_DIR',
    'CONVERSATIONS_DIR',
    'PROJECT_LIST_FILE',
    'ERROR_REPORTS_DIR',
    'ensure_directories',
]
