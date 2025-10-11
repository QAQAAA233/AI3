// AI 自動化開發控制器 Pro v5.5 - JavaScript

// ============================================
// 全局變量
// ============================================
let currentProject = null;
let uploadedFiles = [];
let autoAttachedFiles = [];
let isIterationMode = false;
let currentProjectDir = null;
let autoScreenshot = false;
let attachTerminal = false;
let attachDiagnostics = false;
let allProjects = [];
let modelConfig = null;
let sidebarCollapsed = false;
let MODEL_LIMITS = {};
let projectMemoryState = {};
let autoAttachMemory = true;
let loadingRequestCounter = 0; // <-- 新增此行
const messageDiagnosticsHolderMap = new WeakMap();

// ============================================
// Loading Overlay 控制 - 修復版
// ============================================
function showLoading(message = '處理中...') {
    const overlay = document.getElementById('loadingOverlay');
    const messageEl = document.getElementById('loadingMessage');

    // 只有當第一次顯示時才更新文字，避免後來的快速任務覆蓋掉重要的提示
    if (loadingRequestCounter === 0) {
        if (messageEl) {
            messageEl.textContent = message;
        }
    }
    
    loadingRequestCounter++; // 增加計數
    
    if (overlay) {
        overlay.classList.add('active');
        overlay.style.zIndex = '99999';
    }
}

function hideLoading() {
    loadingRequestCounter--; // 減少計數

    if (loadingRequestCounter <= 0) {
        loadingRequestCounter = 0; // 重設以防萬一
        const overlay = document.getElementById('loadingOverlay');
        if (overlay) {
            overlay.classList.remove('active');
        }
    }
}

// ============================================
// 初始化
// ============================================
window.addEventListener('DOMContentLoaded', () => {
    loadConfig();
    loadSettings();
    loadProjectsList();
    checkRunningPrograms();
    setInterval(checkRunningPrograms, 5000);

    const memoryMenuItem = document.getElementById('memoryMenuItem');
    if (memoryMenuItem) {
        memoryMenuItem.classList.add('active');
    }
    updateMemoryMenuHint();
    renderMemoryPanel();
    
    // 點擊外部關閉選單
    document.addEventListener('click', (e) => {
        const plusMenu = document.getElementById('plusMenu');
        const attachBtn = document.getElementById('plusMenuBtn');
        
        if (plusMenu && attachBtn && !plusMenu.contains(e.target) && !attachBtn.contains(e.target)) {
            plusMenu.classList.remove('active');
        }
    });

    // 文件上傳處理
    const fileInput = document.getElementById('fileInput');
    if (fileInput) {
        fileInput.addEventListener('change', async (e) => {
            showLoading('正在處理檔案...');
            try {
                for (let file of e.target.files) {
                    await processFile(file);
                }
                updateFilesPreview();
                updateAttachedFilesDisplay();
                showNotification(`已上傳 ${e.target.files.length} 個檔案`, 'success');
                e.target.value = '';
            } finally {
                hideLoading();
            }
        });
    }
});

function getFolderNameFromPath(path) {
    if (!path) return '未命名專案';
    const segments = path.split(/[\\/]+/).filter(Boolean);
    if (segments.length === 0) return path;
    return segments[segments.length - 1];
}

function upsertProjectListEntry(entry) {
    if (!entry || !entry.path) return;

    const now = new Date().toISOString();
    entry.last_accessed = entry.last_accessed || now;

    const existingIndex = allProjects.findIndex(project => project.path === entry.path);
    if (existingIndex >= 0) {
        allProjects[existingIndex] = { ...allProjects[existingIndex], ...entry };
    } else {
        allProjects.unshift({
            created_at: now,
            description: '',
            status: 'ready',
            ...entry
        });
    }

    displayProjectsList(allProjects);
}

function registerPendingProject(userPrompt) {
    if (!currentProjectDir) return;

    const baseName = currentProject?.name || getFolderNameFromPath(currentProjectDir) || '新專案';
    const description = isIterationMode
        ? '延續既有專案'
        : '專案建立中，等待 AI 回應';

    const entry = {
        path: currentProjectDir,
        name: baseName,
        description,
        status: isIterationMode ? 'ready' : 'pending'
    };

    if (userPrompt && !isIterationMode) {
        entry.description = `建立中：${userPrompt.slice(0, 30)}${userPrompt.length > 30 ? '…' : ''}`;
    }

    upsertProjectListEntry(entry);
}

// ============================================
// 配置載入
// ============================================
async function loadConfig() {
    try {
        const response = await fetch('/api/config');
        const config = await response.json();
        
        MODEL_LIMITS = {
            'gemini-2.5-pro': { name: 'Gemini 2.5 Pro', inputLimit: 1048576, outputLimit: 65535 },
            'gemini-2.5-flash': { name: 'Gemini 2.5 Flash', inputLimit: 1048576, outputLimit: 65536 },
            'gemini-2.5-flash-lite': { name: 'Gemini 2.5 Flash-Lite', inputLimit: 1048576, outputLimit: 8192 },
            'gemini-1.5-pro': { name: 'Gemini 1.5 Pro', inputLimit: 2097152, outputLimit: 8192 },
            'gemini-1.5-flash': { name: 'Gemini 1.5 Flash', inputLimit: 1048576, outputLimit: 8192 }
        };
        modelConfig = config;
    } catch (error) {
        console.error('載入配置失敗:', error);
    }
}

// ============================================
// 檔案處理
// ============================================
async function processFile(file) {
    return new Promise((resolve) => {
        const reader = new FileReader();
        
        const isTextFile = file.type.startsWith('text/') || 
                           file.type === 'application/json' ||
                           file.type === 'application/xml' ||
                           file.name.match(/\.(py|js|html|css|md|txt|csv|json|xml)$/i);
        
        reader.onload = (e) => {
            uploadedFiles.push({
                name: file.name,
                type: file.type || 'text/plain',
                size: file.size,
                content: e.target.result,
                isText: isTextFile
            });
            resolve();
        };
        
        if (isTextFile) {
            reader.readAsText(file, 'utf-8');
        } else {
            reader.readAsDataURL(file);
        }
    });
}

function updateFilesPreview() {
    const previewArea = document.getElementById('filesPreviewArea');
    const previewList = document.getElementById('previewFilesList');
    
    if (!previewArea || !previewList) return;
    
    if (uploadedFiles.length === 0) {
        previewArea.classList.remove('active');
        return;
    }
    
    previewArea.classList.add('active');
    previewList.innerHTML = '';
    
    uploadedFiles.forEach((file, index) => {
        const chip = document.createElement('div');
        chip.className = 'preview-file-chip';
        chip.innerHTML = `
            <span class="preview-file-name" title="${file.name}">${file.name}</span>
            <button class="preview-remove-btn" onclick="removeFile(${index})">×</button>
        `;
        previewList.appendChild(chip);
    });
}

function removeFile(index) {
    uploadedFiles.splice(index, 1);
    updateFilesPreview();
    updateAttachedFilesDisplay();
    showNotification('已移除檔案', 'info');
}

function setAutoAttachedFiles(files) {
    autoAttachedFiles = (files || [])
        .map(file => ({
            name: file?.name || file?.filename,
            type: (file?.type || file?.filetype || 'file').toLowerCase()
        }))
        .filter(file => !!file.name);
    updateAttachedFilesDisplay();
}

function updateAttachedFilesDisplay() {
    const section = document.getElementById('attachedFilesSection');
    const countBadge = document.getElementById('attachedFilesCount');
    const manualList = document.getElementById('attachedFilesList');
    const manualContainer = document.getElementById('manualAttachedFilesContainer');
    const autoContainer = document.getElementById('autoAttachedFilesContainer');
    const autoList = document.getElementById('autoAttachedFilesList');

    if (!section || !countBadge || !manualList || !manualContainer || !autoContainer || !autoList) {
        return;
    }

    const totalCount = uploadedFiles.length + autoAttachedFiles.length;

    if (totalCount === 0) {
        section.style.display = 'none';
        manualList.innerHTML = '';
        autoList.innerHTML = '';
        manualContainer.style.display = 'none';
        autoContainer.style.display = 'none';
        updateProjectPanelVisibility();
        return;
    }

    section.style.display = 'block';
    countBadge.textContent = String(totalCount);

    if (autoAttachedFiles.length > 0) {
        autoContainer.style.display = 'block';
        autoList.innerHTML = '';

        autoAttachedFiles.forEach(file => {
            if (!file || !file.name) return;

            const fileItem = document.createElement('div');
            fileItem.className = 'project-file-item attached-auto';

            const badge = document.createElement('span');
            badge.className = `file-type-badge ${file.type || 'text'}`;
            badge.textContent = (file.type || 'FILE').toUpperCase();

            const info = document.createElement('div');
            info.style.flex = '1';
            info.style.minWidth = '0';

            const nameEl = document.createElement('div');
            nameEl.className = 'file-name-text';
            nameEl.textContent = file.name;
            info.appendChild(nameEl);

            fileItem.append(badge, info);
            autoList.appendChild(fileItem);
        });
    } else {
        autoContainer.style.display = 'none';
        autoList.innerHTML = '';
    }

    if (uploadedFiles.length > 0) {
        manualContainer.style.display = 'block';
        manualList.innerHTML = '';

        uploadedFiles.forEach((file, index) => {
            const fileItem = document.createElement('div');
            fileItem.className = 'attached-file-item';
            fileItem.innerHTML = `
                <span class="attached-file-name">${file.name}</span>
                <button class="remove-attached-btn" onclick="removeFile(${index})">×</button>
            `;
            manualList.appendChild(fileItem);
        });
    } else {
        manualContainer.style.display = 'none';
        manualList.innerHTML = '';
    }

    updateProjectPanelVisibility();
}

// ============================================
// UI 控制
// ============================================
function toggleSidebar() {
    const sidebar = document.getElementById('sidebar');
    const mainContent = document.getElementById('mainContent');
    
    sidebarCollapsed = !sidebarCollapsed;
    
    if (sidebarCollapsed) {
        sidebar.style.transform = 'translateX(-100%)';
        mainContent.style.marginLeft = '0';
    } else {
        sidebar.style.transform = 'translateX(0)';
        mainContent.style.marginLeft = '260px';
    }
}

function toggleProjectPanel() {
    const content = document.getElementById('projectPanelContent');
    const toggle = document.getElementById('projectPanelToggle');
    
    if (!content || !toggle) return;
    
    if (content.classList.contains('active')) {
        content.classList.remove('active');
        toggle.style.display = 'flex';
    } else {
        content.classList.add('active');
        toggle.style.display = 'none';
        updateProjectPanelVisibility();
    }
}

function updateProjectPanelVisibility() {
    const hasProject = document.getElementById('projectStructureSection')?.style.display !== 'none';
    const hasAttached = uploadedFiles.length > 0 || autoAttachedFiles.length > 0;
    const emptyState = document.getElementById('panelEmptyState');

    if (emptyState) {
        emptyState.style.display = (hasProject || hasAttached) ? 'none' : 'block';
    }
}

function togglePlusMenu() {
    const menu = document.getElementById('plusMenu');
    const btn = document.getElementById('plusMenuBtn');
    if (menu) menu.classList.toggle('active');
    if (btn) btn.classList.toggle('active');
}

function triggerFileInput() {
    document.getElementById('fileInput')?.click();
    togglePlusMenu();
}

function toggleAutoScreenshot() {
    autoScreenshot = !autoScreenshot;
    const menuItem = document.getElementById('screenshotMenuItem');
    if (menuItem) {
        if (autoScreenshot) {
            menuItem.classList.add('active');
            showNotification('已啟用自動截圖(迭代時)', 'success');
        } else {
            menuItem.classList.remove('active');
            showNotification('已關閉自動截圖', 'info');
        }
    }
    togglePlusMenu();
}

function toggleAttachTerminal() {
    attachTerminal = !attachTerminal;
    const menuItem = document.getElementById('terminalMenuItem');
    if (menuItem) {
        if (attachTerminal) {
            menuItem.classList.add('active');
            showNotification('已啟用附加 Terminal 輸出', 'success');
        } else {
            menuItem.classList.remove('active');
            showNotification('已關閉附加 Terminal 輸出', 'info');
        }
    }
    togglePlusMenu();
}

function toggleAttachDiagnostics() {
    attachDiagnostics = !attachDiagnostics;
    const menuItem = document.getElementById('diagnosticsMenuItem');
    if (menuItem) {
        if (attachDiagnostics) {
            menuItem.classList.add('active');
            showNotification('已啟用語法偵錯結果附加', 'success');
        } else {
            menuItem.classList.remove('active');
            showNotification('已關閉語法偵錯結果附加', 'info');
        }
    }
    togglePlusMenu();
}

function toggleAutoAttachMemory() {
    autoAttachMemory = !autoAttachMemory;
    const menuItem = document.getElementById('memoryMenuItem');
    if (menuItem) {
        if (autoAttachMemory) {
            menuItem.classList.add('active');
            showNotification('已啟用自動附加記憶上下文', 'success');
        } else {
            menuItem.classList.remove('active');
            showNotification('已關閉自動附加記憶上下文', 'info');
        }
    }
    togglePlusMenu();
}

function diagnosticsStatusIcon(status) {
    switch (status) {
        case 'passed':
            return '✅';
        case 'failed':
            return '❌';
        case 'warning':
            return '⚠️';
        case 'skipped':
            return 'ℹ️';
        default:
            return '•';
    }
}

function applyDiagnosticsToMessage(messageElement, report = []) {
    if (!messageElement) return;
    const holder = messageDiagnosticsHolderMap.get(messageElement);
    if (!holder) return;

    holder.innerHTML = '';

    const safeReport = Array.isArray(report) ? report : [];
    const details = document.createElement('details');
    details.className = 'diagnostics-details';
    if (safeReport.some(item => item && item.status === 'failed')) {
        details.open = true;
    }

    const summary = document.createElement('summary');
    const count = safeReport.length;
    summary.textContent = `語法偵錯結果（${count}）`;
    details.appendChild(summary);

    if (count === 0) {
        const empty = document.createElement('div');
        empty.className = 'diagnostics-empty';
        empty.textContent = '未找到可用的語法偵錯資訊，請確認專案檔案是否支援自動檢查。';
        details.appendChild(empty);
    } else {
        const list = document.createElement('ul');
        list.className = 'diagnostics-list';

        safeReport.forEach(item => {
            if (!item) return;
            const listItem = document.createElement('li');
            listItem.className = 'diagnostics-item';

            const status = item.status || 'info';
            listItem.dataset.status = status;

            const icon = document.createElement('span');
            icon.className = 'diagnostics-icon';
            icon.textContent = diagnosticsStatusIcon(status);

            const content = document.createElement('div');
            content.className = 'diagnostics-content';

            const header = document.createElement('div');
            header.className = 'diagnostics-header';
            const language = item.language || '未知語言';
            const fileName = item.file || '未知檔案';
            header.textContent = `[${language}] ${fileName}`;

            const message = document.createElement('div');
            message.className = 'diagnostics-message';
            message.textContent = item.message || '';

            content.append(header, message);
            listItem.append(icon, content);
            list.appendChild(listItem);
        });

        details.appendChild(list);
    }

    holder.appendChild(details);
    holder.style.display = 'block';
}

function getCurrentMemoryState() {
    if (!currentProjectDir) return null;
    return projectMemoryState[currentProjectDir] || null;
}

function setProjectMemoryState(projectDir, memorySnapshot = {}, evaluationSnapshot = {}) {
    if (!projectDir) return;
    projectMemoryState[projectDir] = {
        memory: memorySnapshot || {},
        evaluation: evaluationSnapshot || {}
    };

    if (projectDir === currentProjectDir) {
        updateMemoryMenuHint();
        renderMemoryPanel();
    }
}

function updateMemoryMenuHint() {
    const hint = document.getElementById('memorySuggestionPreview');
    if (!hint) return;

    if (!currentProjectDir) {
        hint.textContent = '上一輪改進建議：尚未選擇專案';
        hint.title = '';
        return;
    }

    const state = getCurrentMemoryState();
    const suggestion = state?.evaluation?.['改進建議'];

    if (suggestion !== undefined && suggestion !== null && suggestion !== '') {
        const trimmed = suggestion.length > 40 ? `${suggestion.slice(0, 40)}…` : suggestion;
        hint.textContent = `上一輪改進建議：${trimmed}`;
        hint.title = suggestion;
    } else {
        hint.textContent = '上一輪改進建議：尚未有資料';
        hint.title = '';
    }
}

function renderMemoryPanel() {
    const panel = document.getElementById('memoryPanel');
    const body = document.getElementById('memoryPanelBody');
    const scoreEl = document.getElementById('memoryScoreDisplay');
    const projectLabel = document.getElementById('memoryProjectLabel');
    const evaluationList = document.getElementById('memoryEvaluationList');
    const summaryBox = document.getElementById('memorySummaryBox');
    const stmList = document.getElementById('memorySTMList');
    const ltmList = document.getElementById('memoryLTMList');
    const goalsList = document.getElementById('memoryGoalsList');

    if (!panel || !body || !scoreEl || !projectLabel || !evaluationList || !summaryBox || !stmList || !ltmList || !goalsList) {
        return;
    }

    if (!currentProjectDir) {
        panel.style.display = 'none';
        body.style.maxHeight = 'none';
        return;
    }

    panel.style.display = 'flex';
    body.style.maxHeight = 'none';
    projectLabel.textContent = currentProject?.name || '未命名專案';

    const state = getCurrentMemoryState();
    const evaluation = state?.evaluation || {};
    const memory = state?.memory || {};

    const score = evaluation['評分'];
    scoreEl.textContent = (score !== undefined && score !== null && score !== '') ? `${score} 分` : '--';

    evaluationList.innerHTML = '';
    const evaluationItems = [
        { label: '內容評價', value: evaluation['內容評價'] },
        { label: '扣分原因', value: evaluation['扣分原因'] },
        { label: '改進建議', value: evaluation['改進建議'] }
    ];

    let hasEvaluationContent = false;
    evaluationItems.forEach(item => {
        const hasValue = item.value || item.value === '無';
        if (hasValue) {
            hasEvaluationContent = true;
            const row = document.createElement('div');
            row.className = 'memory-evaluation-item';
            const labelEl = document.createElement('span');
            labelEl.className = 'memory-eval-label';
            labelEl.textContent = item.label;
            const valueEl = document.createElement('span');
            valueEl.className = 'memory-eval-value';
            valueEl.textContent = item.value;
            row.append(labelEl, valueEl);
            evaluationList.appendChild(row);
        }
    });

    if (!hasEvaluationContent) {
        const placeholder = document.createElement('div');
        placeholder.className = 'memory-placeholder';
        placeholder.textContent = '尚未產生評分資訊';
        evaluationList.appendChild(placeholder);
    }

    summaryBox.textContent = memory['專案總結'] || '尚未建立專案總結';

    const renderList = (element, data, emptyText) => {
        if (!element) return;
        element.innerHTML = '';

        const normalized = Array.isArray(data)
            ? data.filter(item => item !== null && item !== undefined && `${item}`.trim() !== '')
            : (data ? [`${data}`] : []);

        if (normalized.length === 0) {
            const placeholder = document.createElement('li');
            placeholder.className = 'memory-placeholder';
            placeholder.textContent = emptyText;
            element.appendChild(placeholder);
            return;
        }

        normalized.forEach(text => {
            const item = document.createElement('li');
            item.className = 'memory-bullet-item';
            item.textContent = text;
            element.appendChild(item);
        });
    };

    renderList(stmList, memory['短期記憶'], '尚未累積短期記憶');
    renderList(ltmList, memory['長期記憶'], '尚未建立長期記憶');

    goalsList.innerHTML = '';
    const goals = Array.isArray(memory['專案目標']) ? memory['專案目標'] : [];
    if (goals.length === 0) {
        const placeholder = document.createElement('div');
        placeholder.className = 'memory-placeholder';
        placeholder.textContent = '尚未設定專案目標';
        goalsList.appendChild(placeholder);
    } else {
        const statusClassWhitelist = new Set(['已完成', '進行中', '未開始']);

        goals.forEach(goal => {
            const item = document.createElement('div');
            item.className = 'memory-goal-item';

            const stepEl = document.createElement('div');
            stepEl.className = 'goal-step';
            const stepLabel = goal && Object.prototype.hasOwnProperty.call(goal, '步驟')
                ? `步驟 ${goal['步驟']}`
                : '步驟 ?';
            const stepLabelEl = document.createElement('span');
            stepLabelEl.textContent = stepLabel;
            stepEl.appendChild(stepLabelEl);

            if (goal && goal['是否為當前任務']) {
                const badge = document.createElement('span');
                badge.className = 'goal-current';
                badge.textContent = '當前';
                stepEl.appendChild(badge);
            }

            const taskEl = document.createElement('div');
            taskEl.className = 'goal-task';
            taskEl.textContent = goal && goal['任務'] ? goal['任務'] : '未提供任務描述';

            const statusEl = document.createElement('div');
            statusEl.className = 'goal-status';
            const statusText = goal && goal['狀態'] ? goal['狀態'] : '未設定';
            statusEl.textContent = statusText;
            if (statusClassWhitelist.has(statusText)) {
                statusEl.classList.add(statusText);
            }

            item.append(stepEl, taskEl, statusEl);
            goalsList.appendChild(item);
        });
    }

    updateMemoryMenuHint();
}

function toggleMemoryPanel() {
    const panel = document.getElementById('memoryPanel');
    const btn = document.getElementById('memoryCollapseBtn');
    const layout = document.getElementById('conversationLayout');

    if (!panel || !btn) return;

    const isCollapsed = panel.classList.toggle('collapsed');
    btn.classList.toggle('collapsed', isCollapsed);
    btn.setAttribute('aria-expanded', (!isCollapsed).toString());

    if (layout) {
        layout.classList.toggle('memory-panel-collapsed', isCollapsed);
    }
}

function showAdvancedSettings() {
    togglePlusMenu();
    showSettingsModal();
}

function autoResize(textarea) {
    textarea.style.height = 'auto';
    textarea.style.height = Math.min(textarea.scrollHeight, 200) + 'px';
}

function updateSubmitButton() {
    const input = document.getElementById('mainInput');
    const btn = document.getElementById('submitBtn');
    
    if (input && btn) {
        if (input.value.trim()) {
            btn.classList.add('active');
        } else {
            btn.classList.remove('active');
        }
    }
}

function handleKeyDown(event) {
    if (event.key === 'Enter' && !event.shiftKey) {
        event.preventDefault();
        handleSubmit();
    }
}

function showResultsPlaceholder(message) {
    const container = document.getElementById('resultsContainer');
    if (!container) return;

    container.dataset.hasPlaceholder = 'true';
    container.innerHTML = '';

    const placeholder = document.createElement('div');
    placeholder.className = 'results-placeholder';
    placeholder.textContent = message;
    container.appendChild(placeholder);
}

function clearResultsPlaceholder() {
    const container = document.getElementById('resultsContainer');
    if (!container) return;

    if (container.dataset.hasPlaceholder === 'true') {
        container.innerHTML = '';
        delete container.dataset.hasPlaceholder;
    }
}

// ============================================
// 核心功能
// ============================================
async function handleSubmit() {
    const input = document.getElementById('mainInput');
    const userPrompt = input?.value.trim();

    if (!userPrompt) return;

    if (!currentProjectDir) {
        showNotification('請先選擇或創建專案', 'warning');
        createNewProject();
        return;
    }

    registerPendingProject(userPrompt);

    document.getElementById('emptyState').style.display = 'none';
    document.getElementById('resultsContainer').style.display = 'block';

    const attachmentsForMessage = uploadedFiles.map(file => ({
        name: file.name,
        type: file.type || 'text/plain'
    }));

    let requestPrompt = userPrompt;
    let memoryContextBlock = null;

    if (autoAttachMemory) {
        const state = getCurrentMemoryState();
        if (state) {
            const memoryLines = [];
            const memory = state.memory || {};
            const evaluation = state.evaluation || {};

            if (memory['專案總結']) {
                memoryLines.push(`專案總結：${memory['專案總結']}`);
            }
            const formatListBlock = (title, raw) => {
                if (!raw) return null;
                const items = Array.isArray(raw)
                    ? raw.filter(item => item !== null && item !== undefined && `${item}`.trim() !== '')
                    : [`${raw}`];

                if (items.length === 0) return null;
                const bullet = items.map(item => `- ${item}`).join('\n');
                return `${title}：\n${bullet}`;
            };

            const stmBlock = formatListBlock('短期記憶', memory['短期記憶']);
            if (stmBlock) {
                memoryLines.push(stmBlock);
            }

            const ltmBlock = formatListBlock('長期記憶', memory['長期記憶']);
            if (ltmBlock) {
                memoryLines.push(ltmBlock);
            }

            const goals = Array.isArray(memory['專案目標']) ? memory['專案目標'] : [];
            if (goals.length > 0) {
                const goalLines = goals.map(goal => {
                    const currentFlag = goal['是否為當前任務'] ? '【當前任務】' : '';
                    return `步驟${goal['步驟']} ${goal['任務']} (${goal['狀態'] || '未設定'})${currentFlag}`;
                });
                memoryLines.push(`專案目標：\n${goalLines.join('\n')}`);
            }

            const improvement = evaluation['改進建議'];
            if (improvement && improvement !== '無') {
                memoryLines.push(`上一輪改進建議：${improvement}`);
            }

            if (memoryLines.length > 0) {
                memoryContextBlock = `【長短期記憶摘要】\n${memoryLines.join('\n')}`;
                requestPrompt = `${memoryContextBlock}\n\n【使用者請求】\n${userPrompt}`;
            }
        }
    }

    const userMetadata = {};
    if (memoryContextBlock) {
        userMetadata.memoryContext = memoryContextBlock;
    }

    clearResultsPlaceholder();
    const userMessage = addMessage('user', userPrompt, null, null, attachmentsForMessage, userMetadata);

    input.value = '';
    updateSubmitButton();
    autoResize(input);

    showLoading('AI 正在處理您的請求...');

    try {
        const config = await getConfig();

        const response = await fetch('/run-process', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                folder_path: currentProjectDir,
                prompt: requestPrompt,
                display_prompt: userPrompt,
                memory_context: memoryContextBlock,
                config: config,
                files: uploadedFiles,
                is_iteration: isIterationMode,
                attach_screenshot: isIterationMode && autoScreenshot,
                attach_terminal: attachTerminal,
                attach_diagnostics: attachDiagnostics
            })
        });

        const result = await response.json();

        if (userMessage) {
            if (Array.isArray(result.diagnostics_report)) {
                applyDiagnosticsToMessage(userMessage, result.diagnostics_report);
            } else if (attachDiagnostics) {
                applyDiagnosticsToMessage(userMessage, []);
            }
        }

        if (result.success) {
            addMessage('assistant', result.output, result.usage_metadata, result.terminal_output, [], {
                evaluation: result.evaluation_snapshot,
                memory: result.memory_snapshot
            });

            if (currentProjectDir) {
                setProjectMemoryState(
                    currentProjectDir,
                    result.memory_snapshot || {},
                    result.evaluation_snapshot || {}
                );
            }

            if (result.project) {
                currentProject = result.project;
                if (result.ai_response_json) {
                    currentProject.json_data = result.ai_response_json;
                    displayProjectStructure(result.ai_response_json.files);
                }

                if (Array.isArray(result.auto_attach_preview)) {
                    setAutoAttachedFiles(result.auto_attach_preview);
                } else if (result.ai_response_json && Array.isArray(result.ai_response_json.files)) {
                    setAutoAttachedFiles(result.ai_response_json.files.map(file => ({
                        name: file.filename,
                        type: file.filetype
                    })));
                }

                document.getElementById('currentProjectName').textContent = currentProject.name;

                if (!isIterationMode) {
                    const previousDir = currentProjectDir;
                    const newProjectDir = currentProjectDir + '/' + currentProject.name;
                    currentProjectDir = newProjectDir;

                    isIterationMode = true;
                    const badge = document.getElementById('projectModeBadge');
                    if (badge) {
                        badge.textContent = '延續';
                        badge.style.background = '#0ea5e9';
                    }

                    allProjects = allProjects.filter(project => project.path !== previousDir);
                    displayProjectsList(allProjects);
                }
            }

            showNotification(result.is_iteration ? '專案迭代成功!' : '專案創建成功!', 'success');

            loadProjectsList();
            uploadedFiles = [];
            updateFilesPreview();
            updateAttachedFilesDisplay();
        } else {
            addMessage('assistant', `✕ 執行失敗：${result.error || result.output}`);
            showNotification(`執行失敗：${result.error}`, 'error');
        }
    } catch (error) {
        addMessage('assistant', `✕ 連接錯誤：${error}`);
        showNotification(`連接錯誤：${error}`, 'error');
    } finally {
        hideLoading();
    }
}

function addMessage(role, content, usageMetadata = null, terminalOutput = null, attachments = [], metadata = {}) {
    const container = document.getElementById('resultsContainer');
    if (!container) return null;

    clearResultsPlaceholder();

    const message = document.createElement('div');
    message.className = `result-message ${role} selectable`;

    const header = document.createElement('div');
    header.className = 'message-header';

    const avatar = document.createElement('div');
    avatar.className = `avatar ${role}`;
    avatar.textContent = role === 'user' ? 'U' : 'AI';

    const roleLabel = document.createElement('span');
    roleLabel.textContent = role === 'user' ? '您' : 'AI 助手';
    roleLabel.style.fontWeight = '500';

    header.appendChild(avatar);
    header.appendChild(roleLabel);

    const messageContent = document.createElement('div');
    messageContent.className = 'message-content selectable';
    messageContent.textContent = content;

    message.appendChild(header);
    message.appendChild(messageContent);

    if (attachments && attachments.length > 0) {
        const attachmentsSection = document.createElement('div');
        attachmentsSection.className = 'message-attachments';

        attachments.forEach(file => {
            if (!file || !file.name) return;
            const chip = document.createElement('div');
            chip.className = 'attachment-chip';

            const iconEl = document.createElement('span');
            iconEl.className = 'attachment-icon';
            iconEl.textContent = '📎';

            const nameSpan = document.createElement('span');
            nameSpan.className = 'attachment-name';
            nameSpan.textContent = file.name;
            nameSpan.title = file.name;

            const typeSpan = document.createElement('span');
            typeSpan.className = 'attachment-type';
            const typeLabelRaw = (file.type || '檔案').split('/')[0];
            const typeLabel = typeLabelRaw ? typeLabelRaw.toUpperCase() : '檔案';
            typeSpan.textContent = typeLabel;

            chip.append(iconEl, nameSpan, typeSpan);
            attachmentsSection.appendChild(chip);
        });

        message.appendChild(attachmentsSection);
    }

    if (metadata && metadata.memoryContext) {
        const contextDetails = document.createElement('details');
        contextDetails.className = 'memory-context-details';

        const summaryEl = document.createElement('summary');
        summaryEl.textContent = '已附加記憶上下文';

        const contextText = document.createElement('pre');
        contextText.className = 'memory-context-text selectable';
        contextText.textContent = metadata.memoryContext;

        contextDetails.append(summaryEl, contextText);
        message.appendChild(contextDetails);
    }

    const diagnosticsHolder = document.createElement('div');
    diagnosticsHolder.className = 'diagnostics-holder';
    diagnosticsHolder.style.display = 'none';
    message.appendChild(diagnosticsHolder);
    messageDiagnosticsHolderMap.set(message, diagnosticsHolder);

    if (metadata && metadata.evaluation) {
        const evalData = metadata.evaluation;
        const hasScore = Object.prototype.hasOwnProperty.call(evalData, '評分');
        const hasSuggestion = Object.prototype.hasOwnProperty.call(evalData, '改進建議');

        if (hasScore || hasSuggestion) {
            const scoreText = hasScore && evalData['評分'] !== null && evalData['評分'] !== undefined
                ? `${evalData['評分']} 分`
                : '未提供';
            const suggestionRaw = hasSuggestion ? evalData['改進建議'] : undefined;
            const suggestionText = suggestionRaw === undefined || suggestionRaw === '' ? '暫無' : suggestionRaw;

            const evaluationBox = document.createElement('div');
            evaluationBox.className = 'message-evaluation-box';

            const scoreRow = document.createElement('div');
            scoreRow.className = 'evaluation-row';
            const scoreLabel = document.createElement('span');
            scoreLabel.className = 'evaluation-label';
            scoreLabel.textContent = '評分';
            const scoreValueEl = document.createElement('span');
            scoreValueEl.className = 'evaluation-value';
            scoreValueEl.textContent = scoreText;
            scoreRow.append(scoreLabel, scoreValueEl);

            const suggestionRow = document.createElement('div');
            suggestionRow.className = 'evaluation-row suggestion-row'; // <-- 修改此行，多加一個 'suggestion-row'
            const suggestionLabel = document.createElement('span');
            suggestionLabel.className = 'evaluation-label';
            suggestionLabel.textContent = '改進建議';
            const suggestionValue = document.createElement('span');
            suggestionValue.className = 'evaluation-value';
            suggestionValue.textContent = suggestionText;
            suggestionRow.append(suggestionLabel, suggestionValue);

            evaluationBox.append(scoreRow, suggestionRow);
            message.appendChild(evaluationBox);
        }
    }

    if (metadata && metadata.memory) {
        setProjectMemoryState(currentProjectDir, metadata.memory, metadata.evaluation || {});
    }

    if (metadata && Array.isArray(metadata.diagnosticsReport)) {
        applyDiagnosticsToMessage(message, metadata.diagnosticsReport);
    }

    if (terminalOutput && terminalOutput.trim()) {
        const terminalSection = document.createElement('div');
        terminalSection.className = 'terminal-output-section';

        const terminalHeader = document.createElement('div');
        terminalHeader.className = 'terminal-header';
        const terminalTitle = document.createElement('span');
        terminalTitle.className = 'terminal-title';
        terminalTitle.textContent = 'Terminal 輸出';
        terminalHeader.appendChild(terminalTitle);

        const terminalBody = document.createElement('div');
        terminalBody.className = 'terminal-body selectable';
        terminalBody.textContent = terminalOutput;

        terminalSection.append(terminalHeader, terminalBody);
        message.appendChild(terminalSection);
    }

    if (role === 'assistant' && usageMetadata && typeof usageMetadata === 'object') {
        const tokenUsage = document.createElement('div');
        tokenUsage.className = 'token-usage';
        tokenUsage.innerHTML = `
            <div class="token-item">
                <span class="token-label">輸入</span>
                <span class="token-value">${usageMetadata.prompt_token_count || 0}</span>
            </div>
            <div class="token-item">
                <span class="token-label">輸出</span>
                <span class="token-value">${usageMetadata.candidates_token_count || 0}</span>
            </div>
            <div class="token-item">
                <span class="token-label">思考</span>
                <span class="token-value">${usageMetadata.thoughts_token_count || 0}</span>
            </div>
            <div class="token-item">
                <span class="token-label">總計</span>
                <span class="token-value">${usageMetadata.total_token_count || 0}</span>
            </div>
        `;
        message.appendChild(tokenUsage);
    }

    container.appendChild(message);
    message.scrollIntoView({ behavior: 'smooth' });

    return message;
}

function useSuggestion(text) {
    const input = document.getElementById('mainInput');
    if (input) {
        input.value = text;
        updateSubmitButton();
    }
    if (!currentProjectDir) {
        createNewProject();
    }
}

// ============================================
// 專案管理
// ============================================
async function createNewProject() {
    showLoading('正在開啟資料夾選擇器...');
    try {
        const response = await fetch('/select-folder');
        const result = await response.json();
        
        if (result.success && result.path) {
            currentProjectDir = result.path;
            isIterationMode = false;

            setProjectMemoryState(currentProjectDir, {}, {});

            document.getElementById('currentProjectDisplay').style.display = 'block';
            document.getElementById('currentProjectName').textContent = '新專案';
            const badge = document.getElementById('projectModeBadge');
            if (badge) {
                badge.textContent = '新建';
                badge.style.background = '#10a37f';
            }
            
            document.getElementById('homeBtn').style.display = 'flex';
            
            document.querySelectorAll('.project-item').forEach(item => {
                item.classList.remove('active');
            });
            
            uploadedFiles = [];
            updateFilesPreview();
            setAutoAttachedFiles([]);

            document.getElementById('projectStructureSection').style.display = 'none';
            document.getElementById('emptyState').style.display = 'none';
            document.getElementById('resultsContainer').style.display = 'block';
            showResultsPlaceholder('等待您的第一個指令…');

            showNotification('已選擇專案資料夾', 'success');
            document.getElementById('mainInput')?.focus();
        } else {
            showNotification(result.error || '未選擇資料夾', 'warning');
        }
    } catch (error) {
        showNotification(`錯誤: ${error}`, 'error');
    } finally {
        hideLoading();
    }
}

async function selectExistingFolder() {
    showLoading('正在開啟資料夾選擇器...');
    try {
        const response = await fetch('/select-folder');
        const result = await response.json();
        
        if (result.success && result.path) {
            currentProjectDir = result.path;
            isIterationMode = true;
            
            uploadedFiles = [];
            updateFilesPreview();
            setAutoAttachedFiles([]);

            const loadResult = await loadExistingProject(result.path);
            
            if (loadResult) {
                document.getElementById('currentProjectDisplay').style.display = 'block';
                document.getElementById('currentProjectName').textContent = currentProject.name;
                const badge = document.getElementById('projectModeBadge');
                if (badge) {
                    badge.textContent = '延續';
                    badge.style.background = '#0ea5e9';
                }
                
                document.getElementById('homeBtn').style.display = 'flex';
                
                document.querySelectorAll('.project-item').forEach(item => {
                    item.classList.remove('active');
                });
                
                document.getElementById('emptyState').style.display = 'none';
                document.getElementById('resultsContainer').style.display = 'block';
                
                showNotification(`已載入專案: ${currentProject.name}`, 'success');
            } else {
                showNotification('此資料夾不是有效的專案，將作為新專案', 'warning');
                isIterationMode = false;
                document.getElementById('currentProjectDisplay').style.display = 'block';
                document.getElementById('currentProjectName').textContent = '新專案';
                const badge = document.getElementById('projectModeBadge');
                if (badge) {
                    badge.textContent = '新建';
                    badge.style.background = '#10a37f';
                }
                
                document.getElementById('homeBtn').style.display = 'flex';
                document.getElementById('projectStructureSection').style.display = 'none';
            }
            
            document.getElementById('mainInput')?.focus();
        } else {
            showNotification(result.error || '未選擇資料夾', 'warning');
        }
    } catch (error) {
        showNotification(`錯誤: ${error}`, 'error');
    } finally {
        hideLoading();
    }
}

async function loadProjectsList() {
    try {
        const response = await fetch('/api/projects');
        const result = await response.json();
        
        if (result.success) {
            allProjects = result.projects;
            displayProjectsList(allProjects);
        }
    } catch (error) {
        console.error('載入專案列表失敗:', error);
    }
}

function displayProjectsList(projects) {
    const container = document.getElementById('projectsList');
    if (!container) return;
    
    container.innerHTML = '';
    
    if (projects.length === 0) {
        container.innerHTML = '<div style="padding: 12px; text-align: center; color: var(--text-tertiary); font-size: 13px;">尚無專案</div>';
        return;
    }
    
    projects.forEach(project => {
        const item = document.createElement('div');
        item.className = 'project-item';

        if (currentProjectDir === project.path) {
            item.classList.add('active');
        }

        const timeAgo = getTimeAgo(project.last_accessed);
        const statusBadge = project.status === 'pending'
            ? '<span class="project-status pending">建立中</span>'
            : (project.status && project.status !== 'ready'
                ? `<span class="project-status">${project.status}</span>`
                : '');

        item.innerHTML = `
            <div class="project-item-name">
                <span>${project.name}</span>
                ${statusBadge}
                <button class="delete-project-btn">×</button>
            </div>
            <div class="project-item-desc">${project.description || '無描述'}</div>
            <div class="project-item-time">${timeAgo}</div>
        `;

        const deleteBtn = item.querySelector('.delete-project-btn');
        if (deleteBtn) {
            deleteBtn.addEventListener('click', (evt) => {
                evt.stopPropagation();
                deleteProject(project.path);
            });
        }

        item.addEventListener('click', (evt) => selectProject(project, evt));
        container.appendChild(item);
    });
}

function getTimeAgo(dateString) {
    const date = new Date(dateString);
    const now = new Date();
    const seconds = Math.floor((now - date) / 1000);
    
    if (seconds < 60) return '剛剛';
    const minutes = Math.floor(seconds / 60);
    if (minutes < 60) return `${minutes} 分鐘前`;
    const hours = Math.floor(minutes / 60);
    if (hours < 24) return `${hours} 小時前`;
    const days = Math.floor(hours / 24);
    if (days < 7) return `${days} 天前`;
    return date.toLocaleDateString('zh-TW');
}

async function selectProject(project, evt) {
    currentProjectDir = project.path;
    isIterationMode = true;

    renderMemoryPanel();
    updateMemoryMenuHint();

    document.getElementById('currentProjectDisplay').style.display = 'block';
    document.getElementById('currentProjectName').textContent = project.name;
    const badge = document.getElementById('projectModeBadge');
    if (badge) {
        badge.textContent = '延續';
        badge.style.background = '#0ea5e9';
    }
    
    document.getElementById('homeBtn').style.display = 'flex';
    
    document.querySelectorAll('.project-item').forEach(item => {
        item.classList.remove('active');
    });
    evt?.currentTarget?.classList.add('active');
    
    document.getElementById('emptyState').style.display = 'none';
    document.getElementById('resultsContainer').style.display = 'block';
    document.getElementById('resultsContainer').innerHTML = '';
    
    uploadedFiles = [];
    updateFilesPreview();
    setAutoAttachedFiles([]);
    
    await loadExistingProject(project.path);

    showNotification(`已切換到專案: ${project.name}`, 'success');
}

async function loadExistingProject(projectDir) {
    showLoading('正在載入專案...');
    try {
        const response = await fetch('/load-project', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ project_dir: projectDir })
        });
        
        const result = await response.json();
        
        if (result.success) {
            currentProject = {
                name: result.project_info.project_name,
                description: result.project_info.description,
                files_count: result.files_count,
                main_file: result.project_info.main_file,
                json_data: {
                    project_name: result.project_info.project_name,
                    description: result.project_info.description,
                    files: result.project_info.files,
                    main_file: result.project_info.main_file
                }
            };

            document.getElementById('currentProjectName').textContent = currentProject.name;
            displayProjectStructure(result.project_info.files);
            setAutoAttachedFiles(result.auto_attach_preview || []);

            upsertProjectListEntry({
                path: projectDir,
                name: currentProject.name,
                description: currentProject.description || '無描述',
                status: 'ready'
            });

            if (result.conversation && result.conversation.messages) {
                const container = document.getElementById('resultsContainer');
                if (container) {
                    container.innerHTML = '';
                    
                    for (const msg of result.conversation.messages) {
                        const rawMetadata = msg.metadata || {};
                        const normalizedMetadata = {
                            ...rawMetadata
                        };

                        if (rawMetadata.evaluation_snapshot && !normalizedMetadata.evaluation) {
                            normalizedMetadata.evaluation = rawMetadata.evaluation_snapshot;
                        }
                        if (rawMetadata.memory_snapshot && !normalizedMetadata.memory) {
                            normalizedMetadata.memory = rawMetadata.memory_snapshot;
                        }
                        if (rawMetadata.memory_context && !normalizedMetadata.memoryContext) {
                            normalizedMetadata.memoryContext = rawMetadata.memory_context;
                        }
                        if (rawMetadata.diagnostics_report && !normalizedMetadata.diagnosticsReport) {
                            normalizedMetadata.diagnosticsReport = rawMetadata.diagnostics_report;
                        }

                        addMessage(
                            msg.role,
                            msg.content,
                            msg.usage_metadata,
                            msg.terminal_output,
                            msg.files || [],
                            normalizedMetadata
                        );
                    }
                }
            } else {
                const container = document.getElementById('resultsContainer');
                if (container) {
                    showResultsPlaceholder('尚未有對話紀錄');
                }
            }

            const container = document.getElementById('resultsContainer');
            if (container && container.dataset.hasPlaceholder !== 'true' && container.children.length === 0) {
                showResultsPlaceholder('尚未有對話紀錄');
            }

            if (result.conversation) {
                setProjectMemoryState(
                    projectDir,
                    result.conversation.memory_snapshot || {},
                    result.conversation.evaluation_snapshot || {}
                );
            } else {
                setProjectMemoryState(projectDir, {}, {});
            }

            return true;
        } else {
            return false;
        }
    } catch (error) {
        console.error('載入專案失敗:', error);
        return false;
    } finally {
        hideLoading();
    }
}

function displayProjectStructure(files) {
    const section = document.getElementById('projectStructureSection');
    const filesList = document.getElementById('projectFilesList');
    const countBadge = document.getElementById('projectFilesCount');
    
    if (!section || !filesList || !countBadge) return;
    
    if (!files || files.length === 0) {
        section.style.display = 'none';
        updateProjectPanelVisibility();
        return;
    }
    
    section.style.display = 'block';
    countBadge.textContent = files.length;
    filesList.innerHTML = '';
    
    files.forEach(file => {
        const fileItem = document.createElement('div');
        fileItem.className = 'project-file-item';
        
        const badge = document.createElement('span');
        badge.className = `file-type-badge ${file.filetype || 'text'}`;
        badge.textContent = (file.filetype || 'TEXT').toUpperCase();
        
        const fileInfo = document.createElement('div');
        fileInfo.style.flex = '1';
        fileInfo.style.minWidth = '0';
        
        const fileName = document.createElement('div');
        fileName.className = 'file-name-text';
        fileName.textContent = file.filename;
        
        fileInfo.appendChild(fileName);
        
        if (file.description) {
            const fileDesc = document.createElement('div');
            fileDesc.className = 'file-desc-text';
            fileDesc.textContent = file.description;
            fileInfo.appendChild(fileDesc);
        }
        
        fileItem.appendChild(badge);
        fileItem.appendChild(fileInfo);
        filesList.appendChild(fileItem);
    });
    
    updateProjectPanelVisibility();
}

async function deleteProject(projectPath) {
    if (!confirm('確定要從列表移除此專案嗎？(不會刪除實際檔案)')) {
        return;
    }
    
    showLoading('正在移除專案...');
    
    try {
        const response = await fetch(`/api/projects/${encodeURIComponent(projectPath)}`, {
            method: 'DELETE'
        });
        const result = await response.json();
        
        if (result.success) {
            showNotification('專案已從列表移除', 'success');
            allProjects = allProjects.filter(p => p.path !== projectPath);
            displayProjectsList(allProjects);
            
            if (currentProjectDir === projectPath) {
                resetToHome();
            }
        } else {
            showNotification('移除失敗', 'error');
        }
    } catch (error) {
        showNotification(`錯誤: ${error}`, 'error');
    } finally {
        hideLoading();
    }
}

function resetToHome() {
    if (!confirm('確定要回到初始介面嗎？當前專案選擇將被清除。')) {
        return;
    }
    
    currentProjectDir = null;
    currentProject = null;
    isIterationMode = false;
    uploadedFiles = [];
    autoAttachedFiles = [];

    document.getElementById('currentProjectDisplay').style.display = 'none';
    document.getElementById('emptyState').style.display = 'flex';
    document.getElementById('resultsContainer').style.display = 'none';
    document.getElementById('resultsContainer').innerHTML = '';
    document.getElementById('projectStructureSection').style.display = 'none';
    document.getElementById('homeBtn').style.display = 'none';

    document.querySelectorAll('.project-item').forEach(item => {
        item.classList.remove('active');
    });

    updateFilesPreview();
    setAutoAttachedFiles([]);
    renderMemoryPanel();
    updateMemoryMenuHint();

    showNotification('已回到初始介面', 'info');
}

// ============================================
// 設定管理
// ============================================
async function loadSettings() {
    try {
        const response = await fetch('/api/config');
        const config = await response.json();
        
        document.getElementById('apiKey').value = config.gemini_api_key || '';
        document.getElementById('modelName').value = config.model_name || 'gemini-2.5-pro';

        const promptModeSelect = document.getElementById('promptMode');
        if (promptModeSelect) {
            promptModeSelect.value = config.prompt_mode || 'default';
        }

        const genParams = config.generation_params || {};
        document.getElementById('temperature').value = genParams.temperature || 0.7;
        document.getElementById('topP').value = genParams.top_p || 0.95;
        document.getElementById('topK').value = genParams.top_k || 64;
        document.getElementById('maxOutputTokens').value = genParams.max_output_tokens || 8192;
        
        const thinkingConfig = config.thinking_config || {};
        document.getElementById('thinkingBudget').value = thinkingConfig.thinking_budget || -1;
        
        const safetySettings = config.safety_settings || {};
        document.getElementById('safetyHarassment').value = safetySettings.HARM_CATEGORY_HARASSMENT || 'BLOCK_MEDIUM_AND_ABOVE';
        document.getElementById('safetyHateSpeech').value = safetySettings.HARM_CATEGORY_HATE_SPEECH || 'BLOCK_MEDIUM_AND_ABOVE';
        document.getElementById('safetySexuallyExplicit').value = safetySettings.HARM_CATEGORY_SEXUALLY_EXPLICIT || 'BLOCK_MEDIUM_AND_ABOVE';
        document.getElementById('safetyDangerousContent').value = safetySettings.HARM_CATEGORY_DANGEROUS_CONTENT || 'BLOCK_MEDIUM_AND_ABOVE';
        
        updateSliderValue('thinkingBudget');
        updateSliderValue('temperature');
        updateSliderValue('topP');
        updateSliderValue('topK');
        updateSliderValue('maxOutputTokens');
        
        updateModelLimits();
    } catch (error) {
        console.error('Failed to load settings:', error);
        showNotification('載入設定失敗，使用預設值', 'warning');
    }
}

async function saveSettings() {
    showLoading('正在儲存設定...');
    
    try {
        const config = {
            connection_method: 'api_key',
            gemini_api_key: document.getElementById('apiKey').value,
            model_name: document.getElementById('modelName').value,
            prompt_mode: (document.getElementById('promptMode')?.value || 'default'),
            generation_params: {
                temperature: parseFloat(document.getElementById('temperature').value),
                top_p: parseFloat(document.getElementById('topP').value),
                top_k: parseInt(document.getElementById('topK').value),
                max_output_tokens: parseInt(document.getElementById('maxOutputTokens').value),
                candidate_count: 1,
                stop_sequences: [],
                response_mime_type: 'application/json'
            },
            thinking_config: {
                thinking_budget: parseInt(document.getElementById('thinkingBudget').value)
            },
            safety_settings: {
                "HARM_CATEGORY_HARASSMENT": document.getElementById('safetyHarassment').value,
                "HARM_CATEGORY_HATE_SPEECH": document.getElementById('safetyHateSpeech').value,
                "HARM_CATEGORY_SEXUALLY_EXPLICIT": document.getElementById('safetySexuallyExplicit').value,
                "HARM_CATEGORY_DANGEROUS_CONTENT": document.getElementById('safetyDangerousContent').value
            },
            automation_settings: {
                auto_error_fix: false,
                auto_optimize: false,
                auto_test: false,
                monitor_interval: 5
            }
        };

        const response = await fetch('/api/config', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(config)
        });

        if (response.ok) {
            showNotification('設定已儲存', 'success');
            closeModal('settingsModal');
            
            const limits = MODEL_LIMITS[config.model_name];
            if (limits) {
                document.getElementById('currentModel').textContent = limits.name;
            }
        } else {
            showNotification('儲存失敗', 'error');
        }
    } catch (error) {
        showNotification(`錯誤: ${error}`, 'error');
    } finally {
        hideLoading();
    }
}

function togglePasswordVisibility(inputId) {
    const input = document.getElementById(inputId);
    const icon = document.getElementById(inputId + 'ToggleIcon');
    
    if (!input) return;
    
    if (input.type === 'password') {
        input.type = 'text';
    } else {
        input.type = 'password';
    }
}

function switchTab(tabId) {
    document.querySelectorAll('.tab').forEach(tab => tab.classList.remove('active'));
    event.target.classList.add('active');
    
    document.querySelectorAll('.tab-content').forEach(content => content.classList.remove('active'));
    document.getElementById(tabId)?.classList.add('active');
}

function updateSliderValue(sliderId) {
    const slider = document.getElementById(sliderId);
    const valueSpan = document.getElementById(sliderId + 'Value');
    
    if (!slider || !valueSpan) return;
    
    let displayValue = slider.value;
    
    if (sliderId === 'thinkingBudget') {
        if (slider.value == -1) {
            displayValue = '動態 (-1)';
        } else if (slider.value == 0) {
            displayValue = '關閉 (0)';
        } else {
            displayValue = slider.value;
        }
    }
    
    valueSpan.textContent = displayValue;
}

function updateModelLimits() {
    const modelName = document.getElementById('modelName')?.value;
    const limits = MODEL_LIMITS[modelName];
    
    if (limits) {
        document.getElementById('modelInfoTitle').textContent = limits.name;
        document.getElementById('modelInfoText').textContent = 
            `輸入上限: ${limits.inputLimit.toLocaleString()} tokens | 輸出上限: ${limits.outputLimit.toLocaleString()} tokens`;
        
        const maxOutputSlider = document.getElementById('maxOutputTokens');
        if (maxOutputSlider) {
            maxOutputSlider.max = limits.outputLimit;
            if (parseInt(maxOutputSlider.value) > limits.outputLimit) {
                maxOutputSlider.value = limits.outputLimit;
                updateSliderValue('maxOutputTokens');
            }
        }
    }
}

async function getConfig() {
    const response = await fetch('/api/config');
    return await response.json();
}

// ============================================
// 截圖和監控
// ============================================
async function captureScreenshotsNow() {
    if (!currentProject) {
        showNotification('請先選擇專案', 'warning');
        return;
    }
    
    showLoading('正在擷取畫面...');

    let windowTitles = [];
    let projectName = currentProject.name;

    if (currentProject.json_data && currentProject.json_data.files) {
        for (const file of currentProject.json_data.files) {
            if (file.web_title) windowTitles.push(file.web_title);
            if (file.window_title) windowTitles.push(file.window_title);
        }
        windowTitles = [...new Set(windowTitles)];
    }

    try {
        const response = await fetch('/capture-screenshots', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                mode: 'programs',
                window_titles: windowTitles,
                project_name: projectName,
                project_json: currentProject?.json_data
            })
        });

        const result = await response.json();

        if (result.success) {
            displayScreenshots(result.screenshots);
            if (result.count > 0) {
                showNotification(`成功擷取 ${result.count} 張截圖`, 'success');
                showMonitorModal();
            } else {
                showNotification('未找到指定視窗，請確認程式已啟動', 'warning');
            }
        }
    } catch (error) {
        showNotification(`錯誤: ${error}`, 'error');
    } finally {
        hideLoading();
    }
}

async function delayedCaptureScreenshots() {
    let countdown = 5;
    const updateCountdown = () => {
        showLoading(`將在 ${countdown} 秒後擷取...`);
        countdown--;

        if (countdown >= 0) {
            setTimeout(updateCountdown, 1000);
        } else {
            captureScreenshotsNow();
        }
    };

    updateCountdown();
}

function displayScreenshots(screenshots) {
    const container = document.getElementById('screenshotPreview');
    if (!container) return;
    
    container.innerHTML = '';

    screenshots.forEach(screenshot => {
        const item = document.createElement('div');
        item.className = 'screenshot-item';
        
        const img = document.createElement('img');
        img.src = `/screenshot/${screenshot.filename}`;
        img.alt = screenshot.name;

        item.appendChild(img);
        container.appendChild(item);
    });
}

async function checkRunningPrograms() {
    try {
        const response = await fetch('/running-programs');
        const result = await response.json();

        const container = document.getElementById('runningPrograms');
        if (!container) return;

        if (result.success && result.programs.length > 0) {
            let html = '';
            result.programs.forEach(prog => {
                const statusIcon = prog.status === 'running' ? '●' : '○';
                const statusText = prog.status === 'running' 
                    ? `運行中 (${prog.run_time}秒)` 
                    : `已結束`;

                html += `
                    <div class="program-card">
                        <div class="program-header">
                            <div class="program-info">
                                <div class="program-status">
                                    ${statusIcon} <strong>PID ${prog.pid}:</strong> ${prog.filename}
                                </div>
                                <div class="program-details">${statusText}</div>
                            </div>
                            ${prog.status === 'running' ? `
                                <button onclick="terminateProgram(${prog.pid})" style="padding: 6px 12px; background: #ef4146; color: white; border: none; border-radius: 6px; cursor: pointer;">
                                    停止
                                </button>
                            ` : ''}
                        </div>
                        ${prog.terminal_output ? `
                            <div class="terminal-output-section" style="margin-top: 8px;">
                                <div class="terminal-header">
                                    <span class="terminal-title">輸出</span>
                                </div>
                                <div class="terminal-body selectable" style="max-height: 150px;">${prog.terminal_output}</div>
                            </div>
                        ` : ''}
                    </div>
                `;
            });
            container.innerHTML = html;
        } else {
            container.innerHTML = '<div class="empty-programs">暫無運行中的程式</div>';
        }
    } catch (error) {
        console.error('Failed to check programs:', error);
    }
}

async function terminateProgram(pid) {
    if (!confirm(`確定要終止 PID ${pid} 的程式嗎？`)) return;

    try {
        const response = await fetch(`/terminate-program/${pid}`, {
            method: 'POST'
        });
        const result = await response.json();

        if (result.success) {
            showNotification('程式已終止', 'success');
            checkRunningPrograms();
        } else {
            showNotification(result.error, 'error');
        }
    } catch (error) {
        showNotification(`錯誤: ${error}`, 'error');
    }
}

// ============================================
// 模態框控制
// ============================================
function showSettingsModal() {
    const modal = document.getElementById('settingsModal');
    if (modal) modal.classList.add('active');
}

function showMonitorModal() {
    const modal = document.getElementById('monitorModal');
    if (modal) modal.classList.add('active');
    checkRunningPrograms();
}

function closeModal(modalId) {
    const modal = document.getElementById(modalId);
    if (modal) modal.classList.remove('active');
}

// ============================================
// 通知系統
// ============================================
function showNotification(message, type = 'info') {
    const container = document.getElementById('toastContainer');
    if (!container) return;
    
    const toast = document.createElement('div');
    toast.className = `toast ${type}`;

    const icons = {
        'success': '✓',
        'warning': '⚠',
        'error': '✕',
        'info': 'ℹ'
    };

    toast.innerHTML = `
        <span style="font-size: 18px; font-weight: bold;">${icons[type]}</span>
        <span>${message}</span>
    `;

    container.appendChild(toast);

    setTimeout(() => {
        toast.style.animation = 'slideIn 0.3s ease reverse';
        setTimeout(() => toast.remove(), 300);
    }, 5000);
}