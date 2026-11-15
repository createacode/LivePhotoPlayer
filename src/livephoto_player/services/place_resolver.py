"""地点解析线程：把有坐标但没有地名的照片补上"省 市 区县"。

- 离线模式：纯本地查表，几乎瞬间完成，不联网；
- 在线模式：按源的限速逐个请求，失败只记日志并跳过（同一路径本进程内不再重试），
  不阻塞界面、不弹窗。
"""

from __future__ import annotations

import threading
import time
from pathlib import Path

from PySide6.QtCore import QThread, Signal

from livephoto_player.services.catalog import Catalog
from livephoto_player.services.geocode import GeocodeError, provider_info, reverse_geocode
from livephoto_player.services.geodb import default_geo_db
from livephoto_player.utils.logger import get_logger

IDLE_SLEEP_MS = 400
BATCH = 120


# 同 indexer：超时未退出时寄存，避免 QThread 运行中被析构导致 abort
_ORPHANS: list[QThread] = []


class PlaceResolver(QThread):
    """后台补地名；模式可随时切换。"""

    progress = Signal(int)  # 本次已解析条数
    pending_changed = Signal(int)  # 剩余待解析条数
    failed = Signal(str)

    def __init__(self, db_path: Path, parent: object | None = None) -> None:
        super().__init__(parent)  # type: ignore[arg-type]
        self._logger = get_logger("places")
        self._db_path = db_path
        self._lock = threading.Lock()
        self._mode = "offline"
        self._provider = "tianditu"
        self._key = ""
        self._wake = threading.Event()
        self._stop = threading.Event()
        self._failed_paths: set[str] = set()
        self._quota_limited = False

    # ------------------------------------------------------------------ 对外接口
    def configure(self, mode: str, provider: str, key: str) -> None:
        """切换解析方式并唤醒线程。"""
        with self._lock:
            self._mode = mode
            self._provider = provider
            self._key = key
        self._failed_paths.clear()
        self.request()

    def request(self) -> None:
        """唤醒线程去处理待解析记录。"""
        self._wake.set()

    def stop(self, timeout_ms: int = 2500) -> None:
        """停止线程；超时则寄存引用，保证不会在运行中被销毁。"""
        self._stop.set()
        self._wake.set()
        if not self.isRunning():
            return
        if self.wait(timeout_ms):
            return
        get_logger("place").warning("地名线程未在 %dms 内退出，寄存引用后继续退出", timeout_ms)
        _ORPHANS.append(self)

    @property
    def mode(self) -> str:
        """当前模式。"""
        with self._lock:
            return self._mode

    # ------------------------------------------------------------------ 线程主体
    def run(self) -> None:
        catalog: Catalog | None = None
        try:
            catalog = Catalog(self._db_path)
            while not self._stop.is_set():
                mode = self.mode
                if mode == "off":
                    self._wake.wait(1.0)
                    self._wake.clear()
                    continue
                rows = catalog.pending_places(BATCH)
                if not rows:
                    self._wake.wait(1.0)
                    self._wake.clear()
                    continue
                self._wake.clear()
                done = 0
                for path, latitude, longitude in rows:
                    if self._stop.is_set():
                        return
                    if str(path) in self._failed_paths:
                        continue
                    place_text = self._resolve(latitude, longitude, mode)
                    if place_text is None:
                        if self._quota_limited:
                            # 配额/网络类错误：整批停下歇一会，下轮再试，不标记永久失败
                            catalog.commit()
                            self.pending_changed.emit(catalog.pending_place_count())
                            self.msleep(8000)
                            self._quota_limited = False
                            continue
                        self._failed_paths.add(str(path))
                        continue
                    catalog.set_place(path, place_text)
                    done += 1
                    if done % 20 == 0:
                        catalog.commit()
                        self.progress.emit(done)
                catalog.commit()
                if done:
                    self.progress.emit(done)
                self.pending_changed.emit(catalog.pending_place_count())
                if mode == "api":
                    self.msleep(50)
        except Exception as exc:  # noqa: BLE001 - 线程边界兜底
            self._logger.error("地名解析线程异常：%s", exc)
            self.failed.emit(str(exc))
        finally:
            if catalog is not None:
                catalog.commit()
                catalog.close()

    # ------------------------------------------------------------------ 内部实现
    def _resolve(self, latitude: float, longitude: float, mode: str) -> str | None:
        """返回地名文本；解析不出返回 ``None``。"""
        if mode == "offline":
            place = default_geo_db().lookup(latitude, longitude)
            return place.text if place else None
        with self._lock:
            provider = self._provider
            key = self._key
        info = provider_info(provider)
        if info.needs_key and not key:
            self.failed.emit("天地图需要先在设置里填入 key")
            self._stop.set()
            return None
        try:
            place = reverse_geocode(latitude, longitude, provider=provider, key=key)
        except GeocodeError as exc:
            message = str(exc)
            self._logger.warning("在线解析失败：%s", message)
            self.failed.emit(message)
            self._quota_limited = any(
                token in message for token in ("429", "超时", "网络", "HTTP 5", "HTTP 4")
            )
            time.sleep(info.min_interval)
            return None
        time.sleep(info.min_interval)
        return place.text or None
