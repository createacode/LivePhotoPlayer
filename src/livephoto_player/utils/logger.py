"""日志系统：按规范命名、大小轮转、保留策略与全局异常落盘。"""

from __future__ import annotations

import faulthandler
import logging
import sys
import threading
import time
from datetime import datetime, timedelta
from pathlib import Path
from types import TracebackType
from typing import IO, Final

from livephoto_player.utils.paths import APP_ID, logs_dir

LOGGER_NAME: Final = "livephoto_player"
MAX_BYTES: Final = 10 * 1024 * 1024
RETENTION_DAYS: Final = 30
RETENTION_FILES: Final = 100

_configured: bool = False
_fault_file: IO[str] | None = None


class SizedRotatingFileHandler(logging.FileHandler):
    """按大小轮转，且轮转文件名保持 ``log_YYYYMMDD_HHMMSS_NN.log`` 规范。"""

    def __init__(self, directory: Path, stamp: str, max_bytes: int = MAX_BYTES) -> None:
        self._directory = directory
        self._stamp = stamp
        self._max_bytes = max_bytes
        self._sequence = _next_sequence(directory, stamp)
        super().__init__(self._build_path(), encoding="utf-8", delay=False)

    def _build_path(self) -> str:
        return str(self._directory / f"log_{self._stamp}_{self._sequence:02d}.log")

    def _rollover(self) -> None:
        if self.stream is not None:
            self.stream.close()
            self.stream = None
        self._sequence += 1
        self.baseFilename = self._build_path()
        self.stream = self._open()

    def emit(self, record: logging.LogRecord) -> None:
        try:
            if self._max_bytes > 0 and self.stream is not None:
                self.stream.seek(0, 2)
                if self.stream.tell() >= self._max_bytes:
                    self._rollover()
        except (OSError, ValueError):
            pass
        super().emit(record)


def _next_sequence(directory: Path, stamp: str) -> int:
    """同一秒内多次启动时取下一个序号，避免覆盖已有日志。"""
    used: set[int] = set()
    try:
        for item in directory.glob(f"log_{stamp}_*.log"):
            suffix = item.stem.rsplit("_", 1)[-1]
            if suffix.isdigit():
                used.add(int(suffix))
    except OSError:
        return 0
    seq = 0
    while seq in used:
        seq += 1
    return seq


def _prune(directory: Path) -> None:
    """保留最近 30 天或 100 个文件，按修改时间清理。"""
    try:
        files = sorted(
            (p for p in directory.glob("log_*.log") if p.is_file()),
            key=lambda p: p.stat().st_mtime,
            reverse=True,
        )
    except OSError:
        return
    deadline = time.time() - RETENTION_DAYS * 86400
    for index, path in enumerate(files):
        try:
            expired = path.stat().st_mtime < deadline
        except OSError:
            continue
        if index >= RETENTION_FILES or expired:
            try:
                path.unlink()
            except OSError:
                continue


def configure(level: str = "INFO") -> Path:
    """初始化日志，返回本次日志文件路径。重复调用不会重复挂载处理器。"""
    global _configured, _fault_file
    logger = logging.getLogger(LOGGER_NAME)
    if _configured:
        for handler in logger.handlers:
            if isinstance(handler, SizedRotatingFileHandler):
                return Path(handler.baseFilename)
        return logs_dir().path

    target = logs_dir()
    resolved_level = getattr(logging, level.upper(), logging.INFO)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    handler = SizedRotatingFileHandler(target.path, stamp)
    handler.setLevel(logging.DEBUG)
    handler.setFormatter(logging.Formatter("%(asctime)s - %(name)s - %(levelname)s - %(message)s"))
    logger.handlers.clear()
    logger.addHandler(handler)
    logger.setLevel(resolved_level)
    logger.propagate = False

    _prune(target.path)
    _configured = True

    logger.info(
        "启动 %s 日志文件=%s 回退=%s %s",
        APP_ID,
        handler.baseFilename,
        target.fallback,
        target.reason,
    )
    if target.fallback:
        logger.warning("日志目录发生回退：%s", target.reason)

    fault_path = target.path / f"crash_{stamp}.log"
    try:
        _fault_file = fault_path.open("a", encoding="utf-8")
        faulthandler.enable(file=_fault_file, all_threads=True)
    except OSError:
        _fault_file = None
        logger.warning("faulthandler 落盘不可用：%s", fault_path)
    return Path(handler.baseFilename)


def get_logger(name: str | None = None) -> logging.Logger:
    """取得日志器；未初始化时自动初始化。"""
    if not _configured:
        configure()
    if name:
        return logging.getLogger(f"{LOGGER_NAME}.{name}")
    return logging.getLogger(LOGGER_NAME)


def _format_exception(
    exc_type: type[BaseException],
    exc_value: BaseException,
    exc_tb: TracebackType | None,
) -> str:
    import traceback

    return "".join(traceback.format_exception(exc_type, exc_value, exc_tb))


def install_exception_hooks() -> None:
    """接管未捕获异常，先落盘再交给默认处理。"""
    logger = get_logger("crash")

    def _hook(
        exc_type: type[BaseException],
        exc_value: BaseException,
        exc_tb: TracebackType | None,
    ) -> None:
        logger.critical("未捕获异常\n%s", _format_exception(exc_type, exc_value, exc_tb))
        sys.__excepthook__(exc_type, exc_value, exc_tb)

    def _thread_hook(args: threading.ExceptHookArgs) -> None:
        if args.exc_value is None:  # pragma: no cover - 理论上不会发生
            return
        logger.critical(
            "线程 %s 未捕获异常\n%s",
            getattr(args.thread, "name", "?"),
            _format_exception(args.exc_type, args.exc_value, args.exc_traceback),
        )

    sys.excepthook = _hook
    threading.excepthook = _thread_hook


def install_qt_message_handler() -> None:
    """把 Qt / FFmpeg 的消息接进日志，避免控制台缺失时彻底静默。"""
    from PySide6.QtCore import QtMsgType, qInstallMessageHandler

    logger = get_logger("qt")
    level_map = {
        QtMsgType.QtDebugMsg: logging.DEBUG,
        QtMsgType.QtInfoMsg: logging.INFO,
        QtMsgType.QtWarningMsg: logging.WARNING,
        QtMsgType.QtCriticalMsg: logging.ERROR,
        QtMsgType.QtFatalMsg: logging.CRITICAL,
    }

    def _handler(mode: QtMsgType, context: object, message: str) -> None:
        logger.log(level_map.get(mode, logging.INFO), "%s", message)

    qInstallMessageHandler(_handler)


def shutdown() -> None:
    """退出前冲刷并关闭日志。"""
    global _fault_file
    logging.getLogger(LOGGER_NAME).info("退出")
    for handler in logging.getLogger(LOGGER_NAME).handlers:
        try:
            handler.flush()
            handler.close()
        except OSError:
            continue
    if _fault_file is not None:
        try:
            faulthandler.disable()
            _fault_file.close()
        except OSError:
            pass
        _fault_file = None


def purge_old_crash_files(days: int = RETENTION_DAYS) -> None:
    """清理过期的 crash 文件。"""
    directory = logs_dir().path
    deadline = datetime.now() - timedelta(days=days)
    try:
        for path in directory.glob("crash_*.log"):
            if datetime.fromtimestamp(path.stat().st_mtime) < deadline:
                path.unlink()
    except OSError:
        return
