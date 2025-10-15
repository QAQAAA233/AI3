"""共用工具函式。"""

from __future__ import annotations

import json
import logging
import re
from datetime import datetime
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


def get_json_schema() -> Dict[str, Any]:
    """回傳 Gemini 生成時使用的 JSON Schema。"""

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
                        "description": "⭐本輪新增的重要發現、原則、限制或教訓（將累積到歷史長期記憶中）",
                        "items": {"type": "string"},
                    },
                    "專案目標": {
                        "type": "array",
                        "description": "以可驗證的任務陳述",
                        "items": {
                            "type": "object",
                            "properties": {
                                "步驟": {"type": "integer"},
                                "任務": {"type": "string"},
                                "狀態": {
                                    "type": "string",
                                    "enum": ["未開始", "進行中", "已完成"],
                                },
                                "是否為當前任務": {"type": "boolean"},
                            },
                            "required": ["步驟", "任務", "狀態", "是否為當前任務"],
                        },
                        "minItems": 4,
                    },
                },
                "required": [
                    "專案總結",
                    "短期記憶",
                    "長期記憶新增",
                    "專案目標",
                ],
            },
            "專案輸出": {
                "type": "object",
                "description": "包含可執行程式與操作資訊",
                "properties": {
                    "project_name": {"type": "string"},
                    "description": {"type": "string"},
                    "main_file": {"type": "string"},
                    "setup_instructions": {
                        "type": "array",
                        "items": {"type": "string"},
                    },
                    "run_instructions": {
                        "type": "array",
                        "items": {"type": "string"},
                    },
                    "files": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "filename": {"type": "string"},
                                "filetype": {"type": "string"},
                                "code": {
                                    "type": "string",
                                    "description": "⚠️ 完整可執行程式；繁中註解；嚴禁在開頭加入檔案路徑或名稱",
                                },
                                "opens_window": {"type": "boolean"},
                                "window_title": {"type": ["string", "null"]},
                                "install_requirements": {
                                    "type": "array",
                                    "items": {"type": "string"},
                                },
                                "dependencies": {
                                    "type": "array",
                                    "items": {"type": "string"},
                                },
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
        "required": [
            "評分",
            "內容評價",
            "扣分原因",
            "改進建議",
            "核心記憶模塊",
            "專案輸出",
        ],
    }


def get_json_system_instruction(
    mode: str = "default",
    custom_instruction: str = "",
    accumulated_memory: Optional[List[str]] = None,
) -> str:
    """構建 Gemini 使用的 system_instruction。"""

    normalized_mode = (mode or "default").lower()
    if normalized_mode not in {"default", "creative"}:
        normalized_mode = "default"

    memory_context = ""
    if accumulated_memory:
        memory_context = "\n\n【歷史長期記憶】（這些是從過往對話中累積的重要知識，請參考但不要在回應中重複）：\n"
        for index, mem in enumerate(accumulated_memory[-20:], 1):
            memory_context += f"{index}. {mem}\n"

    base_instruction = f"""你是 AI 自動化開發控制器 Pro v5.5。請嚴格遵守以下規範：
{memory_context}
輸出格式必須為 JSON，且符合提供的 Schema。"""

    creative_block = """【模式：創意模式 - 強化版】

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
- 趣味性：加入遊戲化元素或驚喜效果"""

    default_block = """【模式：默認模式】
- 穩健與可維性優先：補齊測試、錯誤處理、效能與相容性；文件化步驟可重現。"""

    mode_instruction = creative_block if normalized_mode == "creative" else default_block

    custom_block = f"\n【使用者自訂補充】\n{custom_instruction.strip()}" if custom_instruction else ""

    template_requirements = """【輸出模板】
{{
  "評分":0-100,
  "內容評價":"≤200字摘要", 
  "扣分原因":"具體說明或填『無』",
  "改進建議":"下一步改善或填『無』",
  "核心記憶模塊":{{
      "專案總結":"最新狀態", 
      "短期記憶":["最近決策"], 
      "長期記憶新增":["重要原則"],
      "專案目標":[{{"步驟":1,"任務":"...","狀態":"進行中","是否為當前任務":true}}]
  }},
  "專案輸出":{{
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
8) ⭐ 長期記憶累積：在「長期記憶新增」中記錄本輪新發現的重要原則、限制或教訓，這些會累積到歷史記憶中。"""

    return "\n".join(
        [
            base_instruction,
            mode_instruction,
            "請嚴格依此最新模板回覆，避免外露推理，且不得遺漏任何欄位。" + custom_block,
            template_requirements,
        ]
    )


def sanitize_json_strings(data: Any) -> Any:
    """將輸出中的控制符號轉為安全字元。"""

    if isinstance(data, dict):
        return {key: sanitize_json_strings(value) for key, value in data.items()}
    if isinstance(data, list):
        return [sanitize_json_strings(item) for item in data]
    if isinstance(data, str):
        sanitized = re.sub(r"[\x00-\x08\x0B-\x0C\x0E-\x1F]", "", data)
        sanitized = sanitized.replace("\r\n", "\n")
        sanitized = sanitized.replace("\r", "\\r")
        sanitized = sanitized.replace("\n", "\\n")
        sanitized = sanitized.replace("\t", "\\t")
        return sanitized
    return data


def _is_escaped(text: str, index: int) -> bool:
    backslash_count = 0
    index -= 1
    while index >= 0 and text[index] == "\\":
        backslash_count += 1
        index -= 1
    return backslash_count % 2 == 1


def _reescape_string_literal_controls(code: str) -> str:
    pattern = r"(['\"])((?:\\.|[^\\\1])*)\1"

    def _replace(match: re.Match[str]) -> str:
        quote = match.group(1)
        content = match.group(2)
        content = content.replace("\\n", "\\\n").replace("\\r", "\\\r").replace("\\t", "\\\t")
        return f"{quote}{content}{quote}"

    return re.sub(pattern, _replace, code)


def normalize_code_content(code: str) -> str:
    code = code.replace("\r\n", "\n")
    code = _reescape_string_literal_controls(code)
    return code


def clean_code_header(code: str, filetype: str) -> str:
    lines = code.splitlines()
    cleaned_lines: List[str] = []
    skip_header = True

    patterns = [
        r"^\s*#",
        r"^\s*//",
        r"^\s*/\*",
        r"^\s*\*",
        r"^\s*--",
        r"^\s*<!--",
    ]

    for line in lines:
        if skip_header:
            is_comment = any(re.match(pattern, line) for pattern in patterns)
            if is_comment:
                lower_line = line.lower()
                if any(keyword in lower_line for keyword in ["file:", "filename:", "path:", "檔案:", "檔名:", "路徑:"]):
                    continue
                if line.strip() in ["#", "//", "/*", "*/", "<!--", "-->"]:
                    continue
            if not is_comment or (is_comment and not any(
                keyword in line.lower() for keyword in ["file:", "filename:", "path:", "檔案:", "檔名:", "路徑:"]
            )):
                skip_header = False
                cleaned_lines.append(line)
        else:
            cleaned_lines.append(line)

    return "\n".join(cleaned_lines)


__all__ = [
    "get_json_schema",
    "get_json_system_instruction",
    "sanitize_json_strings",
    "normalize_code_content",
    "clean_code_header",
]
