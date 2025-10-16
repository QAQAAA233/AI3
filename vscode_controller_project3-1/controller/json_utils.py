"""JSON 與程式碼處理工具函數。"""
from __future__ import annotations

import json
import re
from typing import Any, Dict, List, Optional


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
                                "code": {
                                    "type": "string",
                                    "description": "⚠️ 完整可執行程式；繁中註解；嚴禁在開頭加入檔案路徑或名稱",
                                },
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
    """獲取 JSON 模式的系統指令（優化版）"""
    normalized_mode = (mode or "default").lower()
    if normalized_mode not in {"default", "creative"}:
        normalized_mode = "default"

    memory_context = ""
    if accumulated_memory:
        memory_context = "\n\n【歷史長期記憶】（這些是從過往對話中累積的重要知識，請參考但不要在回應中重複）：\n"
        for index, memory in enumerate(accumulated_memory[-20:], 1):
            memory_context += f"{index}. {memory}\n"

    base_instruction = f"""你是一位專業的程式碼與專案助理。每次回應必須只輸出**單一 JSON 物件**，包含可執行程式碼、評分紀錄與記憶模塊。

{memory_context}

請在內部以私有思考空間完成『分解→多路徑探索→規劃→工具/程式輔助→驗證→收斂』：先用 Least-to-Most 拆解子任務；再以 Self-Consistency 蒐集多條潛在解並內隱評分；必要時展開 Tree/Graph-of-Thoughts 或 Plan-and-Solve 先擬計畫再執行；重檢索/互動任務採 ReAct 規劃行動與查詢；數值/符號/代碼問題可用 PoT/PAL 令『推理用自然語言、計算交由執行環境』。完成草案後以 Chain-of-Verification 擬訂並回答自我驗證問題；若為長算步驟，內隱套用 Process Supervision 思維逐步自檢；最後僅輸出單一最終 JSON，嚴禁外露任何中間推理/草稿/工具細節。
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
        "請嚴格依此最新模板回覆，避免外露推理，且不得遺漏任何欄位。" + custom_block,
    ])


def sanitize_json_strings(data: Any) -> Any:
    """將字串中的控制符號轉換成安全的跳脫字元（增強版）"""
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
    """判斷索引位置的字元是否被跳脫"""
    backslash_count = 0
    pointer = index - 1
    while pointer >= 0 and text[pointer] == '\\':
        backslash_count += 1
        pointer -= 1
    return backslash_count % 2 == 1


def _reescape_string_literal_controls(code: str) -> str:
    """將單行字串常值中的控制字元重新轉換為跳脫序列"""
    if not code:
        return code

    result: List[str] = []
    index = 0
    length = len(code)
    in_string = False
    string_delim = ''
    is_triple = False
    in_comment = False

    while index < length:
        ch = code[index]

        if in_comment:
            result.append(ch)
            if ch == '\n':
                in_comment = False
            index += 1
            continue

        if not in_string:
            if ch == '#':
                in_comment = True
                result.append(ch)
                index += 1
                continue

            if ch in ('"', "'"):
                if code.startswith(ch * 3, index):
                    string_delim = ch * 3
                    is_triple = True
                    in_string = True
                    result.append(string_delim)
                    index += 3
                    continue
                string_delim = ch
                is_triple = False
                in_string = True
                result.append(ch)
                index += 1
                continue

            result.append(ch)
            if ch == '\n':
                in_comment = False
            index += 1
            continue

        if is_triple:
            if code.startswith(string_delim, index):
                result.append(string_delim)
                index += len(string_delim)
                in_string = False
                is_triple = False
                string_delim = ''
            else:
                result.append(ch)
                index += 1
            continue

        if ch in ('"', "'") and ch == string_delim and not _is_escaped(code, index):
            result.append(ch)
            index += 1
            in_string = False
            string_delim = ''
            continue

        if ch == '\n':
            result.append('\\n')
            index += 1
            continue

        if ch == '\r':
            result.append('\\r')
            index += 1
            continue

        if ch == '\t':
            result.append('\\t')
            index += 1
            continue

        result.append(ch)
        index += 1

    return ''.join(result)


def normalize_code_content(code: str) -> str:
    """恢復字串中的跳脫字元（增強版）"""
    if not isinstance(code, str):
        return code

    normalized = code.replace('\\r\\n', '\n')
    normalized = normalized.replace('\\n', '\n')
    normalized = normalized.replace('\\t', '\t')
    return _reescape_string_literal_controls(normalized)


def clean_code_header(code: str, filetype: str) -> str:
    """移除代碼開頭的檔案路徑或名稱註釋"""
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

            if not is_comment or (is_comment and not any(keyword in line.lower() for keyword in ['file:', 'filename:', 'path:', '檔案:', '檔名:', '路徑:'])):
                skip_header = False
                cleaned_lines.append(line)
        else:
            cleaned_lines.append(line)

    return '\n'.join(cleaned_lines)


__all__ = [
    'get_json_schema',
    'get_json_system_instruction',
    'sanitize_json_strings',
    'normalize_code_content',
    'clean_code_header',
]
