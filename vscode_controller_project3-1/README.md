# AI 自動化開發控制器 Pro v5.5
# 建議使用py3.11.9
[![Python](https://img.shields.io/badge/Python-3.11.9-blue?logo=python)](https://www.python.org/)
[![Flask](https://img.shields.io/badge/Flask-3.0-green?logo=flask)](https://flask.palletsprojects.com/)
[![Gemini](https://img.shields.io/badge/Gemini-2.5%20Pro-purple?logo=google)](https://ai.google.dev/)
[![License](https://img.shields.io/badge/License-MIT-yellow)](LICENSE)

> **本地化AI開發工作流引擎** - 智能代碼生成 × 自動化測試 × 持續迭代優化

---

## 🎯 核心價值

這是一個革命性的本地AI開發助手，徹底改變傳統編程工作流：

- **📝 自然語言編程**：用人話描述需求，AI自動生成完整項目
- **🔄 智能迭代優化**：自動擷取運行畫面，AI分析問題並修復
- **🎨 視覺化驗證**：自動檢測UI問題（重疊、溢出、樣式錯誤）
- **💾 長期記憶管理**：對話歷史持久化，Token計數防止降智
- **🚀 一鍵部署運行**：自動安裝依賴、啟動VS Code、執行程式

---

## ✨ v5.5 重大更新

### 🔧 核心修復
- ✅ **Token統計持久化**：`usage_metadata`作為獨立字段，永久保存到對話歷史
- ✅ **項目路徑一致性**：修復新建/迭代模式下的目錄處理邏輯
- ✅ **對話記錄清理**：自動清理臨時對話文件，避免數據污染

### 🆕 新增功能
- 🎯 **Terminal輸出附加**：可選擇性將程式執行輸出發送給AI分析
- 🖼️ **自動截圖開關**：迭代模式下可啟用自動視窗擷取
- 📊 **實時Token監控**：前端顯示每次對話的Token消耗明細

---

## 🌟 功能特性矩陣

| 功能模塊 | 能力描述 | 技術實現 |
|---------|---------|---------|
| **多模態輸入** | 圖片/PDF/文本文件上傳與分析 | Gemini Vision API |
| **代碼生成** | 多文件項目結構化輸出（JSON Schema） | GPT-4級別的代碼能力 |
| **VS Code控制** | 自動打開編輯器並定位到關鍵文件 | pywinctl + pyautogui |
| **程式執行** | 跨平台終端管理與輸出捕獲 | subprocess + queue |
| **智能截圖** | 視窗標題多層匹配邏輯 | mss + 模糊搜索 |
| **瀏覽器開啟** | 獨立APP模式（無標籤欄） | Chrome/Edge --app參數 |
| **對話管理** | 完整歷史記錄與Token統計 | JSON持久化 + MD5索引 |
| **項目列表** | 最近訪問項目快速切換 | project_list.json |

---

## 🔧 技術架構

### 系統分層

```
┌─────────────────────────────────────┐
│   前端層 (HTML/CSS/JavaScript)      │
│   - 拖放文件上傳                     │
│   - 實時Token顯示                    │
│   - 項目面板管理                     │
└──────────────┬──────────────────────┘
               │ HTTP/JSON
┌──────────────▼──────────────────────┐
│   Flask路由層 (8個API端點)          │
│   /run-process | /capture-screenshots│
│   /load-project | /running-programs  │
└──────────────┬──────────────────────┘
               │ 函數調用
┌──────────────▼──────────────────────┐
│   核心引擎層 (6大管理器)            │
│   ProcessManager | GeminiAI         │
│   ConversationManager | VSCodeController│
│   ScreenCapture | ProgramManager    │
└──────────────┬──────────────────────┘
               │ 系統調用
┌──────────────▼──────────────────────┐
│   外部服務層                         │
│   Gemini API | VS Code | 瀏覽器     │
└─────────────────────────────────────┘
```

### 數據模型

```python
@dataclass
class ConversationMessage:
    role: str                      # "user" 或 "assistant"
    content: str                   # 對話內容
    timestamp: str                 # ISO格式時間戳
    files: Optional[List[Dict]]    # 附加文件元數據
    terminal_output: Optional[str] # 終端輸出
    usage_metadata: Optional[Dict] # ★ Token統計（v5.5新增）
```

---

## 📦 安裝指南

### 前置需求

| 軟件 | 版本 | 用途 |
|-----|------|------|
| Python | 3.11.9 | 推薦版本，確保最佳兼容性 |
| VS Code | 最新版 | 必須安裝並加入PATH |
| Chrome/Edge | 最新版 | 用於Web應用展示 |

### 步驟1：克隆倉庫

```bash
git clone https://github.com/your-repo/ai-controller-pro.git
cd ai-controller-pro
```

### 步驟2：創建虛擬環境

```bash
# Windows
python -m venv venv
.\venv\Scripts\activate

# macOS/Linux
python3 -m venv venv
source venv/bin/activate
```

### 步驟3：安裝依賴

```bash
pip install -r requirements.txt
```

**requirements.txt內容：**
```
Flask==3.0.0
pywebview==4.4.1
pywinctl==0.3
PyAutoGUI==0.9.54
pyperclip==1.8.2
mss==9.0.1
Pillow==10.1.0
google-generativeai==0.3.2
python-dotenv==1.0.0
google-auth==2.25.2
```

### 步驟4：配置API Key

1. 訪問 [Google AI Studio](https://aistudio.google.com/app/apikey)
2. 生成新的API Key
3. 啟動應用後在設定界面輸入

### 步驟5：驗證VS Code

```bash
# 確認code命令可用
code --version

# Windows: 若無效，手動添加到PATH
setx PATH "%PATH%;C:\Program Files\Microsoft VS Code\bin"
```

---

## 🚀 快速開始

### 1. 啟動應用

```bash
python app.py
```

應用將自動：
- 啟動Flask服務器（127.0.0.1:5001）
- 打開桌面視窗界面
- 初始化配置目錄結構

### 2. 創建第一個項目

#### 方式A：新建項目
1. 點擊側邊欄「✨ 新增專案」
2. 選擇存放代碼的資料夾
3. 輸入需求（例如：「創建一個待辦事項應用」）
4. 點擊「→」發送

#### 方式B：選擇現有項目
1. 點擊「📂 選擇現有資料夾」
2. 瀏覽到已有的項目目錄
3. 系統自動載入項目結構與對話歷史

### 3. 迭代優化流程

**場景：修復UI bug**

```
用戶操作流程：
1. 運行生成的Web應用（系統自動啟動）
2. 發現按鈕位置錯誤
3. 啟用「➕ → 📸 自動截圖」開關
4. 輸入：「按鈕超出了容器範圍，請修復」
5. 系統自動：
   - 擷取瀏覽器視窗
   - 發送截圖+Terminal輸出給AI
   - AI分析問題並修改CSS
   - 重新啟動應用
   - 再次截圖驗證
```

---

## 💡 使用案例

### 案例1：基於設計稿生成前端

**輸入：**
- 上傳：product_design.png（UI設計稿）
- 指令：「根據這個設計稿創建響應式網頁，使用Tailwind CSS」

**輸出：**
```
項目結構：
├── index.html          # 主頁面
├── styles.css          # 全局樣式
├── script.js           # 交互邏輯
└── assets/
    └── images/         # 圖片資源
```

**AI自動完成：**
1. 分析設計稿的佈局、配色、字體
2. 生成HTML結構
3. 編寫CSS樣式（完全匹配設計稿）
4. 添加JavaScript交互
5. 在瀏覽器中自動預覽

### 案例2：PDF文檔轉互動應用

**輸入：**
- 上傳：tutorial.pdf（技術教程）
- 指令：「將這個教程轉換為互動式學習平台」

**輸出：**
```python
# 後端 Flask應用
- 章節導航系統
- 代碼高亮顯示
- 實時練習檢查
- 進度保存功能
```

### 案例3：Bug自動修復（核心功能）

**場景：** Python程式執行錯誤

```
第1輪對話：
用戶：「創建一個數據可視化應用」
AI：生成完整Flask + Matplotlib項目

[程式自動執行，Terminal捕獲錯誤]
ModuleNotFoundError: No module named 'pandas'

第2輪對話（自動觸發）：
系統：[附加Terminal輸出 + 啟用「💻 Terminal輸出」開關]
用戶：「程式報錯了，請修復」
AI：檢測到缺少pandas依賴，自動更新requirements.txt

第3輪對話（驗證）：
系統：[程式成功運行，附加截圖]
AI：「問題已修復，應用正常運行」
```

---

## ⚙️ 進階配置

### Gemini模型選擇

| 模型 | 輸入上限 | 輸出上限 | 適用場景 |
|-----|---------|---------|---------|
| **Gemini 2.5 Pro** | 1,048,576 | 65,535 | 複雜項目（推薦） |
| Gemini 2.5 Flash | 1,048,576 | 65,536 | 快速迭代 |
| Gemini 1.5 Pro | 2,097,152 | 8,192 | 超大上下文 |

### 參數調優指南

```json
{
  "temperature": 0.7,        // 創造性 (0=保守, 2=激進)
  "top_p": 0.95,             // 核心採樣
  "top_k": 64,               // 候選詞彙數
  "max_output_tokens": 8192, // 輸出長度
  "thinking_budget": -1      // -1=動態思考
}
```

**場景建議：**
- **新項目創建**：Temperature 0.9（需要創意）
- **Bug修復**：Temperature 0.3（需要精確）
- **UI優化**：Temperature 0.7（平衡創意與準確）

### 安全設定

```python
safety_settings = {
    "HARM_CATEGORY_HARASSMENT": "BLOCK_MEDIUM_AND_ABOVE",
    "HARM_CATEGORY_HATE_SPEECH": "BLOCK_MEDIUM_AND_ABOVE",
    "HARM_CATEGORY_SEXUALLY_EXPLICIT": "BLOCK_MEDIUM_AND_ABOVE",
    "HARM_CATEGORY_DANGEROUS_CONTENT": "BLOCK_MEDIUM_AND_ABOVE"
}
```

---

## 📊 對話管理與Token優化

### Token計數機制

每次對話後自動記錄：

```json
{
  "usage_metadata": {
    "prompt_token_count": 1250,      // 輸入Token數
    "candidates_token_count": 3840,  // 輸出Token數
    "thoughts_token_count": 512,     // 思考鏈Token數
    "total_token_count": 5602        // 總計
  }
}
```

### 長期記憶策略

**當前實現：**
- 每個專案獨立對話歷史（MD5哈希索引）
- 完整保存所有輪次（無Token限制）
- 前端顯示最近50條Terminal輸出

**未來規劃（基於初始構想）：**

```python
# 短期記憶：最近5輪對話
short_term_memory = conversation.messages[-10:]

# 長期記憶：關鍵決策摘要
long_term_memory = {
    "project_goal": "待辦事項應用",
    "tech_stack": ["Flask", "SQLite", "Bootstrap"],
    "resolved_issues": [
        "修復資料庫連接錯誤",
        "優化前端響應速度"
    ]
}

# Token閾值檢測
if total_tokens > 50000:
    # 創建新對話並注入長期記憶
    new_conversation = create_with_memory(long_term_memory)
```

---

## 🖼️ 智能截圖原理

### 視窗匹配邏輯

```python
# 優先級排序
1. VS Code視窗 + 專案名稱精確匹配
2. 瀏覽器視窗 + web_title包含關鍵字
3. 視窗標題直接包含指定字符
4. 專案名稱變體模糊匹配
   - "my_project" → ["my project", "MyProject", "myproject"]
```

### 擷取時機控制

```javascript
// 前端JavaScript
function toggleAutoScreenshot() {
    autoScreenshot = !autoScreenshot;
    // 啟用後，每次迭代請求自動附加截圖
}

// 手動觸發
function captureScreenshotsNow() {
    // 立即擷取
}

function delayedCaptureScreenshots() {
    // 延遲5秒（等待程式完全載入）
}
```

---

## 🛠️ 故障排除

### 問題1：找不到VS Code

**症狀：** `FileNotFoundError: 'code' command not found`

**解決方案：**

```bash
# Windows
1. 安裝VS Code時勾選「添加到PATH」
2. 或手動添加：
   系統變數 → Path → 新增 → C:\Program Files\Microsoft VS Code\bin

# macOS
sudo ln -s "/Applications/Visual Studio Code.app/Contents/Resources/app/bin/code" /usr/local/bin/code

# Linux
sudo update-alternatives --install /usr/bin/code code /usr/share/code/bin/code 100
```

### 問題2：Gemini API 429錯誤

**症狀：** `Rate limit exceeded`

**解決方案：**
- 免費版限制：60請求/分鐘
- 升級到付費API獲得更高配額
- 或使用`time.sleep(2)`在請求間增加延遲

### 問題3：截圖擷取不到視窗

**檢查清單：**
1. ✅ 程式是否已完全啟動？（使用延遲截圖）
2. ✅ 視窗標題是否包含關鍵字？
3. ✅ 視窗是否被最小化？
4. ✅ 是否使用獨立瀏覽器模式？（非Chrome擴展）

### 問題4：Terminal輸出為空

**原因：**
- Windows平台subprocess.Popen需要特殊配置

**修復（已在v5.5實現）：**

```python
env = os.environ.copy()
env['PYTHONUNBUFFERED'] = '1'  # 禁用緩衝

process = subprocess.Popen(
    [sys.executable, '-u', filepath],  # -u 強制無緩衝
    stdout=subprocess.PIPE,
    stderr=subprocess.STDOUT,
    bufsize=1,                         # 行緩衝
    env=env
)
```

---

## 🔐 安全性說明

### 本地優先原則
- ✅ API Key僅存儲在本地`config.json`
- ✅ 對話歷史不上傳到任何雲端
- ✅ 截圖文件僅保存在本地磁盤

### 代碼審查建議
AI生成的代碼應進行人工審查：
- 檢查是否有硬編碼的敏感信息
- 驗證網路請求的目標地址
- 確認文件操作的路徑安全

### API使用限制
```python
# 建議實現（未來版本）
rate_limiter = {
    "requests_per_minute": 10,
    "max_tokens_per_request": 8192,
    "daily_quota": 1000000
}
```

---

## 📁 目錄結構

```
ai-controller-pro/
│
├── app.py                      # 主程式（5500+行）
├── requirements.txt            # Python依賴
├── README.md                   # 本文檔
│
├── templates/
│   └── index.html              # 前端界面（2500+行）
│
├── static/
│   └── styles.css              # 樣式表（1800+行）
│
└── ~/.ai_controller_v5/        # 用戶數據目錄（自動創建）
    ├── config.json             # 配置文件
    ├── project_list.json       # 項目列表
    │
    ├── conversations/          # 對話歷史
    │   ├── conv_abc123.json    # MD5(project_dir)
    │   └── conv_def456.json
    │
    ├── screenshots/            # 螢幕截圖
    │   ├── capture_Chrome_20250101.png
    │   └── capture_VSCode_20250102.png
    │
    ├── logs/                   # 執行日誌
    └── projects/               # 生成的項目（可選）
```

---

## 🤝 貢獻指南

歡迎提交Issue和Pull Request！

### 開發分支策略
- `main`：穩定發布版本
- `develop`：開發中功能
- `feature/*`：新功能分支
- `bugfix/*`：錯誤修復分支

### 提交規範

```bash
git commit -m "feat: 添加長短期記憶管理"
git commit -m "fix: 修復Token統計消失問題"
git commit -m "docs: 更新安裝指南"
```

### 本地測試

```bash
# 單元測試（待實現）
pytest tests/

# 代碼風格檢查
flake8 app.py
black app.py --check
```

---

## 📈 路線圖

### v6.0（計劃中）

**核心功能：長短期記憶系統**
- [ ] 自動摘要歷史對話
- [ ] Token閾值自動新開視窗
- [ ] 長期記憶JSON結構設計
- [ ] 對話壓縮算法

**增強功能**
- [ ] 支持更多文件格式（Word、Excel）
- [ ] 內建Prompt模板庫
- [ ] 多語言界面（英文、日文）

### v7.0（遠景）

**自動化測試**
- [ ] UI自動化測試生成
- [ ] 單元測試生成
- [ ] 性能基準測試

**協作功能**
- [ ] 團隊項目共享
- [ ] 對話歷史導出/導入
- [ ] 雲端備份（可選）

