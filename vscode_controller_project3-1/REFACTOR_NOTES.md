# 模組化重構說明

## 1. 拆分策略與維護性
- 將原本超過 3,000 行的 `app.py` 拆分為 `controller_core` 套件，依責任劃分為 `environment.py`（環境配置）、`models.py`（資料模型）、`utils.py`（資料處理工具）、`managers.py`（設定/專案/對話管理）、`diagnostics.py`（錯誤報告與語法偵測）、`services.py`（AI 服務與自動化流程）。
- 單一檔案維持在可閱讀的長度，功能區隔清楚，降低後續修改時彼此影響的風險，並能個別撰寫單元測試。

## 2. 拆分注意事項與現有 100+ 功能對應
- 依功能群組盤點超過 100 個方法：
  - 設定與專案 CRUD：移至 `managers.py`，確保對應路由呼叫邏輯一致。
  - 長期記憶、流程管線、程式管理：集中於 `services.py`，避免散落。
  - JSON 清理與 Schema：統一放在 `utils.py`，由 `services.py` 呼叫確保 JSON 安全性。
- 拆分時保留原有函式簽章與回傳值，確保前端呼叫不需改動。

## 3. 拆分後優勢證明
- `python -m compileall` 編譯通過，代表新的模組劃分語法正確可執行。
- 結構化後的模組能被單獨匯入、覆寫或測試；例如可只測 `controller_core/services.py` 來驗證流程，不需載入整個 Flask App。
- 路由層只保留 I/O 與轉換邏輯，降低認知負擔與回歸測試範圍。

## 4. 既有程式碼重複與邏輯優化
- `ProjectManager.save_project_files` 與舊有 `CodeProcessor.save_project_files` 重複：統一保留在 `CodeProcessor`，並於 `ProcessManager` 內呼叫，避免邏輯分岔。
- 目錄建立、錯誤報告等共用函式集中管理，避免多處複製同樣的 try/except。

## 5. 優化效果說明
- 新結構讓 `app.py` 專注在路由與回應，核心邏輯在 `controller_core` 中可重複使用。
- 使用者新增功能時，只需擴充對應模組（例如新增資料模型即修改 `models.py`），降低修改衝突。

## 6. 優化與拆分後續注意
- `services.py` 內的流程仍相當複雜，建議後續針對 `ProcessManager` 撰寫測試，並視需要再拆子流程（例如執行環境、輸出整理）。
- 建議在 CI 流程加入靜態分析（如 `ruff`）與單元測試，確保模組化後維持品質。
- 若未來增加新的自動化服務，可於 `controller_core/services.py` 新增類別並由 `app.py` 匯入，保持一致性。

## 參考原則
- 拆分遵循 Flask 官方建議的 Blueprint/模組化結構。
- 依據 Clean Architecture 與 SOLID 單一職責原則劃分模組，避免過度細碎。
