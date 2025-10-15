"""Flask application factory and route definitions."""
from __future__ import annotations

import logging
import threading
import time
import traceback
from pathlib import Path
from typing import Any, Dict, Optional

from flask import Flask, jsonify, render_template, request, send_file
import webview

from .error_reporting import ErrorReporter
from .managers import ConfigManager, ConversationManager, ProjectManager
from .models import AIConfig, asdict
from .services import ProcessManager, ProgramManager, ScreenCapture
from .settings import (
    CONFIG_DIR,
    CONVERSATIONS_DIR,
    ERROR_REPORTS_DIR,
    HOST,
    LOG_DIR,
    PORT,
    PROJECTS_DIR,
    SCREENSHOT_DIR,
    ensure_directories,
)

logger = logging.getLogger(__name__)

_window: Optional[webview.Window] = None


def set_webview_window(window: Optional[webview.Window]) -> None:
    """Register the PyWebView window so routes can access it."""
    global _window
    _window = window


def create_app() -> Flask:
    """Build and configure the Flask application."""
    if not logging.getLogger().handlers:
        logging.basicConfig(
            level=logging.INFO,
            format='[%(asctime)s] %(levelname)s: %(message)s',
            datefmt='%Y-%m-%d %H:%M:%S',
        )

    ensure_directories()

    app = Flask(__name__)

    register_routes(app)
    return app


def register_routes(app: Flask) -> None:
    """Attach all Flask route handlers to *app*."""

    @app.route('/')
    def index() -> str:
        """Serve the main dashboard."""
        return render_template('index.html')

    @app.route('/api/config', methods=['GET', 'POST'])
    def handle_config():
        """Load or persist AI configuration settings."""
        if request.method == 'GET':
            try:
                config = ConfigManager.load()
                return jsonify(asdict(config))
            except Exception as exc:  # pragma: no cover - defensive logging
                logger.error("載入配置時發生錯誤: %s", exc)
                default_config = AIConfig()
                return jsonify(asdict(default_config))

        try:
            data = request.get_json()
            if not data:
                return jsonify({'success': False, 'error': '無效的請求數據'}), 400

            config = AIConfig(**data)
            success = ConfigManager.save(config)

            if success:
                return jsonify({'success': True, 'message': '配置已儲存'})
            return jsonify({'success': False, 'error': '儲存失敗,請檢查權限'}), 500
        except Exception as exc:  # pragma: no cover - defensive logging
            logger.error("保存配置時發生錯誤: %s", exc)
            return jsonify({'success': False, 'error': f'保存失敗: {exc}'}), 500

    @app.route('/select-folder', methods=['GET'])
    def select_folder():
        """Open a folder selection dialog through the PyWebView window."""
        if not _window:
            return jsonify({'success': False, 'error': 'Webview 視窗不存在'}), 500

        try:
            result = _window.create_file_dialog(webview.FOLDER_DIALOG)
            path = result[0] if result else None

            if path:
                logger.info("選擇了資料夾: %s", path)
                return jsonify({'success': True, 'path': path})
            return jsonify({'success': False, 'error': '未選擇資料夾'})
        except Exception as exc:  # pragma: no cover - depends on host OS
            logger.error("選擇資料夾失敗: %s", exc)
            return jsonify({'success': False, 'error': str(exc)}), 500

    @app.route('/load-project', methods=['POST'])
    def load_project():
        """Load project metadata, files, and conversation history."""
        try:
            data = request.get_json() or {}
            project_dir = data.get('project_dir')

            if not project_dir or not Path(project_dir).exists():
                return jsonify({'success': False, 'error': '專案目錄不存在'}), 400

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
                    'files': metadata_files,
                }
            elif not project_info.get('files'):
                project_info['files'] = ProjectManager.build_file_metadata(project_dir)

            if conversation.project_name != project_info.get('project_name'):
                conversation.project_name = project_info.get('project_name', conversation.project_name)
                ConversationManager.save_conversation(conversation)

            ProjectManager.add_to_project_list(
                project_dir,
                project_info.get('project_name', project_dir_path.name),
                project_info.get('description', ''),
                status='ready',
                update_last_accessed=False,
            )

            messages_data = []
            for msg in conversation.messages:
                messages_data.append(
                    {
                        'role': msg.role,
                        'content': msg.content,
                        'timestamp': msg.timestamp,
                        'files': msg.files,
                        'metadata': msg.metadata,
                        'terminal_output': msg.terminal_output,
                        'usage_metadata': msg.usage_metadata,
                    }
                )

            metadata_lookup = {str(item.get('filename')): item for item in project_info.get('files', []) or []}

            auto_attach_preview = []
            for file_data in project_files:
                name = file_data.get('name')
                if not name:
                    continue
                meta = metadata_lookup.get(name, {})
                preview_type = meta.get('filetype') or file_data.get('type', 'text/plain')
                auto_attach_preview.append({'name': name, 'type': preview_type})

            return jsonify(
                {
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
                        'accumulated_long_term_memory': conversation.accumulated_long_term_memory,
                    },
                }
            )
        except Exception as exc:  # pragma: no cover - heavy IO path
            logger.error("載入專案時發生錯誤: %s", exc)
            logger.error(traceback.format_exc())
            return jsonify({'success': False, 'error': str(exc)}), 500

    @app.route('/conversation/<path:project_dir>', methods=['GET'])
    def get_conversation(project_dir: str):
        """Return conversation history for a project."""
        try:
            conversation = ConversationManager.load_conversation(project_dir)

            messages_data = []
            for msg in conversation.messages:
                messages_data.append(
                    {
                        'role': msg.role,
                        'content': msg.content,
                        'timestamp': msg.timestamp,
                        'files': msg.files,
                        'metadata': msg.metadata,
                        'terminal_output': msg.terminal_output,
                        'usage_metadata': msg.usage_metadata,
                    }
                )

            return jsonify(
                {
                    'success': True,
                    'conversation': {
                        'project_name': conversation.project_name,
                        'messages': messages_data,
                        'created_at': conversation.created_at,
                        'updated_at': conversation.updated_at,
                        'memory_snapshot': conversation.memory_snapshot,
                        'evaluation_snapshot': conversation.evaluation_snapshot,
                        'accumulated_long_term_memory': conversation.accumulated_long_term_memory,
                    },
                }
            )
        except Exception as exc:  # pragma: no cover - IO heavy
            logger.error("獲取對話歷史失敗: %s", exc)
            return jsonify({'success': False, 'error': str(exc)}), 500

    @app.route('/api/projects', methods=['GET'])
    def get_projects():
        """List tracked projects."""
        try:
            projects = ProjectManager.get_project_list()
            projects.sort(key=lambda item: item.get('last_accessed', ''), reverse=True)
            return jsonify({'success': True, 'projects': projects})
        except Exception as exc:  # pragma: no cover - IO heavy
            logger.error("獲取專案列表失敗: %s", exc)
            return jsonify({'success': False, 'error': str(exc)}), 500

    @app.route('/api/projects/<path:project_path>', methods=['DELETE'])
    def delete_project(project_path: str):
        """Remove a project from the quick access list."""
        try:
            success = ProjectManager.remove_from_project_list(project_path)
            if success:
                return jsonify({'success': True, 'message': '專案已從列表移除', 'deleted_path': project_path})
            return jsonify({'success': False, 'error': '移除失敗'}), 500
        except Exception as exc:  # pragma: no cover - IO heavy
            logger.error("刪除專案失敗: %s", exc)
            return jsonify({'success': False, 'error': str(exc)}), 500

    @app.route('/run-process', methods=['POST'])
    def run_process():
        """Execute the automation pipeline for a given prompt."""
        try:
            data = request.get_json() or {}

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
                    'ai_response': '',
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
                memory_context=memory_context,
            )

            response_data: Dict[str, Any] = {
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
                'error_report_path': result.error_report_path,
            }

            if attach_diagnostics:
                response_data['diagnostics_report'] = result.diagnostics_report

            if result.project_data:
                response_data['project'] = {
                    'name': result.project_data.project_name,
                    'description': result.project_data.description,
                    'files_count': len(result.project_data.files),
                    'main_file': result.project_data.main_file,
                    'has_gui': any(f.opens_window for f in result.project_data.files),
                }
                response_data['auto_attach_preview'] = [
                    {'name': file.filename, 'type': file.filetype or 'text'}
                    for file in result.project_data.files
                ]

            return jsonify(response_data)
        except Exception as exc:  # pragma: no cover - pipeline failure
            logger.error("執行流程時發生錯誤: %s", exc)
            logger.error(traceback.format_exc())

            error_report_path = ErrorReporter.generate_report(
                error_type="API_ERROR",
                error_message=str(exc),
                stack_trace=traceback.format_exc(),
            )

            return jsonify(
                {
                    'success': False,
                    'error': str(exc),
                    'ai_response': '執行過程中發生未預期的錯誤',
                    'output': f'系統錯誤: {exc}\n\n錯誤報告已生成: {error_report_path}',
                    'error_report_path': str(error_report_path),
                }
            ), 500

    @app.route('/capture-screenshots', methods=['POST'])
    def capture_screenshots():
        """Capture screenshots for running programs if requested."""
        try:
            data = request.get_json() or {}
            capture_mode = data.get('mode', 'programs')
            window_titles = data.get('window_titles', [])
            project_name = data.get('project_name')
            project_json = data.get('project_json')

            screenshots = []

            if capture_mode == 'monitors':
                logger.info("跳過螢幕擷取模式")
            else:
                if window_titles or project_name or project_json:
                    time.sleep(2)
                    program_screenshots = ScreenCapture.capture_running_programs(
                        window_titles,
                        project_name,
                        project_json,
                    )
                    screenshots.extend(program_screenshots)
                else:
                    logger.warning("沒有指定視窗標題或專案名稱")

            logger.info("擷取完成,共 %s 張截圖", len(screenshots))

            return jsonify({'success': True, 'screenshots': screenshots, 'count': len(screenshots)})
        except Exception as exc:  # pragma: no cover - OS dependent
            logger.error("擷取螢幕失敗: %s", exc)
            return jsonify({'success': False, 'error': str(exc)}), 500

    @app.route('/screenshot/<filename>')
    def serve_screenshot(filename: str):
        """Serve stored screenshot files."""
        filepath = SCREENSHOT_DIR / filename
        if filepath.exists():
            return send_file(filepath, mimetype='image/png', as_attachment=False, download_name=filename)
        return "Screenshot not found", 404

    @app.route('/running-programs', methods=['GET'])
    def get_running_programs():
        """Return status of managed runtime processes."""
        try:
            status = ProgramManager.check_programs()
            return jsonify({'success': True, 'programs': status, 'count': len(status)})
        except Exception as exc:  # pragma: no cover - OS dependent
            logger.error("獲取程式狀態失敗: %s", exc)
            return jsonify({'success': False, 'error': str(exc)}), 500

    @app.route('/terminate-program/<int:pid>', methods=['POST'])
    def terminate_program(pid: int):
        """Terminate a managed process by PID."""
        try:
            success = ProgramManager.terminate_program(pid)
            if success:
                return jsonify({'success': True, 'message': f'程式 PID {pid} 已終止'})
            return jsonify({'success': False, 'error': f'找不到 PID {pid} 的程式'}), 404
        except Exception as exc:  # pragma: no cover - OS dependent
            logger.error("終止程式失敗: %s", exc)
            return jsonify({'success': False, 'error': str(exc)}), 500


def run_flask(app: Flask) -> None:
    """Run the Flask development server without reloader."""
    app.run(host=HOST, port=PORT, debug=False, use_reloader=False)


def launch_desktop(app: Flask) -> None:
    """Launch the Flask server and PyWebView UI."""
    logger.info("=== AI 自動化開發控制器 Pro v5.5 啟動 ===")
    logger.info("配置目錄: %s", CONFIG_DIR)
    logger.info("截圖目錄: %s", SCREENSHOT_DIR)
    logger.info("日誌目錄: %s", LOG_DIR)
    logger.info("專案目錄: %s", PROJECTS_DIR)
    logger.info("對話目錄: %s", CONVERSATIONS_DIR)
    logger.info("錯誤報告目錄: %s", ERROR_REPORTS_DIR)

    flask_thread = threading.Thread(target=run_flask, args=(app,), daemon=True)
    flask_thread.start()
    time.sleep(1)

    window = webview.create_window(
        'AI 自動化開發控制器 Pro v5.5',
        f'http://{HOST}:{PORT}',
        width=1400,
        height=1000,
        resizable=True,
        on_top=False,
    )
    set_webview_window(window)

    logger.info("正在啟動圖形界面...")
    webview.start()
