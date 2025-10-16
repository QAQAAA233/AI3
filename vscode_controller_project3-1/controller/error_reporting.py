"""錯誤報告模組。"""
from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any, Dict

from . import ERROR_REPORTS_DIR, logger


class ErrorReporter:
    """錯誤報告生成器 - 自動生成詳細的錯誤報告"""

    @staticmethod
    def generate_report(
        error_type: str,
        error_message: str,
        ai_response: str = "",
        json_data: Any = None,
        stack_trace: str = "",
        context: Dict[str, Any] | None = None
    ) -> Path:
        """生成詳細的錯誤報告文件"""
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        report_filename = f"{error_type}_{timestamp}.md"
        report_path = ERROR_REPORTS_DIR / report_filename

        report_lines = [
            f"# 🚨 錯誤報告：{error_type}",
            f"\n**時間**：{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
            f"\n## 📋 錯誤摘要",
            f"\n```",
            error_message,
            f"```",
        ]

        if stack_trace:
            report_lines.extend([
                f"\n## 🔍 堆疊追蹤",
                f"\n```python",
                stack_trace,
                f"```"
            ])

        if ai_response:
            truncated_response = ai_response[:2000]
            if len(ai_response) > 2000:
                truncated_response += "\n\n... (回應過長，已截斷)"

            report_lines.extend([
                f"\n## 🤖 AI 原始回應",
                f"\n```json",
                truncated_response,
                f"```"
            ])

        if json_data:
            try:
                json_str = json.dumps(json_data, indent=2, ensure_ascii=False)[:1000]
                report_lines.extend([
                    f"\n## 📦 解析的 JSON 數據",
                    f"\n```json",
                    json_str,
                    f"```"
                ])
            except Exception:  # pragma: no cover - 防禦性處理
                pass

        if context:
            report_lines.extend([
                f"\n## 🎯 上下文信息",
                f"\n```json",
                json.dumps(context, indent=2, ensure_ascii=False),
                f"```"
            ])

        suggestions = ErrorReporter._get_fix_suggestions(error_type, error_message)
        if suggestions:
            report_lines.extend([
                f"\n## 💡 修復建議",
                f"\n{suggestions}"
            ])

        report_content = "\n".join(report_lines)
        with open(report_path, 'w', encoding='utf-8') as file:
            file.write(report_content)

        logger.info("✅ 錯誤報告已生成：%s", report_path)
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
            """,
        }

        return suggestions.get(error_type, "請查看上方的錯誤信息並聯繫開發者。")


__all__ = ['ErrorReporter']
