"""AI 相關服務與自動化流程管理。"""

from __future__ import annotations

import base64
import json
import logging
import os
import platform
import queue
import subprocess
import sys
import threading
import time
import traceback
from dataclasses import asdict
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import google.generativeai as genai
import mss
import mss.tools
import pyautogui
import pyperclip
import pywinctl as pwc
from google.generativeai.types import GenerationConfig, HarmBlockThreshold, HarmCategory

try:  # noqa: SIM105 - 動態偵測 google-auth 套件
    import google.auth  # type: ignore

    HAS_GOOGLE_AUTH = True
except ImportError:  # pragma: no cover - 避免在測試環境崩潰
    HAS_GOOGLE_AUTH = False

from .diagnostics import DiagnosticsManager, ErrorReporter
from .environment import CONFIG_DIR, SCREENSHOT_DIR
from .managers import ConversationManager, ProjectManager
from .models import AIConfig, FileOutput, ProcessResult, ProjectOutput
from .utils import clean_code_header, get_json_system_instruction, normalize_code_content, sanitize_json_strings

logger = logging.getLogger(__name__)


# ============================================
# Gemini AI 模塊
# ============================================


class GeminiAI:
    """Gemini AI API 管理器"""

    @staticmethod
    def configure(config: AIConfig) -> None:
        """配置 Gemini API 連接"""
        if config.connection_method == "api_key":
            if not config.gemini_api_key:
                raise ValueError("API Key 模式需要提供有效的 API Key")
            genai.configure(api_key=config.gemini_api_key)
            logger.info("已使用 API Key 連接 Gemini")
        elif config.connection_method == "gcloud_auth":
            if not HAS_GOOGLE_AUTH:
                raise ImportError("缺少 google-auth 套件")
            try:
                credentials, project_id = google.auth.default()  # type: ignore[attr-defined]
                genai.configure(credentials=credentials)
                logger.info("已使用 Google Cloud Auth 連接")
            except google.auth.exceptions.DefaultCredentialsError:  # type: ignore[attr-defined]
                raise ConnectionError("找不到 Google Cloud 憑證")
        else:
            raise ValueError(f"不支援的連接模式: {config.connection_method}")

    @staticmethod
    def generate_content(
        prompt: str,
        config: AIConfig,
        files: List[Dict] = None,
        terminal_output: str = None,
        accumulated_memory: List[str] = None,
    ) -> Tuple[str, Optional[Dict], Optional[Dict]]:
        """呼叫 Gemini API 生成內容（優化版）"""
        try:
            GeminiAI.configure(config)

            gen_params = dict(config.generation_params)
            gen_params["response_mime_type"] = "application/json"

            system_instruction = get_json_system_instruction(
                getattr(config, "prompt_mode", "default"),
                config.system_instruction,
                accumulated_memory,
            )

            gen_config = GenerationConfig(**{k: v for k, v in gen_params.items() if v is not None})

            valid_categories = {
                "HARM_CATEGORY_HARASSMENT",
                "HARM_CATEGORY_HATE_SPEECH",
                "HARM_CATEGORY_SEXUALLY_EXPLICIT",
                "HARM_CATEGORY_DANGEROUS_CONTENT",
            }

            safety_settings = {}
            for category, threshold in config.safety_settings.items():
                if category in valid_categories:
                    try:
                        safety_settings[HarmCategory[category]] = HarmBlockThreshold[threshold]
                    except KeyError:
                        logger.warning("跳過無效的安全類別或閾值: %s=%s", category, threshold)

            model_name = f"models/{config.model_name}"
            logger.info("使用模型: %s", model_name)

            model_kwargs = {
                "model_name": model_name,
                "safety_settings": safety_settings,
            }

            if system_instruction:
                model_kwargs["system_instruction"] = system_instruction

            model_kwargs["generation_config"] = gen_config

            model = genai.GenerativeModel(**model_kwargs)

            content_parts: List[Any] = []

            if terminal_output:
                terminal_part = f"\n=== 程式執行輸出 (Terminal Output) ===\n{terminal_output}\n=== 輸出結束 ===\n"
                content_parts.append(terminal_part)
                logger.info("已添加Terminal輸出到提示詞")

            if files:
                for file_data in files:
                    file_type = file_data.get("type", "")
                    file_content = file_data.get("content", "")
                    file_name = file_data.get("name", "")

                    logger.info("處理檔案: %s, 類型: %s", file_name, file_type)

                    if file_type.startswith("image/"):
                        if "," in file_content:
                            file_content = file_content.split(",")[1]

                        image_data = base64.b64decode(file_content)
                        image_part = {
                            "mime_type": file_type,
                            "data": base64.b64encode(image_data).decode("utf-8"),
                        }
                        content_parts.append(image_part)
                        logger.info("已添加圖片: %s", file_name)

                    elif file_type == "application/pdf":
                        if "," in file_content:
                            file_content = file_content.split(",")[1]

                        pdf_data = base64.b64decode(file_content)
                        pdf_part = {
                            "mime_type": "application/pdf",
                            "data": base64.b64encode(pdf_data).decode("utf-8"),
                        }
                        content_parts.append(pdf_part)
                        logger.info("已添加 PDF: %s", file_name)

                    elif file_type.startswith("text/") or file_type == "application/json":
                        try:
                            if file_content.startswith("data:"):
                                if ";base64," in file_content:
                                    base64_data = file_content.split(";base64,")[1]
                                    text_content = base64.b64decode(base64_data).decode("utf-8", errors="ignore")
                                else:
                                    text_content = file_content.split(",", 1)[1] if "," in file_content else file_content
                            else:
                                text_content = file_content

                            text_part = f"\n--- 檔案: {file_name} ---\n{text_content}\n--- 檔案結束 ---\n"
                            content_parts.append(text_part)
                            logger.info("已添加文本檔案: %s", file_name)
                        except Exception as exc:
                            logger.error("處理文本檔案失敗: %s", exc)

            content_parts.append(prompt)

            if len(content_parts) == 1:
                response = model.generate_content(prompt, generation_config=gen_config)
            else:
                response = model.generate_content(content_parts, generation_config=gen_config)

            response_text = response.text

            json_data = None
            try:
                json_data = json.loads(response_text)
                logger.info("成功解析 JSON 回應")
            except json.JSONDecodeError as exc:
                logger.warning("JSON 解析失敗: %s", exc)

                ErrorReporter.generate_report(
                    error_type="JSON_DECODE_ERROR",
                    error_message=str(exc),
                    ai_response=response_text,
                    stack_trace=traceback.format_exc(),
                    context={"prompt_length": len(prompt), "files_count": len(files or [])},
                )

                try:
                    if "```json" in response_text:
                        response_text = response_text.split("```json")[1].split("```")[0]
                    elif "```" in response_text:
                        response_text = response_text.split("```")[1].split("```")[0]

                    json_data = json.loads(response_text.strip())
                    logger.info("修復後成功解析 JSON")
                except Exception:
                    logger.error("無法解析為JSON")
                    ErrorReporter.generate_report(
                        error_type="JSON_DECODE_ERROR",
                        error_message="JSON 修復嘗試失敗",
                        ai_response=response_text,
                        stack_trace=traceback.format_exc(),
                    )

            usage_metadata = None
            if hasattr(response, "usage_metadata"):
                um = response.usage_metadata
                usage_metadata = {
                    "prompt_token_count": getattr(um, "prompt_token_count", 0),
                    "candidates_token_count": getattr(um, "candidates_token_count", 0),
                    "thoughts_token_count": getattr(um, "thoughts_token_count", 0),
                    "total_token_count": getattr(um, "total_token_count", 0),
                }
                logger.info("Token使用量: %s", usage_metadata)

            return response_text, json_data, usage_metadata

        except Exception as exc:
            logger.error("Gemini API 呼叫失敗: %s", exc)

            ErrorReporter.generate_report(
                error_type="API_ERROR",
                error_message=str(exc),
                stack_trace=traceback.format_exc(),
                context={"model": config.model_name},
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
            "message": "",
        }

        try:
            logger.info("正在啟動 VS Code,資料夾: %s", folder_path)

            if filenames and len(filenames) > 0:
                first_file = Path(folder_path) / filenames[0]
                subprocess.Popen(
                    ["code", folder_path, str(first_file)],
                    shell=(platform.system() == "Windows"),
                )
            else:
                subprocess.Popen(
                    ["code", folder_path],
                    shell=(platform.system() == "Windows"),
                )

            folder_name = os.path.basename(os.path.normpath(folder_path))
            vscode_window = None
            timeout = 15
            start_time = time.time()

            logger.info("尋找包含 '%s' 的 VS Code 視窗...", folder_name)

            while time.time() - start_time < timeout:
                all_windows = pwc.getAllWindows()

                for window in all_windows:
                    if window.title and "visual studio code" in window.title.lower():
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
            logger.info("找到 VS Code 視窗: %s", vscode_window.title)

            if vscode_window.isMinimized:
                vscode_window.restore()
            vscode_window.activate()
            time.sleep(1)

            if len(filenames) > 1:
                hotkey_ctrl = "command" if platform.system() == "Darwin" else "ctrl"

                for filename in filenames[1:3]:
                    time.sleep(0.5)
                    pyautogui.hotkey(hotkey_ctrl, "p")
                    time.sleep(0.3)

                    pyperclip.copy(filename)
                    pyautogui.hotkey(hotkey_ctrl, "v")
                    time.sleep(0.2)

                    pyautogui.press("enter")

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


# ============================================
# 螢幕擷取模塊
# ============================================


class ScreenCapture:
    """螢幕擷取管理器"""

    @staticmethod
    def capture_running_programs(
        window_titles: List[str] = None,
        project_name: str = None,
        project_json: Dict = None,
    ) -> List[Dict[str, str]]:
        """擷取程式視窗"""
        screenshots: List[Dict[str, str]] = []
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")

        all_window_titles: List[str] = []
        if project_json and "files" in project_json:
            for file in project_json["files"]:
                if file.get("web_title"):
                    all_window_titles.append(file["web_title"])
                if file.get("window_title"):
                    all_window_titles.append(file["window_title"])

        if window_titles:
            all_window_titles.extend(window_titles)

        all_window_titles = list(set(all_window_titles))

        logger.info("開始擷取程式視窗")

        all_windows = pwc.getAllWindows()
        captured_titles = set()
        found_windows: List[Tuple[Any, str]] = []

        browser_keywords = ["chrome", "edge", "firefox", "safari", "brave"]

        for window in all_windows:
            if not window.title:
                continue

            window_title_lower = window.title.lower()
            should_capture = False
            capture_reason = ""

            if project_name and "visual studio code" in window_title_lower:
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

                safe_title = window.title[:50].replace(" ", "_").replace("/", "_")
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

        logger.info("擷取完成,共 %s 個視窗", len(screenshots))
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
            project_section = json_data.get("專案輸出", json_data)
            files: List[FileOutput] = []
            for file_data in project_section.get("files", []):
                code = file_data.get("code", "")

                if isinstance(code, str):
                    code = normalize_code_content(code)
                    filetype = file_data.get("filetype", "text")
                    code = clean_code_header(code, filetype)

                files.append(
                    FileOutput(
                        filename=file_data.get("filename", "untitled.txt"),
                        filetype=file_data.get("filetype", "text"),
                        code=code,
                        opens_window=file_data.get("opens_window", False),
                        window_title=file_data.get("window_title"),
                        install_requirements=file_data.get("install_requirements"),
                        dependencies=file_data.get("dependencies"),
                        description=file_data.get("description"),
                        run_command=file_data.get("run_command"),
                        is_web_app=file_data.get("is_web_app", False),
                        can_open_standalone=file_data.get("can_open_standalone", False),
                        server_address=file_data.get("server_address"),
                        web_title=file_data.get("web_title"),
                    )
                )

            return ProjectOutput(
                project_name=project_section.get("project_name", "untitled_project"),
                description=project_section.get("description", ""),
                files=files,
                main_file=project_section.get("main_file"),
                setup_instructions=project_section.get("setup_instructions"),
                run_instructions=project_section.get("run_instructions"),
            )

        except Exception as exc:
            logger.error("解析 JSON 回應失敗: %s", exc)

            ErrorReporter.generate_report(
                error_type="PARSE_ERROR",
                error_message=str(exc),
                json_data=json_data,
                stack_trace=traceback.format_exc(),
            )

            raise

    @staticmethod
    def install_packages(install_requirements: List[str]) -> List[str]:
        """安裝套件"""
        logs: List[str] = []

        for requirement in install_requirements:
            if not requirement:
                continue

            logger.info("執行安裝指令: %s", requirement)

            parts = requirement.split()
            if parts[0] == "pip":
                full_command = [sys.executable, "-m"] + parts
            else:
                full_command = parts

            try:
                result = subprocess.run(
                    full_command,
                    capture_output=True,
                    text=True,
                    check=True,
                    encoding="utf-8",
                )

                log = f"✅ 成功執行: {requirement}\n"
                log += result.stdout
                if result.stderr:
                    log += f"\n⚠️ 警告:\n{result.stderr}"

                logs.append(log)

            except subprocess.CalledProcessError as exc:
                error_msg = f"❌ 安裝失敗: {requirement}\n錯誤: {exc.stderr}"
                logger.error(error_msg)
                logs.append(error_msg)

        return logs

    @staticmethod
    def save_project_files(
        folder_path: str,
        project: ProjectOutput,
        is_iteration: bool = False,
    ) -> Tuple[List[str], List[str]]:
        """儲存專案檔案"""
        saved_files: List[str] = []
        updated_files: List[str] = []
        project_dir = Path(folder_path)

        if not is_iteration:
            project_dir = project_dir / project.project_name

        project_dir.mkdir(parents=True, exist_ok=True)

        for file in project.files:
            filepath = project_dir / file.filename
            filepath.parent.mkdir(parents=True, exist_ok=True)

            try:
                file_exists = filepath.exists()

                with open(filepath, "w", encoding="utf-8") as handle:
                    handle.write(file.code)

                if file_exists:
                    logger.info("已更新檔案: %s", filepath)
                    updated_files.append(str(filepath))
                else:
                    logger.info("已建立檔案: %s", filepath)
                    saved_files.append(str(filepath))

            except IOError as exc:
                logger.error("儲存檔案失敗 %s: %s", filepath, exc)
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


# ============================================
# 程式執行管理
# ============================================


class ProgramManager:
    """管理執行中的程式"""

    running_programs: Dict[int, Dict[str, Any]] = {}
    browser_processes: Dict[str, Dict[str, Any]] = {}

    @classmethod
    def add_program(cls, process, filename, folder_path, window_title=None, output_queue=None):
        """添加程式到管理列表"""
        cls.running_programs[process.pid] = {
            "process": process,
            "filename": filename,
            "folder_path": folder_path,
            "window_title": window_title,
            "start_time": datetime.now(),
            "pid": process.pid,
            "output_queue": output_queue,
            "terminal_output": [],
        }
        logger.info("已添加程式到管理列表: PID %s", process.pid)

    @classmethod
    def add_browser_process(cls, process, project_dir: str):
        """添加瀏覽器進程到追蹤"""
        cls.browser_processes[project_dir] = {
            "process": process,
            "pid": process.pid,
            "start_time": datetime.now(),
        }
        logger.info("已追蹤瀏覽器進程: PID %s", process.pid)

    @classmethod
    def close_project_browsers(cls, project_dir: str):
        """關閉專案相關的瀏覽器視窗"""
        if project_dir in cls.browser_processes:
            browser_info = cls.browser_processes[project_dir]
            try:
                process = browser_info["process"]
                if process.poll() is None:
                    process.terminate()
                    time.sleep(0.3)
                    if process.poll() is None:
                        process.kill()
                logger.info("已關閉舊瀏覽器: PID %s", browser_info["pid"])
            except Exception as exc:
                logger.warning("關閉瀏覽器失敗: %s", exc)
            finally:
                del cls.browser_processes[project_dir]

    @classmethod
    def get_terminal_output(cls, pid: int) -> str:
        """獲取指定程序的Terminal輸出"""
        if pid in cls.running_programs:
            return "\n".join(cls.running_programs[pid]["terminal_output"])
        return ""

    @classmethod
    def get_all_terminal_output(cls) -> str:
        """獲取所有運行程序的Terminal輸出"""
        all_output = []
        for pid, info in cls.running_programs.items():
            if info["terminal_output"]:
                all_output.append(f"=== PID {pid} ({info['filename']}) ===")
                all_output.extend(info["terminal_output"])
                all_output.append("")
        return "\n".join(all_output)

    @classmethod
    def update_outputs(cls):
        """更新所有程序的輸出"""
        for pid, info in list(cls.running_programs.items()):
            if info["output_queue"]:
                try:
                    while not info["output_queue"].empty():
                        line = info["output_queue"].get_nowait()
                        info["terminal_output"].append(line)
                except queue.Empty:
                    pass

    @classmethod
    def check_programs(cls):
        """檢查並更新程式狀態"""
        cls.update_outputs()

        to_remove: List[int] = []
        status: List[Dict[str, Any]] = []

        for pid, info in cls.running_programs.items():
            poll_result = info["process"].poll()
            if poll_result is None:
                run_time = (datetime.now() - info["start_time"]).seconds
                status.append(
                    {
                        "pid": pid,
                        "filename": info["filename"],
                        "window_title": info.get("window_title"),
                        "status": "running",
                        "run_time": run_time,
                        "terminal_output": "\n".join(info["terminal_output"][-50:]),
                    }
                )
            else:
                to_remove.append(pid)
                status.append(
                    {
                        "pid": pid,
                        "filename": info["filename"],
                        "window_title": info.get("window_title"),
                        "status": "finished",
                        "exit_code": poll_result,
                        "terminal_output": "\n".join(info["terminal_output"][-50:]),
                    }
                )

        for pid in to_remove:
            del cls.running_programs[pid]
            logger.info("程式已結束: PID %s", pid)

        return status

    @classmethod
    def terminate_all(cls):
        """終止所有執行中的程式"""
        terminated: List[int] = []
        for pid in list(cls.running_programs.keys()):
            if cls.terminate_program(pid):
                terminated.append(pid)
        return terminated

    @classmethod
    def terminate_program(cls, pid):
        """終止指定的程式"""
        if pid in cls.running_programs:
            try:
                cls.running_programs[pid]["process"].terminate()
                time.sleep(0.5)
                if cls.running_programs[pid]["process"].poll() is None:
                    cls.running_programs[pid]["process"].kill()
                del cls.running_programs[pid]
                logger.info("已終止程式: PID %s", pid)
                return True
            except Exception as exc:
                logger.error("終止程式失敗: %s", exc)
                return False
        return False

    @classmethod
    def run_file(cls, filepath: str, folder_path: str, file_info: FileOutput = None):
        """執行檔案"""
        file_ext = Path(filepath).suffix.lower()
        window_title = file_info.window_title if file_info else None

        try:
            if file_info and file_info.is_web_app:
                if file_ext == ".html":
                    file_path = Path(filepath).resolve()
                    file_url = file_path.as_uri()
                    cls.open_standalone_browser(file_url, file_info.web_title or "Web App", folder_path)
                    return None

                elif file_info.can_open_standalone:
                    if file_ext == ".py":
                        process, output_queue = cls._run_python(filepath, folder_path)
                    elif file_ext == ".js":
                        process, output_queue = cls._run_node(filepath, folder_path)
                    else:
                        return None

                else:
                    if file_ext == ".py":
                        process, output_queue = cls._run_python(filepath, folder_path)
                    elif file_ext == ".js":
                        process, output_queue = cls._run_node(filepath, folder_path)
                    else:
                        return None

            elif file_ext == ".py":
                process, output_queue = cls._run_python(filepath, folder_path)
            elif file_ext == ".js":
                process, output_queue = cls._run_node(filepath, folder_path)
            else:
                if file_info and file_info.run_command:
                    command = file_info.run_command.split()
                    process = subprocess.Popen(
                        command,
                        cwd=folder_path,
                        stdout=subprocess.PIPE,
                        stderr=subprocess.STDOUT,
                        text=True,
                        encoding="utf-8",
                    )
                    output_queue = queue.Queue()

                    def read_output():
                        try:
                            assert process.stdout is not None
                            for line in process.stdout:
                                output_queue.put(line.rstrip())
                        except Exception as exc:
                            logger.warning("讀取程式輸出時發生錯誤: %s", exc)

                    threading.Thread(target=read_output, daemon=True).start()

                    cls.add_program(process, filepath, folder_path, window_title, output_queue)
                    return process, output_queue
                else:
                    logger.warning("不支援的檔案類型: %s", filepath)
                    return None

            cls.add_program(process, filepath, folder_path, window_title, output_queue)
            return process, output_queue

        except Exception as exc:
            logger.error("執行檔案失敗: %s", exc)
            return None

    @classmethod
    def _run_python(cls, filepath: str, folder_path: str) -> Tuple[subprocess.Popen, queue.Queue]:
        command = [sys.executable, filepath]
        process = subprocess.Popen(
            command,
            cwd=folder_path,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
        )
        output_queue: queue.Queue = queue.Queue()

        def read_output():
            try:
                assert process.stdout is not None
                for line in process.stdout:
                    output_queue.put(line.rstrip())
            except Exception as exc:
                logger.warning("讀取程式輸出時發生錯誤: %s", exc)

        threading.Thread(target=read_output, daemon=True).start()
        return process, output_queue

    @classmethod
    def _run_node(cls, filepath: str, folder_path: str) -> Tuple[subprocess.Popen, queue.Queue]:
        command = ["node", filepath]
        process = subprocess.Popen(
            command,
            cwd=folder_path,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
        )
        output_queue: queue.Queue = queue.Queue()

        def read_output():
            try:
                assert process.stdout is not None
                for line in process.stdout:
                    output_queue.put(line.rstrip())
            except Exception as exc:
                logger.warning("讀取程式輸出時發生錯誤: %s", exc)

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
            if platform.system() == "Windows":
                chrome_paths = [
                    r"C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe",
                    r"C:\\Program Files (x86)\\Google\\Chrome\\Application\\chrome.exe",
                    os.path.expanduser(r"~\\AppData\\Local\\Google\\Chrome\\Application\\chrome.exe"),
                ]

                edge_paths = [
                    r"C:\\Program Files (x86)\\Microsoft\\Edge\\Application\\msedge.exe",
                    r"C:\\Program Files\\Microsoft\\Edge\\Application\\msedge.exe",
                ]

                logger.info("嘗試打開瀏覽器，URL: %s", url)

                for chrome_path in chrome_paths:
                    if os.path.exists(chrome_path):
                        logger.info("找到 Chrome: %s", chrome_path)
                        try:
                            browser_process = subprocess.Popen(
                                [
                                    chrome_path,
                                    "--new-window",
                                    f"--app={url}",
                                    "--window-size=1200,800",
                                    f"--user-data-dir={CONFIG_DIR / 'chrome_profile'}",
                                ],
                                creationflags=subprocess.CREATE_NO_WINDOW,
                                stdout=subprocess.PIPE,
                                stderr=subprocess.PIPE,
                            )

                            time.sleep(1)
                            if browser_process.poll() is None:
                                logger.info("✅ Chrome 成功啟動，PID: %s", browser_process.pid)
                                browser_opened = True
                                break
                            else:
                                logger.warning("Chrome 進程立即退出")
                                browser_process = None
                        except Exception as exc:
                            logger.error("啟動 Chrome 失敗: %s", exc)
                            browser_process = None

                if not browser_opened:
                    for edge_path in edge_paths:
                        if os.path.exists(edge_path):
                            logger.info("找到 Edge: %s", edge_path)
                            try:
                                browser_process = subprocess.Popen(
                                    [
                                        edge_path,
                                        "--new-window",
                                        f"--app={url}",
                                        "--window-size=1200,800",
                                        f"--user-data-dir={CONFIG_DIR / 'edge_profile'}",
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
                                else:
                                    logger.warning("Edge 進程立即退出")
                                    browser_process = None
                            except Exception as exc:
                                logger.error("啟動 Edge 失敗: %s", exc)
                                browser_process = None

                if not browser_opened:
                    logger.warning("未找到 Chrome 或 Edge，使用默認瀏覽器")
                    import webbrowser

                    webbrowser.open_new(url)
                    browser_opened = True

            elif platform.system() == "Darwin":
                chrome_app = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
                if os.path.exists(chrome_app):
                    browser_process = subprocess.Popen(
                        [
                            chrome_app,
                            "--new-window",
                            f"--app={url}",
                            "--window-size=1200,800",
                            f"--user-data-dir={CONFIG_DIR / 'chrome_profile'}",
                        ]
                    )
                    logger.info("✅ macOS Chrome 啟動")
                    browser_opened = True
                else:
                    subprocess.Popen(["open", "-n", "-a", "Safari", url])
                    logger.info("✅ macOS Safari 啟動")
                    browser_opened = True

            else:
                browsers = [
                    ("google-chrome", "Google Chrome"),
                    ("google-chrome-stable", "Google Chrome"),
                    ("chromium-browser", "Chromium"),
                    ("firefox", "Firefox"),
                ]

                for browser_cmd, browser_name in browsers:
                    try:
                        result = subprocess.run(["which", browser_cmd], capture_output=True, text=True)
                        if result.returncode == 0:
                            if "chrome" in browser_cmd or "chromium" in browser_cmd:
                                browser_process = subprocess.Popen(
                                    [
                                        browser_cmd,
                                        "--new-window",
                                        f"--app={url}",
                                        "--window-size=1200,800",
                                    ]
                                )
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
                    context={"url": url, "platform": platform.system()},
                )

                raise RuntimeError("無法啟動任何瀏覽器")

            return browser_process

        except Exception as exc:
            logger.error("❌ 開啟獨立瀏覽器失敗: %s", exc)

            ErrorReporter.generate_report(
                error_type="BROWSER_LAUNCH_ERROR",
                error_message=str(exc),
                stack_trace=traceback.format_exc(),
                context={"url": url},
            )

            try:
                import webbrowser

                webbrowser.open_new(url)
                logger.info("使用系統默認瀏覽器打開")
            except Exception:
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
        memory_context: Optional[str] = None,
    ) -> ProcessResult:
        result = ProcessResult(success=False, is_iteration=is_iteration)

        try:
            files = list(files or [])
            user_files_snapshot = list(files)

            normalized_folder = str(Path(folder_path))
            if not is_iteration:
                ProjectManager.ensure_placeholder_project(
                    normalized_folder,
                    Path(normalized_folder).name or "建立中專案",
                )

            diagnostics_report: List[Dict[str, Any]] = []
            diagnostics_prompt_block = ""

            if attach_diagnostics:
                diagnostics_report, diagnostics_prompt_block = DiagnosticsManager.collect(folder_path)
                result.diagnostics_report = diagnostics_report
                if diagnostics_prompt_block:
                    prompt = f"{diagnostics_prompt_block}\n\n{prompt}"

            if is_iteration:
                logger.info("迭代模式:自動載入專案所有檔案")
                project_files = ProjectManager.load_project_files(folder_path)
                if not files:
                    files = []
                files.extend(project_files)
                logger.info("已附加 %s 個專案檔案", len(project_files))

            terminal_output = None
            if attach_terminal:
                terminal_output = ProgramManager.get_all_terminal_output()
                if terminal_output:
                    logger.info("已附加Terminal輸出到AI請求")
                    result.terminal_output = terminal_output

            conversation = ConversationManager.load_conversation(folder_path)
            accumulated_memory = conversation.accumulated_long_term_memory or []
            logger.info("載入累積長期記憶：%s 條", len(accumulated_memory))

            ai_response, json_data, usage_metadata = GeminiAI.generate_content(
                prompt,
                config,
                files,
                terminal_output,
                accumulated_memory,
            )
            result.ai_response = ai_response
            result.usage_metadata = usage_metadata

            normalized_json: Dict[str, Any] = {}
            if json_data:
                if isinstance(json_data, list):
                    normalized_json = json_data[0] if json_data else {}
                else:
                    normalized_json = json_data

            sanitized_json = sanitize_json_strings(normalized_json) if normalized_json else None

            if sanitized_json:
                memory_snapshot = sanitized_json.get("核心記憶模塊") or sanitized_json.get("core_memory_module")
                evaluation_snapshot = {
                    "評分": sanitized_json.get("評分"),
                    "內容評價": sanitized_json.get("內容評價"),
                    "扣分原因": sanitized_json.get("扣分原因"),
                    "改進建議": sanitized_json.get("改進建議"),
                }
                evaluation_snapshot = {k: v for k, v in evaluation_snapshot.items() if v is not None}
                result.memory_snapshot = memory_snapshot
                result.evaluation_snapshot = evaluation_snapshot

                new_long_term_memory = None
                if memory_snapshot:
                    new_long_term_memory = memory_snapshot.get("長期記憶新增") or memory_snapshot.get("long_term_memory_additions")
                    if new_long_term_memory:
                        logger.info("本輪新增長期記憶：%s 條", len(new_long_term_memory))
            else:
                new_long_term_memory = None

            result.ai_response_json = sanitized_json if sanitized_json else None

            logger.info("Step 2: 解析 AI 回應...")
            try:
                if sanitized_json:
                    logger.info("使用 JSON 模式解析")
                    project = CodeProcessor.parse_json_response(sanitized_json)
                else:
                    logger.info("嘗試從文本中提取 JSON")
                    try:
                        json_start = ai_response.find("{")
                        json_end = ai_response.rfind("}") + 1
                        if json_start >= 0 and json_end > json_start:
                            json_str = ai_response[json_start:json_end]
                            json_str = json_str.replace("\\n", "\n")
                            json_str = json_str.replace("\\t", "\t")
                            potential_json = json.loads(json_str)
                            if isinstance(potential_json, list):
                                potential_json = potential_json[0] if potential_json else {}
                            sanitized_potential = sanitize_json_strings(potential_json)
                            project = CodeProcessor.parse_json_response(sanitized_potential)
                            result.ai_response_json = sanitized_potential or None
                            logger.info("成功從文本中提取並解析 JSON")
                        else:
                            raise ValueError("無法從回應中找到有效的JSON結構")
                    except json.JSONDecodeError as exc:
                        error_report_path = ErrorReporter.generate_report(
                            error_type="JSON_DECODE_ERROR",
                            error_message=str(exc),
                            ai_response=ai_response,
                            stack_trace=traceback.format_exc(),
                            context={"is_iteration": is_iteration},
                        )
                        result.error_report_path = str(error_report_path)
                        raise ValueError(f"JSON解析失敗: {exc}")

                result.project_data = project

            except (ValueError, KeyError) as parse_error:
                logger.error("解析 AI 回應失敗: %s", parse_error)
                result.error = f"解析失敗: {parse_error}"

                error_report_path = ErrorReporter.generate_report(
                    error_type="PARSE_ERROR",
                    error_message=str(parse_error),
                    ai_response=ai_response,
                    json_data=sanitized_json,
                    stack_trace=traceback.format_exc(),
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

                ConversationManager.add_message(
                    folder_path,
                    "assistant",
                    result.output,
                    metadata={"error": True, "error_type": "parse_error", "error_report": str(error_report_path)},
                )

                return result

            if is_iteration:
                logger.info("Step 3: 終止舊程式...")
                terminated = ProgramManager.terminate_all()
                if terminated:
                    logger.info("已終止 %s 個程式", len(terminated))
                    time.sleep(1)

            logger.info("Step 4: 安裝必要套件...")
            all_requirements: List[str] = []
            for file in project.files:
                if file.install_requirements:
                    all_requirements.extend(file.install_requirements)

            if all_requirements:
                result.installation_logs = CodeProcessor.install_packages(all_requirements)

            logger.info("Step 5: 儲存專案檔案...")
            saved_files, updated_files = CodeProcessor.save_project_files(folder_path, project, is_iteration)
            result.files_created = saved_files
            result.files_updated = updated_files

            if is_iteration:
                final_project_dir = folder_path
            else:
                final_project_dir = str(Path(folder_path) / project.project_name)

            if not is_iteration and folder_path != final_project_dir:
                logger.info("新建專案:遷移對話記錄...")
                temp_conversation = ConversationManager.load_conversation(folder_path)
                if temp_conversation.messages:
                    temp_conversation.project_dir = final_project_dir
                    temp_conversation.project_name = project.project_name
                    ConversationManager.save_conversation(temp_conversation)
                    logger.info("已遷移 %s 條對話記錄", len(temp_conversation.messages))

                    try:
                        ConversationManager.delete_conversation_file(folder_path)
                        logger.info("已清理臨時對話檔案")
                    except Exception as exc:
                        logger.warning("清理臨時對話檔案失敗: %s", exc)

            logger.info("Step 6: 啟動 VS Code...")
            filenames_to_open = [f.filename for f in project.files[:3]]
            vscode_result = VSCodeController.launch_and_open(final_project_dir, filenames_to_open)

            logger.info("Step 7: 執行程式...")
            execution_status = "尚未執行"
            execution_detail = ""
            window_titles_to_capture: List[str] = []

            ProjectManager.add_to_project_list(final_project_dir, project.project_name, project.description)

            if not is_iteration and folder_path != final_project_dir:
                ProjectManager.remove_from_project_list(folder_path)

            if project.main_file:
                main_file_path = Path(final_project_dir) / project.main_file

                main_file_info = None
                for f in project.files:
                    if f.filename == project.main_file:
                        main_file_info = f
                        break

                if main_file_path.exists():
                    execution_result = ProgramManager.run_file(str(main_file_path), final_project_dir, main_file_info)
                    if execution_result:
                        process, output_queue = execution_result
                        execution_status = "執行中"
                        execution_detail = f"程式 PID: {process.pid}"
                        logger.info("已啟動主程式: PID %s", process.pid)
                else:
                    execution_status = "找不到主程式"
                    execution_detail = f"預期檔案不存在: {main_file_path}"
            else:
                execution_status = "未指定主檔案"

            if attach_screenshot:
                project_info = sanitized_json or {}
                screenshots = ScreenCapture.capture_running_programs(
                    window_titles=window_titles_to_capture,
                    project_name=project_info.get("project_name"),
                    project_json=project_info,
                )

                screenshot_files = []
                for screenshot in screenshots:
                    try:
                        with open(screenshot["path"], "rb") as handle:
                            image_data = handle.read()
                            base64_data = base64.b64encode(image_data).decode("utf-8")
                            screenshot_files.append(
                                {
                                    "name": screenshot["name"],
                                    "type": "image/png",
                                    "content": f"data:image/png;base64,{base64_data}",
                                }
                            )
                    except Exception as exc:
                        logger.error("讀取截圖失敗: %s", exc)

                if not files:
                    files = []
                files.extend(screenshot_files)

                result.screenshots = [s["filename"] for s in screenshots]

            result.output = ai_response
            result.success = True

            ConversationManager.add_message(
                final_project_dir,
                "assistant",
                result.output,
                metadata={
                    "project_name": project.project_name,
                    "files_count": len(project.files),
                    **({"memory_snapshot": result.memory_snapshot} if result.memory_snapshot else {}),
                    **({"evaluation_snapshot": result.evaluation_snapshot} if result.evaluation_snapshot else {}),
                },
                terminal_output=result.terminal_output,
                usage_metadata=usage_metadata,
            )

            if result.memory_snapshot or result.evaluation_snapshot or new_long_term_memory:
                ConversationManager.update_memory_state(
                    final_project_dir,
                    result.memory_snapshot,
                    result.evaluation_snapshot,
                    new_long_term_memory,
                )

        except json.JSONDecodeError as exc:
            result.error = f"AI 回應無法解析為 JSON: {exc}"
            logger.error(result.error)
            ErrorReporter.generate_report(
                error_type="JSON_DECODE_ERROR",
                error_message=str(exc),
                ai_response=result.ai_response,
            )
        except Exception as exc:
            result.error = str(exc)
            logger.error("處理流程失敗: %s", exc)
            stack_trace = traceback.format_exc()
            logger.error(stack_trace)

            error_report_path = ErrorReporter.generate_report(
                error_type="EXECUTION_ERROR",
                error_message=str(exc),
                stack_trace=stack_trace,
                context={"is_iteration": is_iteration, "folder_path": folder_path},
            )
            result.error_report_path = str(error_report_path)

            if not result.ai_response:
                result.ai_response = "無法獲取 AI 回應"

            ConversationManager.add_message(
                folder_path,
                "assistant",
                f"執行失敗: {result.error}\n\n錯誤報告已生成: {error_report_path}",
                metadata={
                    "error": True,
                    "error_type": "execution_error",
                    "error_report": str(error_report_path),
                },
            )

        return result


__all__ = [
    "GeminiAI",
    "VSCodeController",
    "ScreenCapture",
    "CodeProcessor",
    "ProgramManager",
    "ProcessManager",
]
