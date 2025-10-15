"""設定、對話與專案相關管理工具。"""

from __future__ import annotations

import hashlib
import json
import logging
import shutil
from dataclasses import asdict
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from .environment import (
    CONFIG_DIR,
    CONFIG_FILE,
    CONVERSATIONS_DIR,
    PROJECT_LIST_FILE,
)
from .models import AIConfig, ConversationMessage, ProjectConversation, ProjectOutput
from .utils import clean_code_header, normalize_code_content, sanitize_json_strings

logger = logging.getLogger(__name__)


class ConfigManager:
    """處理本地端設定檔的讀寫。"""

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
            logger.warning("配置目錄創建失敗,使用默認配置")
            return AIConfig()

        if not CONFIG_FILE.exists():
            logger.info("配置文件不存在,創建默認配置")
            default_config = AIConfig()
            ConfigManager.save(default_config)
            return default_config

        try:
            with open(CONFIG_FILE, "r", encoding="utf-8") as file:
                data = json.load(file)
                return AIConfig(**data)
        except (json.JSONDecodeError, IOError) as exc:
            logger.error("讀取配置文件失敗: %s", exc)
            logger.info("返回默認配置")
            return AIConfig()

    @staticmethod
    def save(config: AIConfig) -> bool:
        try:
            if not ConfigManager.ensure_config_dir():
                raise IOError("無法創建配置目錄")

            with open(CONFIG_FILE, "w", encoding="utf-8") as file:
                json.dump(asdict(config), file, indent=4, ensure_ascii=False)
            logger.info("配置文件已儲存")
            return True
        except IOError as exc:
            logger.error("儲存配置文件失敗: %s", exc)
            return False


class ConversationManager:
    """負責專案對話歷史的存取。"""

    @staticmethod
    def get_conversation_file(project_dir: str) -> Path:
        project_hash = hashlib.md5(project_dir.encode()).hexdigest()
        return CONVERSATIONS_DIR / f"conv_{project_hash}.json"

    @staticmethod
    def load_conversation(project_dir: str) -> ProjectConversation:
        conv_file = ConversationManager.get_conversation_file(project_dir)

        if not conv_file.exists():
            project_name = Path(project_dir).name
            return ProjectConversation(
                project_dir=project_dir,
                project_name=project_name,
                created_at=datetime.now().isoformat(),
                updated_at=datetime.now().isoformat(),
            )

        try:
            with open(conv_file, "r", encoding="utf-8") as file:
                data = json.load(file)

            messages: List[ConversationMessage] = []
            for msg_data in data.get("messages", []):
                usage_metadata = msg_data.get("usage_metadata")
                if not usage_metadata and msg_data.get("metadata"):
                    usage_metadata = msg_data["metadata"].get("usage_metadata")

                messages.append(
                    ConversationMessage(
                        role=msg_data["role"],
                        content=msg_data["content"],
                        timestamp=msg_data["timestamp"],
                        files=msg_data.get("files"),
                        metadata=msg_data.get("metadata"),
                        terminal_output=msg_data.get("terminal_output"),
                        usage_metadata=usage_metadata,
                    )
                )

            return ProjectConversation(
                project_dir=data["project_dir"],
                project_name=data["project_name"],
                messages=messages,
                created_at=data.get("created_at", ""),
                updated_at=data.get("updated_at", ""),
                memory_snapshot=data.get("memory_snapshot", {}),
                evaluation_snapshot=data.get("evaluation_snapshot", {}),
                accumulated_long_term_memory=data.get("accumulated_long_term_memory", []),
            )
        except Exception as exc:
            logger.error("載入對話歷史失敗: %s", exc)
            return ProjectConversation(
                project_dir=project_dir,
                project_name=Path(project_dir).name,
                created_at=datetime.now().isoformat(),
                updated_at=datetime.now().isoformat(),
            )

    @staticmethod
    def save_conversation(conversation: ProjectConversation) -> bool:
        try:
            conv_file = ConversationManager.get_conversation_file(conversation.project_dir)
            conversation.updated_at = datetime.now().isoformat()

            messages_data = []
            for msg in conversation.messages:
                messages_data.append(
                    {
                        "role": msg.role,
                        "content": msg.content,
                        "timestamp": msg.timestamp,
                        "files": msg.files,
                        "metadata": msg.metadata,
                        "terminal_output": msg.terminal_output,
                        "usage_metadata": msg.usage_metadata,
                    }
                )

            data = {
                "project_dir": conversation.project_dir,
                "project_name": conversation.project_name,
                "messages": messages_data,
                "created_at": conversation.created_at,
                "updated_at": conversation.updated_at,
                "memory_snapshot": conversation.memory_snapshot,
                "evaluation_snapshot": conversation.evaluation_snapshot,
                "accumulated_long_term_memory": conversation.accumulated_long_term_memory,
            }

            with open(conv_file, "w", encoding="utf-8") as file:
                json.dump(data, file, indent=2, ensure_ascii=False)

            logger.info("對話歷史已儲存: %s", conversation.project_name)
            return True
        except Exception as exc:
            logger.error("儲存對話歷史失敗: %s", exc)
            return False

    @staticmethod
    def add_message(
        project_dir: str,
        role: str,
        content: str,
        files: Optional[List[Dict]] = None,
        metadata: Optional[Dict] = None,
        terminal_output: Optional[str] = None,
        usage_metadata: Optional[Dict] = None,
    ) -> None:
        conversation = ConversationManager.load_conversation(project_dir)

        message = ConversationMessage(
            role=role,
            content=content,
            timestamp=datetime.now().isoformat(),
            files=files,
            metadata=metadata,
            terminal_output=terminal_output,
            usage_metadata=usage_metadata,
        )

        conversation.messages.append(message)
        ConversationManager.save_conversation(conversation)

        try:
            ProjectManager.update_last_accessed(project_dir, message.timestamp)
        except Exception as exc:
            logger.warning("更新專案最近使用時間失敗: %s", exc)

    @staticmethod
    def update_memory_state(
        project_dir: str,
        memory_snapshot: Optional[Dict],
        evaluation_snapshot: Optional[Dict],
        new_long_term_memory: Optional[List[str]] = None,
    ) -> None:
        conversation = ConversationManager.load_conversation(project_dir)

        if memory_snapshot:
            conversation.memory_snapshot = memory_snapshot

        if evaluation_snapshot:
            conversation.evaluation_snapshot = {
                key: value for key, value in (evaluation_snapshot or {}).items() if value is not None
            }

        if new_long_term_memory:
            existing_memory = conversation.accumulated_long_term_memory or []
            for mem in new_long_term_memory:
                if mem and mem not in existing_memory:
                    existing_memory.append(mem)
            conversation.accumulated_long_term_memory = existing_memory[-50:]
            logger.info("長期記憶已更新，當前總數：%s", len(conversation.accumulated_long_term_memory))

        ConversationManager.save_conversation(conversation)

    @staticmethod
    def delete_conversation_file(project_dir: str) -> bool:
        try:
            conv_file = ConversationManager.get_conversation_file(project_dir)
            if conv_file.exists():
                conv_file.unlink()
                logger.info("已刪除對話檔案: %s", conv_file)
                return True
            return False
        except Exception as exc:
            logger.error("刪除對話檔案失敗: %s", exc)
            return False


class ProjectManager:
    """管理專案檔案與快照。"""

    @staticmethod
    def load_project_info(project_dir: str) -> Optional[Dict[str, Any]]:
        info_file = Path(project_dir) / "PROJECT_INFO.json"
        if not info_file.exists():
            logger.warning("找不到 PROJECT_INFO.json: %s", info_file)
            return None

        try:
            with open(info_file, "r", encoding="utf-8") as file:
                return json.load(file)
        except (json.JSONDecodeError, IOError) as exc:
            logger.error("讀取專案資訊失敗: %s", exc)
            return None

    @staticmethod
    def load_project_files(project_dir: str) -> List[Dict[str, Any]]:
        project_dir_path = Path(project_dir)
        files_data: List[Dict[str, Any]] = []

        exclude = {"PROJECT_INFO.json", "__pycache__", ".git", "node_modules", "venv", ".vscode"}

        for file_path in project_dir_path.rglob("*"):
            if file_path.is_file() and file_path.name not in exclude:
                if any(ex in file_path.parts for ex in exclude):
                    continue

                try:
                    with open(file_path, "r", encoding="utf-8") as file:
                        content = file.read()

                    rel_path = file_path.relative_to(project_dir_path)
                    files_data.append({"name": str(rel_path), "type": "text/plain", "content": content})
                    logger.info("已載入檔案: %s", rel_path)
                except Exception as exc:
                    logger.warning("無法讀取檔案 %s: %s", file_path, exc)

        return files_data

    @staticmethod
    def _infer_filetype(path: Path) -> str:
        mapping = {
            "py": "python",
            "js": "javascript",
            "ts": "typescript",
            "html": "html",
            "css": "css",
            "json": "json",
            "md": "markdown",
            "txt": "text",
        }
        suffix = path.suffix.lower().lstrip(".")
        return mapping.get(suffix, suffix or "text")

    @staticmethod
    def build_file_metadata(project_dir: str) -> List[Dict[str, Any]]:
        project_dir_path = Path(project_dir)
        metadata: List[Dict[str, Any]] = []

        if not project_dir_path.exists():
            return metadata

        exclude = {"PROJECT_INFO.json", "__pycache__", ".git", "node_modules", "venv", ".vscode"}

        for file_path in project_dir_path.rglob("*"):
            if not file_path.is_file():
                continue

            if file_path.name in exclude or any(ex in file_path.parts for ex in exclude):
                continue

            rel_path = file_path.relative_to(project_dir_path)
            metadata.append(
                {
                    "filename": str(rel_path),
                    "filetype": ProjectManager._infer_filetype(file_path),
                    "description": "現有檔案",
                }
            )

        metadata.sort(key=lambda item: item["filename"].lower())
        return metadata

    @staticmethod
    def get_project_structure(project_dir: str) -> str:
        project_dir_path = Path(project_dir)
        structure_lines = [f"專案目錄: {project_dir_path.name}\n"]

        exclude = {"PROJECT_INFO.json", "__pycache__", ".git", "node_modules", "venv", ".vscode"}

        def build_tree(directory: Path, prefix: str = "") -> None:
            contents = sorted(directory.iterdir(), key=lambda x: (x.is_file(), x.name))
            for index, path in enumerate(contents):
                if path.name in exclude:
                    continue

                is_last = index == len(contents) - 1
                current_prefix = "└── " if is_last else "├── "
                structure_lines.append(f"{prefix}{current_prefix}{path.name}")

                if path.is_dir() and path.name not in exclude:
                    next_prefix = prefix + ("    " if is_last else "│   ")
                    build_tree(path, next_prefix)

        if project_dir_path.exists():
            build_tree(project_dir_path)

        return "\n".join(structure_lines)

    @staticmethod
    def _resolve_project_dir(folder_path: str, project_name: str) -> Path:
        base_dir = Path(folder_path)
        sanitized_name = project_name.strip().replace("/", "_").replace("\\", "_")
        if not sanitized_name:
            sanitized_name = "Unnamed_Project"
        project_dir = base_dir / sanitized_name
        project_dir.mkdir(parents=True, exist_ok=True)
        return project_dir

    @staticmethod
    def save_project(folder_path: str, project: ProjectOutput) -> Tuple[List[str], List[str]]:
        project_dir = ProjectManager._resolve_project_dir(folder_path, project.project_name)

        saved_files: List[str] = []
        updated_files: List[str] = []

        for file in project.files:
            file_path = project_dir / file.filename
            file_path.parent.mkdir(parents=True, exist_ok=True)

            try:
                file_exists = file_path.exists()
                code = file.code or ""
                code = normalize_code_content(code)
                filetype = file.filetype or ProjectManager._infer_filetype(file_path)
                code = clean_code_header(code, filetype)

                with open(file_path, "w", encoding="utf-8") as handle:
                    handle.write(code)

                if file_exists:
                    logger.info("已更新檔案: %s", file_path)
                    updated_files.append(str(file_path))
                else:
                    logger.info("已建立檔案: %s", file_path)
                    saved_files.append(str(file_path))

            except IOError as exc:
                logger.error("儲存檔案失敗 %s: %s", file_path, exc)
                raise

        info_file = project_dir / "PROJECT_INFO.json"
        project_info_data = {
            "project_name": project.project_name,
            "description": project.description,
            "main_file": project.main_file,
            "setup_instructions": project.setup_instructions,
            "run_instructions": project.run_instructions,
            "files": [asdict(file) for file in project.files],
        }

        cleaned_data = sanitize_json_strings(project_info_data)

        with open(info_file, "w", encoding="utf-8") as handle:
            json.dump(cleaned_data, handle, indent=2, ensure_ascii=False)

        if str(info_file) not in saved_files and str(info_file) not in updated_files:
            saved_files.append(str(info_file))

        return saved_files, updated_files

    @staticmethod
    def copy_project_to(project_dir: str, target_dir: str) -> bool:
        try:
            shutil.copytree(project_dir, target_dir, dirs_exist_ok=True)
            logger.info("專案已複製到: %s", target_dir)
            return True
        except Exception as exc:
            logger.error("複製專案失敗: %s", exc)
            return False

    @staticmethod
    def add_to_project_list(
        project_dir: str,
        project_name: str,
        description: str = "",
        status: str = "ready",
        update_last_accessed: bool = True,
    ) -> bool:
        try:
            normalized_dir = str(Path(project_dir))
            project_list = ProjectManager.get_project_list()

            existing = next((p for p in project_list if p["path"] == normalized_dir), None)

            if existing:
                existing["name"] = project_name
                existing["description"] = description
                if update_last_accessed:
                    existing["last_accessed"] = datetime.now().isoformat()
                if status:
                    existing["status"] = status
            else:
                timestamp = datetime.now().isoformat()
                entry = {
                    "path": normalized_dir,
                    "name": project_name,
                    "description": description,
                    "created_at": timestamp,
                    "last_accessed": timestamp,
                }
                if status:
                    entry["status"] = status
                project_list.append(entry)

            with open(PROJECT_LIST_FILE, "w", encoding="utf-8") as file:
                json.dump(project_list, file, indent=2, ensure_ascii=False)

            logger.info("已添加/更新專案到列表: %s (%s)", project_name, normalized_dir)
            return True
        except Exception as exc:
            logger.error("添加專案到列表失敗: %s", exc)
            return False

    @staticmethod
    def ensure_placeholder_project(project_dir: str, project_name: Optional[str] = None, description: str = "") -> bool:
        try:
            normalized_dir = str(Path(project_dir))
            display_name = project_name or Path(normalized_dir).name or "建立中專案"
            placeholder_desc = description or "專案建立中，等待 AI 回應"

            project_list = ProjectManager.get_project_list()
            existing = next((p for p in project_list if p["path"] == normalized_dir), None)

            timestamp = datetime.now().isoformat()

            if existing:
                existing["name"] = display_name
                existing["description"] = placeholder_desc
                existing["last_accessed"] = timestamp
                existing["status"] = "pending"
            else:
                project_list.append(
                    {
                        "path": normalized_dir,
                        "name": display_name,
                        "description": placeholder_desc,
                        "created_at": timestamp,
                        "last_accessed": timestamp,
                        "status": "pending",
                    }
                )

            with open(PROJECT_LIST_FILE, "w", encoding="utf-8") as file:
                json.dump(project_list, file, indent=2, ensure_ascii=False)

            logger.info("已建立專案佔位: %s (%s)", display_name, normalized_dir)
            return True
        except Exception as exc:
            logger.error("建立專案佔位失敗: %s", exc)
            return False

    @staticmethod
    def get_project_list() -> List[Dict[str, Any]]:
        if not PROJECT_LIST_FILE.exists():
            return []

        try:
            with open(PROJECT_LIST_FILE, "r", encoding="utf-8") as file:
                return json.load(file)
        except Exception as exc:
            logger.error("讀取專案列表失敗: %s", exc)
            return []

    @staticmethod
    def remove_from_project_list(project_dir: str) -> bool:
        try:
            normalized_dir = str(Path(project_dir))
            project_list = ProjectManager.get_project_list()
            project_list = [p for p in project_list if p["path"] != normalized_dir]

            with open(PROJECT_LIST_FILE, "w", encoding="utf-8") as file:
                json.dump(project_list, file, indent=2, ensure_ascii=False)

            logger.info("已從列表移除專案: %s", normalized_dir)
            return True
        except Exception as exc:
            logger.error("移除專案失敗: %s", exc)
            return False

    @staticmethod
    def update_last_accessed(project_dir: str, timestamp: Optional[str] = None) -> bool:
        project_list = ProjectManager.get_project_list()
        normalized_dir = str(Path(project_dir))
        existing = next((p for p in project_list if p["path"] == normalized_dir), None)

        if not existing:
            return False

        existing["last_accessed"] = timestamp or datetime.now().isoformat()

        try:
            with open(PROJECT_LIST_FILE, "w", encoding="utf-8") as file:
                json.dump(project_list, file, indent=2, ensure_ascii=False)
            return True
        except Exception as exc:
            logger.error("更新專案最近使用時間失敗: %s", exc)
            return False


__all__ = ["ConfigManager", "ConversationManager", "ProjectManager"]
