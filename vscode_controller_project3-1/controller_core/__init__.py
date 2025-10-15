"""AI 自動化開發控制器共用核心。"""

from .environment import (
    CONFIG_DIR,
    CONFIG_FILE,
    SCREENSHOT_DIR,
    LOG_DIR,
    PROJECTS_DIR,
    CONVERSATIONS_DIR,
    PROJECT_LIST_FILE,
    ERROR_REPORTS_DIR,
    ensure_directories,
)

from . import models, utils, managers, diagnostics, services

__all__ = [
    "CONFIG_DIR",
    "CONFIG_FILE",
    "SCREENSHOT_DIR",
    "LOG_DIR",
    "PROJECTS_DIR",
    "CONVERSATIONS_DIR",
    "PROJECT_LIST_FILE",
    "ERROR_REPORTS_DIR",
    "ensure_directories",
    "models",
    "utils",
    "managers",
    "diagnostics",
    "services",
]
