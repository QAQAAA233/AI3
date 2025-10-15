"""Managers and helpers coordinating configuration, conversations, and projects."""
from __future__ import annotations

import hashlib
import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from .error_reporting import ErrorReporter
from .json_utils import sanitize_json_strings
from .models import (
    AIConfig,
    ConversationMessage,
    FileOutput,
    ProcessResult,
    ProjectConversation,
    ProjectOutput,
    asdict,
)
from .settings import (
    CONFIG_DIR,
    CONFIG_FILE,
    CONVERSATIONS_DIR,
    ERROR_REPORTS_DIR,
    PROJECTS_DIR,
    PROJECT_LIST_FILE,
)

logger = logging.getLogger(__name__)


class ConfigManager:
    """配置文件管理器"""
    
    @staticmethod
    def ensure_config_dir():
        """確保配置目錄存在"""
        try:
            CONFIG_DIR.mkdir(parents=True, exist_ok=True)
            return True
        except Exception as e:
            logger.error(f"無法創建配置目錄 {CONFIG_DIR}: {e}")
            return False
    
    @staticmethod
    def load() -> AIConfig:
        """讀取配置文件"""
        if not ConfigManager.ensure_config_dir():
            logger.warning("配置目錄創建失敗,使用默認配置")
            return AIConfig()
        
        if not CONFIG_FILE.exists():
            logger.info("配置文件不存在,創建默認配置")
            default_config = AIConfig()
            ConfigManager.save(default_config)
            return default_config
        
        try:
            with open(CONFIG_FILE, 'r', encoding='utf-8') as f:
                data = json.load(f)
                return AIConfig(**data)
        except (json.JSONDecodeError, IOError) as e:
            logger.error(f"讀取配置文件失敗: {e}")
            logger.info("返回默認配置")
            return AIConfig()
    
    @staticmethod
    def save(config: AIConfig) -> bool:
        """儲存配置文件"""
        try:
            if not ConfigManager.ensure_config_dir():
                raise IOError("無法創建配置目錄")
            
            with open(CONFIG_FILE, 'w', encoding='utf-8') as f:
                json.dump(asdict(config), f, indent=4, ensure_ascii=False)
            logger.info("配置文件已儲存")
            return True
        except IOError as e:
            logger.error(f"儲存配置文件失敗: {e}")
            return False

class ConversationManager:
    """對話歷史管理器（優化版）"""
    
    @staticmethod
    def get_conversation_file(project_dir: str) -> Path:
        """獲取專案對話檔案路徑"""
        project_hash = hashlib.md5(project_dir.encode()).hexdigest()
        return CONVERSATIONS_DIR / f"conv_{project_hash}.json"
    
    @staticmethod
    def load_conversation(project_dir: str) -> ProjectConversation:
        """載入專案對話歷史"""
        conv_file = ConversationManager.get_conversation_file(project_dir)
        
        if not conv_file.exists():
            project_name = Path(project_dir).name
            conv = ProjectConversation(
                project_dir=project_dir,
                project_name=project_name,
                created_at=datetime.now().isoformat(),
                updated_at=datetime.now().isoformat()
            )
            return conv
        
        try:
            with open(conv_file, 'r', encoding='utf-8') as f:
                data = json.load(f)
                messages = []
                for msg_data in data.get('messages', []):
                    usage_metadata = msg_data.get('usage_metadata')
                    if not usage_metadata and msg_data.get('metadata'):
                        usage_metadata = msg_data['metadata'].get('usage_metadata')
                    
                    messages.append(ConversationMessage(
                        role=msg_data['role'],
                        content=msg_data['content'],
                        timestamp=msg_data['timestamp'],
                        files=msg_data.get('files'),
                        metadata=msg_data.get('metadata'),
                        terminal_output=msg_data.get('terminal_output'),
                        usage_metadata=usage_metadata
                    ))
                
                return ProjectConversation(
                    project_dir=data['project_dir'],
                    project_name=data['project_name'],
                    messages=messages,
                    created_at=data.get('created_at', ''),
                    updated_at=data.get('updated_at', ''),
                    memory_snapshot=data.get('memory_snapshot', {}),
                    evaluation_snapshot=data.get('evaluation_snapshot', {}),
                    accumulated_long_term_memory=data.get('accumulated_long_term_memory', [])  # ⭐ 新增
                )
        except Exception as e:
            logger.error(f"載入對話歷史失敗: {e}")
            return ProjectConversation(
                project_dir=project_dir,
                project_name=Path(project_dir).name,
                created_at=datetime.now().isoformat(),
                updated_at=datetime.now().isoformat()
            )
    
    @staticmethod
    def save_conversation(conversation: ProjectConversation) -> bool:
        """儲存對話歷史"""
        try:
            conv_file = ConversationManager.get_conversation_file(conversation.project_dir)
            conversation.updated_at = datetime.now().isoformat()
            
            messages_data = []
            for msg in conversation.messages:
                msg_dict = {
                    'role': msg.role,
                    'content': msg.content,
                    'timestamp': msg.timestamp,
                    'files': msg.files,
                    'metadata': msg.metadata,
                    'terminal_output': msg.terminal_output,
                    'usage_metadata': msg.usage_metadata
                }
                messages_data.append(msg_dict)
            
            data = {
                'project_dir': conversation.project_dir,
                'project_name': conversation.project_name,
                'messages': messages_data,
                'created_at': conversation.created_at,
                'updated_at': conversation.updated_at,
                'memory_snapshot': conversation.memory_snapshot,
                'evaluation_snapshot': conversation.evaluation_snapshot,
                'accumulated_long_term_memory': conversation.accumulated_long_term_memory  # ⭐ 新增
            }
            
            with open(conv_file, 'w', encoding='utf-8') as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
            
            logger.info(f"對話歷史已儲存: {conversation.project_name}")
            return True
        except Exception as e:
            logger.error(f"儲存對話歷史失敗: {e}")
            return False
    
    @staticmethod
    def add_message(project_dir: str, role: str, content: str, files: Optional[List[Dict]] = None,
                   metadata: Optional[Dict] = None, terminal_output: Optional[str] = None,
                   usage_metadata: Optional[Dict] = None):
        """添加消息到對話歷史"""
        conversation = ConversationManager.load_conversation(project_dir)
        
        message = ConversationMessage(
            role=role,
            content=content,
            timestamp=datetime.now().isoformat(),
            files=files,
            metadata=metadata,
            terminal_output=terminal_output,
            usage_metadata=usage_metadata
        )
        
        conversation.messages.append(message)
        ConversationManager.save_conversation(conversation)
        
        try:
            ProjectManager.update_last_accessed(project_dir, message.timestamp)
        except Exception as e:
            logger.warning(f"更新專案最近使用時間失敗: {e}")
    
    @staticmethod
    def update_memory_state(
        project_dir: str, 
        memory_snapshot: Optional[Dict], 
        evaluation_snapshot: Optional[Dict],
        new_long_term_memory: Optional[List[str]] = None  # ⭐ 新增
    ):
        """更新對話的記憶與評分快照（支持累積長期記憶）"""
        conversation = ConversationManager.load_conversation(project_dir)
        
        if memory_snapshot:
            conversation.memory_snapshot = memory_snapshot
        
        if evaluation_snapshot:
            conversation.evaluation_snapshot = {
                k: v for k, v in (evaluation_snapshot or {}).items() if v is not None
            }
        
        # ⭐ 累積長期記憶
        if new_long_term_memory:
            # 獲取現有的累積記憶
            existing_memory = conversation.accumulated_long_term_memory or []
            # 添加新記憶（避免重複）
            for mem in new_long_term_memory:
                if mem and mem not in existing_memory:
                    existing_memory.append(mem)
            # 保留最近的 50 條記憶（避免過長）
            conversation.accumulated_long_term_memory = existing_memory[-50:]
            logger.info(f"長期記憶已更新，當前總數：{len(conversation.accumulated_long_term_memory)}")
        
        ConversationManager.save_conversation(conversation)
    
    @staticmethod
    def delete_conversation_file(project_dir: str) -> bool:
        """刪除對話檔案"""
        try:
            conv_file = ConversationManager.get_conversation_file(project_dir)
            if conv_file.exists():
                conv_file.unlink()
                logger.info(f"已刪除對話檔案: {conv_file}")
                return True
            return False
        except Exception as e:
            logger.error(f"刪除對話檔案失敗: {e}")
            return False

class ProjectManager:
    """專案管理器"""
    
    @staticmethod
    def load_project_info(project_dir: str) -> Optional[Dict]:
        """載入專案資訊"""
        info_file = Path(project_dir) / "PROJECT_INFO.json"
        if not info_file.exists():
            logger.warning(f"找不到 PROJECT_INFO.json: {info_file}")
            return None
        
        try:
            with open(info_file, 'r', encoding='utf-8') as f:
                return json.load(f)
        except (json.JSONDecodeError, IOError) as e:
            logger.error(f"讀取專案資訊失敗: {e}")
            return None
    
    @staticmethod
    def load_project_files(project_dir: str) -> List[Dict]:
        """載入專案所有檔案內容"""
        project_dir_path = Path(project_dir)
        files_data = []
        
        exclude = {'PROJECT_INFO.json', '__pycache__', '.git', 'node_modules', 'venv', '.vscode'}
        
        for file_path in project_dir_path.rglob('*'):
            if file_path.is_file() and file_path.name not in exclude:
                if any(ex in file_path.parts for ex in exclude):
                    continue
                
                try:
                    with open(file_path, 'r', encoding='utf-8') as f:
                        content = f.read()
                    
                    rel_path = file_path.relative_to(project_dir_path)
                    files_data.append({
                        'name': str(rel_path),
                        'type': 'text/plain',
                        'content': content
                    })
                    logger.info(f"已載入檔案: {rel_path}")
                except Exception as e:
                    logger.warning(f"無法讀取檔案 {file_path}: {e}")
        
        return files_data
    
    @staticmethod
    def _infer_filetype(path: Path) -> str:
        """根據副檔名推斷檔案類型"""
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
        """建立資料夾內檔案的基本描述列表"""
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
            metadata.append({
                'filename': str(rel_path),
                'filetype': ProjectManager._infer_filetype(file_path),
                'description': '現有檔案'
            })
        
        metadata.sort(key=lambda item: item['filename'].lower())
        return metadata
    
    @staticmethod
    def get_project_structure(project_dir: str) -> str:
        """獲取專案結構字串"""
        project_dir_path = Path(project_dir)
        structure_lines = [f"專案目錄: {project_dir_path.name}\n"]
        
        exclude = {'PROJECT_INFO.json', '__pycache__', '.git', 'node_modules', 'venv', '.vscode'}
        
        def build_tree(directory, prefix=""):
            contents = sorted(directory.iterdir(), key=lambda x: (x.is_file(), x.name))
            for i, path in enumerate(contents):
                if path.name in exclude:
                    continue
                
                is_last = i == len(contents) - 1
                current_prefix = "└── " if is_last else "├── "
                structure_lines.append(f"{prefix}{current_prefix}{path.name}")
                
                if path.is_dir() and path.name not in exclude:
                    next_prefix = prefix + ("    " if is_last else "│   ")
                    build_tree(path, next_prefix)
        
        build_tree(project_dir_path)
        return "\n".join(structure_lines)
    
    @staticmethod
    def add_to_project_list(project_dir: str, project_name: str, description: str = "", status: str = 'ready',
                            update_last_accessed: bool = True):
        """添加專案到列表"""
        try:
            normalized_dir = str(Path(project_dir))
            project_list = ProjectManager.get_project_list()
            
            existing = next((p for p in project_list if p['path'] == normalized_dir), None)
            
            if existing:
                existing['name'] = project_name
                existing['description'] = description
                if update_last_accessed:
                    existing['last_accessed'] = datetime.now().isoformat()
                if status:
                    existing['status'] = status
            else:
                timestamp = datetime.now().isoformat()
                entry = {
                    'path': normalized_dir,
                    'name': project_name,
                    'description': description,
                    'created_at': timestamp,
                    'last_accessed': timestamp
                }
                if status:
                    entry['status'] = status
                project_list.append(entry)
            
            with open(PROJECT_LIST_FILE, 'w', encoding='utf-8') as f:
                json.dump(project_list, f, indent=2, ensure_ascii=False)
            
            logger.info(f"已添加/更新專案到列表: {project_name} ({normalized_dir})")
            return True
        except Exception as e:
            logger.error(f"添加專案到列表失敗: {e}")
            return False
    
    @staticmethod
    def ensure_placeholder_project(project_dir: str, project_name: Optional[str] = None, description: str = "") -> bool:
        """確保新建專案在等待 AI 回應時也能出現在列表中"""
        try:
            normalized_dir = str(Path(project_dir))
            display_name = project_name or Path(normalized_dir).name or '建立中專案'
            placeholder_desc = description or '專案建立中，等待 AI 回應'
            
            project_list = ProjectManager.get_project_list()
            existing = next((p for p in project_list if p['path'] == normalized_dir), None)
            
            timestamp = datetime.now().isoformat()
            
            if existing:
                existing['name'] = display_name
                existing['description'] = placeholder_desc
                existing['last_accessed'] = timestamp
                existing['status'] = 'pending'
            else:
                project_list.append({
                    'path': normalized_dir,
                    'name': display_name,
                    'description': placeholder_desc,
                    'created_at': timestamp,
                    'last_accessed': timestamp,
                    'status': 'pending'
                })
            
            with open(PROJECT_LIST_FILE, 'w', encoding='utf-8') as f:
                json.dump(project_list, f, indent=2, ensure_ascii=False)
            
            logger.info(f"已建立專案佔位: {display_name} ({normalized_dir})")
            return True
        except Exception as e:
            logger.error(f"建立專案佔位失敗: {e}")
            return False
    
    @staticmethod
    def get_project_list() -> List[Dict]:
        """獲取專案列表"""
        if not PROJECT_LIST_FILE.exists():
            return []
        
        try:
            with open(PROJECT_LIST_FILE, 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception as e:
            logger.error(f"讀取專案列表失敗: {e}")
            return []
    
    @staticmethod
    def remove_from_project_list(project_dir: str):
        """從列表移除專案"""
        try:
            normalized_dir = str(Path(project_dir))
            project_list = ProjectManager.get_project_list()
            project_list = [p for p in project_list if p['path'] != normalized_dir]
            
            with open(PROJECT_LIST_FILE, 'w', encoding='utf-8') as f:
                json.dump(project_list, f, indent=2, ensure_ascii=False)
            
            logger.info(f"已從列表移除專案: {normalized_dir}")
            return True
        except Exception as e:
            logger.error(f"移除專案失敗: {e}")
            return False
    
    @staticmethod
    def update_last_accessed(project_dir: str, timestamp: Optional[str] = None) -> bool:
        """更新專案的最後使用時間"""
        project_list = ProjectManager.get_project_list()
        normalized_dir = str(Path(project_dir))
        existing = next((p for p in project_list if p['path'] == normalized_dir), None)
        
        if not existing:
            return False
        
        existing['last_accessed'] = timestamp or datetime.now().isoformat()
        
        try:
            with open(PROJECT_LIST_FILE, 'w', encoding='utf-8') as f:
                json.dump(project_list, f, indent=2, ensure_ascii=False)
            return True
        except Exception as e:
            logger.error(f"更新專案最近使用時間失敗: {e}")
            return False

class DiagnosticsManager:
    """語法偵錯管理器"""
    
    EXCLUDE_NAMES = {'PROJECT_INFO.json', '__pycache__', '.git', 'node_modules', 'venv', '.vscode'}
    
    @staticmethod
    def _truncate(text: str, limit: int = 180) -> str:
        if len(text) <= limit:
            return text
        return text[:limit - 1] + '…'
    
    @staticmethod
    def _check_python(file_path: Path) -> Tuple[str, str]:
        try:
            source = file_path.read_text(encoding='utf-8')
        except Exception as e:
            return 'warning', f'無法讀取檔案: {e}'
        
        try:
            compile(source, str(file_path), 'exec')
            return 'passed', '語法檢查通過'
        except SyntaxError as e:
            line = e.lineno or 0
            column = e.offset or 0
            message = f'SyntaxError 第 {line} 行第 {column} 欄: {e.msg}'
            return 'failed', message
        except Exception as e:
            return 'warning', DiagnosticsManager._truncate(str(e))
    
    @staticmethod
    def _check_json(file_path: Path) -> Tuple[str, str]:
        try:
            text = file_path.read_text(encoding='utf-8')
            json.loads(text)
            return 'passed', 'JSON 結構有效'
        except json.JSONDecodeError as e:
            message = f'JSONDecodeError 第 {e.lineno} 行第 {e.colno} 欄: {e.msg}'
            return 'failed', message
        except Exception as e:
            return 'warning', DiagnosticsManager._truncate(str(e))
    
    @staticmethod
    def collect(project_dir: str) -> Tuple[List[Dict[str, Any]], str]:
        """收集語法偵錯結果"""
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
            except Exception as e:
                status, message = 'warning', f'檢查時發生錯誤: {e}'
            
            results.append({
                'file': str(file_path.relative_to(base_path)),
                'language': language,
                'status': status,
                'message': message
            })
        
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