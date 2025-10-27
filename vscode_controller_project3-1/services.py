"""AI 與自動化流程服務模組"""

from __future__ import annotations

import base64
import json
import os
import re
import subprocess
import sys
import time
import traceback
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import google.generativeai as genai
from google.generativeai.types import GenerationConfig, HarmBlockThreshold, HarmCategory

from config import HOST, PORT, logger
from managers import (
    ConversationManager,
    DiagnosticsManager,
    ErrorReporter,
    ProgramManager,
    ProjectManager,
    ScreenCapture,
    VSCodeController,
)
from models import AIConfig, FileOutput, ProcessResult, ProjectOutput

try:  # optional dependency
    import google.auth

    HAS_GOOGLE_AUTH = True
except ImportError:  # pragma: no cover - optional功能
    HAS_GOOGLE_AUTH = False


def get_json_schema() -> Dict[str, Any]:
    """獲取 Gemini API 的 JSON Schema（強化版）"""
    return {
        "type": "object",
        "properties": {
            "評分": {
                "type": "integer",
                "minimum": 0,
                "maximum": 100,
                "description": "以『思考品質與合規度』為核心保守給分",
            },
            "內容評價": {
                "type": "string",
                "description": "≤200字；聚焦要則遵守與品質",
            },
            "扣分原因": {
                "type": "string",
                "description": "未滿分需具體指摘；若無則填『無』",
            },
            "改進建議": {
                "type": "string",
                "description": "提出下一輪可驗證且高增益改進；若確無可改進，填『無』",
            },
            "核心記憶模塊": {
                "type": "object",
                "description": "保存短長期記憶與專案目標",
                "properties": {
                    "專案總結": {
                        "type": "string",
                        "description": "中立概述目前進展、最新限制、決策依據與已驗證輸出",
                    },
                    "短期記憶": {
                        "type": "array",
                        "description": "最近數輪的關鍵事實/決策/限制(每列一句)",
                        "items": {"type": "string"},
                    },
                    "長期記憶新增": {
                        "type": "array",
                        "description": "⭐本輪新增的重要發現、原則、限制或教訓（將累積到歷史長期記憶中）；每次回應【必須】至少新增 2 條以上",
                        "items": {"type": "string"},
                        "minItems": 2,
                    },
                    "專案目標": {
                        "type": "array",
                        "description": "以可驗證的任務陳述",
                        "items": {
                            "type": "object",
                            "properties": {
                                "步驟": {"type": "integer"},
                                "任務": {"type": "string"},
                                "狀態": {"type": "string", "enum": ["未開始", "進行中", "已完成"]},
                                "是否為當前任務": {"type": "boolean"},
                            },
                            "required": ["步驟", "任務", "狀態", "是否為當前任務"],
                        },
                        "minItems": 4,
                    },
                },
                "required": ["專案總結", "短期記憶", "長期記憶新增", "專案目標"],
            },
            "專案輸出": {
                "type": "object",
                "description": "包含可執行程式與操作資訊",
                "properties": {
                    "project_name": {"type": "string"},
                    "description": {"type": "string"},
                    "main_file": {"type": "string"},
                    "setup_instructions": {"type": "array", "items": {"type": "string"}},
                    "run_instructions": {"type": "array", "items": {"type": "string"}},
                    "files": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "filename": {"type": "string"},
                                "filetype": {"type": "string"},
                                "code": {"type": "string", "description": "⚠️ 完整可執行程式；繁中註解；嚴禁在開頭加入檔案路徑或名稱"},
                                "opens_window": {"type": "boolean"},
                                "window_title": {"type": ["string", "null"]},
                                "install_requirements": {"type": "array", "items": {"type": "string"}},
                                "dependencies": {"type": "array", "items": {"type": "string"}},
                                "description": {"type": "string"},
                                "run_command": {"type": ["string", "null"]},
                                "is_web_app": {"type": "boolean"},
                                "can_open_standalone": {"type": "boolean"},
                                "server_address": {"type": ["string", "null"]},
                                "web_title": {"type": ["string", "null"]},
                            },
                            "required": ["filename", "filetype", "code", "opens_window"],
                        },
                    },
                },
                "required": ["project_name", "description", "files"],
            },
        },
        "required": ["評分", "內容評價", "扣分原因", "改進建議", "核心記憶模塊", "專案輸出"],
    }


def get_json_system_instruction(
    mode: str = "default",
    custom_instruction: str = "",
    accumulated_memory: Optional[List[str]] = None,
) -> str:
    normalized_mode = (mode or "default").lower()
    if normalized_mode not in {"default", "creative"}:
        normalized_mode = "default"

    memory_context = ""
    if accumulated_memory:
        memory_context = "\n\n【歷史長期記憶】（這些是從過往對話中累積的重要知識，請參考但不要在回應中重複）：\n"
        for index, mem in enumerate(accumulated_memory[-20:], 1):
            memory_context += f"{index}. {mem}\n"

    base_instruction = f"""你是一位專業的程式碼與專案助理。每次回應必須只輸出**單一 JSON 物件**，包含可執行程式碼、評分紀錄與記憶模塊。

{memory_context}

請在內部以私有思考空間完成『分解→多路徑探索→規劃→工具/程式輔助→驗證→收斂』：先用 Least-to-Most 拆解子任務；再以 Self-Consistency 思考多種方案並取最佳；
確保產出的程式碼完整可執行，並包含繁體中文註解。"""

    creative_block = ""
    if normalized_mode == "creative":
        creative_block = "\n【創意模式】鼓勵提供多種構想，並給出至少兩個可驗證的延伸改進。"

    custom_block = f"\n【使用者自訂補充】\n{custom_instruction.strip()}" if custom_instruction else ""

    return "\n".join(
        [
            base_instruction,
            creative_block,
            "請嚴格依此最新模板回覆，避免外露推理，且不得遺漏任何欄位。" + custom_block,
        ]
    )


def sanitize_json_strings(data: Any) -> Any:
    if isinstance(data, dict):
        return {key: sanitize_json_strings(value) for key, value in data.items()}

    if isinstance(data, list):
        return [sanitize_json_strings(item) for item in data]

    if isinstance(data, str):
        sanitized = re.sub(r'[\x00-\x08\x0B-\x0C\x0E-\x1F]', '', data)
        sanitized = sanitized.replace('\r\n', '\n')
        sanitized = sanitized.replace('\r', '\\r')
        sanitized = sanitized.replace('\n', '\\n')
        sanitized = sanitized.replace('\t', '\\t')
        return sanitized

    return data


def _is_escaped(text: str, index: int) -> bool:
    backslash_count = 0
    pointer = index - 1
    while pointer >= 0 and text[pointer] == '\\':
        backslash_count += 1
        pointer -= 1
    return backslash_count % 2 == 1


def _reescape_string_literal_controls(code: str) -> str:
    if not code:
        return code

    result: List[str] = []
    i = 0
    length = len(code)
    in_string = False
    string_delim = ''
    is_triple = False
    in_comment = False

    while i < length:
        ch = code[i]

        if in_comment:
            result.append(ch)
            if ch == '\n':
                in_comment = False
            i += 1
            continue

        if not in_string:
            if ch == '#':
                in_comment = True
                result.append(ch)
                i += 1
                continue

            if ch in ('"', "'"):
                if code.startswith(ch * 3, i):
                    string_delim = ch * 3
                    is_triple = True
                    in_string = True
                    result.append(string_delim)
                    i += 3
                    continue
                string_delim = ch
                is_triple = False
                in_string = True
                result.append(ch)
                i += 1
                continue

            result.append(ch)
            if ch == '\n':
                in_comment = False
            i += 1
            continue

        if is_triple:
            if code.startswith(string_delim, i):
                result.append(string_delim)
                i += len(string_delim)
                in_string = False
                is_triple = False
                string_delim = ''
            else:
                result.append(ch)
                i += 1
            continue

        if ch in ('"', "'") and ch == string_delim and not _is_escaped(code, i):
            result.append(ch)
            i += 1
            in_string = False
            string_delim = ''
            continue

        if ch == '\n':
            result.append('\\n')
            i += 1
            continue

        if ch == '\r':
            result.append('\\r')
            i += 1
            continue

        if ch == '\t':
            result.append('\\t')
            i += 1
            continue

        result.append(ch)
        i += 1

    return ''.join(result)


def normalize_code_content(code: str) -> str:
    if not isinstance(code, str):
        return code

    normalized = code.replace('\\r\\n', '\n')
    normalized = normalized.replace('\\n', '\n')
    normalized = normalized.replace('\\t', '\t')
    return _reescape_string_literal_controls(normalized)


def clean_code_header(code: str, filetype: str) -> str:
    if not code or not isinstance(code, str):
        return code

    lines = code.split('\n')
    cleaned_lines: List[str] = []
    skip_header = True

    comment_patterns = {
        'python': [r'^\s*#', r'^\s*"""', r"^\s*'''"],
        'javascript': [r'^\s*//', r'^\s*/\*'],
        'typescript': [r'^\s*//', r'^\s*/\*'],
        'html': [r'^\s*<!--'],
        'css': [r'^\s*/\*'],
    }

    patterns = comment_patterns.get(filetype.lower(), [r'^\s*#', r'^\s*//'])

    for line in lines:
        if skip_header:
            is_comment = any(re.match(pattern, line) for pattern in patterns)

            if is_comment:
                lower_line = line.lower()
                if any(keyword in lower_line for keyword in ['file:', 'filename:', 'path:', '檔案:', '檔名:', '路徑:']):
                    continue
                if line.strip() in ['#', '//', '/*', '*/', '<!--', '-->']:
                    continue

            if not is_comment or (
                is_comment and not any(
                    keyword in line.lower() for keyword in ['file:', 'filename:', 'path:', '檔案:', '檔名:', '路徑:']
                )
            ):
                skip_header = False
                cleaned_lines.append(line)
        else:
            cleaned_lines.append(line)

    return '\n'.join(cleaned_lines)


class GeminiAI:
    """Gemini AI API 管理器"""

    @staticmethod
    def configure(config: AIConfig) -> None:
        if config.connection_method == 'api_key':
            if not config.gemini_api_key:
                raise ValueError("API Key 模式需要提供有效的 API Key")
            genai.configure(api_key=config.gemini_api_key)
            logger.info("已使用 API Key 連接 Gemini")
        elif config.connection_method == 'gcloud_auth':
            if not HAS_GOOGLE_AUTH:
                raise ImportError("缺少 google-auth 套件")
            credentials, _project_id = google.auth.default()
            genai.configure(credentials=credentials)
            logger.info("已使用 Google Cloud Auth 連接")
        else:
            raise ValueError(f"不支援的連接模式: {config.connection_method}")

    @staticmethod
    def generate_content(
        prompt: str,
        config: AIConfig,
        files: Optional[List[Dict[str, Any]]] = None,
        terminal_output: Optional[str] = None,
        accumulated_memory: Optional[List[str]] = None,
    ) -> Tuple[str, Optional[Dict[str, Any]], Optional[Dict[str, Any]]]:
        try:
            GeminiAI.configure(config)

            gen_params = dict(config.generation_params)
            gen_params["response_mime_type"] = "application/json"

            system_instruction = get_json_system_instruction(
                getattr(config, 'prompt_mode', 'default'),
                config.system_instruction,
                accumulated_memory,
            )

            gen_config = GenerationConfig(**{key: value for key, value in gen_params.items() if value is not None})

            valid_categories = {
                'HARM_CATEGORY_HARASSMENT',
                'HARM_CATEGORY_HATE_SPEECH',
                'HARM_CATEGORY_SEXUALLY_EXPLICIT',
                'HARM_CATEGORY_DANGEROUS_CONTENT',
            }

            safety_settings: Dict[HarmCategory, HarmBlockThreshold] = {}
            for category, threshold in config.safety_settings.items():
                if category in valid_categories:
                    try:
                        safety_settings[HarmCategory[category]] = HarmBlockThreshold[threshold]
                    except KeyError:
                        logger.warning("跳過無效的安全類別或閾值: %s=%s", category, threshold)

            model_name = f"models/{config.model_name}"
            logger.info("使用模型: %s", model_name)

            model_kwargs: Dict[str, Any] = {
                "model_name": model_name,
                "safety_settings": safety_settings,
                "generation_config": gen_config,
            }

            if system_instruction:
                model_kwargs["system_instruction"] = system_instruction

            model = genai.GenerativeModel(**model_kwargs)

            content_parts: List[Any] = []

            if terminal_output:
                terminal_part = (
                    "\n=== 程式執行輸出 (Terminal Output) ===\n"
                    f"{terminal_output}\n=== 輸出結束 ===\n"
                )
                content_parts.append(terminal_part)
                logger.info("已添加Terminal輸出到提示詞")

            if files:
                for file_data in files:
                    file_type = file_data.get('type', '')
                    file_content = file_data.get('content', '')
                    file_name = file_data.get('name', '')

                    logger.info("處理檔案: %s, 類型: %s", file_name, file_type)

                    if file_type.startswith('image/'):
                        if ',' in file_content:
                            file_content = file_content.split(',')[1]
                        image_data = base64.b64decode(file_content)
                        content_parts.append(
                            {
                                'mime_type': file_type,
                                'data': base64.b64encode(image_data).decode('utf-8'),
                            }
                        )
                        logger.info("已添加圖片: %s", file_name)
                    elif file_type == 'application/pdf':
                        if ',' in file_content:
                            file_content = file_content.split(',')[1]
                        pdf_data = base64.b64decode(file_content)
                        content_parts.append(
                            {
                                'mime_type': 'application/pdf',
                                'data': base64.b64encode(pdf_data).decode('utf-8'),
                            }
                        )
                        logger.info("已添加 PDF: %s", file_name)
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

                            content_parts.append(
                                f"\n--- 檔案: {file_name} ---\n{text_content}\n--- 檔案結束 ---\n"
                            )
                            logger.info("已添加文本檔案: %s", file_name)
                        except Exception as exc:
                            logger.error("處理文本檔案失敗: %s", exc)

            content_parts.append(prompt)

            if len(content_parts) == 1:
                response = model.generate_content(prompt, generation_config=gen_config)
            else:
                response = model.generate_content(content_parts, generation_config=gen_config)

            response_text = response.text
            json_data: Optional[Dict[str, Any]] = None

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
                    context={'prompt_length': len(prompt), 'files_count': len(files or [])},
                )

                try:
                    if '```json' in response_text:
                        response_text = response_text.split('```json')[1].split('```')[0]
                    elif '```' in response_text:
                        response_text = response_text.split('```')[1].split('```')[0]

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
            if hasattr(response, 'usage_metadata'):
                metadata = response.usage_metadata
                usage_metadata = {
                    'prompt_token_count': getattr(metadata, 'prompt_token_count', 0),
                    'candidates_token_count': getattr(metadata, 'candidates_token_count', 0),
                    'thoughts_token_count': getattr(metadata, 'thoughts_token_count', 0),
                    'total_token_count': getattr(metadata, 'total_token_count', 0),
                }
                logger.info("Token使用量: %s", usage_metadata)

            return response_text, json_data, usage_metadata
        except Exception as exc:
            logger.error("Gemini API 呼叫失敗: %s", exc)
            ErrorReporter.generate_report(
                error_type="API_ERROR",
                error_message=str(exc),
                stack_trace=traceback.format_exc(),
                context={'model': config.model_name},
            )
            raise


class CodeProcessor:
    """程式碼解析與處理工具"""

    @staticmethod
    def parse_json_response(json_data: Dict[str, Any]) -> ProjectOutput:
        try:
            project_section = json_data.get('專案輸出', json_data)
            files: List[FileOutput] = []

            for file_data in project_section.get('files', []):
                code = file_data.get('code', '')

                if isinstance(code, str):
                    code = normalize_code_content(code)
                    filetype = file_data.get('filetype', 'text')
                    code = clean_code_header(code, filetype)

                files.append(
                    FileOutput(
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
                        web_title=file_data.get('web_title'),
                    )
                )

            return ProjectOutput(
                project_name=project_section.get('project_name', 'untitled_project'),
                description=project_section.get('description', ''),
                files=files,
                main_file=project_section.get('main_file'),
                setup_instructions=project_section.get('setup_instructions'),
                run_instructions=project_section.get('run_instructions'),
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
        logs: List[str] = []

        for requirement in install_requirements:
            if not requirement:
                continue

            logger.info("執行安裝指令: %s", requirement)
            parts = requirement.split()
            full_command = [sys.executable, "-m"] + parts if parts[0] == 'pip' else parts

            try:
                result = subprocess.run(
                    full_command,
                    capture_output=True,
                    text=True,
                    check=True,
                    encoding='utf-8',
                )

                log = f"✅ 成功執行: {requirement}\n" + result.stdout
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
                filepath.write_text(file.code, encoding='utf-8')

                if file_exists:
                    updated_files.append(str(filepath))
                else:
                    saved_files.append(str(filepath))
            except Exception as exc:
                logger.error("儲存檔案失敗 %s: %s", filepath, exc)
                ErrorReporter.generate_report(
                    error_type="FILE_SAVE_ERROR",
                    error_message=str(exc),
                    stack_trace=traceback.format_exc(),
                    context={'filepath': str(filepath)},
                )

        info_file = project_dir / "PROJECT_INFO.json"
        info_data = {
            'project_name': project.project_name,
            'description': project.description,
            'main_file': project.main_file,
            'setup_instructions': project.setup_instructions,
            'run_instructions': project.run_instructions,
            'files': [
                {
                    'filename': file.filename,
                    'filetype': file.filetype,
                    'description': file.description,
                    'opens_window': file.opens_window,
                    'window_title': file.window_title,
                    'install_requirements': file.install_requirements,
                    'dependencies': file.dependencies,
                    'run_command': file.run_command,
                    'is_web_app': file.is_web_app,
                    'can_open_standalone': file.can_open_standalone,
                    'server_address': file.server_address,
                    'web_title': file.web_title,
                }
                for file in project.files
            ],
        }

        info_file.write_text(json.dumps(info_data, indent=2, ensure_ascii=False), encoding='utf-8')

        if str(info_file) not in saved_files and str(info_file) not in updated_files:
            saved_files.append(str(info_file))

        return saved_files, updated_files


class ProcessManager:
    """主要處理流程管理器（優化版）"""

    @staticmethod
    def run_automation_process(
        folder_path: str,
        prompt: str,
        config: AIConfig,
        files: Optional[List[Dict[str, Any]]] = None,
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
                    Path(normalized_folder).name or '建立中專案',
                )

            diagnostics_report: List[Dict[str, Any]] = []
            diagnostics_prompt_block = ''

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

            display_prompt = user_visible_prompt or prompt
            metadata_payload: Dict[str, Any] = {}
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
                metadata=metadata_payload if metadata_payload else None,
            )

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

                    window_titles: List[str] = []
                    for file_data in project_info.get('files', []):
                        if file_data.get('web_title'):
                            window_titles.append(file_data['web_title'])

                    screenshots = ScreenCapture.capture_running_programs(
                        window_titles=window_titles,
                        project_name=project_info.get('project_name'),
                        project_json=project_info,
                    )

                    screenshot_files: List[Dict[str, Any]] = []
                    for screenshot in screenshots:
                        try:
                            with open(screenshot['path'], 'rb') as handle:
                                image_data = handle.read()
                                base64_data = base64.b64encode(image_data).decode('utf-8')
                                screenshot_files.append(
                                    {
                                        'name': screenshot['name'],
                                        'type': 'image/png',
                                        'content': f'data:image/png;base64,{base64_data}',
                                    }
                                )
                        except Exception as exc:
                            logger.error("讀取截圖失敗: %s", exc)

                    if not files:
                        files = []
                    files.extend(screenshot_files)
                    result.screenshots = [s['filename'] for s in screenshots]

            logger.info("Step 1: 呼叫 Gemini AI...")
            if files:
                logger.info("包含 %s 個檔案", len(files))
            if terminal_output:
                logger.info("包含 Terminal 輸出")

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

            new_long_term_memory = None
            if sanitized_json:
                memory_snapshot = sanitized_json.get('核心記憶模塊') or sanitized_json.get('core_memory_module')
                evaluation_snapshot = {
                    '評分': sanitized_json.get('評分'),
                    '內容評價': sanitized_json.get('內容評價'),
                    '扣分原因': sanitized_json.get('扣分原因'),
                    '改進建議': sanitized_json.get('改進建議'),
                }
                evaluation_snapshot = {key: value for key, value in evaluation_snapshot.items() if value is not None}
                result.memory_snapshot = memory_snapshot
                result.evaluation_snapshot = evaluation_snapshot

                if memory_snapshot:
                    new_long_term_memory = (
                        memory_snapshot.get('長期記憶新增')
                        or memory_snapshot.get('long_term_memory_additions')
                    )
                    if new_long_term_memory:
                        logger.info("本輪新增長期記憶：%s 條", len(new_long_term_memory))

            result.ai_response_json = sanitized_json if sanitized_json else None

            logger.info("Step 2: 解析 AI 回應...")
            try:
                if sanitized_json:
                    logger.info("使用 JSON 模式解析")
                    project = CodeProcessor.parse_json_response(sanitized_json)
                else:
                    logger.info("嘗試從文本中提取 JSON")
                    json_start = ai_response.find('{')
                    json_end = ai_response.rfind('}') + 1
                    if json_start >= 0 and json_end > json_start:
                        json_str = ai_response[json_start:json_end]
                        json_str = json_str.replace('\\n', '\n').replace('\\t', '\t')
                        potential_json = json.loads(json_str)
                        if isinstance(potential_json, list):
                            potential_json = potential_json[0] if potential_json else {}
                        sanitized_potential = sanitize_json_strings(potential_json)
                        project = CodeProcessor.parse_json_response(sanitized_potential)
                        result.ai_response_json = sanitized_potential or None
                        logger.info("成功從文本中提取並解析 JSON")
                    else:
                        raise ValueError("無法從回應中找到有效的JSON結構")
            except Exception as exc:
                logger.error("解析 AI 回應失敗: %s", exc)
                raise

            logger.info("Step 3: 儲存專案檔案...")
            saved_files, updated_files = CodeProcessor.save_project_files(
                folder_path,
                project,
                is_iteration,
            )
            result.files_created = saved_files
            result.files_updated = updated_files
            result.project_data = project

            installation_logs: List[str] = []
            requirements: List[str] = []
            for file in project.files:
                if file.install_requirements:
                    requirements.extend(file.install_requirements)

            if requirements:
                installation_logs = CodeProcessor.install_packages(requirements)
                result.installation_logs = installation_logs

            logger.info("Step 4: 啟動 VS Code 與程式...")
            final_project_dir = (
                Path(folder_path) / project.project_name if not is_iteration else Path(folder_path)
            )

            filenames_to_open = [file.filename for file in project.files[:3]]
            vscode_result = VSCodeController.launch_and_open(str(final_project_dir), filenames_to_open)

            main_file = project.main_file
            execution_status = "未啟動"
            execution_detail = ""

            if main_file:
                main_file_path = final_project_dir / main_file
                target_file = next((file for file in project.files if file.filename == main_file), None)
                if target_file:
                    process = ProgramManager.run_file(str(main_file_path), str(final_project_dir), target_file)
                    if process:
                        execution_status = "已啟動"
                        execution_detail = f"PID: {process.pid}"
                else:
                    execution_detail = "找不到主程式設定"

            result.output = f"""
=== ✅ 專案生成成功 ===
📦 專案名稱: {project.project_name}
📄 檔案數量: {len(project.files)}
🎯 主檔案: {project.main_file or '無指定'}
"""
            for file in project.files:
                file_icon = "🐍" if file.filetype == "python" else "📄"
                window_info = f" (視窗: {file.window_title})" if file.opens_window and file.window_title else ""
                update_status = (
                    " [已更新]" if str(final_project_dir / file.filename) in updated_files else " [新建]"
                )
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

            result.output += """
=== 💡 操作提示 ===
1. 查看 VS Code 視窗以編輯程式碼
2. 使用「延遲 5 秒後擷取」來擷取運行畫面
3. 查看「執行中的程式」監控程式狀態
4. 如果是圖形程式,應該會看到新視窗出現
5. 查看「監控」中的 Terminal 輸出以了解程式運行狀況
"""

            result.success = True

            ConversationManager.add_message(
                str(final_project_dir),
                'assistant',
                result.output,
                metadata={
                    'project_name': project.project_name,
                    'files_count': len(project.files),
                    **({'memory_snapshot': result.memory_snapshot} if result.memory_snapshot else {}),
                    **({'evaluation_snapshot': result.evaluation_snapshot} if result.evaluation_snapshot else {}),
                },
                terminal_output=result.terminal_output,
                usage_metadata=usage_metadata,
            )

            if result.memory_snapshot or result.evaluation_snapshot or new_long_term_memory:
                ConversationManager.update_memory_state(
                    str(final_project_dir),
                    result.memory_snapshot,
                    result.evaluation_snapshot,
                    new_long_term_memory,
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
                context={'is_iteration': is_iteration, 'folder_path': folder_path},
            )
            result.error_report_path = str(error_report_path)

            if not result.ai_response:
                result.ai_response = "無法獲取 AI 回應"

            ConversationManager.add_message(
                folder_path,
                'assistant',
                f"執行失敗: {result.error}\n\n錯誤報告已生成: {error_report_path}",
                metadata={
                    'error': True,
                    'error_type': 'execution_error',
                    'error_report': str(error_report_path),
                },
            )

        return result


__all__ = [
    'GeminiAI',
    'CodeProcessor',
    'ProcessManager',
    'get_json_schema',
    'get_json_system_instruction',
    'sanitize_json_strings',
    'normalize_code_content',
    'clean_code_header',
]
