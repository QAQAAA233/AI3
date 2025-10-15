"""錯誤報告與語法偵錯工具。"""

from __future__ import annotations

import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from .environment import ERROR_REPORTS_DIR

logger = logging.getLogger(__name__)


class ErrorReporter:
    """負責產生結構化的錯誤報告。"""

    @staticmethod
    def generate_report(
        error_type: str,
        error_message: str,
        ai_response: str = "",
        json_data: Any = None,
        stack_trace: str = "",
        context: Optional[Dict[str, Any]] = None,
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
            report_lines.extend(
                [
                    "\n## 🔍 堆疊追蹤",
                    "\n```python",
                    stack_trace,
                    "```",
                ]
            )

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
                report_lines.extend(
                    [
                        "\n## 📦 解析的 JSON 數據",
                        "\n```json",
                        json_str,
                        "```",
                    ]
                )
            except Exception:  # pragma: no cover - 避免報告流程被中斷
                pass

        if context:
            report_lines.extend(
                [
                    "\n## 🎯 上下文信息",
                    "\n```json",
                    json.dumps(context, indent=2, ensure_ascii=False),
                    "```",
                ]
            )

        suggestions = ErrorReporter._get_fix_suggestions(error_type, error_message)
        if suggestions:
            report_lines.extend([
                "\n## 💡 修復建議",
                f"\n{suggestions}",
            ])

        report_content = "\n".join(report_lines)
        with open(report_path, "w", encoding="utf-8") as file:
            file.write(report_content)

        logger.info("✅ 錯誤報告已生成：%s", report_path)
        return report_path

    @staticmethod
    def _get_fix_suggestions(error_type: str, error_message: str) -> str:
        suggestions = {
            "JSON_DECODE_ERROR": """
1. **檢查 AI 回應格式**：確認 AI 是否正確輸出 JSON 格式
2. **清理控制字元**：檢查是否有未跳脫的 `\\n`, `\\r`, `\\t` 等字元
3. **驗證 JSON 結構**：使用線上 JSON 驗證器檢查結構完整性
4. **調整 AI 模型**：考慮切換到更穩定的模型版本
5. **簡化需求**：如果內容過於複雜，嘗試分步驟生成""",
            "CONTROL_CHARACTER_ERROR": """
1. **啟用字串清理**：確認 `sanitize_json_strings()` 函數正常運作
2. **檢查 AI 輸出**：查看上方的 AI 原始回應，找出非法字元位置
3. **更新提示詞**：在 system_instruction 中明確要求避免特殊字元
4. **手動修復**：如果是特定文件，可以手動編輯 PROJECT_INFO.json""",
            "BROWSER_LAUNCH_ERROR": """
1. **檢查路徑**：確認檔案路徑不包含中文或特殊字元
2. **使用 file:// URL**：確保使用 `Path.resolve().as_uri()` 格式
3. **等待檔案生成**：在打開瀏覽器前加入 `time.sleep(0.5)`
4. **檢查瀏覽器**：確認 Chrome 或 Edge 已正確安裝""",
        }

        return suggestions.get(error_type, "請查看上方的錯誤信息並聯繫開發者。")


class DiagnosticsManager:
    """提供專案語法檢查的功能。"""

    EXCLUDE_NAMES = {
        "PROJECT_INFO.json",
        "__pycache__",
        ".git",
        "node_modules",
        "venv",
        ".vscode",
    }

    @staticmethod
    def _truncate(text: str, limit: int = 180) -> str:
        if len(text) <= limit:
            return text
        return text[: limit - 1] + "…"

    @staticmethod
    def _check_python(file_path: Path) -> Tuple[str, str]:
        try:
            source = file_path.read_text(encoding="utf-8")
        except Exception as exc:
            return "warning", f"無法讀取檔案: {exc}"

        try:
            compile(source, str(file_path), "exec")
            return "passed", "語法檢查通過"
        except SyntaxError as exc:
            line = exc.lineno or 0
            column = exc.offset or 0
            message = f"SyntaxError 第 {line} 行第 {column} 欄: {exc.msg}"
            return "failed", message
        except Exception as exc:  # pragma: no cover - 其他語法錯誤
            return "warning", DiagnosticsManager._truncate(str(exc))

    @staticmethod
    def _check_json(file_path: Path) -> Tuple[str, str]:
        try:
            text = file_path.read_text(encoding="utf-8")
            json.loads(text)
            return "passed", "JSON 結構有效"
        except json.JSONDecodeError as exc:
            message = f"JSONDecodeError 第 {exc.lineno} 行第 {exc.colno} 欄: {exc.msg}"
            return "failed", message
        except Exception as exc:
            return "warning", DiagnosticsManager._truncate(str(exc))

    @staticmethod
    def collect(project_dir: str) -> Tuple[List[Dict[str, Any]], str]:
        base_path = Path(project_dir)
        if not base_path.exists():
            return [], ""

        handlers = {
            ".py": ("Python", DiagnosticsManager._check_python),
            ".json": ("JSON", DiagnosticsManager._check_json),
        }

        results: List[Dict[str, Any]] = []
        for file_path in base_path.rglob("*"):
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
                status, message = "warning", f"檢查時發生錯誤: {exc}"

            results.append(
                {
                    "file": str(file_path.relative_to(base_path)),
                    "language": language,
                    "status": status,
                    "message": message,
                }
            )

        prompt_block = DiagnosticsManager._format_prompt(results)
        return results, prompt_block

    @staticmethod
    def _format_prompt(results: List[Dict[str, Any]]) -> str:
        if not results:
            return ""

        icon_map = {
            "passed": "✅",
            "failed": "❌",
            "warning": "⚠️",
        }

        lines = ["【語法偵錯結果】"]
        for item in results:
            icon = icon_map.get(item.get("status"), "•")
            language = item.get("language", "未知語言")
            file_name = item.get("file", "未知檔案")
            message = item.get("message", "")
            lines.append(f"{icon} [{language}] {file_name} -> {message}")

        return "\n".join(lines)


__all__ = ["ErrorReporter", "DiagnosticsManager"]
