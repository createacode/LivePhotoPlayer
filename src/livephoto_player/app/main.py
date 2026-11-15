"""应用入口：``main()`` 的唯一实现。

启动顺序刻意保持精简：日志与异常钩子 → QApplication → 配置 → 单实例 →
主窗口。VLC 之类的重型运行时已经不存在，首屏不会被任何解码器初始化阻塞。
"""

from __future__ import annotations

import contextlib
import ctypes
import sys
from pathlib import Path

from PySide6.QtCore import Qt, QThreadPool
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QApplication

from livephoto_player.app.single_instance import SingleInstance
from livephoto_player.core.version import COPYRIGHT_SUFFIX, __software_name__, __version__
from livephoto_player.ui import theme
from livephoto_player.ui.main_window import MainWindow
from livephoto_player.utils.config import ConfigStore
from livephoto_player.utils.logger import (
    configure,
    get_logger,
    install_exception_hooks,
    install_qt_message_handler,
    shutdown,
)
from livephoto_player.utils.paths import APP_ID, app_dir, resource_path


def _set_windows_app_id() -> None:
    """让任务栏使用本程序自己的图标分组，而不是 python.exe。"""
    if sys.platform != "win32":
        return
    try:
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(f"{APP_ID}.4")
    except (AttributeError, OSError):
        return


def _startup_path_from_argv(argv: list[str]) -> str | None:
    for argument in argv[1:]:
        if argument.startswith("-"):
            continue
        candidate = Path(argument)
        if candidate.exists():
            return str(candidate)
    return None


def _emit_cli_text(text: str) -> None:
    """输出命令行信息。

    ``--windowed`` 打包的 exe 没有控制台，``sys.stdout`` 为 ``None``，
    此时退回 Windows 消息框，保证 ``--version`` / ``--help`` 仍然可见。
    """
    if sys.stdout is not None:
        print(text)
        return
    if sys.platform == "win32":
        try:
            title = f"{__software_name__} v{__version__}"
            ctypes.windll.user32.MessageBoxW(None, text, title, 0x40)
        except (AttributeError, OSError):
            return


def _handle_cli(argv: list[str]) -> int | None:
    """处理 ``--version`` / ``--help``；返回 ``None`` 表示继续启动图形界面。"""
    for argument in argv[1:]:
        if argument in ("--version", "-V"):
            _emit_cli_text(f"{__software_name__} v{__version__} - {COPYRIGHT_SUFFIX}")
            return 0
        if argument in ("--help", "-h", "/?"):
            _emit_cli_text(
                f"{__software_name__} v{__version__}\n"
                "用法：LivePhotoPlayer.exe [文件或目录]\n"
                "  --version  显示版本信息\n"
                "  --help     显示本帮助\n"
                "不带参数启动时进入图形界面。"
            )
            return 0
    return None


def main() -> int:
    """启动应用，返回进程退出码。"""
    cli_result = _handle_cli(sys.argv)
    if cli_result is not None:
        return cli_result

    log_path = configure("INFO")
    install_exception_hooks()
    install_qt_message_handler()
    logger = get_logger("main")
    logger.info("%s v%s 启动，日志：%s", __software_name__, __version__, log_path)

    _set_windows_app_id()

    QApplication.setApplicationName(APP_ID)
    # 不要设置 applicationDisplayName：Qt 会把它追加到窗口标题后面造成重复
    QApplication.setOrganizationName("XAF")
    QApplication.setAttribute(Qt.ApplicationAttribute.AA_UseHighDpiPixmaps, True)

    app = QApplication(sys.argv)
    app.setApplicationVersion(__version__)
    app.setStyleSheet(theme.STYLE_SHEET)
    icon_path = resource_path("app.ico")
    if icon_path.exists():
        app.setWindowIcon(QIcon(str(icon_path)))
    else:
        logger.warning("未找到图标文件：%s", icon_path)

    store = ConfigStore()
    if store.fallback:
        logger.warning("配置目录回退：%s", store.fallback_reason)
    config = store.load()
    logger.info("运行目录：%s", app_dir())

    instance = SingleInstance(app)
    startup_path = _startup_path_from_argv(sys.argv)
    payload = startup_path or ""
    if not instance.try_acquire(payload):
        logger.info("已有实例在运行，已转发请求并退出")
        shutdown()
        return 0

    window = MainWindow(store, config, startup_path, start_timeline="--timeline" in sys.argv[1:])
    instance.message_received.connect(window.handle_external_request)
    window.show()

    if "--geo" in sys.argv[1:]:
        # 调试入口：直接把地点解析设置打开，便于截图核对
        from PySide6.QtCore import QTimer

        QTimer.singleShot(800, lambda: window._show_geo_dialog())
    window.startup()

    if store.fallback:
        window.show_path_warning(store.fallback_reason)

    def _drain_threads() -> None:
        """退出前把线程池里的任务等干净，避免资源在运行中被销毁。"""
        with contextlib.suppress(Exception):
            QThreadPool.globalInstance().waitForDone(3000)

    app.aboutToQuit.connect(_drain_threads)

    exit_code = app.exec()
    _drain_threads()
    instance.close()
    shutdown()
    return int(exit_code)


__all__ = ["main"]
