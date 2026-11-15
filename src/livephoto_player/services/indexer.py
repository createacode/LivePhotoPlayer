"""后台索引线程：慢慢把照片的拍摄时间与地点写进结构化目录。

设计要点对应"不要抢占主资源、不打扰、可断续恢复"：

- 单独一条**低优先级**线程，每处理一个文件主动休眠若干毫秒，把 CPU/IO 让出去；
- 只做 ``stat`` 比对，大小与修改时间没变就跳过，增量更新；
- 每批 40 条提交一次事务，异常中断也不会丢掉已完成的部分；
- 扫描进度写入 ``scan_state``，下次从断点续扫；
- 扫描结束才清理"文件已删除"的记录，避免中途误删；
- 全程不弹窗、不抢焦点，只用信号回报进度。
"""

from __future__ import annotations

import threading
import time
from pathlib import Path

from PySide6.QtCore import QThread, Signal

from livephoto_player.core.models import PhotoRecord
from livephoto_player.services.browser import SUPPORTED_EXTENSIONS
from livephoto_player.services.catalog import Catalog
from livephoto_player.services.metadata import read_metadata
from livephoto_player.utils.logger import get_logger

FILE_DELAY_MS = 6
BATCH_COMMIT = 40
IDLE_SLEEP_MS = 150
CURSOR_SAVE_EVERY = 20


# 停止超时后把线程对象寄存起来：QThread 在运行中被析构会直接 abort，
# 进程反正要退出，宁可泄漏一个对象也不能崩。
_ORPHANS: list[QThread] = []


class IndexWorker(QThread):
    """低优先级、可中断、可续扫的目录索引线程。"""

    progress = Signal(str, int, int)
    directory_done = Signal(str, int)
    failed = Signal(str)

    def __init__(self, db_path: Path, parent: object | None = None) -> None:
        super().__init__(parent)  # type: ignore[arg-type]
        self._logger = get_logger("indexer")
        self._db_path = db_path
        self._lock = threading.Lock()
        self._pending: list[Path] = []
        self._done: set[str] = set()
        self._stop = threading.Event()

    # ------------------------------------------------------------------ 对外接口
    def enqueue(self, directory: Path) -> None:
        """把目录加入扫描队列（同一目录扫完前不会重复入队）。"""
        try:
            resolved = directory.resolve()
        except OSError:
            return
        if not resolved.is_dir():
            return
        key = str(resolved)
        with self._lock:
            if key in self._done or any(str(item) == key for item in self._pending):
                return
            self._pending.append(resolved)

    def stop(self, timeout_ms: int = 2500) -> None:
        """请求停止并等待收尾；超时则寄存引用，避免运行中被析构。"""
        self._stop.set()
        if not self.isRunning():
            return
        self.requestInterruption()
        if self.wait(timeout_ms):
            return
        get_logger("indexer").warning("索引线程未在 %dms 内退出，寄存引用后继续退出", timeout_ms)
        _ORPHANS.append(self)

    def queued(self) -> int:
        """队列里还剩几个目录。"""
        with self._lock:
            return len(self._pending)

    # ------------------------------------------------------------------ 线程主体
    def run(self) -> None:
        catalog: Catalog | None = None
        try:
            catalog = Catalog(self._db_path)
            while not self._stop.is_set():
                directory = self._pop()
                if directory is None:
                    self.msleep(IDLE_SLEEP_MS)
                    continue
                self._scan(catalog, directory)
                with self._lock:
                    self._done.add(str(directory))
        except Exception as exc:  # noqa: BLE001 - 线程边界必须兜底
            self._logger.error("索引线程异常退出：%s", exc)
            self.failed.emit(str(exc))
        finally:
            if catalog is not None:
                catalog.commit()
                catalog.close()

    def _pop(self) -> Path | None:
        with self._lock:
            if not self._pending:
                return None
            return self._pending.pop(0)

    def _scan(self, catalog: Catalog, directory: Path) -> None:
        directory_key = str(directory)
        try:
            files = sorted(
                (
                    directory / entry.name
                    for entry in directory.iterdir()
                    if entry.is_file() and entry.suffix.lower() in SUPPORTED_EXTENSIONS
                ),
                key=lambda item: item.name.lower(),
            )
        except OSError as exc:
            self._logger.warning("无法扫描 %s：%s", directory_key, exc)
            return

        total = len(files)
        if total == 0:
            self.directory_done.emit(directory_key, 0)
            return

        cursor = catalog.get_scan_cursor(directory_key)
        start = 0
        if cursor:
            for position, item in enumerate(files):
                if item.name == cursor:
                    start = position + 1
                    break

        changed = 0
        pending_commit = 0
        for position in range(start, total):
            if self._stop.is_set():
                return
            path = files[position]
            try:
                stat = path.stat()
            except OSError:
                continue
            if catalog.need_index(path, stat.st_size, int(stat.st_mtime)):
                record = self._build_record(path, stat.st_size, int(stat.st_mtime))
                catalog.upsert(record)
                changed += 1
                pending_commit += 1
                if pending_commit >= BATCH_COMMIT:
                    catalog.commit()
                    pending_commit = 0
            if position % CURSOR_SAVE_EVERY == 0:
                catalog.set_scan_cursor(directory_key, path.name)
            if position % 5 == 0:
                self.progress.emit(directory_key, position + 1, total)
            self.msleep(FILE_DELAY_MS)

        catalog.commit()
        # 整目录扫完才清理已删除的文件，避免中断时误删
        existing = {str(item) for item in files}
        removed = catalog.prune_directory(directory_key, existing)
        catalog.set_scan_cursor(directory_key, "")
        catalog.commit()
        self.progress.emit(directory_key, total, total)
        self.directory_done.emit(directory_key, changed)
        if changed or removed:
            self._logger.info(
                "索引完成 %s：新增/更新 %s 条，清理 %s 条", directory_key, changed, removed
            )

    def _build_record(self, path: Path, size_bytes: int, mtime: int) -> PhotoRecord:
        meta = read_metadata(path)
        return PhotoRecord(
            path=path,
            name=path.name,
            directory=str(path.parent),
            kind=meta.kind,
            size_bytes=size_bytes,
            mtime=mtime,
            taken_ts=meta.taken_ts,
            time_source=meta.time_source,
            latitude=meta.latitude,
            longitude=meta.longitude,
            camera=meta.camera,
            width=meta.width,
            height=meta.height,
        )


def now_seconds() -> int:
    """当前 Unix 秒（便于测试替换）。"""
    return int(time.time())
