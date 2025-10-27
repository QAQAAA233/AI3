"""資料模型定義模組"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional


class ResponseMode(Enum):
    """AI 回應模式"""

    JSON = "json"


@dataclass
class ThinkingConfig:
    """思考配置"""

    thinking_budget: int = -1


@dataclass
class FileOutput:
    """單個檔案輸出的結構描述"""

    filename: str
    filetype: str
    code: str
    opens_window: bool = False
    window_title: Optional[str] = None
    install_requirements: Optional[List[str]] = None
    dependencies: Optional[List[str]] = None
    description: Optional[str] = None
    run_command: Optional[str] = None
    is_web_app: bool = False
    can_open_standalone: bool = False
    server_address: Optional[str] = None
    web_title: Optional[str] = None
    file_operation: Optional[str] = None


@dataclass
class ProjectOutput:
    """專案輸出結構"""

    project_name: str
    description: str
    files: List[FileOutput]
    main_file: Optional[str] = None
    setup_instructions: Optional[List[str]] = None
    run_instructions: Optional[List[str]] = None


@dataclass
class AIConfig:
    """AI 配置資料模型"""

    connection_method: str = "api_key"
    gemini_api_key: str = ""
    model_name: str = "gemini-2.5-pro"
    system_instruction: str = ""
    prompt_mode: str = "default"
    generation_params: Optional[Dict[str, Any]] = None
    thinking_config: Optional[Dict[str, Any]] = None
    safety_settings: Optional[Dict[str, str]] = None
    automation_settings: Optional[Dict[str, Any]] = None

    def __post_init__(self) -> None:
        if self.generation_params is None:
            self.generation_params = {
                "temperature": 0.7,
                "top_p": 0.95,
                "top_k": 64,
                "max_output_tokens": 8192,
                "candidate_count": 1,
                "stop_sequences": [],
                "response_mime_type": "application/json",
            }

        if self.thinking_config is None:
            self.thinking_config = {"thinking_budget": -1}

        if self.safety_settings is None:
            self.safety_settings = {
                "HARM_CATEGORY_HARASSMENT": "BLOCK_MEDIUM_AND_ABOVE",
                "HARM_CATEGORY_HATE_SPEECH": "BLOCK_MEDIUM_AND_ABOVE",
                "HARM_CATEGORY_SEXUALLY_EXPLICIT": "BLOCK_MEDIUM_AND_ABOVE",
                "HARM_CATEGORY_DANGEROUS_CONTENT": "BLOCK_MEDIUM_AND_ABOVE",
            }

        if self.automation_settings is None:
            self.automation_settings = {
                "auto_error_fix": False,
                "auto_optimize": False,
                "auto_test": False,
                "monitor_interval": 5,
            }

        if not self.prompt_mode:
            self.prompt_mode = "default"
        else:
            normalized = str(self.prompt_mode).lower()
            self.prompt_mode = normalized if normalized in {"default", "creative"} else "default"


@dataclass
class ConversationMessage:
    """對話訊息記錄"""

    role: str
    content: str
    timestamp: str
    files: Optional[List[Dict[str, Any]]] = None
    metadata: Optional[Dict[str, Any]] = None
    terminal_output: Optional[str] = None
    usage_metadata: Optional[Dict[str, Any]] = None


@dataclass
class ProjectConversation:
    """專案對話歷史"""

    project_dir: str
    project_name: str
    messages: List[ConversationMessage] = field(default_factory=list)
    created_at: str = ""
    updated_at: str = ""
    memory_snapshot: Dict[str, Any] = field(default_factory=dict)
    evaluation_snapshot: Dict[str, Any] = field(default_factory=dict)
    accumulated_long_term_memory: List[str] = field(default_factory=list)


@dataclass
class ProcessResult:
    """自動化流程的執行結果"""

    success: bool
    output: str = ""
    files_created: List[str] = field(default_factory=list)
    files_updated: List[str] = field(default_factory=list)
    project_data: Optional[ProjectOutput] = None
    ai_response: str = ""
    ai_response_json: Optional[Dict[str, Any]] = None
    installation_logs: List[str] = field(default_factory=list)
    error: str = ""
    screenshots: List[str] = field(default_factory=list)
    is_iteration: bool = False
    usage_metadata: Optional[Dict[str, Any]] = None
    terminal_output: str = ""
    memory_snapshot: Optional[Dict[str, Any]] = None
    evaluation_snapshot: Optional[Dict[str, Any]] = None
    diagnostics_report: List[Dict[str, Any]] = field(default_factory=list)
    error_report_path: Optional[str] = None


__all__ = [
    'ResponseMode',
    'ThinkingConfig',
    'FileOutput',
    'ProjectOutput',
    'AIConfig',
    'ConversationMessage',
    'ProjectConversation',
    'ProcessResult',
]
