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

import threading
import json
import logging
import time
import traceback
from datetime import datetime
from pathlib import Path
from dataclasses import asdict

# Web framework imports
from flask import Flask, render_template, jsonify, request, send_file
import webview

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

from controller_core import (
    CONFIG_DIR,
    CONFIG_FILE,
    SCREENSHOT_DIR,
    LOG_DIR,
    PROJECTS_DIR,
    CONVERSATIONS_DIR,
    PROJECT_LIST_FILE,
    ERROR_REPORTS_DIR,
    ensure_directories,
)
from controller_core.models import AIConfig
from controller_core.managers import ConfigManager, ConversationManager, ProjectManager
from controller_core.diagnostics import ErrorReporter, DiagnosticsManager
from controller_core.services import ProgramManager, ProcessManager, ScreenCapture

try:
    ensure_directories()
except Exception as e:
    logger.critical(f"初始化失敗: {e}")

# ============================================
# Flask 路由
# ============================================
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