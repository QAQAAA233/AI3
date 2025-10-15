"""Utility helpers for working with JSON responses and generated code."""
from __future__ import annotations

import json
import re
import textwrap
from typing import Any, Dict, List


def get_json_schema() -> Dict[str, Any]:
    """Return the JSON schema expected from the Gemini responses."""
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
                "required": ["專案總結", "短期記憶", "長期記憶新增", "專案目標"],
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
        "required": ["評分", "內容評價", "扣分原因", "改進建議", "核心記憶模塊", "專案輸出"],
    }


def get_json_system_instruction(
    mode: str = "default",
    custom_instruction: str = "",
    accumulated_memory: List[str] | None = None,
) -> str:
    """Return the system instruction used for JSON mode prompts."""
    normalized_mode = (mode or "default").lower()
    if normalized_mode not in {"default", "creative"}:
        normalized_mode = "default"

    memory_context = ""
    if accumulated_memory:
        memory_context = "\n\n【歷史長期記憶】（這些是從過往對話中累積的重要知識，請參考但不要在回應中重複）：\n"
        for index, memory in enumerate(accumulated_memory[-20:], 1):
            memory_context += f"{index}. {memory}\n"

    base_instruction = textwrap.dedent(
        f"""
        你是一位專業的程碼與專案助理。每次回應必須只輸出**單一 JSON 物件**，包含可執行程式碼、評分紀錄與記憶模塊。

        {memory_context}

        請在內部以私有思考空間完成『分解→多路徑探索→規劃→工具/程式輔助→驗證→收斂』：先用 Least-to-Most 拆解子任務；再以 Self-Consistency 蒐集多條潛在解並內隱評分；必要時展開 Tree/Graph-of-Thoughts 或 Plan-and-Solve 先擬計畫再執行；重檢索/互動任務採 ReAct 規劃行動與查詢；數值/符號/代碼問題可用 PoT/PAL 令『推理用自然語言、計算交由執行環境』。完成草案後以 Chain-of-Verification 擬訂並回答自我驗證問題；若為長算步驟，內隱套用 Process Supervision 思維逐步自檢；最後僅輸出單一最終 JSON，嚴禁外露任何中間推理/草稿/工具細節。

        【輸出規範】
        1. 嚴禁提供任何 JSON 物件以外的內容（如普通文字、程式碼區塊、Markdown、列表等）。
        2. 若需描述多個檔案，請放入 `專案輸出.files` 陣列。
        3. 檔案 `code` 欄位務必為「純程式碼字串」。禁止在開頭加入檔案名稱/路徑/註解。
        4. 所有繁體中文註解請凝練聚焦目的與限制。
        5. 若需建議指令或後續操作，放入 `專案輸出.run_instructions`。
        6. 若要更新記憶，請正確填入 `核心記憶模塊`。
        7. 回應前請再次確認 JSON 無語法錯誤，字串需妥善跳脫控制字元。
        """
    ).strip()

    if normalized_mode == "creative":
        creative_instruction = textwrap.dedent(
            """
            【創意增益模式】
            - 保留實用程式核心的同時，可加入更多創意細節、介面強化或體驗優化。
            - 若遇到模糊需求，請提出兩種以上可行方案於 `專案輸出.description` 裡比較。
            - 請確保所有創意仍可實際落地，並在 `專案輸出.run_instructions` 補充測試方式。
            """
        ).strip()
        base_instruction += f"\n\n{creative_instruction}"

    if custom_instruction:
        custom_block = textwrap.dedent(custom_instruction).strip()
        if custom_block:
            base_instruction += f"\n\n【使用者額外指令】\n{custom_block}"

    return base_instruction


def sanitize_json_strings(data: Any) -> Any:
    """Recursively escape control characters inside JSON string values."""
    if isinstance(data, dict):
        return {key: sanitize_json_strings(value) for key, value in data.items()}
    if isinstance(data, list):
        return [sanitize_json_strings(item) for item in data]
    if isinstance(data, str):
        return (
            data.replace("\r", "\\r")
            .replace("\n", "\\n")
            .replace("\t", "\\t")
            .replace("\u2028", "\\u2028")
            .replace("\u2029", "\\u2029")
        )
    return data


def _is_escaped(text: str, index: int) -> bool:
    """Return True if the character at *index* is escaped."""
    backslash_count = 0
    i = index - 1
    while i >= 0 and text[i] == "\\":
        backslash_count += 1
        i -= 1
    return backslash_count % 2 == 1


def _reescape_string_literal_controls(code: str) -> str:
    """Re-escape control characters in string literals for readability."""
    if not code:
        return code

    result: List[str] = []
    i = 0
    length = len(code)
    in_string = False
    string_delim = ""
    is_triple = False
    in_comment = False

    while i < length:
        ch = code[i]

        if in_comment:
            result.append(ch)
            if ch == "\n":
                in_comment = False
            i += 1
            continue

        if not in_string:
            if ch == "#":
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
            if ch == "\n":
                in_comment = False
            i += 1
            continue

        if is_triple:
            if code.startswith(string_delim, i):
                result.append(string_delim)
                i += len(string_delim)
                in_string = False
                is_triple = False
                string_delim = ""
            else:
                result.append(ch)
                i += 1
            continue

        if ch in ('"', "'") and ch == string_delim and not _is_escaped(code, i):
            result.append(ch)
            i += 1
            in_string = False
            string_delim = ""
            continue

        if ch == "\n":
            result.append("\\n")
            i += 1
            continue

        if ch == "\r":
            result.append("\\r")
            i += 1
            continue

        if ch == "\t":
            result.append("\\t")
            i += 1
            continue

        result.append(ch)
        i += 1

    return "".join(result)


def normalize_code_content(code: str) -> str:
    """Normalize escape characters in generated code strings."""
    if not isinstance(code, str):
        return code

    normalized = code.replace("\\r\\n", "\n")
    normalized = normalized.replace("\\n", "\n")
    normalized = normalized.replace("\\t", "\t")

    return _reescape_string_literal_controls(normalized)


def clean_code_header(code: str, filetype: str) -> str:
    """Remove leading file path comments that frequently appear in responses."""
    if not code or not isinstance(code, str):
        return code

    lines = code.split("\n")
    cleaned_lines: List[str] = []
    skip_header = True

    comment_patterns = {
        "python": [r"^\s*#", r"^\s*\"\"\"", r"^\s*'''"],
        "javascript": [r"^\s*//", r"^\s*/\*"],
        "typescript": [r"^\s*//", r"^\s*/\*"],
        "html": [r"^\s*<!--"],
        "css": [r"^\s*/\*"],
    }

    patterns = comment_patterns.get(filetype.lower(), [r"^\s*#", r"^\s*//"])

    for line in lines:
        if skip_header:
            is_comment = any(re.match(pattern, line) for pattern in patterns)
            if is_comment:
                lower_line = line.lower()
                if any(
                    keyword in lower_line
                    for keyword in ["file:", "filename:", "path:", "檔案:", "檔名:", "路徑:"]
                ):
                    continue
                if line.strip() in ["#", "//", "/*", "*/", "<!--", "-->"]:
                    continue
            if not is_comment or (
                is_comment
                and not any(
                    keyword in line.lower()
                    for keyword in ["file:", "filename:", "path:", "檔案:", "檔名:", "路徑:"]
                )
            ):
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
