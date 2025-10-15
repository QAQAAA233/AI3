"""
AI 自動化開發控制器 Pro v5.5 - 完整優化版

主要改進：
1. 修復 JSON 解析失敗問題（增強字串清理和錯誤報告）
2. 修復瀏覽器自動打開問題（使用 file:// URL）
3. 改進長期記憶系統（累積式而非重置式）
4. 增強錯誤報告系統（詳細的偵錯日誌）
5. 優化創意模式提示詞（增加思維鏈 SOP）
6. 嚴格禁止代碼開頭出現路徑/檔名
"""

import sys
import os
import subprocess
import threading
import time
import re
import json
import shutil
import platform
import logging
import queue
import traceback
from typing import Dict, List, Optional, Tuple, Any
from datetime import datetime
from pathlib import Path
from dataclasses import dataclass, asdict, field
from enum import Enum

# Web framework imports
from flask import Flask, render_template, jsonify, request, send_file
import webview

# AI and automation imports
import google.generativeai as genai
from google.generativeai.types import GenerationConfig, HarmCategory, HarmBlockThreshold
import pywinctl as pwc
import pyautogui
import pyperclip

# Screen capture imports
import mss
import mss.tools
from PIL import Image
import io
import base64

# Optional Google Cloud Auth support
try:
    import google.auth
    HAS_GOOGLE_AUTH = True
except ImportError:
    HAS_GOOGLE_AUTH = False

# ============================================
# 配置和常量
# ============================================

logging.basicConfig(
    level=logging.INFO,
    format='[%(asctime)s] %(levelname)s: %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)
logger = logging.getLogger(__name__)

app = Flask(__name__)
HOST = '127.0.0.1'
PORT = 5001

CONFIG_DIR = Path.home() / '.ai_controller_v5'
CONFIG_FILE = CONFIG_DIR / 'config.json'
SCREENSHOT_DIR = CONFIG_DIR / 'screenshots'
LOG_DIR = CONFIG_DIR / 'logs'
PROJECTS_DIR = CONFIG_DIR / 'projects'
CONVERSATIONS_DIR = CONFIG_DIR / 'conversations'
PROJECT_LIST_FILE = CONFIG_DIR / 'project_list.json'
ERROR_REPORTS_DIR = CONFIG_DIR / 'error_reports'  # ⭐ 新增：錯誤報告目錄

# 確保所有目錄都存在
def ensure_directories():
    """確保所有必要的目錄都存在"""
    directories = [
        CONFIG_DIR, SCREENSHOT_DIR, LOG_DIR, PROJECTS_DIR, 
        CONVERSATIONS_DIR, ERROR_REPORTS_DIR  # ⭐ 新增
    ]
    
    for directory in directories:
        try:
            directory.mkdir(parents=True, exist_ok=True)
            logger.info(f"目錄已準備: {directory}")
        except Exception as e:
            logger.error(f"無法創建目錄 {directory}: {e}")
            raise RuntimeError(f"無法創建必要的目錄: {directory}")

try:
    ensure_directories()
except Exception as e:
    logger.critical(f"初始化失敗: {e}")

# ============================================
# ⭐ 新增：錯誤報告系統
# ============================================

class ErrorReporter:
    """錯誤報告生成器 - 自動生成詳細的錯誤報告"""
    
    @staticmethod
    def generate_report(
        error_type: str,
        error_message: str,
        ai_response: str = "",
        json_data: Any = None,
        stack_trace: str = "",
        context: Dict[str, Any] = None
    ) -> Path:
        """生成詳細的錯誤報告文件"""
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        report_filename = f"{error_type}_{timestamp}.md"
        report_path = ERROR_REPORTS_DIR / report_filename
        
        # 構建報告內容
        report_lines = [
            f"# 🚨 錯誤報告：{error_type}",
            f"\n**時間**：{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
            f"\n## 📋 錯誤摘要",
            f"\n```",
            error_message,
            f"```",
        ]
        
        # 添加堆疊追蹤
        if stack_trace:
            report_lines.extend([
                f"\n## 🔍 堆疊追蹤",
                f"\n```python",
                stack_trace,
                f"```"
            ])
        
        # 添加 AI 原始回應
        if ai_response:
            # 截取前2000字符，避免文件過大
            truncated_response = ai_response[:2000]
            if len(ai_response) > 2000:
                truncated_response += "\n\n... (回應過長，已截斷)"
            
            report_lines.extend([
                f"\n## 🤖 AI 原始回應",
                f"\n```json",
                truncated_response,
                f"```"
            ])
        
        # 添加解析的 JSON（如果有）
        if json_data:
            try:
                json_str = json.dumps(json_data, indent=2, ensure_ascii=False)[:1000]
                report_lines.extend([
                    f"\n## 📦 解析的 JSON 數據",
                    f"\n```json",
                    json_str,
                    f"```"
                ])
            except:
                pass
        
        # 添加上下文信息
        if context:
            report_lines.extend([
                f"\n## 🎯 上下文信息",
                f"\n```json",
                json.dumps(context, indent=2, ensure_ascii=False),
                f"```"
            ])
        
        # 添加修復建議
        suggestions = ErrorReporter._get_fix_suggestions(error_type, error_message)
        if suggestions:
            report_lines.extend([
                f"\n## 💡 修復建議",
                f"\n{suggestions}"
            ])
        
        # 寫入文件
        report_content = "\n".join(report_lines)
        with open(report_path, 'w', encoding='utf-8') as f:
            f.write(report_content)
        
        logger.info(f"✅ 錯誤報告已生成：{report_path}")
        return report_path
    
    @staticmethod
    def _get_fix_suggestions(error_type: str, error_message: str) -> str:
        """根據錯誤類型提供修復建議"""
        suggestions = {
            "JSON_DECODE_ERROR": """
1. **檢查 AI 回應格式**：確認 AI 是否正確輸出 JSON 格式
2. **清理控制字元**：檢查是否有未跳脫的 `\\n`, `\\r`, `\\t` 等字元
3. **驗證 JSON 結構**：使用線上 JSON 驗證器檢查結構完整性
4. **調整 AI 模型**：考慮切換到更穩定的模型版本
5. **簡化需求**：如果內容過於複雜，嘗試分步驟生成
            """,
            "CONTROL_CHARACTER_ERROR": """
1. **啟用字串清理**：確認 `sanitize_json_strings()` 函數正常運作
2. **檢查 AI 輸出**：查看上方的 AI 原始回應，找出非法字元位置
3. **更新提示詞**：在 system_instruction 中明確要求避免特殊字元
4. **手動修復**：如果是特定文件，可以手動編輯 PROJECT_INFO.json
            """,
            "BROWSER_LAUNCH_ERROR": """
1. **檢查路徑**：確認檔案路徑不包含中文或特殊字元
2. **使用 file:// URL**：確保使用 `Path.resolve().as_uri()` 格式
3. **等待檔案生成**：在打開瀏覽器前加入 `time.sleep(0.5)`
4. **檢查瀏覽器**：確認 Chrome 或 Edge 已正確安裝
            """
        }
        
        return suggestions.get(error_type, "請查看上方的錯誤信息並聯繫開發者。")

# ============================================
# 數據模型
# ============================================

class ResponseMode(Enum):
    """AI 回應模式"""
    JSON = "json"

@dataclass
class ThinkingConfig:
    """思考配置"""
    thinking_budget: int = -1

@dataclass
class FileOutput:
    """單個檔案輸出結構"""
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
    """AI 配置數據模型"""
    connection_method: str = "api_key"
    gemini_api_key: str = ""
    model_name: str = "gemini-2.5-pro"
    system_instruction: str = ""
    prompt_mode: str = "default"
    generation_params: Dict[str, Any] = None
    thinking_config: Dict[str, Any] = None
    safety_settings: Dict[str, str] = None
    automation_settings: Dict[str, Any] = None

    def __post_init__(self):
        if self.generation_params is None:
            self.generation_params = {
                "temperature": 0.7,
                "top_p": 0.95,
                "top_k": 64,
                "max_output_tokens": 8192,
                "candidate_count": 1,
                "stop_sequences": [],
                "response_mime_type": "application/json"
            }
        if self.thinking_config is None:
            self.thinking_config = {
                "thinking_budget": -1
            }
        if self.safety_settings is None:
            self.safety_settings = {
                "HARM_CATEGORY_HARASSMENT": "BLOCK_MEDIUM_AND_ABOVE",
                "HARM_CATEGORY_HATE_SPEECH": "BLOCK_MEDIUM_AND_ABOVE",
                "HARM_CATEGORY_SEXUALLY_EXPLICIT": "BLOCK_MEDIUM_AND_ABOVE",
                "HARM_CATEGORY_DANGEROUS_CONTENT": "BLOCK_MEDIUM_AND_ABOVE"
            }
        if self.automation_settings is None:
            self.automation_settings = {
                "auto_error_fix": False,
                "auto_optimize": False,
                "auto_test": False,
                "monitor_interval": 5
            }

        if not self.prompt_mode:
            self.prompt_mode = "default"
        else:
            self.prompt_mode = str(self.prompt_mode).lower()
            if self.prompt_mode not in {"default", "creative"}:
                self.prompt_mode = "default"

@dataclass
class ConversationMessage:
    """對話消息"""
    role: str
    content: str
    timestamp: str
    files: Optional[List[Dict]] = None
    metadata: Optional[Dict] = None
    terminal_output: Optional[str] = None
    usage_metadata: Optional[Dict] = None

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
    accumulated_long_term_memory: List[str] = field(default_factory=list)  # ⭐ 新增：累積的長期記憶

@dataclass
class ProcessResult:
    """處理結果數據模型"""
    success: bool
    output: str = ""
    files_created: List[str] = field(default_factory=list)
    files_updated: List[str] = field(default_factory=list)
    project_data: Optional[ProjectOutput] = None
    ai_response: str = ""
    ai_response_json: Optional[Dict] = None
    installation_logs: List[str] = field(default_factory=list)
    error: str = ""
    screenshots: List[str] = field(default_factory=list)
    is_iteration: bool = False
    usage_metadata: Optional[Dict] = None
    terminal_output: str = ""
    memory_snapshot: Optional[Dict[str, Any]] = None
    evaluation_snapshot: Optional[Dict[str, Any]] = None
    diagnostics_report: List[Dict[str, Any]] = field(default_factory=list)
    error_report_path: Optional[str] = None  # ⭐ 新增：錯誤報告路徑

# ============================================
# ⭐ 新增/優化：JSON Schema 定義
# ============================================

def get_json_schema():
    """獲取 Gemini API 的 JSON Schema（強化版）"""
    return {
        "type": "object",
        "properties": {
            "評分": {
                "type": "integer",
                "minimum": 0,
                "maximum": 100,
                "description": "以『思考品質與合規度』為核心保守給分"
            },
            "內容評價": {
                "type": "string",
                "description": "≤200字；聚焦要則遵守與品質"
            },
            "扣分原因": {
                "type": "string",
                "description": "未滿分需具體指摘；若無則填『無』"
            },
            "改進建議": {
                "type": "string",
                "description": "提出下一輪可驗證且高增益改進；若確無可改進，填『無』"
            },
            "核心記憶模塊": {
                "type": "object",
                "description": "保存短長期記憶與專案目標",
                "properties": {
                    "專案總結": {
                        "type": "string", 
                        "description": "中立概述目前進展、最新限制、決策依據與已驗證輸出"
                    },
                    "短期記憶": {
                        "type": "array",
                        "description": "最近數輪的關鍵事實/決策/限制(每列一句)",
                        "items": {"type": "string"}
                    },
                    "長期記憶新增": {
                        "type": "array",
                        "description": "⭐本輪新增的重要發現、原則、限制或教訓（將累積到歷史長期記憶中）",
                        "items": {"type": "string"}
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
                                "是否為當前任務": {"type": "boolean"}
                            },
                            "required": ["步驟", "任務", "狀態", "是否為當前任務"]
                        },
                        "minItems": 4
                    }
                },
                "required": ["專案總結", "短期記憶", "長期記憶新增", "專案目標"]
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
                                "web_title": {"type": ["string", "null"]}
                            },
                            "required": ["filename", "filetype", "code", "opens_window"]
                        }
                    }
                },
                "required": ["project_name", "description", "files"]
            }
        },
        "required": ["評分", "內容評價", "扣分原因", "改進建議", "核心記憶模塊", "專案輸出"]
    }

# ⭐ 新增/優化：系統指令
def get_json_system_instruction(
    mode: str = "default", 
    custom_instruction: str = "",
    accumulated_memory: List[str] = None  # ⭐ 新增：累積的長期記憶
) -> str:
    """獲取 JSON 模式的系統指令（優化版）"""
    normalized_mode = (mode or "default").lower()
    if normalized_mode not in {"default", "creative"}:
        normalized_mode = "default"

    # ⭐ 構建累積的長期記憶上下文
    memory_context = ""
    if accumulated_memory and len(accumulated_memory) > 0:
        memory_context = "\n\n【歷史長期記憶】（這些是從過往對話中累積的重要知識，請參考但不要在回應中重複）：\n"
        for i, mem in enumerate(accumulated_memory[-20:], 1):  # 最多顯示最近20條
            memory_context += f"{i}. {mem}\n"

    base_instruction = f"""你是一位專業的程式碼與專案助理。每次回應必須只輸出**單一 JSON 物件**，包含可執行程式碼、評分紀錄與記憶模塊。

{memory_context}

請在內部以私有思考空間完成『分解→多路徑探索→規劃→工具/程式輔助→驗證→收斂』：先用 Least-to-Most 拆解子任務；再以 Self-Consistency 蒐集多條潛在解並內隱評分；必要時展開 Tree/Graph-of-Thoughts 或 Plan-and-Solve 先擬計畫再執行；重檢索/互動任務採 ReAct 規劃行動與查詢；數值/符號/代碼問題可用 PoT/PAL 令『推理用自然語言、計算交由執行環境』。完成草案後以 Chain-of-Verification 擬訂並回答自我驗證問題；若為長算步驟，內隱套用 Process Supervision 思維逐步自檢；最後僅輸出單一最終 JSON，嚴禁外露任何中間推理/草稿/工具細節。

JSON 結構必須包含以下欄位：
{{
  "評分": 0-100 的整數,
  "內容評價": "≤200字要則遵守與品質摘要",
  "扣分原因": "若未滿分需具體指摘；否則『無』",
  "改進建議": "下一輪可驗證的強化方向；無則『無』",
  "核心記憶模塊": {{
      "專案總結": "中立概述進展/新限制/依據",
      "短期記憶": ["最近關鍵事實/決策/限制"],
      "長期記憶新增": ["⭐本輪新發現的重要原則/限制/教訓（會累積）"],
      "專案目標": [
          {{"步驟":1,"任務":"可驗證任務","狀態":"已完成/進行中/未開始","是否為當前任務":true/false}},
          ... 至少四項
      ]
  }},
  "專案輸出": {{
      "project_name":"專案名稱",
      "description":"問題→解法→驗證；含邊界/例外/回退",
      "main_file":"主要檔案名稱",
      "setup_instructions":["環境設置指令"],
      "run_instructions":["啟動指令"],
      "files":[
          {{
              "filename":"檔名.副檔名",
              "filetype":"python/javascript/html/...",
              "code":"⚠️ 完整可執行程式；繁中註解；【嚴禁】在代碼開頭加入任何檔案路徑或名稱註釋",
              "opens_window":true/false,
              "window_title":"視窗標題或null",
              "install_requirements":["pip install ..."],
              "dependencies":["套件清單"],
              "description":"用途/關鍵API/邊界",
              "run_command":"執行命令或null",
              "is_web_app":true/false,
              "can_open_standalone":true/false,
              "server_address":"http://localhost:5100或null",
              "web_title":"網頁標題或null"
          }}
      ]
  }}
}}

核心要範：
1) 僅輸出有效 JSON；不得加入 Markdown/註解/多餘文字。
2) 內部思考採『Least-to-Most→Self-Consistency→ToT/GoT→ReAct→PoT/PAL→CoVe→收斂』之流程。
3) ⚠️ 代碼格式嚴格要求：
   - `files[].code` 中的程式碼【絕對禁止】在開頭加入檔案路徑或名稱
   - 程式碼必須從實際的程式語句開始（如 Python 的 import，JavaScript 的 const 等）
   - 任何 # /path/to/file.py 或 // filename.js 這類註釋都是【嚴格禁止】的
   - 檔案名稱只能出現在 "filename" 欄位中
4) 安全與隱私：禁止外露中間推理；僅呈現可驗證結論與程式；第三方素材須標明授權假設或以自製替代。
5) 可執行性優先：`files[].code` 為可跑版本；避免除錯模式；Flask 以 `app.run(host='0.0.0.0', port=5100)`。
6) 結構自檢：輸出前內隱檢核鍵/必填/enum/型別/可解析性/依賴一致/命令可跑。
7) 使用者介面：若含UI，先內隱評估流程/回饋/響應式/可近用性；必要時加入狀態提示與錯誤訊息。
8) ⭐ 長期記憶累積：在「長期記憶新增」中記錄本輪新發現的重要原則、限制或教訓，這些會累積到歷史記憶中。
"""

    if normalized_mode == "creative":
        mode_instruction = """【模式：創意模式 - 強化版】

🎨 創意思維 SOP（Systematic Operational Procedure）：

**階段 1：需求理解與創意發想**
1. 深入理解用戶需求的核心訴求
2. 腦力激盪 3-5 個不同的創意方向
3. 評估每個方向的可行性和吸引力
4. 選擇最佳方案或融合多個方案

**階段 2：設計規劃**
1. UI/UX 設計：
   - 使用現代設計趨勢（漸層、陰影、動畫）
   - 考慮色彩心理學（活潑用橙黃、專業用藍灰、溫暖用粉紅）
   - 設計響應式布局（手機/平板/桌面）
   - 加入微互動（hover 效果、過渡動畫）

2. 互動設計：
   - 設計直觀的操作流程
   - 加入即時反饋（loading、success、error 狀態）
   - 考慮無障礙設計（鍵盤導航、screen reader）

3. 內容豐富度：
   - 生成多樣化的內容（至少 10+ 題目/選項/場景）
   - 加入隨機性和變化性
   - 設計遊戲化元素（分數、等級、成就）

**階段 3：技術實現**
1. 選擇合適的技術棧（優先考慮美觀和互動性）
2. 實現核心功能（確保完整可用）
3. 加入動畫和特效（CSS animations, transitions）
4. 優化性能（避免卡頓）

**階段 4：品質檢驗**
1. 自我測試所有功能
2. 檢查視覺一致性
3. 確認響應式設計
4. 驗證無障礙性

**具體要求**：
- 前端美觀度：使用現代 CSS 框架風格（Tailwind, Material Design, Glassmorphism）
- 色彩搭配：至少使用 3 種協調的顏色
- 字體層次：標題、副標題、正文有明顯區分
- 空白利用：避免擁擠，保持視覺呼吸感
- 動畫效果：至少包含 3 種互動動畫
- 內容豐富：生成的題目/選項/內容至少 10 個以上
- 趣味性：加入遊戲化元素或驚喜效果
"""
    else:
        mode_instruction = """【模式：默認模式】
- 穩健與可維護性優先：補齊測試、錯誤處理、效能與相容性；文件化步驟可重現。
"""

    custom_block = ""
    if custom_instruction:
        custom_block = f"\n【使用者自訂補充】\n{custom_instruction.strip()}"

    return "\n".join([
        base_instruction,
        mode_instruction,
        "請嚴格依此最新模板回覆，避免外露推理，且不得遺漏任何欄位。" + custom_block
    ])

# ============================================
# ⭐ 優化：JSON 字串清理函數
# ============================================

def sanitize_json_strings(data: Any) -> Any:
    """將字串中的控制符號轉換成安全的跳脫字元（增強版）"""
    if isinstance(data, dict):
        return {key: sanitize_json_strings(value) for key, value in data.items()}
    
    if isinstance(data, list):
        return [sanitize_json_strings(item) for item in data]
    
    if isinstance(data, str):
        # 移除或轉換 ASCII 控制字元（0x00-0x1F，除了 \t, \n, \r）
        sanitized = re.sub(r'[\x00-\x08\x0B-\x0C\x0E-\x1F]', '', data)
        
        # 確保 \n, \r, \t 被正確跳脫
        sanitized = sanitized.replace('\r\n', '\n')  # 統一換行符
        sanitized = sanitized.replace('\r', '\\r')
        sanitized = sanitized.replace('\n', '\\n')
        sanitized = sanitized.replace('\t', '\\t')
        
        return sanitized
    
    return data

def _is_escaped(text: str, index: int) -> bool:
    """判斷索引位置的字元是否被跳脫"""
    backslash_count = 0
    i = index - 1
    while i >= 0 and text[i] == '\\':
        backslash_count += 1
        i -= 1
    return backslash_count % 2 == 1

def _reescape_string_literal_controls(code: str) -> str:
    """將單行字串常值中的控制字元重新轉換為跳脫序列"""
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
                else:
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
    """恢復字串中的跳脫字元（增強版）"""
    if not isinstance(code, str):
        return code
    
    # 統一換行符
    normalized = code.replace('\\r\\n', '\n')
    normalized = normalized.replace('\\n', '\n')
    normalized = normalized.replace('\\t', '\t')
    
    # 重新跳脫單行字串中的控制字元
    return _reescape_string_literal_controls(normalized)

# ⭐ 新增：代碼清理函數 - 移除開頭的檔案路徑/名稱註釋
def clean_code_header(code: str, filetype: str) -> str:
    """移除代碼開頭的檔案路徑或名稱註釋"""
    if not code or not isinstance(code, str):
        return code
    
    lines = code.split('\n')
    cleaned_lines = []
    skip_header = True
    
    # 定義不同語言的註釋符號
    comment_patterns = {
        'python': [r'^\s*#', r'^\s*"""', r"^\s*'''"],
        'javascript': [r'^\s*//', r'^\s*/\*'],
        'typescript': [r'^\s*//', r'^\s*/\*'],
        'html': [r'^\s*<!--'],
        'css': [r'^\s*/\*'],
    }
    
    patterns = comment_patterns.get(filetype.lower(), [r'^\s*#', r'^\s*//'])
    
    for line in lines:
        # 如果還在處理開頭
        if skip_header:
            # 檢查是否為註釋行
            is_comment = any(re.match(pattern, line) for pattern in patterns)
            
            # 如果是註釋且包含檔案相關關鍵字，跳過
            if is_comment:
                lower_line = line.lower()
                if any(keyword in lower_line for keyword in ['file:', 'filename:', 'path:', '檔案:', '檔名:', '路徑:']):
                    continue
                # 如果是空註釋行，跳過
                if line.strip() in ['#', '//', '/*', '*/', '<!--', '-->']:
                    continue
            
            # 遇到非註釋行或不含檔案關鍵字的註釋，開始保留
            if not is_comment or (is_comment and not any(keyword in line.lower() for keyword in ['file:', 'filename:', 'path:', '檔案:', '檔名:', '路徑:'])):
                skip_header = False
                cleaned_lines.append(line)
        else:
            cleaned_lines.append(line)
    
    return '\n'.join(cleaned_lines)

# ============================================
# 配置管理模塊
# ============================================

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

# ============================================
# ⭐ 優化：對話歷史管理 - 支持累積長期記憶
# ============================================

class ConversationManager:
    """對話歷史管理器（優化版）"""
    
    @staticmethod
    def get_conversation_file(project_dir: str) -> Path:
        """獲取專案對話檔案路徑"""
        import hashlib
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

# ============================================
# 專案管理模塊
# ============================================

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

# ============================================
# 語法偵錯管理
# ============================================

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

# ============================================
# Gemini AI 模塊
# ============================================

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
# Flask 路由
# ============================================

window = None

@app.route('/')
def index():
    """主頁面"""
    return render_template('index.html')

@app.route('/api/config', methods=['GET', 'POST'])
def handle_config():
    """處理配置 API"""
    if request.method == 'GET':
        try:
            config = ConfigManager.load()
            return jsonify(asdict(config))
        except Exception as e:
            logger.error(f"載入配置時發生錯誤: {e}")
            default_config = AIConfig()
            return jsonify(asdict(default_config))
    
    elif request.method == 'POST':
        try:
            data = request.get_json()
            if not data:
                return jsonify({'success': False, 'error': '無效的請求數據'}), 400
            
            config = AIConfig(**data)
            success = ConfigManager.save(config)
            
            if success:
                return jsonify({'success': True, 'message': '配置已儲存'})
            else:
                return jsonify({'success': False, 'error': '儲存失敗,請檢查權限'}), 500
        except Exception as e:
            logger.error(f"保存配置時發生錯誤: {e}")
            return jsonify({'success': False, 'error': f'保存失敗: {str(e)}'}), 500

@app.route('/select-folder', methods=['GET'])
def select_folder():
    """選擇資料夾"""
    global window
    
    if not window:
        return jsonify({'success': False, 'error': 'Webview 視窗不存在'}), 500
    
    try:
        result = window.create_file_dialog(webview.FOLDER_DIALOG)
        path = result[0] if result else None
        
        if path:
            logger.info(f"選擇了資料夾: {path}")
            return jsonify({'success': True, 'path': path})
        else:
            return jsonify({'success': False, 'error': '未選擇資料夾'})
            
    except Exception as e:
        logger.error(f"選擇資料夾失敗: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/load-project', methods=['POST'])
def load_project():
    """載入現有專案"""
    try:
        data = request.get_json()
        project_dir = data.get('project_dir')
        
        if not project_dir or not Path(project_dir).exists():
            return jsonify({
                'success': False,
                'error': '專案目錄不存在'
            }), 400
        
        project_dir_path = Path(project_dir)
        project_info = ProjectManager.load_project_info(project_dir)
        project_files = ProjectManager.load_project_files(project_dir)
        project_structure = ProjectManager.get_project_structure(project_dir)
        conversation = ConversationManager.load_conversation(project_dir)
        
        is_ad_hoc_folder = False
        if not project_info:
            is_ad_hoc_folder = True
            metadata_files = ProjectManager.build_file_metadata(project_dir)
            project_info = {
                'project_name': project_dir_path.name,
                'description': '已匯入的現有資料夾',
                'main_file': None,
                'setup_instructions': [],
                'run_instructions': [],
                'files': metadata_files
            }
        else:
            if not project_info.get('files'):
                project_info['files'] = ProjectManager.build_file_metadata(project_dir)
        
        if conversation.project_name != project_info.get('project_name'):
            conversation.project_name = project_info.get('project_name', conversation.project_name)
            ConversationManager.save_conversation(conversation)
        
        ProjectManager.add_to_project_list(
            project_dir,
            project_info.get('project_name', project_dir_path.name),
            project_info.get('description', ''),
            status='ready',
            update_last_accessed=False
        )
        
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
        
        metadata_lookup = {}
        for item in project_info.get('files', []) or []:
            filename = item.get('filename')
            if filename:
                metadata_lookup[str(filename)] = item
        
        auto_attach_preview = []
        for file_data in project_files:
            name = file_data.get('name')
            if not name:
                continue
            
            meta = metadata_lookup.get(name, {})
            preview_type = meta.get('filetype') or file_data.get('type', 'text/plain')
            auto_attach_preview.append({
                'name': name,
                'type': preview_type
            })
        
        return jsonify({
            'success': True,
            'project_info': project_info,
            'project_files': project_files,
            'project_structure': project_structure,
            'files_count': len(project_files),
            'auto_attach_preview': auto_attach_preview,
            'is_ad_hoc_folder': is_ad_hoc_folder,
            'conversation': {
                'messages': messages_data,
                'created_at': conversation.created_at,
                'updated_at': conversation.updated_at,
                'memory_snapshot': conversation.memory_snapshot,
                'evaluation_snapshot': conversation.evaluation_snapshot,
                'accumulated_long_term_memory': conversation.accumulated_long_term_memory  # ⭐ 新增
            }
        })
        
    except Exception as e:
        logger.error(f"載入專案時發生錯誤: {e}")
        logger.error(traceback.format_exc())
        
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500

@app.route('/conversation/<path:project_dir>', methods=['GET'])
def get_conversation(project_dir):
    """獲取專案對話歷史"""
    try:
        conversation = ConversationManager.load_conversation(project_dir)
        
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
        
        return jsonify({
            'success': True,
            'conversation': {
                'project_name': conversation.project_name,
                'messages': messages_data,
                'created_at': conversation.created_at,
                'updated_at': conversation.updated_at,
                'memory_snapshot': conversation.memory_snapshot,
                'evaluation_snapshot': conversation.evaluation_snapshot,
                'accumulated_long_term_memory': conversation.accumulated_long_term_memory  # ⭐ 新增
            }
        })
    except Exception as e:
        logger.error(f"獲取對話歷史失敗: {e}")
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500

@app.route('/api/projects', methods=['GET'])
def get_projects():
    """獲取專案列表"""
    try:
        projects = ProjectManager.get_project_list()
        projects.sort(key=lambda x: x.get('last_accessed', ''), reverse=True)
        return jsonify({
            'success': True,
            'projects': projects
        })
    except Exception as e:
        logger.error(f"獲取專案列表失敗: {e}")
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500

@app.route('/api/projects/<path:project_path>', methods=['DELETE'])
def delete_project(project_path):
    """從列表移除專案"""
    try:
        success = ProjectManager.remove_from_project_list(project_path)
        if success:
            return jsonify({
                'success': True,
                'message': '專案已從列表移除',
                'deleted_path': project_path
            })
        else:
            return jsonify({
                'success': False,
                'error': '移除失敗'
            }), 500
    except Exception as e:
        logger.error(f"刪除專案失敗: {e}")
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500

@app.route('/run-process', methods=['POST'])
def run_process():
    """執行自動化流程"""
    try:
        data = request.get_json()
        
        folder_path = data.get('folder_path')
        prompt = data.get('prompt')
        display_prompt = data.get('display_prompt')
        memory_context = data.get('memory_context')
        config_data = data.get('config', {})
        files = data.get('files', [])
        is_iteration = data.get('is_iteration', False)
        attach_screenshot = data.get('attach_screenshot', False)
        attach_terminal = data.get('attach_terminal', False)
        attach_diagnostics = data.get('attach_diagnostics', False)
        
        if not all([folder_path, prompt]):
            return jsonify({
                'success': False,
                'error': '缺少必要參數(資料夾路徑或 AI 指令)',
                'ai_response': ''
            }), 400
        
        config = AIConfig(**{k: v for k, v in config_data.items() if k != 'response_mode'})
        
        result = ProcessManager.run_automation_process(
            folder_path,
            prompt,
            config,
            files,
            is_iteration,
            attach_screenshot,
            attach_terminal,
            attach_diagnostics,
            user_visible_prompt=display_prompt,
            memory_context=memory_context
        )
        
        response_data = {
            'success': result.success,
            'output': result.output,
            'files_created': result.files_created,
            'files_updated': result.files_updated,
            'ai_response': result.ai_response or '無 AI 回應',
            'ai_response_json': result.ai_response_json,
            'installation_logs': result.installation_logs,
            'error': result.error,
            'screenshots': result.screenshots,
            'is_iteration': result.is_iteration,
            'usage_metadata': result.usage_metadata,
            'terminal_output': result.terminal_output,
            'memory_snapshot': result.memory_snapshot,
            'evaluation_snapshot': result.evaluation_snapshot,
            'error_report_path': result.error_report_path  # ⭐ 新增
        }
        
        if attach_diagnostics:
            response_data['diagnostics_report'] = result.diagnostics_report
        
        if result.project_data:
            response_data['project'] = {
                'name': result.project_data.project_name,
                'description': result.project_data.description,
                'files_count': len(result.project_data.files),
                'main_file': result.project_data.main_file,
                'has_gui': any(f.opens_window for f in result.project_data.files)
            }
            response_data['auto_attach_preview'] = [
                {
                    'name': file.filename,
                    'type': file.filetype or 'text'
                }
                for file in result.project_data.files
            ]
        
        return jsonify(response_data)
        
    except Exception as e:
        logger.error(f"執行流程時發生錯誤: {e}")
        logger.error(traceback.format_exc())
        
        # ⭐ 生成錯誤報告
        error_report_path = ErrorReporter.generate_report(
            error_type="API_ERROR",
            error_message=str(e),
            stack_trace=traceback.format_exc()
        )
        
        return jsonify({
            'success': False,
            'error': str(e),
            'ai_response': '執行過程中發生未預期的錯誤',
            'output': f'系統錯誤: {str(e)}\n\n錯誤報告已生成: {error_report_path}',
            'error_report_path': str(error_report_path)  # ⭐ 新增
        }), 500

@app.route('/capture-screenshots', methods=['POST'])
def capture_screenshots():
    """擷取螢幕畫面"""
    try:
        data = request.get_json() or {}
        capture_mode = data.get('mode', 'programs')
        window_titles = data.get('window_titles', [])
        project_name = data.get('project_name')
        project_json = data.get('project_json')
        
        screenshots = []
        
        if capture_mode == 'monitors':
            logger.info("跳過螢幕擷取模式")
        
        elif capture_mode == 'programs':
            if window_titles or project_name or project_json:
                time.sleep(2)
                program_screenshots = ScreenCapture.capture_running_programs(
                    window_titles, 
                    project_name,
                    project_json
                )
                screenshots.extend(program_screenshots)
            else:
                logger.warning("沒有指定視窗標題或專案名稱")
        
        elif capture_mode == 'all':
            logger.info("不建議使用 'all' 模式")
            if window_titles or project_name or project_json:
                time.sleep(2)
                program_screenshots = ScreenCapture.capture_running_programs(
                    window_titles,
                    project_name,
                    project_json
                )
                screenshots.extend(program_screenshots)
        
        logger.info(f"擷取完成,共 {len(screenshots)} 張截圖")
        
        return jsonify({
            'success': True,
            'screenshots': screenshots,
            'count': len(screenshots)
        })
        
    except Exception as e:
        logger.error(f"擷取螢幕失敗: {e}")
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500

@app.route('/screenshot/<filename>')
def serve_screenshot(filename):
    """提供螢幕截圖"""
    filepath = SCREENSHOT_DIR / filename
    if filepath.exists():
        return send_file(
            filepath, 
            mimetype='image/png',
            as_attachment=False,
            download_name=filename
        )
    else:
        return "Screenshot not found", 404

@app.route('/running-programs', methods=['GET'])
def get_running_programs():
    """獲取運行中的程式列表"""
    try:
        status = ProgramManager.check_programs()
        return jsonify({
            'success': True,
            'programs': status,
            'count': len(status)
        })
    except Exception as e:
        logger.error(f"獲取程式狀態失敗: {e}")
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500

@app.route('/terminate-program/<int:pid>', methods=['POST'])
def terminate_program(pid):
    """終止指定的程式"""
    try:
        success = ProgramManager.terminate_program(pid)
        if success:
            return jsonify({
                'success': True,
                'message': f'程式 PID {pid} 已終止'
            })
        else:
            return jsonify({
                'success': False,
                'error': f'找不到 PID {pid} 的程式'
            }), 404
    except Exception as e:
        logger.error(f"終止程式失敗: {e}")
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500

# ============================================
# 主程式入口
# ============================================

def run_flask():
    """運行 Flask 伺服器"""
    app.run(host=HOST, port=PORT, debug=False, use_reloader=False)

def main():
    """主程式入口"""
    logger.info("=== AI 自動化開發控制器 Pro v5.5 啟動 ===")
    logger.info(f"配置目錄: {CONFIG_DIR}")
    logger.info(f"截圖目錄: {SCREENSHOT_DIR}")
    logger.info(f"日誌目錄: {LOG_DIR}")
    logger.info(f"專案目錄: {PROJECTS_DIR}")
    logger.info(f"對話目錄: {CONVERSATIONS_DIR}")
    logger.info(f"錯誤報告目錄: {ERROR_REPORTS_DIR}")  # ⭐ 新增
    
    flask_thread = threading.Thread(target=run_flask)
    flask_thread.daemon = True
    flask_thread.start()
    
    time.sleep(1)
    
    global window
    window = webview.create_window(
        'AI 自動化開發控制器 Pro v5.5',
        f'http://{HOST}:{PORT}',
        width=1400,
        height=1000,
        resizable=True,
        on_top=False
    )
    
    logger.info("正在啟動圖形界面...")
    webview.start()

if __name__ == '__main__':
    main()