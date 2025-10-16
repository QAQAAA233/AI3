"""資料與配置管理模組。"""
from __future__ import annotations

import hashlib
import json
import shutil
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from . import (
    CONFIG_DIR,
    CONFIG_FILE,
    CONVERSATIONS_DIR,
    PROJECTS_DIR,
    PROJECT_LIST_FILE,
    SCREENSHOT_DIR,
    logger,
)
from .models import (
    AIConfig,
    ConversationMessage,
    FileOutput,
    ProjectConversation,
    ProjectOutput,
    asdict,
)


class ConfigManager:
    """配置文件管理器"""

    @staticmethod
    def ensure_config_dir() -> bool:
        try:
            CONFIG_DIR.mkdir(parents=True, exist_ok=True)
            return True
        except Exception as exc:  # pragma: no cover - 防禦性處理
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
            with open(CONFIG_FILE, 'r', encoding='utf-8') as file:
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

            with open(CONFIG_FILE, 'w', encoding='utf-8') as file:
                json.dump(asdict(config), file, indent=4, ensure_ascii=False)
            logger.info("配置文件已儲存")
            return True
        except IOError as exc:  # pragma: no cover - 防禦性處理
            logger.error("儲存配置文件失敗: %s", exc)
            return False


class ConversationManager:
    """對話歷史管理器（優化版）"""

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
            with open(conv_file, 'r', encoding='utf-8') as file:
                data = json.load(file)
                messages: List[ConversationMessage] = []
                for msg_data in data.get('messages', []):
                    usage_metadata = msg_data.get('usage_metadata')
                    if not usage_metadata and msg_data.get('metadata'):
                        usage_metadata = msg_data['metadata'].get('usage_metadata')

                    messages.append(
                        ConversationMessage(
                            role=msg_data['role'],
                            content=msg_data['content'],
                            timestamp=msg_data['timestamp'],
                            files=msg_data.get('files'),
                            metadata=msg_data.get('metadata'),
                            terminal_output=msg_data.get('terminal_output'),
                            usage_metadata=usage_metadata,
                        )
                    )

                return ProjectConversation(
                    project_dir=data['project_dir'],
                    project_name=data['project_name'],
                    messages=messages,
                    created_at=data.get('created_at', ''),
                    updated_at=data.get('updated_at', ''),
                    memory_snapshot=data.get('memory_snapshot', {}),
                    evaluation_snapshot=data.get('evaluation_snapshot', {}),
                    accumulated_long_term_memory=data.get('accumulated_long_term_memory', []),
                )
        except Exception as exc:  # pragma: no cover - 防禦性處理
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

            messages_data: List[Dict[str, Any]] = []
            for msg in conversation.messages:
                messages_data.append(
                    {
                        'role': msg.role,
                        'content': msg.content,
                        'timestamp': msg.timestamp,
                        'files': msg.files,
                        'metadata': msg.metadata,
                        'terminal_output': msg.terminal_output,
                        'usage_metadata': msg.usage_metadata,
                    }
                )

            data = {
                'project_dir': conversation.project_dir,
                'project_name': conversation.project_name,
                'messages': messages_data,
                'created_at': conversation.created_at,
                'updated_at': conversation.updated_at,
                'memory_snapshot': conversation.memory_snapshot,
                'evaluation_snapshot': conversation.evaluation_snapshot,
                'accumulated_long_term_memory': conversation.accumulated_long_term_memory,
            }

            with open(conv_file, 'w', encoding='utf-8') as file:
                json.dump(data, file, indent=2, ensure_ascii=False)

            logger.info("對話歷史已儲存: %s", conversation.project_name)
            return True
        except Exception as exc:  # pragma: no cover - 防禦性處理
            logger.error("儲存對話歷史失敗: %s", exc)
            return False

    @staticmethod
    def add_message(
        project_dir: str,
        role: str,
        content: str,
        files: Optional[List[Dict[str, Any]]] = None,
        terminal_output: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
        usage_metadata: Optional[Dict[str, Any]] = None,
    ) -> None:
        conversation = ConversationManager.load_conversation(project_dir)
        conversation.messages.append(
            ConversationMessage(
                role=role,
                content=content,
                timestamp=datetime.now().isoformat(),
                files=files,
                metadata=metadata,
                terminal_output=terminal_output,
                usage_metadata=usage_metadata,
            )
        )
        ConversationManager.save_conversation(conversation)

    @staticmethod
    def update_memory(
        project_dir: str,
        memory_snapshot: Dict[str, Any],
        evaluation_snapshot: Dict[str, Any],
        accumulated_long_term_memory: Optional[List[str]] = None,
    ) -> None:
        conversation = ConversationManager.load_conversation(project_dir)
        conversation.memory_snapshot = memory_snapshot
        conversation.evaluation_snapshot = evaluation_snapshot
        if accumulated_long_term_memory is not None:
            conversation.accumulated_long_term_memory = accumulated_long_term_memory
        ConversationManager.save_conversation(conversation)


class ProjectManager:
    """專案管理器"""

    @staticmethod
    def load_project_info(project_dir: str) -> Optional[Dict[str, Any]]:
        info_file = Path(project_dir) / "PROJECT_INFO.json"
        if not info_file.exists():
            logger.warning("找不到 PROJECT_INFO.json: %s", info_file)
            return None

        try:
            with open(info_file, 'r', encoding='utf-8') as file:
                return json.load(file)
        except (json.JSONDecodeError, IOError) as exc:
            logger.error("讀取專案資訊失敗: %s", exc)
            return None

    @staticmethod
    def load_project_files(project_dir: str) -> List[Dict[str, Any]]:
        project_dir_path = Path(project_dir)
        files_data: List[Dict[str, Any]] = []

        exclude = {'PROJECT_INFO.json', '__pycache__', '.git', 'node_modules', 'venv', '.vscode'}

        for file_path in project_dir_path.rglob('*'):
            if file_path.is_file() and file_path.name not in exclude:
                if any(ex in file_path.parts for ex in exclude):
                    continue

                try:
                    with open(file_path, 'r', encoding='utf-8') as file:
                        content = file.read()

                    rel_path = file_path.relative_to(project_dir_path)
                    files_data.append(
                        {
                            'name': str(rel_path),
                            'type': 'text/plain',
                            'content': content,
                        }
                    )
                    logger.info("已載入檔案: %s", rel_path)
                except Exception as exc:  # pragma: no cover - 防禦性處理
                    logger.warning("無法讀取檔案 %s: %s", file_path, exc)

        return files_data

    @staticmethod
    def _infer_filetype(path: Path) -> str:
        mapping = {
            'py': 'python',
            'js': 'javascript',
            'ts': 'typescript',
            'html': 'html',
            'css': 'css',
            'json': 'json',
            'md': 'markdown',
            'txt': 'text',
        }
        suffix = path.suffix.lower().lstrip('.')
        return mapping.get(suffix, suffix or 'text')

    @staticmethod
    def build_file_metadata(project_dir: str) -> List[Dict[str, Any]]:
        project_dir_path = Path(project_dir)
        metadata: List[Dict[str, Any]] = []

        if not project_dir_path.exists():
            return metadata

        exclude = {'PROJECT_INFO.json', '__pycache__', '.git', 'node_modules', 'venv', '.vscode'}

        for file_path in project_dir_path.rglob('*'):
            if not file_path.is_file():
                continue

            if file_path.name in exclude or any(ex in file_path.parts for ex in exclude):
                continue

            rel_path = file_path.relative_to(project_dir_path)
            metadata.append(
                {
                    'filename': str(rel_path),
                    'filetype': ProjectManager._infer_filetype(file_path),
                    'description': '現有檔案',
                }
            )

        metadata.sort(key=lambda item: item['filename'].lower())
        return metadata

    @staticmethod
    def get_project_structure(project_dir: str) -> str:
        project_dir_path = Path(project_dir)
        structure_lines = [f"專案目錄: {project_dir_path.name}\n"]

        exclude = {'PROJECT_INFO.json', '__pycache__', '.git', 'node_modules', 'venv', '.vscode'}

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

        build_tree(project_dir_path)
        return "\n".join(structure_lines)

    @staticmethod
    def add_to_project_list(
        project_dir: str,
        project_name: str,
        description: str = "",
        status: str = 'ready',
        update_last_accessed: bool = True,
    ) -> None:
        try:
            normalized_dir = str(Path(project_dir))
            project_list = ProjectManager.get_project_list()

            existing = next((item for item in project_list if item['path'] == normalized_dir), None)
            timestamp = datetime.now().isoformat()

            if existing:
                existing.update({
                    'name': project_name,
                    'description': description,
                    'status': status,
                })
                if update_last_accessed:
                    existing['last_accessed'] = timestamp
            else:
                project_list.append(
                    {
                        'path': normalized_dir,
                        'name': project_name,
                        'description': description,
                        'status': status,
                        'created_at': timestamp,
                        'last_accessed': timestamp,
                    }
                )

            PROJECT_LIST_FILE.parent.mkdir(parents=True, exist_ok=True)
            with open(PROJECT_LIST_FILE, 'w', encoding='utf-8') as file:
                json.dump(project_list, file, indent=2, ensure_ascii=False)
        except Exception as exc:  # pragma: no cover - 防禦性處理
            logger.error("更新專案列表失敗: %s", exc)

    @staticmethod
    def get_project_list() -> List[Dict[str, Any]]:
        if not PROJECT_LIST_FILE.exists():
            return []

        try:
            with open(PROJECT_LIST_FILE, 'r', encoding='utf-8') as file:
                return json.load(file)
        except Exception as exc:  # pragma: no cover - 防禦性處理
            logger.error("讀取專案列表失敗: %s", exc)
            return []

    @staticmethod
    def remove_from_project_list(project_dir: str) -> bool:
        try:
            normalized_dir = str(Path(project_dir))
            projects = ProjectManager.get_project_list()
            new_projects = [proj for proj in projects if proj.get('path') != normalized_dir]

            with open(PROJECT_LIST_FILE, 'w', encoding='utf-8') as file:
                json.dump(new_projects, file, indent=2, ensure_ascii=False)

            return len(projects) != len(new_projects)
        except Exception as exc:  # pragma: no cover - 防禦性處理
            logger.error("刪除專案失敗: %s", exc)
            return False

    @staticmethod
    def ensure_placeholder_project(project_dir: str, project_name: str) -> None:
        ProjectManager.add_to_project_list(project_dir, project_name, status='building')
        placeholder_info = {
            'project_name': project_name,
            'description': '專案建立中...',
            'files': [],
            'main_file': None,
            'setup_instructions': [],
            'run_instructions': [],
        }

        info_file = Path(project_dir) / "PROJECT_INFO.json"
        info_file.parent.mkdir(parents=True, exist_ok=True)
        with open(info_file, 'w', encoding='utf-8') as file:
            json.dump(placeholder_info, file, indent=2, ensure_ascii=False)

    @staticmethod
    def save_project_info(project_dir: str, project: ProjectOutput, is_iteration: bool = False) -> None:
        if not is_iteration:
            project_dir_path = Path(project_dir) / project.project_name
        else:
            project_dir_path = Path(project_dir)

        project_dir_path.mkdir(parents=True, exist_ok=True)

        info_data = {
            'project_name': project.project_name,
            'description': project.description,
            'files': [asdict(file) for file in project.files],
            'main_file': project.main_file,
            'setup_instructions': project.setup_instructions,
            'run_instructions': project.run_instructions,
        }

        info_file = project_dir_path / "PROJECT_INFO.json"
        with open(info_file, 'w', encoding='utf-8') as file:
            json.dump(info_data, file, indent=2, ensure_ascii=False)

    @staticmethod
    def cleanup_temp_project(project_dir: str) -> None:
        try:
            shutil.rmtree(project_dir, ignore_errors=True)
        except Exception as exc:  # pragma: no cover - 防禦性處理
            logger.error("清理專案失敗: %s", exc)


class DiagnosticsManager:
    """語法診斷管理器"""

    EXCLUDE_NAMES = {'PROJECT_INFO.json', '__pycache__', '.git', 'node_modules', 'venv', '.vscode'}

    @staticmethod
    def _truncate(text: str, limit: int = 200) -> str:
        if len(text) <= limit:
            return text
        return text[:limit] + '...'

    @staticmethod
    def _check_python(file_path: Path) -> Tuple[str, str]:
        try:
            source = file_path.read_text(encoding='utf-8')
        except Exception as exc:  # pragma: no cover - 防禦性處理
            return 'warning', f'無法讀取檔案: {exc}'

        try:
            compile(source, str(file_path), 'exec')
            return 'passed', '語法查通過'
        except SyntaxError as err:
            line = err.lineno or 0
            column = err.offset or 0
            message = f'SyntaxError 第 {line} 行第 {column} 欄: {err.msg}'
            return 'failed', message
        except Exception as exc:  # pragma: no cover - 防禦性處理
            return 'warning', DiagnosticsManager._truncate(str(exc))

    @staticmethod
    def _check_json(file_path: Path) -> Tuple[str, str]:
        try:
            text = file_path.read_text(encoding='utf-8')
            json.loads(text)
            return 'passed', 'JSON 結構有效'
        except json.JSONDecodeError as err:
            message = f'JSONDecodeError 第 {err.lineno} 行第 {err.colno} 欄: {err.msg}'
            return 'failed', message
        except Exception as exc:  # pragma: no cover - 防禦性處理
            return 'warning', DiagnosticsManager._truncate(str(exc))

    @staticmethod
    def collect(project_dir: str) -> Tuple[List[Dict[str, Any]], str]:
        base_path = Path(project_dir)
        if not base_path.exists():
            return [], ''

        handlers = {
            '.py': ('Python', DiagnosticsManager._check_python),
            '.json': ('JSON', DiagnosticsManager._check_json),
        }

        results: List[Dict[str, Any]] = []

        for file_path in base_path.rglob('*'):
            if not file_path.is_file():
                continue

            if file_path.name in DiagnosticsManager.EXCLUDE_NAMES:
                continue

            suffix = file_path.suffix.lower()
            if suffix not in handlers:
                continue

            language, handler = handlers[suffix]

            try:
                status, message = handler(file_path)
            except Exception as exc:  # pragma: no cover - 防禦性處理
                status, message = 'warning', f'檢查時發生錯誤: {exc}'

            results.append(
                {
                    'file': str(file_path.relative_to(base_path)),
                    'language': language,
                    'status': status,
                    'message': message,
                }
            )

        prompt_block = DiagnosticsManager._format_prompt(results)
        return results, prompt_block

    @staticmethod
    def _format_prompt(results: List[Dict[str, Any]]) -> str:
        if not results:
            return ''

        icon_map = {
            'passed': '✅',
            'failed': '❌',
            'warning': '⚠️',
        }

        lines = ['【語法偵錯結果】']
        for item in results:
            icon = icon_map.get(item.get('status'), '•')
            language = item.get('language', '未知語言')
            file_name = item.get('file', '未知檔案')
            message = item.get('message', '')
            lines.append(f"{icon} [{language}] {file_name} -> {message}")

        return '\n'.join(lines)


__all__ = [
    'ConfigManager',
    'ConversationManager',
    'ProjectManager',
    'DiagnosticsManager',
]
