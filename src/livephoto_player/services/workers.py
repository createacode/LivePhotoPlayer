"""轻量后台任务：把阻塞操作（导出、更新检查）挪出 UI 线程。"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from PySide6.QtCore import QObject, QRunnable, QThreadPool, Signal

from livephoto_player.utils.logger import get_logger


class _TaskSignals(QObject):
    finished = Signal(int, object, str)


class _Task(QRunnable):
    def __init__(self, task_id: int, function: Callable[[], Any], signals: _TaskSignals) -> None:
        super().__init__()
        self._task_id = task_id
        self._function = function
        self._signals = signals

    def run(self) -> None:
        try:
            result = self._function()
        except Exception as exc:  # noqa: BLE001 - 任务边界统一兜底
            get_logger("task").error("后台任务失败：%s", exc)
            self._signals.finished.emit(self._task_id, None, str(exc))
            return
        self._signals.finished.emit(self._task_id, result, "")


class TaskRunner(QObject):
    """极简任务队列：提交函数，成功/失败都回到 UI 线程。"""

    succeeded = Signal(object)
    failed = Signal(str)

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._pool = QThreadPool(self)
        self._pool.setMaxThreadCount(2)
        self._signals = _TaskSignals(self)
        self._signals.finished.connect(self._on_finished)
        self._active: set[int] = set()
        self._callbacks: dict[
            int, tuple[Callable[[object], None] | None, Callable[[str], None] | None]
        ] = {}
        self._sequence = 0

    def submit(
        self,
        function: Callable[[], Any],
        *,
        on_success: Callable[[object], None] | None = None,
        on_error: Callable[[str], None] | None = None,
    ) -> None:
        """提交一个无参可调用对象，可选地为本次任务挂回调。"""
        self._sequence += 1
        task_id = self._sequence
        self._active.add(task_id)
        self._callbacks[task_id] = (on_success, on_error)
        self._pool.start(_Task(task_id, function, self._signals))

    def shutdown(self) -> None:
        """退出前收尾，避免线程残留。"""
        self._pool.clear()
        self._pool.waitForDone(3000)

    def _on_finished(self, task_id: int, result: object, error: str) -> None:
        self._active.discard(task_id)
        on_success, on_error = self._callbacks.pop(task_id, (None, None))
        if error:
            if on_error is not None:
                on_error(error)
            self.failed.emit(error)
            return
        if on_success is not None:
            on_success(result)
        self.succeeded.emit(result)
