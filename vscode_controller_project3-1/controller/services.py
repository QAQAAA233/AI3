"""AI 與自動化服務模組。"""
from __future__ import annotations

import base64
import io
import json
import os
import platform
import queue
import subprocess
import sys
import threading
import time
import traceback
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import google
import google.generativeai as genai
from google.generativeai.types import GenerationConfig, HarmCategory, HarmBlockThreshold
import mss
import mss.tools
import pyautogui
import pyperclip
import pywinctl as pwc
from PIL import Image

from . import CONFIG_DIR, SCREENSHOT_DIR, logger
from .error_reporting import ErrorReporter
from .json_utils import (
    clean_code_header,
    get_json_schema,
    get_json_system_instruction,
    normalize_code_content,
    sanitize_json_strings,
)
from .managers import ConversationManager, DiagnosticsManager, ProjectManager
from .models import AIConfig, FileOutput, ProcessResult, ProjectOutput

try:
    import google.auth  # type: ignore[attr-defined]
    HAS_GOOGLE_AUTH = True
except ImportError:  # pragma: no cover - 避免測試環境缺少套件
    HAS_GOOGLE_AUTH = False


class GeminiAI:
    """Gemini AI API 管理器"""
    
    @staticmethod
    def configure(config: AIConfig) -> None:
        """配置 Gemini API 連接"""
        if config.connection_method == 'api_key':
            if not config.gemini_api_key:
                raise ValueError("API Key 模式需要提供有效的 API Key")
            genai.configure(api_key=config.gemini_api_key)
            logger.info("已使用 API Key 連接 Gemini")
        elif config.connection_method == 'gcloud_auth':
            if not HAS_GOOGLE_AUTH:
                raise ImportError("缺少 google-auth 套件")
            try:
                credentials, project_id = google.auth.default()
                genai.configure(credentials=credentials)
                logger.info(f"已使用 Google Cloud Auth 連接")
            except google.auth.exceptions.DefaultCredentialsError:
                raise ConnectionError("找不到 Google Cloud 憑證")
        else:
            raise ValueError(f"不支援的連接模式: {config.connection_method}")
    
    @staticmethod
    def generate_content(
        prompt: str, 
        config: AIConfig, 
        files: List[Dict] = None, 
        terminal_output: str = None,
        accumulated_memory: List[str] = None  # ⭐ 新增：累積的長期記憶
    ) -> Tuple[str, Optional[Dict], Optional[Dict]]:
        """呼叫 Gemini API 生成內容（優化版）"""
        try:
            GeminiAI.configure(config)
            
            gen_params = dict(config.generation_params)
            gen_params["response_mime_type"] = "application/json"
            
            # ⭐ 傳遞累積的長期記憶
            system_instruction = get_json_system_instruction(
                getattr(config, 'prompt_mode', 'default'),
                config.system_instruction,
                accumulated_memory  # ⭐ 傳遞累積記憶
            )
            
            gen_config = GenerationConfig(**{
                k: v for k, v in gen_params.items() if v is not None
            })
            
            valid_categories = {
                'HARM_CATEGORY_HARASSMENT',
                'HARM_CATEGORY_HATE_SPEECH', 
                'HARM_CATEGORY_SEXUALLY_EXPLICIT',
                'HARM_CATEGORY_DANGEROUS_CONTENT'
            }
            
            safety_settings = {}
            for category, threshold in config.safety_settings.items():
                if category in valid_categories:
                    try:
                        safety_settings[HarmCategory[category]] = HarmBlockThreshold[threshold]
                    except KeyError:
                        logger.warning(f"跳過無效的安全類別或閾值: {category}={threshold}")
            
            model_name = f"models/{config.model_name}"
            logger.info(f"使用模型: {model_name}")
            
            model_kwargs = {
                "model_name": model_name,
                "safety_settings": safety_settings
            }
            
            if system_instruction:
                model_kwargs["system_instruction"] = system_instruction
            
            model_kwargs["generation_config"] = gen_config
            
            model = genai.GenerativeModel(**model_kwargs)
            
            content_parts = []
            
            if terminal_output:
                terminal_part = f"\n=== 程式執行輸出 (Terminal Output) ===\n{terminal_output}\n=== 輸出結束 ===\n"
                content_parts.append(terminal_part)
                logger.info("已添加Terminal輸出到提示詞")
            
            if files:
                for file_data in files:
                    file_type = file_data.get('type', '')
                    file_content = file_data.get('content', '')
                    file_name = file_data.get('name', '')
                    
                    logger.info(f"處理檔案: {file_name}, 類型: {file_type}")
                    
                    if file_type.startswith('image/'):
                        if ',' in file_content:
                            file_content = file_content.split(',')[1]
                        
                        image_data = base64.b64decode(file_content)
                        image_part = {
                            'mime_type': file_type,
                            'data': base64.b64encode(image_data).decode('utf-8')
                        }
                        content_parts.append(image_part)
                        logger.info(f"已添加圖片: {file_name}")
                    
                    elif file_type == 'application/pdf':
                        if ',' in file_content:
                            file_content = file_content.split(',')[1]
                        
                        pdf_data = base64.b64decode(file_content)
                        pdf_part = {
                            'mime_type': 'application/pdf',
                            'data': base64.b64encode(pdf_data).decode('utf-8')
                        }
                        content_parts.append(pdf_part)
                        logger.info(f"已添加 PDF: {file_name}")
                    
                    elif file_type.startswith('text/') or file_type == 'application/json':
                        try:
                            if file_content.startswith('data:'):
                                if ';base64,' in file_content:
                                    base64_data = file_content.split(';base64,')[1]
                                    text_content = base64.b64decode(base64_data).decode('utf-8', errors='ignore')
                                else:
                                    text_content = file_content.split(',', 1)[1] if ',' in file_content else file_content
                            else:
                                text_content = file_content
                            
                            text_part = f"\n--- 檔案: {file_name} ---\n{text_content}\n--- 檔案結束 ---\n"
                            content_parts.append(text_part)
                            logger.info(f"已添加文本檔案: {file_name}")
                        except Exception as e:
                            logger.error(f"處理文本檔案失敗: {e}")
            
            content_parts.append(prompt)
            
            if len(content_parts) == 1:
                response = model.generate_content(prompt, generation_config=gen_config)
            else:
                response = model.generate_content(content_parts, generation_config=gen_config)
            
            response_text = response.text
            
            json_data = None
            parse_error = None
            try:
                json_data = json.loads(response_text)
                logger.info("成功解析 JSON 回應")
            except json.JSONDecodeError as e:
                parse_error = e
                logger.warning(f"JSON 解析失敗: {e}")
                
                # ⭐ 生成錯誤報告
                ErrorReporter.generate_report(
                    error_type="JSON_DECODE_ERROR",
                    error_message=str(e),
                    ai_response=response_text,
                    stack_trace=traceback.format_exc(),
                    context={'prompt_length': len(prompt), 'files_count': len(files or [])}
                )
                
                try:
                    if '```json' in response_text:
                        response_text = response_text.split('```json')[1].split('```')[0]
                    elif '```' in response_text:
                        response_text = response_text.split('```')[1].split('```')[0]
                    
                    json_data = json.loads(response_text.strip())
                    logger.info("修復後成功解析 JSON")
                except:
                    logger.error("無法解析為JSON")
                    # ⭐ 再次生成詳細報告
                    ErrorReporter.generate_report(
                        error_type="JSON_DECODE_ERROR",
                        error_message="JSON 修復嘗試失敗",
                        ai_response=response_text,
                        stack_trace=traceback.format_exc()
                    )
            
            usage_metadata = None
            if hasattr(response, 'usage_metadata'):
                um = response.usage_metadata
                usage_metadata = {
                    'prompt_token_count': getattr(um, 'prompt_token_count', 0),
                    'candidates_token_count': getattr(um, 'candidates_token_count', 0),
                    'thoughts_token_count': getattr(um, 'thoughts_token_count', 0),
                    'total_token_count': getattr(um, 'total_token_count', 0)
                }
                logger.info(f"Token使用量: {usage_metadata}")
            
            return response_text, json_data, usage_metadata
            
        except Exception as e:
            logger.error(f"Gemini API 呼叫失敗: {e}")
            
            # ⭐ 生成通用錯誤報告
            ErrorReporter.generate_report(
                error_type="API_ERROR",
                error_message=str(e),
                stack_trace=traceback.format_exc(),
                context={'model': config.model_name}
            )
            
            raise

# ============================================
# VS Code 自動化控制模塊
# ============================================

class VSCodeController:
    """VS Code 自動化控制器"""
    
    @staticmethod
    def launch_and_open(folder_path: str, filenames: List[str]) -> Dict[str, Any]:
        """啟動 VS Code 並打開指定檔案"""
        result = {
            "success": False,
            "window_found": False,
            "files_opened": [],
            "message": ""
        }
        
        try:
            logger.info(f"正在啟動 VS Code,資料夾: {folder_path}")
            
            if filenames and len(filenames) > 0:
                first_file = Path(folder_path) / filenames[0]
                subprocess.Popen(
                    ['code', folder_path, str(first_file)],
                    shell=(platform.system() == 'Windows')
                )
            else:
                subprocess.Popen(
                    ['code', folder_path],
                    shell=(platform.system() == 'Windows')
                )
            
            folder_name = os.path.basename(os.path.normpath(folder_path))
            vscode_window = None
            timeout = 15
            start_time = time.time()
            
            logger.info(f"尋找包含 '{folder_name}' 的 VS Code 視窗...")
            
            while time.time() - start_time < timeout:
                all_windows = pwc.getAllWindows()
                
                for window in all_windows:
                    if window.title and 'visual studio code' in window.title.lower():
                        if folder_name.lower() in window.title.lower():
                            vscode_window = window
                            break
                
                if vscode_window:
                    break
                time.sleep(0.5)
            
            if not vscode_window:
                possible_windows = [w for w in pwc.getAllWindows() if w.title and "Visual Studio Code" in w.title]
                if possible_windows:
                    vscode_window = possible_windows[0]
                    logger.warning("使用找到的第一個 VS Code 視窗")
                else:
                    result["message"] = f"在 {timeout} 秒內找不到 VS Code 視窗"
                    logger.warning(result["message"])
                    return result
            
            result["window_found"] = True
            logger.info(f"找到 VS Code 視窗: {vscode_window.title}")
            
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
                    logger.info(f"已打開檔案: {filename}")
            
            if filenames:
                result["files_opened"].insert(0, filenames[0])
            
            result["success"] = True
            result["message"] = f"成功打開 VS Code 和 {len(result['files_opened'])} 個檔案"
            logger.info(result["message"])
            
        except FileNotFoundError:
            result["message"] = "找不到 'code' 命令"
            logger.error(result["message"])
        except Exception as e:
            result["message"] = f"VS Code 控制失敗: {str(e)}"
            logger.error(result["message"])
        
        return result

# ============================================
# 螢幕擷取模塊
# ============================================

class ScreenCapture:
    """螢幕擷取管理器"""
    
    @staticmethod
    def capture_running_programs(window_titles: List[str] = None, project_name: str = None, 
                                project_json: Dict = None) -> List[Dict[str, str]]:
        """擷取程式視窗"""
        screenshots = []
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        
        all_window_titles = []
        if project_json and 'files' in project_json:
            for file in project_json['files']:
                if file.get('web_title'):
                    all_window_titles.append(file['web_title'])
                if file.get('window_title'):
                    all_window_titles.append(file['window_title'])
        
        if window_titles:
            all_window_titles.extend(window_titles)
        
        all_window_titles = list(set(all_window_titles))
        
        logger.info(f"開始擷取程式視窗")
        
        all_windows = pwc.getAllWindows()
        captured_titles = set()
        found_windows = []
        
        browser_keywords = ['chrome', 'edge', 'firefox', 'safari', 'brave']
        
        for window in all_windows:
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
                        "height": min(window.height, 2160)
                    }
                    
                    sct_img = sct.grab(monitor)
                    mss.tools.to_png(sct_img.rgb, sct_img.size, output=str(filepath))
                
                screenshots.append({
                    "name": f"{window.title} ({reason})",
                    "filename": filename,
                    "path": str(filepath),
                    "width": window.width,
                    "height": window.height,
                    "timestamp": timestamp
                })
                
                logger.info(f"成功擷取視窗: {window.title}")
                
            except Exception as e:
                logger.warning(f"擷取視窗失敗: {e}")
        
        logger.info(f"擷取完成,共 {len(screenshots)} 個視窗")
        return screenshots

# ============================================
# 程式碼處理模塊
# ============================================

class CodeProcessor:
    """程式碼解析和處理器（優化版）"""
    
    @staticmethod
    def parse_json_response(json_data: Dict) -> ProjectOutput:
        """解析 JSON 格式的 AI 回應（優化版）"""
        try:
            project_section = json_data.get('專案輸出', json_data)
            files = []
            for file_data in project_section.get('files', []):
                code = file_data.get('code', '')
                
                if isinstance(code, str):
                    # ⭐ 標準化代碼內容
                    code = normalize_code_content(code)
                    # ⭐ 清理代碼開頭的路徑/檔名註釋
                    filetype = file_data.get('filetype', 'text')
                    code = clean_code_header(code, filetype)
                
                files.append(FileOutput(
                    filename=file_data.get('filename', 'untitled.txt'),
                    filetype=file_data.get('filetype', 'text'),
                    code=code,
                    opens_window=file_data.get('opens_window', False),
                    window_title=file_data.get('window_title'),
                    install_requirements=file_data.get('install_requirements'),
                    dependencies=file_data.get('dependencies'),
                    description=file_data.get('description'),
                    run_command=file_data.get('run_command'),
                    is_web_app=file_data.get('is_web_app', False),
                    can_open_standalone=file_data.get('can_open_standalone', False),
                    server_address=file_data.get('server_address'),
                    web_title=file_data.get('web_title')
                ))
            
            return ProjectOutput(
                project_name=project_section.get('project_name', 'untitled_project'),
                description=project_section.get('description', ''),
                files=files,
                main_file=project_section.get('main_file'),
                setup_instructions=project_section.get('setup_instructions'),
                run_instructions=project_section.get('run_instructions')
            )
        
        except Exception as e:
            logger.error(f"解析 JSON 回應失敗: {e}")
            
            # ⭐ 生成錯誤報告
            ErrorReporter.generate_report(
                error_type="PARSE_ERROR",
                error_message=str(e),
                json_data=json_data,
                stack_trace=traceback.format_exc()
            )
            
            raise
    
    @staticmethod
    def install_packages(install_requirements: List[str]) -> List[str]:
        """安裝套件"""
        logs = []
        
        for requirement in install_requirements:
            if not requirement:
                continue
            
            logger.info(f"執行安裝指令: {requirement}")
            
            parts = requirement.split()
            if parts[0] == 'pip':
                full_command = [sys.executable, "-m"] + parts
            else:
                full_command = parts
            
            try:
                result = subprocess.run(
                    full_command,
                    capture_output=True,
                    text=True,
                    check=True,
                    encoding='utf-8'
                )
                
                log = f"✅ 成功執行: {requirement}\n"
                log += result.stdout
                if result.stderr:
                    log += f"\n⚠️ 警告:\n{result.stderr}"
                
                logs.append(log)
                
            except subprocess.CalledProcessError as e:
                error_msg = f"❌ 安裝失敗: {requirement}\n錯誤: {e.stderr}"
                logger.error(error_msg)
                logs.append(error_msg)
        
        return logs
    
    @staticmethod
    def save_project_files(folder_path: str, project: ProjectOutput, is_iteration: bool = False) -> Tuple[List[str], List[str]]:
        """儲存專案檔案"""
        saved_files = []
        updated_files = []
        project_dir = Path(folder_path)
        
        if not is_iteration:
            project_dir = project_dir / project.project_name
        
        project_dir.mkdir(parents=True, exist_ok=True)
        
        for file in project.files:
            filepath = project_dir / file.filename
            filepath.parent.mkdir(parents=True, exist_ok=True)
            
            try:
                file_exists = filepath.exists()
                
                with open(filepath, 'w', encoding='utf-8') as f:
                    f.write(file.code)
                
                if file_exists:
                    logger.info(f"已更新檔案: {filepath}")
                    updated_files.append(str(filepath))
                else:
                    logger.info(f"已建立檔案: {filepath}")
                    saved_files.append(str(filepath))
                
            except IOError as e:
                logger.error(f"儲存檔案失敗 {filepath}: {e}")
                raise
        
        # ⭐ 儲存時也要清理 JSON
        info_file = project_dir / "PROJECT_INFO.json"
        project_info_data = {
            "project_name": project.project_name,
            "description": project.description,
            "main_file": project.main_file,
            "setup_instructions": project.setup_instructions,
            "run_instructions": project.run_instructions,
            "files": [asdict(file) for file in project.files]
        }
        
        # ⭐ 清理 JSON 數據
        cleaned_data = sanitize_json_strings(project_info_data)
        
        with open(info_file, 'w', encoding='utf-8') as f:
            json.dump(cleaned_data, f, indent=2, ensure_ascii=False)
        
        if info_file not in saved_files and info_file not in updated_files:
            saved_files.append(str(info_file))
        
        return saved_files, updated_files

# ============================================
# 程式執行管理
# ============================================

class ProgramManager:
    """管理執行中的程式"""
    
    running_programs = {}
    browser_processes = {}
    
    @classmethod
    def add_program(cls, process, filename, folder_path, window_title=None, output_queue=None):
        """添加程式到管理列表"""
        cls.running_programs[process.pid] = {
            'process': process,
            'filename': filename,
            'folder_path': folder_path,
            'window_title': window_title,
            'start_time': datetime.now(),
            'pid': process.pid,
            'output_queue': output_queue,
            'terminal_output': []
        }
        logger.info(f"已添加程式到管理列表: PID {process.pid}")
    
    @classmethod
    def add_browser_process(cls, process, project_dir: str):
        """添加瀏覽器進程到追蹤"""
        cls.browser_processes[project_dir] = {
            'process': process,
            'pid': process.pid,
            'start_time': datetime.now()
        }
        logger.info(f"已追蹤瀏覽器進程: PID {process.pid}")
    
    @classmethod
    def close_project_browsers(cls, project_dir: str):
        """關閉專案相關的瀏覽器視窗"""
        if project_dir in cls.browser_processes:
            browser_info = cls.browser_processes[project_dir]
            try:
                process = browser_info['process']
                if process.poll() is None:
                    process.terminate()
                    time.sleep(0.3)
                    if process.poll() is None:
                        process.kill()
                logger.info(f"已關閉舊瀏覽器: PID {browser_info['pid']}")
            except Exception as e:
                logger.warning(f"關閉瀏覽器失敗: {e}")
            finally:
                del cls.browser_processes[project_dir]
    
    @classmethod
    def get_terminal_output(cls, pid: int) -> str:
        """獲取指定程序的Terminal輸出"""
        if pid in cls.running_programs:
            return '\n'.join(cls.running_programs[pid]['terminal_output'])
        return ""
    
    @classmethod
    def get_all_terminal_output(cls) -> str:
        """獲取所有運行程序的Terminal輸出"""
        all_output = []
        for pid, info in cls.running_programs.items():
            if info['terminal_output']:
                all_output.append(f"=== PID {pid} ({info['filename']}) ===")
                all_output.extend(info['terminal_output'])
                all_output.append("")
        return '\n'.join(all_output)
    
    @classmethod
    def update_outputs(cls):
        """更新所有程序的輸出"""
        for pid, info in list(cls.running_programs.items()):
            if info['output_queue']:
                try:
                    while not info['output_queue'].empty():
                        line = info['output_queue'].get_nowait()
                        info['terminal_output'].append(line)
                except queue.Empty:
                    pass
    
    @classmethod
    def check_programs(cls):
        """檢查並更新程式狀態"""
        cls.update_outputs()
        
        to_remove = []
        status = []
        
        for pid, info in cls.running_programs.items():
            poll_result = info['process'].poll()
            if poll_result is None:
                run_time = (datetime.now() - info['start_time']).seconds
                status.append({
                    'pid': pid,
                    'filename': info['filename'],
                    'window_title': info.get('window_title'),
                    'status': 'running',
                    'run_time': run_time,
                    'terminal_output': '\n'.join(info['terminal_output'][-50:])
                })
            else:
                to_remove.append(pid)
                status.append({
                    'pid': pid,
                    'filename': info['filename'],
                    'window_title': info.get('window_title'),
                    'status': 'finished',
                    'exit_code': poll_result,
                    'terminal_output': '\n'.join(info['terminal_output'][-50:])
                })
        
        for pid in to_remove:
            del cls.running_programs[pid]
            logger.info(f"程式已結束: PID {pid}")
        
        return status
    
    @classmethod
    def terminate_all(cls):
        """終止所有執行中的程式"""
        terminated = []
        for pid in list(cls.running_programs.keys()):
            if cls.terminate_program(pid):
                terminated.append(pid)
        return terminated
    
    @classmethod
    def terminate_program(cls, pid):
        """終止指定的程式"""
        if pid in cls.running_programs:
            try:
                cls.running_programs[pid]['process'].terminate()
                time.sleep(0.5)
                if cls.running_programs[pid]['process'].poll() is None:
                    cls.running_programs[pid]['process'].kill()
                del cls.running_programs[pid]
                logger.info(f"已終止程式: PID {pid}")
                return True
            except Exception as e:
                logger.error(f"終止程式失敗: {e}")
                return False
        return False
    
    @classmethod
    def run_file(cls, filepath: str, folder_path: str, file_info: FileOutput = None):
        """執行檔案"""
        file_ext = Path(filepath).suffix.lower()
        window_title = file_info.window_title if file_info else None
        
        try:
            if file_info and file_info.is_web_app:
                if file_ext == '.html':
                    # ⭐ 修復：使用 file:// URL 格式
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
                        cls.open_standalone_browser(file_info.server_address, file_info.web_title or "Web App", folder_path)
                
                cls.add_program(process, Path(filepath).name, folder_path, window_title, output_queue)
                return process
            
            elif file_ext == '.py':
                process, output_queue = cls._run_python(filepath, folder_path)
                cls.add_program(process, Path(filepath).name, folder_path, window_title, output_queue)
                return process
            
            elif file_ext == '.js':
                process, output_queue = cls._run_node(filepath, folder_path)
                cls.add_program(process, Path(filepath).name, folder_path, window_title, output_queue)
                return process
            
            elif file_ext == '.html':
                # ⭐ 修復：使用 file:// URL 格式
                file_path = Path(filepath).resolve()
                file_url = file_path.as_uri()
                import webbrowser
                webbrowser.open(file_url)
                return None
            
            else:
                logger.warning(f"不支援直接執行的檔案類型: {file_ext}")
                return None
        
        except Exception as e:
            logger.error(f"執行檔案失敗 {filepath}: {e}")
            
            # ⭐ 生成錯誤報告
            ErrorReporter.generate_report(
                error_type="FILE_EXECUTION_ERROR",
                error_message=str(e),
                stack_trace=traceback.format_exc(),
                context={'filepath': filepath, 'file_ext': file_ext}
            )
            
            raise
    
    @classmethod
    def _run_python(cls, filepath: str, folder_path: str) -> Tuple[subprocess.Popen, queue.Queue]:
        """執行 Python 檔案"""
        output_queue = queue.Queue()
        
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
                env=env
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
                    env=env
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
                    env=env
                )
        
        def read_output():
            try:
                for line in iter(process.stdout.readline, ''):
                    if line:
                        output_queue.put(line.strip())
            except:
                pass
        
        threading.Thread(target=read_output, daemon=True).start()
        
        return process, output_queue
    
    @classmethod
    def _run_node(cls, filepath: str, folder_path: str) -> Tuple[subprocess.Popen, queue.Queue]:
        """執行 Node.js 檔案"""
        output_queue = queue.Queue()
        
        process = subprocess.Popen(
            ['node', str(filepath)],
            cwd=folder_path,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding='utf-8',
            bufsize=1
        )
        
        def read_output():
            try:
                for line in iter(process.stdout.readline, ''):
                    if line:
                        output_queue.put(line.strip())
            except:
                pass
        
        threading.Thread(target=read_output, daemon=True).start()
        
        return process, output_queue
    
    @classmethod
    def open_standalone_browser(cls, url: str, title: str = "Web App", project_dir: str = None):
        """開啟獨立的瀏覽器視窗（增強版）"""
        if project_dir:
            cls.close_project_browsers(project_dir)
        
        browser_process = None
        browser_opened = False
        
        try:
            if platform.system() == 'Windows':
                chrome_paths = [
                    r"C:\Program Files\Google\Chrome\Application\chrome.exe",
                    r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
                    os.path.expanduser(r"~\AppData\Local\Google\Chrome\Application\chrome.exe"),
                ]
                
                edge_paths = [
                    r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
                    r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
                ]
                
                logger.info(f"嘗試打開瀏覽器，URL: {url}")
                
                for chrome_path in chrome_paths:
                    if os.path.exists(chrome_path):
                        logger.info(f"找到 Chrome: {chrome_path}")
                        try:
                            browser_process = subprocess.Popen([
                                chrome_path,
                                '--new-window',
                                f'--app={url}',
                                '--window-size=1200,800',
                                f'--user-data-dir={CONFIG_DIR / "chrome_profile"}',
                            ], 
                            creationflags=subprocess.CREATE_NO_WINDOW,
                            stdout=subprocess.PIPE,
                            stderr=subprocess.PIPE
                            )
                            
                            time.sleep(1)
                            if browser_process.poll() is None:
                                logger.info(f"✅ Chrome 成功啟動，PID: {browser_process.pid}")
                                browser_opened = True
                                break
                            else:
                                logger.warning(f"Chrome 進程立即退出")
                                browser_process = None
                        except Exception as e:
                            logger.error(f"啟動 Chrome 失敗: {e}")
                            browser_process = None
                
                if not browser_opened:
                    for edge_path in edge_paths:
                        if os.path.exists(edge_path):
                            logger.info(f"找到 Edge: {edge_path}")
                            try:
                                browser_process = subprocess.Popen([
                                    edge_path,
                                    '--new-window',
                                    f'--app={url}',
                                    '--window-size=1200,800',
                                    f'--user-data-dir={CONFIG_DIR / "edge_profile"}',
                                ],
                                creationflags=subprocess.CREATE_NO_WINDOW,
                                stdout=subprocess.PIPE,
                                stderr=subprocess.PIPE
                                )
                                
                                time.sleep(1)
                                if browser_process.poll() is None:
                                    logger.info(f"✅ Edge 成功啟動")
                                    browser_opened = True
                                    break
                                else:
                                    logger.warning(f"Edge 進程立即退出")
                                    browser_process = None
                            except Exception as e:
                                logger.error(f"啟動 Edge 失敗: {e}")
                                browser_process = None
                
                if not browser_opened:
                    logger.warning("未找到 Chrome 或 Edge，使用默認瀏覽器")
                    import webbrowser
                    webbrowser.open_new(url)
                    browser_opened = True
            
            elif platform.system() == 'Darwin':
                chrome_app = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
                if os.path.exists(chrome_app):
                    browser_process = subprocess.Popen([
                        chrome_app,
                        '--new-window',
                        f'--app={url}',
                        '--window-size=1200,800',
                        f'--user-data-dir={CONFIG_DIR / "chrome_profile"}'
                    ])
                    logger.info(f"✅ macOS Chrome 啟動")
                    browser_opened = True
                else:
                    subprocess.Popen(['open', '-n', '-a', 'Safari', url])
                    logger.info(f"✅ macOS Safari 啟動")
                    browser_opened = True
            
            else:
                browsers = [
                    ('google-chrome', 'Google Chrome'),
                    ('google-chrome-stable', 'Google Chrome'),
                    ('chromium-browser', 'Chromium'),
                    ('firefox', 'Firefox')
                ]
                
                for browser_cmd, browser_name in browsers:
                    try:
                        result = subprocess.run(['which', browser_cmd], 
                                            capture_output=True, text=True)
                        if result.returncode == 0:
                            if 'chrome' in browser_cmd or 'chromium' in browser_cmd:
                                browser_process = subprocess.Popen([
                                    browser_cmd,
                                    '--new-window',
                                    f'--app={url}',
                                    '--window-size=1200,800'
                                ])
                            else:
                                browser_process = subprocess.Popen([browser_cmd, url])
                            
                            logger.info(f"✅ {browser_name} 啟動")
                            browser_opened = True
                            break
                    except Exception as e:
                        continue
                
                if not browser_opened:
                    import webbrowser
                    webbrowser.open_new(url)
                    browser_opened = True
            
            if browser_process and project_dir:
                cls.add_browser_process(browser_process, project_dir)
            
            if not browser_opened:
                logger.error("❌ 所有瀏覽器啟動方式都失敗")
                
                # ⭐ 生成錯誤報告
                ErrorReporter.generate_report(
                    error_type="BROWSER_LAUNCH_ERROR",
                    error_message="無法啟動任何瀏覽器",
                    context={'url': url, 'platform': platform.system()}
                )
                
                raise RuntimeError("無法啟動任何瀏覽器")
            
            return browser_process
        
        except Exception as e:
            logger.error(f"❌ 開啟獨立瀏覽器失敗: {e}")
            
            # ⭐ 生成錯誤報告
            ErrorReporter.generate_report(
                error_type="BROWSER_LAUNCH_ERROR",
                error_message=str(e),
                stack_trace=traceback.format_exc(),
                context={'url': url}
            )
            
            try:
                import webbrowser
                webbrowser.open_new(url)
                logger.info("使用系統默認瀏覽器打開")
            except:
                logger.error("連默認瀏覽器也無法打開")
            
            return None

# ============================================
# ⭐ 優化：主要處理流程 - 支持累積長期記憶
# ============================================

class ProcessManager:
    """主要處理流程管理器（優化版）"""
    
    @staticmethod
    def run_automation_process(
        folder_path: str,
        prompt: str,
        config: AIConfig,
        files: List[Dict] = None,
        is_iteration: bool = False,
        attach_screenshot: bool = False,
        attach_terminal: bool = False,
        attach_diagnostics: bool = False,
        user_visible_prompt: Optional[str] = None,
        memory_context: Optional[str] = None
    ) -> ProcessResult:
        """執行完整的自動化流程（優化版）"""
        
        result = ProcessResult(success=False, is_iteration=is_iteration)
        
        try:
            files = list(files or [])
            user_files_snapshot = list(files)
            
            normalized_folder = str(Path(folder_path))
            if not is_iteration:
                ProjectManager.ensure_placeholder_project(
                    normalized_folder,
                    Path(normalized_folder).name or '建立中專案'
                )
            
            # 語法診斷
            diagnostics_report: List[Dict[str, Any]] = []
            diagnostics_prompt_block = ''
            
            if attach_diagnostics:
                diagnostics_report, diagnostics_prompt_block = DiagnosticsManager.collect(folder_path)
                result.diagnostics_report = diagnostics_report
                if diagnostics_prompt_block:
                    prompt = f"{diagnostics_prompt_block}\n\n{prompt}"
            
            # 迭代模式自動載入專案檔案
            if is_iteration:
                logger.info("迭代模式:自動載入專案所有檔案")
                project_files = ProjectManager.load_project_files(folder_path)
                if not files:
                    files = []
                files.extend(project_files)
                logger.info(f"已附加 {len(project_files)} 個專案檔案")
            
            # Terminal 輸出
            terminal_output = None
            if attach_terminal:
                terminal_output = ProgramManager.get_all_terminal_output()
                if terminal_output:
                    logger.info("已附加Terminal輸出到AI請求")
                    result.terminal_output = terminal_output
            
            # ⭐ 載入累積的長期記憶
            conversation = ConversationManager.load_conversation(folder_path)
            accumulated_memory = conversation.accumulated_long_term_memory or []
            logger.info(f"載入累積長期記憶：{len(accumulated_memory)} 條")
            
            # 保存用戶消息
            display_prompt = user_visible_prompt or prompt
            metadata_payload = {}
            if memory_context:
                metadata_payload['memory_context'] = memory_context
            if diagnostics_report:
                metadata_payload['diagnostics_report'] = diagnostics_report
            
            ConversationManager.add_message(
                folder_path,
                'user',
                display_prompt,
                files=[{'name': f.get('name'), 'type': f.get('type')} for f in user_files_snapshot],
                terminal_output=terminal_output,
                metadata=metadata_payload if metadata_payload else None
            )
            
            # 迭代模式截圖
            if is_iteration and attach_screenshot:
                project_info = ProjectManager.load_project_info(folder_path)
                if project_info:
                    logger.info("迭代模式:檢查是否有運行中的程序")
                    
                    running_programs = ProgramManager.check_programs()
                    
                    if not running_programs or all(p['status'] != 'running' for p in running_programs):
                        logger.info("沒有運行中的程序,啟動主程式")
                        main_file = project_info.get('main_file')
                        if main_file:
                            main_file_path = Path(folder_path) / main_file
                            
                            main_file_info = None
                            for file_data in project_info.get('files', []):
                                if file_data['filename'] == main_file:
                                    main_file_info = FileOutput(**file_data)
                                    break
                            
                            if main_file_info:
                                ProgramManager.run_file(str(main_file_path), folder_path, main_file_info)
                                
                                if main_file_info.is_web_app:
                                    time.sleep(4)
                                else:
                                    time.sleep(3)
                    else:
                        logger.info("已有運行中的程序,直接使用")
                    
                    window_titles = []
                    for file_data in project_info.get('files', []):
                        if file_data.get('web_title'):
                            window_titles.append(file_data['web_title'])
                    
                    screenshots = ScreenCapture.capture_running_programs(
                        window_titles=window_titles,
                        project_name=project_info.get('project_name'),
                        project_json=project_info
                    )
                    
                    screenshot_files = []
                    for screenshot in screenshots:
                        try:
                            with open(screenshot['path'], 'rb') as f:
                                image_data = f.read()
                                base64_data = base64.b64encode(image_data).decode('utf-8')
                                screenshot_files.append({
                                    'name': screenshot['name'],
                                    'type': 'image/png',
                                    'content': f'data:image/png;base64,{base64_data}'
                                })
                        except Exception as e:
                            logger.error(f"讀取截圖失敗: {e}")
                    
                    if not files:
                        files = []
                    files.extend(screenshot_files)
                    
                    result.screenshots = [s['filename'] for s in screenshots]
            
            # ⭐ Step 1: 呼叫 Gemini AI（傳遞累積記憶）
            logger.info("Step 1: 呼叫 Gemini AI...")
            if files:
                logger.info(f"包含 {len(files)} 個檔案")
            if terminal_output:
                logger.info("包含 Terminal 輸出")
            
            ai_response, json_data, usage_metadata = GeminiAI.generate_content(
                prompt, 
                config, 
                files, 
                terminal_output,
                accumulated_memory  # ⭐ 傳遞累積記憶
            )
            result.ai_response = ai_response
            result.usage_metadata = usage_metadata
            
            # 標準化和清理 JSON
            normalized_json = {}
            if json_data:
                if isinstance(json_data, list):
                    normalized_json = json_data[0] if json_data else {}
                else:
                    normalized_json = json_data
            
            sanitized_json = sanitize_json_strings(normalized_json) if normalized_json else None
            
            if sanitized_json:
                memory_snapshot = sanitized_json.get('核心記憶模塊') or sanitized_json.get('core_memory_module')
                evaluation_snapshot = {
                    '評分': sanitized_json.get('評分'),
                    '內容評價': sanitized_json.get('內容評價'),
                    '扣分原因': sanitized_json.get('扣分原因'),
                    '改進建議': sanitized_json.get('改進建議')
                }
                evaluation_snapshot = {k: v for k, v in evaluation_snapshot.items() if v is not None}
                result.memory_snapshot = memory_snapshot
                result.evaluation_snapshot = evaluation_snapshot
                
                # ⭐ 提取新增的長期記憶
                new_long_term_memory = None
                if memory_snapshot:
                    new_long_term_memory = memory_snapshot.get('長期記憶新增') or memory_snapshot.get('long_term_memory_additions')
                    if new_long_term_memory:
                        logger.info(f"本輪新增長期記憶：{len(new_long_term_memory)} 條")
            
            result.ai_response_json = sanitized_json if sanitized_json else None
            
            # Step 2: 解析 AI 回應
            logger.info("Step 2: 解析 AI 回應...")
            try:
                if sanitized_json:
                    logger.info("使用 JSON 模式解析")
                    project = CodeProcessor.parse_json_response(sanitized_json)
                else:
                    logger.info("嘗試從文本中提取 JSON")
                    try:
                        json_start = ai_response.find('{')
                        json_end = ai_response.rfind('}') + 1
                        if json_start >= 0 and json_end > json_start:
                            json_str = ai_response[json_start:json_end]
                            json_str = json_str.replace('\\n', '\n')
                            json_str = json_str.replace('\\t', '\t')
                            potential_json = json.loads(json_str)
                            if isinstance(potential_json, list):
                                potential_json = potential_json[0] if potential_json else {}
                            sanitized_potential = sanitize_json_strings(potential_json)
                            project = CodeProcessor.parse_json_response(sanitized_potential)
                            result.ai_response_json = sanitized_potential or None
                            logger.info("成功從文本中提取並解析 JSON")
                        else:
                            raise ValueError("無法從回應中找到有效的JSON結構")
                    except json.JSONDecodeError as e:
                        # ⭐ 生成錯誤報告
                        error_report_path = ErrorReporter.generate_report(
                            error_type="JSON_DECODE_ERROR",
                            error_message=str(e),
                            ai_response=ai_response,
                            stack_trace=traceback.format_exc(),
                            context={'is_iteration': is_iteration}
                        )
                        result.error_report_path = str(error_report_path)
                        
                        raise ValueError(f"JSON解析失敗: {e}")
                
                result.project_data = project
                
            except (ValueError, KeyError) as parse_error:
                logger.error(f"解析 AI 回應失敗: {parse_error}")
                result.error = f"解析失敗: {str(parse_error)}"
                
                # ⭐ 生成錯誤報告
                error_report_path = ErrorReporter.generate_report(
                    error_type="PARSE_ERROR",
                    error_message=str(parse_error),
                    ai_response=ai_response,
                    json_data=sanitized_json,
                    stack_trace=traceback.format_exc()
                )
                result.error_report_path = str(error_report_path)
                
                error_details = f"""
=== ❌ 解析錯誤 ===
{parse_error}

=== 🔍 錯誤報告 ===
詳細的錯誤報告已生成：
{error_report_path}

請查看此文件以了解：
1. AI 的原始回應
2. JSON 解析錯誤的詳細位置
3. 建議的修復方法

=== 💡 快速解決方案 ===
1. 檢查錯誤報告文件
2. 確認 AI 回應格式正確
3. 嘗試重新生成或調整提示詞
4. 如問題持續，請考慮切換到其他模型

=== 🤖 AI 回應預覽 ===
請查看下方「AI 回應」區域以檢視完整內容。
                """
                
                result.output = error_details
                
                # 保存錯誤消息
                ConversationManager.add_message(
                    folder_path,
                    'assistant',
                    result.output,
                    metadata={'error': True, 'error_type': 'parse_error', 'error_report': str(error_report_path)}
                )
                
                return result
            
            # Step 3-7: 繼續正常流程...
            if is_iteration:
                logger.info("Step 3: 終止舊程式...")
                terminated = ProgramManager.terminate_all()
                if terminated:
                    logger.info(f"已終止 {len(terminated)} 個程式")
                    time.sleep(1)
            
            logger.info("Step 4: 安裝必要套件...")
            all_requirements = []
            for file in project.files:
                if file.install_requirements:
                    all_requirements.extend(file.install_requirements)
            
            if all_requirements:
                result.installation_logs = CodeProcessor.install_packages(all_requirements)
            
            logger.info("Step 5: 儲存專案檔案...")
            saved_files, updated_files = CodeProcessor.save_project_files(folder_path, project, is_iteration)
            result.files_created = saved_files
            result.files_updated = updated_files
            
            # 確定最終的專案目錄
            if is_iteration:
                final_project_dir = folder_path
            else:
                final_project_dir = str(Path(folder_path) / project.project_name)
            
            # ⭐ 處理對話遷移
            if not is_iteration and folder_path != final_project_dir:
                logger.info("新建專案:遷移對話記錄...")
                temp_conversation = ConversationManager.load_conversation(folder_path)
                if temp_conversation.messages:
                    temp_conversation.project_dir = final_project_dir
                    temp_conversation.project_name = project.project_name
                    ConversationManager.save_conversation(temp_conversation)
                    logger.info(f"已遷移 {len(temp_conversation.messages)} 條對話記錄")
                    
                    try:
                        ConversationManager.delete_conversation_file(folder_path)
                        logger.info("已清理臨時對話檔案")
                    except Exception as e:
                        logger.warning(f"清理臨時對話檔案失敗: {e}")
            
            # 繼續 Step 6-7...
            logger.info("Step 6: 啟動 VS Code...")
            filenames_to_open = [f.filename for f in project.files[:3]]
            vscode_result = VSCodeController.launch_and_open(final_project_dir, filenames_to_open)
            
            logger.info("Step 7: 執行程式...")
            execution_status = "尚未執行"
            execution_detail = ""
            window_titles_to_capture = []
            
            ProjectManager.add_to_project_list(final_project_dir, project.project_name, project.description)
            
            if not is_iteration and folder_path != final_project_dir:
                ProjectManager.remove_from_project_list(folder_path)
            
            if project.main_file:
                main_file_path = Path(final_project_dir) / project.main_file
                
                main_file_info = None
                for file in project.files:
                    if file.filename == project.main_file:
                        main_file_info = file
                        break
                
                if main_file_info:
                    if is_iteration:
                        time.sleep(1)
                    
                    process = ProgramManager.run_file(
                        str(main_file_path),
                        final_project_dir,
                        main_file_info
                    )
                    
                    if process:
                        time.sleep(1)
                        poll_result = process.poll()
                        
                        if poll_result is None:
                            execution_status = "✅ 程式已在背景成功啟動"
                            execution_detail = f"程序 ID (PID): {process.pid}"
                            
                            if main_file_info.opens_window or main_file_info.is_web_app:
                                for file in project.files:
                                    if file.opens_window and file.window_title:
                                        window_titles_to_capture.append(file.window_title)
                                    elif file.is_web_app and file.web_title:
                                        window_titles_to_capture.append(file.web_title)
                                
                                if main_file_info.is_web_app:
                                    time.sleep(5)
                                else:
                                    time.sleep(3)
                                
                                if window_titles_to_capture:
                                    logger.info("開始自動截圖...")
                                    program_screenshots = ScreenCapture.capture_running_programs(
                                        window_titles_to_capture, 
                                        project.project_name,
                                        result.ai_response_json
                                    )
                                    for screenshot in program_screenshots:
                                        result.screenshots.append(screenshot['filename'])
                                    
                                    if program_screenshots:
                                        execution_detail += f"\n已擷取 {len(program_screenshots)} 個視窗"
                                    else:
                                        execution_detail += "\n注意:視窗可能需要更多時間才能顯示"
                            
                            if main_file_info.is_web_app:
                                if main_file_info.server_address:
                                    execution_detail += f"\n🌐 網頁地址: {main_file_info.server_address}"
                                if main_file_info.web_title:
                                    execution_detail += f"\n📖 網頁標題: {main_file_info.web_title}"
                                if not main_file_info.can_open_standalone:
                                    execution_detail += "\n✅ 已自動開啟獨立瀏覽器視窗"
                        
                        elif poll_result == 0:
                            terminal_out = ProgramManager.get_terminal_output(process.pid)
                            execution_status = "✅ 程式執行完成"
                            execution_detail = f"輸出:\n{terminal_out}" if terminal_out else "程式已結束"
                            result.terminal_output = terminal_out
                        else:
                            terminal_out = ProgramManager.get_terminal_output(process.pid)
                            execution_status = "⚠️ 程式執行遇到問題"
                            execution_detail = f"錯誤:\n{terminal_out}" if terminal_out else f"退出碼: {poll_result}"
                            result.terminal_output = terminal_out
                    
                    elif main_file_info.is_web_app and Path(main_file_path).suffix.lower() == '.html':
                        execution_status = "✅ 已開啟 HTML 檔案"
                        execution_detail = f"已在獨立瀏覽器視窗中開啟"
                        if main_file_info.web_title:
                            window_titles_to_capture.append(main_file_info.web_title)
                            time.sleep(3)
                            program_screenshots = ScreenCapture.capture_running_programs(
                                window_titles_to_capture, 
                                project.project_name,
                                result.ai_response_json
                            )
                            for screenshot in program_screenshots:
                                result.screenshots.append(screenshot['filename'])
            
            # 構建輸出報告
            result.output = f"""
=== 🎉 專案{'迭代' if is_iteration else '生成'}成功 ===
📦 專案名稱: {project.project_name}
📝 描述: {project.description}
📂 專案位置: {final_project_dir}
📄 檔案數量: {len(project.files)}
🎯 主檔案: {project.main_file or '無指定'}

=== 📋 檔案列表 ===
"""
            for file in project.files:
                file_icon = "🐍" if file.filetype == "python" else "📄"
                window_info = f" (視窗: {file.window_title})" if file.opens_window and file.window_title else ""
                update_status = " [已更新]" if str(Path(final_project_dir) / file.filename) in updated_files else " [新建]"
                result.output += f"{file_icon} {file.filename}{update_status} - {file.description or file.filetype}{window_info}\n"
            
            result.output += f"""
=== 💻 VS Code 狀態 ===
{'✅ 已開啟' if vscode_result.get('success') else '⚠️ 開啟失敗'}
已開啟檔案: {', '.join(vscode_result.get('files_opened', []))}

=== ⚡ 程式執行狀態 ===
{execution_status}
{execution_detail}
"""
            
            if is_iteration:
                result.output += f"""
=== 🔄 迭代資訊 ===
新建檔案: {len(saved_files)}
更新檔案: {len(updated_files)}
"""
            
            if project.setup_instructions:
                result.output += f"""
=== 🔧 設置指令 ===
{chr(10).join(f"• {inst}" for inst in project.setup_instructions)}
"""
            
            if project.run_instructions:
                result.output += f"""
=== ▶️ 執行指令 ===
{chr(10).join(f"• {inst}" for inst in project.run_instructions)}
"""
            
            if result.installation_logs:
                result.output += f"""
=== 📦 套件安裝日誌 ===
{chr(10).join(result.installation_logs)}
"""
            
            if usage_metadata:
                result.output += f"""
=== 📊 Token 使用量 ===
• 輸入: {usage_metadata.get('prompt_token_count', 0)} tokens
• 輸出: {usage_metadata.get('candidates_token_count', 0)} tokens
• 思考: {usage_metadata.get('thoughts_token_count', 0)} tokens
• 總計: {usage_metadata.get('total_token_count', 0)} tokens
"""
            
            result.output += f"""
=== 💡 操作提示 ===
1. 查看 VS Code 視窗以編輯程式碼
2. 使用「延遲 5 秒後擷取」來擷取運行畫面
3. 查看「執行中的程式」監控程式狀態
4. 如果是圖形程式,應該會看到新視窗出現
5. 查看「監控」中的 Terminal 輸出以了解程式運行狀況
"""
            
            result.success = True
            
            # ⭐ 保存AI回應並更新累積長期記憶
            ConversationManager.add_message(
                final_project_dir,
                'assistant',
                result.output,
                metadata={
                    'project_name': project.project_name,
                    'files_count': len(project.files),
                    **({'memory_snapshot': result.memory_snapshot} if result.memory_snapshot else {}),
                    **({'evaluation_snapshot': result.evaluation_snapshot} if result.evaluation_snapshot else {})
                },
                terminal_output=result.terminal_output,
                usage_metadata=usage_metadata
            )
            
            # ⭐ 更新記憶狀態（包括累積長期記憶）
            if result.memory_snapshot or result.evaluation_snapshot or new_long_term_memory:
                ConversationManager.update_memory_state(
                    final_project_dir,
                    result.memory_snapshot,
                    result.evaluation_snapshot,
                    new_long_term_memory  # ⭐ 傳遞新增的長期記憶
                )
        
        except Exception as e:
            result.error = str(e)
            logger.error(f"處理流程失敗: {e}")
            stack_trace = traceback.format_exc()
            logger.error(stack_trace)
            
            # ⭐ 生成錯誤報告
            error_report_path = ErrorReporter.generate_report(
                error_type="EXECUTION_ERROR",
                error_message=str(e),
                stack_trace=stack_trace,
                context={'is_iteration': is_iteration, 'folder_path': folder_path}
            )
            result.error_report_path = str(error_report_path)
            
            if not result.ai_response:
                result.ai_response = "無法獲取 AI 回應"
            
            # 錯誤情況下也保存消息
            ConversationManager.add_message(
                folder_path,
                'assistant',
                f"執行失敗: {result.error}\n\n錯誤報告已生成: {error_report_path}",
                metadata={
                    'error': True, 
                    'error_type': 'execution_error',
                    'error_report': str(error_report_path)
                }
            )
        
        return result

# ============================================
