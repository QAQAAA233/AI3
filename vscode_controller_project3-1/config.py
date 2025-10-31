"""核心設定與目錄管理模組"""

from __future__ import annotations

import json
import logging
from dataclasses import asdict
from pathlib import Path

# 全域日誌設定
logging.basicConfig(
    level=logging.INFO,
    format='[%(asctime)s] %(levelname)s: %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)

logger = logging.getLogger('ai_controller')

# 伺服器設定
HOST = '127.0.0.1'
PORT = 5001

# 應用程式目錄
CONFIG_DIR = Path.home() / '.ai_controller_v5'
CONFIG_FILE = CONFIG_DIR / 'config.json'
SCREENSHOT_DIR = CONFIG_DIR / 'screenshots'
LOG_DIR = CONFIG_DIR / 'logs'
PROJECTS_DIR = CONFIG_DIR / 'projects'
CONVERSATIONS_DIR = CONFIG_DIR / 'conversations'
PROJECT_LIST_FILE = CONFIG_DIR / 'project_list.json'
ERROR_REPORTS_DIR = CONFIG_DIR / 'error_reports'


def ensure_directories() -> None:
    """確保所有必要的目錄存在"""
    for directory in [
        CONFIG_DIR,
        SCREENSHOT_DIR,
        LOG_DIR,
        PROJECTS_DIR,
        CONVERSATIONS_DIR,
        ERROR_REPORTS_DIR,
    ]:
        directory.mkdir(parents=True, exist_ok=True)
        logger.info("目錄已準備: %s", directory)


try:
    ensure_directories()
except Exception as exc:  # pragma: no cover - 無法建立目錄屬嚴重錯誤
    logger.critical("初始化失敗: %s", exc)
    raise


from models import AIConfig  # 延遲匯入以避免循環依賴


class ConfigManager:
    """應用程式設定檔案管理器"""

    @staticmethod
    def ensure_config_dir() -> bool:
        try:
            CONFIG_DIR.mkdir(parents=True, exist_ok=True)
            return True
        except Exception as exc:
            logger.error("無法創建配置目錄 %s: %s", CONFIG_DIR, exc)
            return False

    @staticmethod
    def load() -> AIConfig:
        if not ConfigManager.ensure_config_dir():
            logger.warning("配置目錄創建失敗, 使用預設設定")
            return AIConfig()

        if not CONFIG_FILE.exists():
            logger.info("配置檔不存在, 建立預設設定")
            default_config = AIConfig()
            ConfigManager.save(default_config)
            return default_config

        try:
            with open(CONFIG_FILE, 'r', encoding='utf-8') as handle:
                data = json.load(handle)
                return AIConfig(**data)
        except (json.JSONDecodeError, OSError) as exc:
            logger.error("讀取配置檔失敗: %s", exc)
            logger.info("回退使用預設設定")
            return AIConfig()

    @staticmethod
    def save(config: AIConfig) -> bool:
        try:
            if not ConfigManager.ensure_config_dir():
                raise OSError("無法創建配置目錄")

            with open(CONFIG_FILE, 'w', encoding='utf-8') as handle:
                json.dump(asdict(config), handle, indent=4, ensure_ascii=False)
            logger.info("配置檔已儲存")
            return True
        except OSError as exc:
            logger.error("儲存配置檔失敗: %s", exc)
            return False


__all__ = [
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
    'ConfigManager',
    'logger',
]
