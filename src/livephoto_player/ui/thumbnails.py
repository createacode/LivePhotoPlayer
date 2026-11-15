"""缩略图缓存：图片走解码、视频抓首帧；异步 + LRU，绝不阻塞滚动。"""

from __future__ import annotations

from collections import OrderedDict, deque
from pathlib import Path

from PySide6.QtCore import QObject, QRunnable, QThreadPool, Signal
from PySide6.QtGui import QImage

from livephoto_player.core.models import MediaKind
from livephoto_player.services.image_loader import decode_image
from livephoto_player.services.poster import PosterGrabber
from livephoto_player.utils.logger import get_logger

_THUMB_WIDTH = 480
_CACHE_LIMIT = 160
_MAX_PENDING = 10


class _TaskSignals(QObject):
    finished = Signal(str, object)


class _ThumbTask(QRunnable):
    def __init__(self, path: Path, signals: _TaskSignals) -> None:
        super().__init__()
        self._path = path
        self._signals = signals

    def run(self) -> None:
        try:
            image, _ = decode_image(self._path, _THUMB_WIDTH)
        except Exception as exc:  # noqa: BLE001 - 缩略图失败不能影响界面
            get_logger("thumb").debug("缩略图失败 %s：%s", self._path.name, exc)
            image = QImage()
        self._signals.finished.emit(str(self._path), image)


class ThumbnailCache(QObject):
    """图片与视频共用的缩略图来源。"""

    updated = Signal()

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._cache: OrderedDict[str, QImage] = OrderedDict()
        self._pending: set[str] = set()
        self._pool = QThreadPool(self)
        self._pool.setMaxThreadCount(2)
        self._signals = _TaskSignals(self)
        self._signals.finished.connect(self._on_finished)

        # 视频只能靠播放器抓帧，PosterGrabber 一次只处理一个，这里排队
        self._grabber = PosterGrabber(self)
        self._grabber.poster_ready.connect(self._on_poster)
        self._video_queue: deque[Path] = deque()
        self._grab_busy = False

    def get(self, path: Path, kind: MediaKind = MediaKind.PHOTO) -> QImage | None:
        """取缩略图；没有则发起异步加载并返回 ``None``。"""
        key = str(path)
        image = self._cache.get(key)
        if image is not None:
            self._cache.move_to_end(key)
            return image
        if kind is MediaKind.VIDEO:
            if not self._grab_busy and path not in self._video_queue:
                self._video_queue.append(path)
                self._pump_video()
            return None
        if key not in self._pending and len(self._pending) < _MAX_PENDING:
            self._pending.add(key)
            self._pool.start(_ThumbTask(path, self._signals))
        return None

    def shutdown(self) -> None:
        """退出前停止线程池与抓帧器。"""
        self._video_queue.clear()
        self._grabber.shutdown()
        self._pool.clear()
        self._pool.waitForDone(2000)

    # ------------------------------------------------------------------ 内部
    def _pump_video(self) -> None:
        if self._grab_busy or not self._video_queue:
            return
        path = self._video_queue.popleft()
        self._grab_busy = True
        self._grabber.request(str(path), path)

    def _on_poster(self, key: str, image: object) -> None:
        self._grab_busy = False
        if isinstance(image, QImage) and not image.isNull():
            self._remember(key, image)
        self._pump_video()

    def _on_finished(self, key: str, image: object) -> None:
        self._pending.discard(key)
        if isinstance(image, QImage) and not image.isNull():
            self._remember(key, image)
        self.updated.emit()

    def _remember(self, key: str, image: QImage) -> None:
        self._cache[key] = image
        self._cache.move_to_end(key)
        while len(self._cache) > _CACHE_LIMIT:
            self._cache.popitem(last=False)
        self.updated.emit()
