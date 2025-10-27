"""資料與外部資源管理模組"""

from __future__ import annotations

import hashlib
import json
import os
import platform
import queue
import subprocess
import threading
import time
import traceback
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import mss
import mss.tools
import pyautogui
import pyperclip
import pywinctl as pwc

from config import (
    CONFIG_DIR,
    CONVERSATIONS_DIR,
    ERROR_REPORTS_DIR,
    PROJECT_LIST_FILE,
    SCREENSHOT_DIR,
    logger,
)
from models import ConversationMessage, FileOutput, ProjectConversation


class ErrorReporter:
    """錯誤報告生成器 - 自動生成詳細的錯誤報告"""

    @staticmethod
    def generate_report(
        error_type: str,
        error_message: str,
        ai_response: str = "",
        json_data: Any = None,
        stack_trace: str = "",
        context: Dict[str, Any] | None = None,
    ) -> Path:
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        report_filename = f"{error_type}_{timestamp}.md"
        report_path = ERROR_REPORTS_DIR / report_filename

        report_lines = [
            f"# 🚨 錯誤報告：{error_type}",
            f"\n**時間**：{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
            "\n## 📋 錯誤摘要",
            "\n```",
            error_message,
            "```",
        ]

        if stack_trace:
            report_lines.extend([
                "\n## 🔍 堆疊追蹤",
                "\n```python",
                stack_trace,
                "```",
            ])

        if ai_response:
            truncated_response = ai_response[:2000]
            if len(ai_response) > 2000:
                truncated_response += "\n\n... (回應過長，已截斷)"

            report_lines.extend([
                "\n## 🤖 AI 原始回應",
                "\n```json",
                truncated_response,
                "```",
            ])

        if json_data:
            try:
                json_str = json.dumps(json_data, indent=2, ensure_ascii=False)[:1000]
                report_lines.extend([
                    "\n## 📦 解析的 JSON 數據",
                    "\n```json",
                    json_str,
                    "```",
                ])
            except Exception as exc:  # pragma: no cover - 僅記錄失敗資訊
                report_lines.extend([
                    "\n## 📦 解析的 JSON 數據",
                    "\nJSON 序列化失敗: " + str(exc),
                ])

        if context:
            try:
                context_str = json.dumps(context, indent=2, ensure_ascii=False)
            except Exception:
                context_str = str(context)

            report_lines.extend([
                "\n## 📂 上下文資訊",
                "\n```json",
                context_str,
                "```",
            ])

        try:
            report_path.write_text("\n".join(report_lines), encoding='utf-8')
            logger.info("錯誤報告已生成: %s", report_path)
        except Exception as exc:
            logger.error("錯誤報告生成失敗: %s", exc)

        return report_path


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
            with open(conv_file, 'r', encoding='utf-8') as handle:
                data = json.load(handle)

            messages = []
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

            with open(conv_file, 'w', encoding='utf-8') as handle:
                json.dump(data, handle, indent=2, ensure_ascii=False)

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
        files: Optional[List[Dict[str, Any]]] = None,
        metadata: Optional[Dict[str, Any]] = None,
        terminal_output: Optional[str] = None,
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

        try:
            ProjectManager.update_last_accessed(project_dir, datetime.now().isoformat())
        except Exception as exc:
            logger.warning("更新專案最近使用時間失敗: %s", exc)

    @staticmethod
    def update_memory_state(
        project_dir: str,
        memory_snapshot: Optional[Dict[str, Any]],
        evaluation_snapshot: Optional[Dict[str, Any]],
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
            for item in new_long_term_memory:
                if item and item not in existing_memory:
                    existing_memory.append(item)
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
    """專案管理器"""

    @staticmethod
    def load_project_info(project_dir: str) -> Optional[Dict[str, Any]]:
        info_file = Path(project_dir) / "PROJECT_INFO.json"
        if not info_file.exists():
            logger.warning("找不到 PROJECT_INFO.json: %s", info_file)
            return None

        try:
            with open(info_file, 'r', encoding='utf-8') as handle:
                return json.load(handle)
        except (json.JSONDecodeError, OSError) as exc:
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
                    content = file_path.read_text(encoding='utf-8')
                    rel_path = file_path.relative_to(project_dir_path)
                    files_data.append({
                        'name': str(rel_path),
                        'type': 'text/plain',
                        'content': content,
                    })
                    logger.info("已載入檔案: %s", rel_path)
                except Exception as exc:
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
            contents = sorted(directory.iterdir(), key=lambda item: (item.is_file(), item.name))
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
    ) -> bool:
        try:
            normalized_dir = str(Path(project_dir))
            project_list = ProjectManager.get_project_list()
            existing = next((item for item in project_list if item['path'] == normalized_dir), None)

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
                    'last_accessed': timestamp,
                }
                if status:
                    entry['status'] = status
                project_list.append(entry)

            with open(PROJECT_LIST_FILE, 'w', encoding='utf-8') as handle:
                json.dump(project_list, handle, indent=2, ensure_ascii=False)

            logger.info("已添加/更新專案到列表: %s (%s)", project_name, normalized_dir)
            return True
        except Exception as exc:
            logger.error("添加專案到列表失敗: %s", exc)
            return False

    @staticmethod
    def ensure_placeholder_project(
        project_dir: str,
        project_name: Optional[str] = None,
        description: str = "",
    ) -> bool:
        try:
            normalized_dir = str(Path(project_dir))
            display_name = project_name or Path(normalized_dir).name or '建立中專案'
            placeholder_desc = description or '專案建立中，等待 AI 回應'

            project_list = ProjectManager.get_project_list()
            existing = next((item for item in project_list if item['path'] == normalized_dir), None)
            timestamp = datetime.now().isoformat()

            if existing:
                existing['name'] = display_name
                existing['description'] = placeholder_desc
                existing['last_accessed'] = timestamp
                existing['status'] = 'pending'
            else:
                project_list.append(
                    {
                        'path': normalized_dir,
                        'name': display_name,
                        'description': placeholder_desc,
                        'created_at': timestamp,
                        'last_accessed': timestamp,
                        'status': 'pending',
                    }
                )

            with open(PROJECT_LIST_FILE, 'w', encoding='utf-8') as handle:
                json.dump(project_list, handle, indent=2, ensure_ascii=False)

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
            with open(PROJECT_LIST_FILE, 'r', encoding='utf-8') as handle:
                return json.load(handle)
        except Exception as exc:
            logger.error("讀取專案列表失敗: %s", exc)
            return []

    @staticmethod
    def remove_from_project_list(project_dir: str) -> bool:
        try:
            normalized_dir = str(Path(project_dir))
            project_list = ProjectManager.get_project_list()
            project_list = [item for item in project_list if item['path'] != normalized_dir]

            with open(PROJECT_LIST_FILE, 'w', encoding='utf-8') as handle:
                json.dump(project_list, handle, indent=2, ensure_ascii=False)

            logger.info("已從列表移除專案: %s", normalized_dir)
            return True
        except Exception as exc:
            logger.error("移除專案失敗: %s", exc)
            return False

    @staticmethod
    def update_last_accessed(project_dir: str, timestamp: Optional[str] = None) -> bool:
        project_list = ProjectManager.get_project_list()
        normalized_dir = str(Path(project_dir))
        existing = next((item for item in project_list if item['path'] == normalized_dir), None)

        if not existing:
            return False

        existing['last_accessed'] = timestamp or datetime.now().isoformat()

        try:
            with open(PROJECT_LIST_FILE, 'w', encoding='utf-8') as handle:
                json.dump(project_list, handle, indent=2, ensure_ascii=False)
            return True
        except Exception as exc:
            logger.error("更新專案最近使用時間失敗: %s", exc)
            return False


class DiagnosticsManager:
    """語法偵錯管理器"""

    EXCLUDE_NAMES = {'PROJECT_INFO.json', '__pycache__', '.git', 'node_modules', 'venv', '.vscode'}

    @staticmethod
    def _truncate(text: str, limit: int = 180) -> str:
        if len(text) <= limit:
            return text
        return text[: limit - 1] + '…'

    @staticmethod
    def _check_python(file_path: Path) -> Tuple[str, str]:
        try:
            source = file_path.read_text(encoding='utf-8')
        except Exception as exc:
            return 'warning', f'無法讀取檔案: {exc}'

        try:
            compile(source, str(file_path), 'exec')
            return 'passed', '語法檢查通過'
        except SyntaxError as exc:
            line = exc.lineno or 0
            column = exc.offset or 0
            message = f'SyntaxError 第 {line} 行第 {column} 欄: {exc.msg}'
            return 'failed', message
        except Exception as exc:
            return 'warning', DiagnosticsManager._truncate(str(exc))

    @staticmethod
    def _check_json(file_path: Path) -> Tuple[str, str]:
        try:
            text = file_path.read_text(encoding='utf-8')
            json.loads(text)
            return 'passed', 'JSON 結構有效'
        except json.JSONDecodeError as exc:
            message = f'JSONDecodeError 第 {exc.lineno} 行第 {exc.colno} 欄: {exc.msg}'
            return 'failed', message
        except Exception as exc:
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
            except Exception as exc:
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


class VSCodeController:
    """VS Code 自動化控制器"""

    @staticmethod
    def launch_and_open(folder_path: str, filenames: List[str]) -> Dict[str, Any]:
        result: Dict[str, Any] = {
            "success": False,
            "window_found": False,
            "files_opened": [],
            "message": "",
        }

        try:
            logger.info("正在啟動 VS Code, 資料夾: %s", folder_path)

            if filenames:
                first_file = Path(folder_path) / filenames[0]
                subprocess.Popen(['code', folder_path, str(first_file)], shell=(platform.system() == 'Windows'))
            else:
                subprocess.Popen(['code', folder_path], shell=(platform.system() == 'Windows'))

            folder_name = os.path.basename(os.path.normpath(folder_path))
            vscode_window = None
            timeout = 15
            start_time = time.time()

            logger.info("尋找包含 '%s' 的 VS Code 視窗...", folder_name)

            while time.time() - start_time < timeout:
                for window in pwc.getAllWindows():
                    if window.title and 'visual studio code' in window.title.lower():
                        if folder_name.lower() in window.title.lower():
                            vscode_window = window
                            break

                if vscode_window:
                    break
                time.sleep(0.5)

            if not vscode_window:
                possible_windows = [w for w in pwc.getAllWindows() if w.title and 'Visual Studio Code' in w.title]
                if possible_windows:
                    vscode_window = possible_windows[0]
                    logger.warning("使用找到的第一個 VS Code 視窗")
                else:
                    result["message"] = f"在 {timeout} 秒內找不到 VS Code 視窗"
                    logger.warning(result["message"])
                    return result

            result["window_found"] = True
            logger.info("找到 VS Code 視窗: %s", vscode_window.title)

            if vscode_window.isMinimized:
                vscode_window.restore()
            vscode_window.activate()
            time.sleep(1)

            if len(filenames) > 1:
                hotkey_ctrl = 'command' if platform.system() == 'Darwin' else 'ctrl'

                for filename in filenames[1:3]:
                    time.sleep(0.5)
                    pyautogui.hotkey(hotkey_ctrl, 'p')
                    time.sleep(0.3)

                    pyperclip.copy(filename)
                    pyautogui.hotkey(hotkey_ctrl, 'v')
                    time.sleep(0.2)

                    pyautogui.press('enter')
                    result["files_opened"].append(filename)
                    logger.info("已打開檔案: %s", filename)

            if filenames:
                result["files_opened"].insert(0, filenames[0])

            result["success"] = True
            result["message"] = f"成功打開 VS Code 和 {len(result['files_opened'])} 個檔案"
            logger.info(result["message"])

        except FileNotFoundError:
            result["message"] = "找不到 'code' 命令"
            logger.error(result["message"])
        except Exception as exc:
            result["message"] = f"VS Code 控制失敗: {exc}"
            logger.error(result["message"])

        return result


class ScreenCapture:
    """螢幕擷取管理器"""

    @staticmethod
    def capture_running_programs(
        window_titles: Optional[List[str]] = None,
        project_name: Optional[str] = None,
        project_json: Optional[Dict[str, Any]] = None,
    ) -> List[Dict[str, Any]]:
        screenshots: List[Dict[str, Any]] = []
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")

        all_window_titles: List[str] = []
        if project_json and 'files' in project_json:
            for file in project_json['files']:
                if file.get('web_title'):
                    all_window_titles.append(file['web_title'])
                if file.get('window_title'):
                    all_window_titles.append(file['window_title'])

        if window_titles:
            all_window_titles.extend(window_titles)

        all_window_titles = list(set(all_window_titles))
        logger.info("開始擷取程式視窗")

        captured_titles = set()
        found_windows = []
        browser_keywords = ['chrome', 'edge', 'firefox', 'safari', 'brave']

        for window in pwc.getAllWindows():
            if not window.title:
                continue

            window_title_lower = window.title.lower()
            should_capture = False
            capture_reason = ""

            if project_name and 'visual studio code' in window_title_lower:
                if project_name.lower() in window_title_lower:
                    should_capture = True
                    capture_reason = "VS Code - 專案視窗"

            if not should_capture:
                for browser in browser_keywords:
                    if browser in window_title_lower:
                        for keyword in all_window_titles:
                            if keyword.lower() in window_title_lower:
                                should_capture = True
                                capture_reason = f"瀏覽器 - {keyword}"
                                break
                        if should_capture:
                            break

            if should_capture and window.title not in captured_titles:
                found_windows.append((window, capture_reason))
                captured_titles.add(window.title)

        for window, reason in found_windows:
            try:
                if window.isMinimized:
                    window.restore()
                window.activate()
                time.sleep(0.5)

                safe_title = window.title[:50].replace(' ', '_').replace('/', '_')
                filename = f"capture_{safe_title}_{timestamp}.png"
                filepath = SCREENSHOT_DIR / filename

                with mss.mss() as sct:
                    monitor = {
                        "top": max(0, window.top),
                        "left": max(0, window.left),
                        "width": min(window.width, 3840),
                        "height": min(window.height, 2160),
                    }

                    sct_img = sct.grab(monitor)
                    mss.tools.to_png(sct_img.rgb, sct_img.size, output=str(filepath))

                screenshots.append(
                    {
                        "name": f"{window.title} ({reason})",
                        "filename": filename,
                        "path": str(filepath),
                        "width": window.width,
                        "height": window.height,
                        "timestamp": timestamp,
                    }
                )

                logger.info("成功擷取視窗: %s", window.title)
            except Exception as exc:
                logger.warning("擷取視窗失敗: %s", exc)

        logger.info("擷取完成, 共 %s 個視窗", len(screenshots))
        return screenshots


class ProgramManager:
    """管理執行中的程式"""

    running_programs: Dict[int, Dict[str, Any]] = {}
    browser_processes: Dict[str, Dict[str, Any]] = {}

    @classmethod
    def _extract_port_from_address(cls, server_address: Optional[str]) -> Optional[int]:
        if not server_address:
            return None

        try:
            import re

            match = re.search(r':(\d+)', server_address)
            if match:
                return int(match.group(1))
        except Exception:
            pass

        return None

    @classmethod
    def _find_processes_using_port(cls, port: int) -> List[int]:
        pids = []
        for pid, info in list(cls.running_programs.items()):
            if info.get('port') == port:
                pids.append(pid)
        return pids

    @classmethod
    def _close_port_processes(cls, port: int) -> None:
        pids = cls._find_processes_using_port(port)
        if pids:
            logger.info("⚠️ 檢測到端口 %s 被 %s 個進程佔用", port, len(pids))
            for pid in pids:
                logger.info("正在關閉佔用端口 %s 的進程 PID %s...", port, pid)
                cls.terminate_program(pid)
                time.sleep(0.5)
            logger.info("✅ 已關閉所有佔用端口 %s 的進程", port)
            time.sleep(1)
        else:
            logger.info("✓ 端口 %s 未被佔用", port)

    @classmethod
    def add_program(
        cls,
        process: subprocess.Popen,
        filename: str,
        folder_path: str,
        window_title: Optional[str] = None,
        output_queue: Optional[queue.Queue] = None,
        port: Optional[int] = None,
    ) -> None:
        cls.running_programs[process.pid] = {
            'process': process,
            'filename': filename,
            'folder_path': folder_path,
            'window_title': window_title,
            'start_time': datetime.now(),
            'pid': process.pid,
            'output_queue': output_queue,
            'terminal_output': [],
            'port': port,
        }
        if port:
            logger.info("已添加程式到管理列表: PID %s, 使用端口 %s", process.pid, port)
        else:
            logger.info("已添加程式到管理列表: PID %s", process.pid)

    @classmethod
    def add_browser_process(cls, process: subprocess.Popen, project_dir: str) -> None:
        cls.browser_processes[project_dir] = {
            'process': process,
            'pid': process.pid,
            'start_time': datetime.now(),
        }
        logger.info("已追蹤瀏覽器進程: PID %s", process.pid)

    @classmethod
    def close_project_browsers(cls, project_dir: str) -> None:
        if project_dir in cls.browser_processes:
            browser_info = cls.browser_processes[project_dir]
            try:
                process = browser_info['process']
                if process.poll() is None:
                    process.terminate()
                    time.sleep(0.3)
                    if process.poll() is None:
                        process.kill()
                logger.info("已關閉舊瀏覽器: PID %s", browser_info['pid'])
            except Exception as exc:
                logger.warning("關閉瀏覽器失敗: %s", exc)
            finally:
                del cls.browser_processes[project_dir]

    @classmethod
    def get_terminal_output(cls, pid: int) -> str:
        if pid in cls.running_programs:
            return '\n'.join(cls.running_programs[pid]['terminal_output'])
        return ""

    @classmethod
    def get_all_terminal_output(cls) -> str:
        all_output: List[str] = []
        for pid, info in cls.running_programs.items():
            if info['terminal_output']:
                all_output.append(f"=== PID {pid} ({info['filename']}) ===")
                all_output.extend(info['terminal_output'])
        return '\n'.join(all_output)

    @classmethod
    def update_outputs(cls) -> None:
        for pid, info in list(cls.running_programs.items()):
            output_queue = info.get('output_queue')
            if not output_queue:
                continue

            try:
                while True:
                    line = output_queue.get_nowait()
                    info['terminal_output'].append(line)
                    if len(info['terminal_output']) > 200:
                        info['terminal_output'] = info['terminal_output'][-200:]
            except queue.Empty:
                pass

    @classmethod
    def check_programs(cls) -> List[Dict[str, Any]]:
        cls.update_outputs()
        to_remove = []
        status: List[Dict[str, Any]] = []

        for pid, info in cls.running_programs.items():
            poll_result = info['process'].poll()
            if poll_result is None:
                run_time = (datetime.now() - info['start_time']).seconds
                status.append(
                    {
                        'pid': pid,
                        'filename': info['filename'],
                        'window_title': info.get('window_title'),
                        'status': 'running',
                        'run_time': run_time,
                        'terminal_output': '\n'.join(info['terminal_output'][-50:]),
                    }
                )
            else:
                to_remove.append(pid)
                status.append(
                    {
                        'pid': pid,
                        'filename': info['filename'],
                        'window_title': info.get('window_title'),
                        'status': 'finished',
                        'exit_code': poll_result,
                        'terminal_output': '\n'.join(info['terminal_output'][-50:]),
                    }
                )

        for pid in to_remove:
            del cls.running_programs[pid]
            logger.info("程式已結束: PID %s", pid)

        return status

    @classmethod
    def terminate_all(cls) -> List[int]:
        terminated: List[int] = []
        for pid in list(cls.running_programs.keys()):
            if cls.terminate_program(pid):
                terminated.append(pid)
        return terminated

    @classmethod
    def terminate_program(cls, pid: int) -> bool:
        if pid in cls.running_programs:
            try:
                cls.running_programs[pid]['process'].terminate()
                time.sleep(0.5)
                if cls.running_programs[pid]['process'].poll() is None:
                    cls.running_programs[pid]['process'].kill()
                del cls.running_programs[pid]
                logger.info("已終止程式: PID %s", pid)
                return True
            except Exception as exc:
                logger.error("終止程式失敗: %s", exc)
                return False
        return False

    @classmethod
    def run_file(cls, filepath: str, folder_path: str, file_info: Optional[FileOutput] = None):
        file_ext = Path(filepath).suffix.lower()
        window_title = file_info.window_title if file_info else None
        filename = Path(filepath).name

        port = None
        if file_info and file_info.is_web_app and file_info.server_address:
            port = cls._extract_port_from_address(file_info.server_address)
            if port:
                logger.info("檢測到程式將使用端口: %s", port)

        if port:
            logger.info("🔍 檢查端口 %s 的使用狀況...", port)
            cls._close_port_processes(port)

        logger.info("🔍 檢查是否有相同檔案 '%s' 正在運行...", filename)
        pids_to_close: List[int] = []
        for pid, info in list(cls.running_programs.items()):
            if info['filename'] == filename and info['folder_path'] == folder_path:
                pids_to_close.append(pid)
                logger.info("發現相同檔案正在運行: PID %s", pid)

        for pid in pids_to_close:
            logger.info("正在關閉舊進程 PID %s...", pid)
            cls.terminate_program(pid)
            time.sleep(0.5)

        if pids_to_close:
            logger.info("✅ 已關閉 %s 個舊進程", len(pids_to_close))
            time.sleep(1)

        try:
            if file_info and file_info.is_web_app:
                if file_ext == '.html':
                    file_path = Path(filepath).resolve()
                    file_url = file_path.as_uri()
                    cls.open_standalone_browser(file_url, file_info.web_title or "Web App", folder_path)
                    return None
                elif file_info.can_open_standalone:
                    if file_ext == '.py':
                        process, output_queue = cls._run_python(filepath, folder_path)
                    elif file_ext == '.js':
                        process, output_queue = cls._run_node(filepath, folder_path)
                    else:
                        return None
                else:
                    if file_ext == '.py':
                        process, output_queue = cls._run_python(filepath, folder_path)
                    elif file_ext == '.js':
                        process, output_queue = cls._run_node(filepath, folder_path)
                    else:
                        return None

                if file_info.server_address:
                    time.sleep(2)
                    cls.open_standalone_browser(
                        file_info.server_address,
                        file_info.web_title or "Web App",
                        folder_path,
                    )

                cls.add_program(process, Path(filepath).name, folder_path, window_title, output_queue, port)
                return process

            if file_ext == '.py':
                process, output_queue = cls._run_python(filepath, folder_path)
                cls.add_program(process, Path(filepath).name, folder_path, window_title, output_queue, port)
                return process

            if file_ext == '.js':
                process, output_queue = cls._run_node(filepath, folder_path)
                cls.add_program(process, Path(filepath).name, folder_path, window_title, output_queue, port)
                return process

            if file_ext == '.html':
                file_path = Path(filepath).resolve()
                file_url = file_path.as_uri()
                import webbrowser

                webbrowser.open(file_url)
                return None

            logger.warning("不支援直接執行的檔案類型: %s", file_ext)
            return None
        except Exception as exc:
            logger.error("執行檔案失敗 %s: %s", filepath, exc)

            ErrorReporter.generate_report(
                error_type="FILE_EXECUTION_ERROR",
                error_message=str(exc),
                stack_trace=traceback.format_exc(),
                context={'filepath': filepath, 'file_ext': file_ext, 'port': port},
            )

            raise

    @classmethod
    def _run_python(cls, filepath: str, folder_path: str) -> Tuple[subprocess.Popen, queue.Queue]:
        output_queue: queue.Queue = queue.Queue()
        env = os.environ.copy()
        env['PYTHONUNBUFFERED'] = '1'

        if platform.system() == 'Windows':
            process = subprocess.Popen(
                [sys.executable, '-u', str(filepath)],
                cwd=folder_path,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                creationflags=subprocess.CREATE_NEW_CONSOLE,
                text=True,
                encoding='utf-8',
                bufsize=1,
                env=env,
            )
        else:
            if platform.system() == 'Darwin':
                process = subprocess.Popen(
                    ['osascript', '-e', f'tell application "Terminal" to do script "cd {folder_path} && python3 -u {filepath}"'],
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT,
                    text=True,
                    encoding='utf-8',
                    bufsize=1,
                    env=env,
                )
            else:
                process = subprocess.Popen(
                    ['x-terminal-emulator', '-e', f'cd {folder_path} && python3 -u {filepath}'],
                    cwd=folder_path,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT,
                    text=True,
                    encoding='utf-8',
                    bufsize=1,
                    env=env,
                )

        def read_output() -> None:
            try:
                for line in iter(process.stdout.readline, ''):
                    if line:
                        output_queue.put(line.strip())
            except Exception:
                pass

        threading.Thread(target=read_output, daemon=True).start()
        return process, output_queue

    @classmethod
    def _run_node(cls, filepath: str, folder_path: str) -> Tuple[subprocess.Popen, queue.Queue]:
        output_queue: queue.Queue = queue.Queue()
        process = subprocess.Popen(
            ['node', str(filepath)],
            cwd=folder_path,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding='utf-8',
            bufsize=1,
        )

        def read_output() -> None:
            try:
                for line in iter(process.stdout.readline, ''):
                    if line:
                        output_queue.put(line.strip())
            except Exception:
                pass

        threading.Thread(target=read_output, daemon=True).start()
        return process, output_queue

    @classmethod
    def open_standalone_browser(
        cls,
        url: str,
        title: str,
        project_dir: Optional[str] = None,
    ):
        try:
            cls.close_project_browsers(project_dir or '')

            browser_process = None
            browser_opened = False

            if platform.system() == 'Windows':
                chrome_paths = [
                    r"C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe",
                    r"C:\\Program Files (x86)\\Google\\Chrome\\Application\\chrome.exe",
                ]
                edge_paths = [
                    r"C:\\Program Files (x86)\\Microsoft\\Edge\\Application\\msedge.exe",
                    r"C:\\Program Files\\Microsoft\\Edge\\Application\\msedge.exe",
                ]

                for chrome_path in chrome_paths:
                    if os.path.exists(chrome_path):
                        try:
                            browser_process = subprocess.Popen(
                                [
                                    chrome_path,
                                    '--new-window',
                                    f'--app={url}',
                                    '--window-size=1200,800',
                                    f'--user-data-dir={CONFIG_DIR / "chrome_profile"}',
                                ],
                                creationflags=subprocess.CREATE_NO_WINDOW,
                                stdout=subprocess.PIPE,
                                stderr=subprocess.PIPE,
                            )
                            time.sleep(1)
                            if browser_process.poll() is None:
                                logger.info("✅ Chrome 成功啟動")
                                browser_opened = True
                                break
                        except Exception as exc:
                            logger.error("啟動 Chrome 失敗: %s", exc)
                            browser_process = None

                if not browser_opened:
                    for edge_path in edge_paths:
                        if os.path.exists(edge_path):
                            try:
                                browser_process = subprocess.Popen(
                                    [
                                        edge_path,
                                        '--new-window',
                                        f'--app={url}',
                                        '--window-size=1200,800',
                                        f'--user-data-dir={CONFIG_DIR / "edge_profile"}',
                                    ],
                                    creationflags=subprocess.CREATE_NO_WINDOW,
                                    stdout=subprocess.PIPE,
                                    stderr=subprocess.PIPE,
                                )
                                time.sleep(1)
                                if browser_process.poll() is None:
                                    logger.info("✅ Edge 成功啟動")
                                    browser_opened = True
                                    break
                                browser_process = None
                            except Exception as exc:
                                logger.error("啟動 Edge 失敗: %s", exc)
                                browser_process = None

                if not browser_opened:
                    logger.warning("未找到 Chrome 或 Edge，使用默認瀏覽器")
                    import webbrowser

                    webbrowser.open_new(url)
                    browser_opened = True

            elif platform.system() == 'Darwin':
                chrome_app = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
                if os.path.exists(chrome_app):
                    browser_process = subprocess.Popen(
                        [
                            chrome_app,
                            '--new-window',
                            f'--app={url}',
                            '--window-size=1200,800',
                            f'--user-data-dir={CONFIG_DIR / "chrome_profile"}',
                        ]
                    )
                    logger.info("✅ macOS Chrome 啟動")
                    browser_opened = True
                else:
                    subprocess.Popen(['open', '-n', '-a', 'Safari', url])
                    logger.info("✅ macOS Safari 啟動")
                    browser_opened = True

            else:
                browsers = [
                    ('google-chrome', 'Google Chrome'),
                    ('google-chrome-stable', 'Google Chrome'),
                    ('chromium-browser', 'Chromium'),
                    ('firefox', 'Firefox'),
                ]

                for browser_cmd, browser_name in browsers:
                    try:
                        result = subprocess.run(['which', browser_cmd], capture_output=True, text=True)
                        if result.returncode == 0:
                            if 'chrome' in browser_cmd or 'chromium' in browser_cmd:
                                browser_process = subprocess.Popen([
                                    browser_cmd,
                                    '--new-window',
                                    f'--app={url}',
                                    '--window-size=1200,800',
                                ])
                            else:
                                browser_process = subprocess.Popen([browser_cmd, url])

                            logger.info("✅ %s 啟動", browser_name)
                            browser_opened = True
                            break
                    except Exception:
                        continue

                if not browser_opened:
                    import webbrowser

                    webbrowser.open_new(url)
                    browser_opened = True

            if browser_process and project_dir:
                cls.add_browser_process(browser_process, project_dir)

            if not browser_opened:
                logger.error("❌ 所有瀏覽器啟動方式都失敗")
                ErrorReporter.generate_report(
                    error_type="BROWSER_LAUNCH_ERROR",
                    error_message="無法啟動任何瀏覽器",
                    context={'url': url, 'platform': platform.system()},
                )
                raise RuntimeError("無法啟動任何瀏覽器")

            return browser_process
        except Exception as exc:
            logger.error("❌ 開啟獨立瀏覽器失敗: %s", exc)
            ErrorReporter.generate_report(
                error_type="BROWSER_LAUNCH_ERROR",
                error_message=str(exc),
                stack_trace=traceback.format_exc(),
                context={'url': url},
            )

            try:
                import webbrowser

                webbrowser.open_new(url)
                logger.info("使用系統默認瀏覽器打開")
            except Exception:
                logger.error("連默認瀏覽器也無法打開")

            return None


__all__ = [
    'ErrorReporter',
    'ConversationManager',
    'ProjectManager',
    'DiagnosticsManager',
    'VSCodeController',
    'ScreenCapture',
    'ProgramManager',
]
