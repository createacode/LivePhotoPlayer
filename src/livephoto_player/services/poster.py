"""视频封面抓取：从视频本身取一帧作为封面。

独立于主播放器实例，抓到首帧后立刻停止并释放媒体，不落地任何临时文件。
实况照片不需要封面（照片本身就是封面），只有独立视频文件会用到。
"""

from __future__ import annotations

import contextlib
from collections import OrderedDict
from pathlib import Path

from PySide6.QtCore import QObject, QTimer, QUrl, Signal
from PySide6.QtGui import QImage
from PySide6.QtMultimedia import QAudioOutput, QMediaPlayer, QVideoSink

from livephoto_player.core.models import VideoSpan
from livephoto_player.services.tail_device import TailDevice
from livephoto_player.utils.logger import get_logger

_GRAB_POSITION_MS = 300
_TIMEOUT_MS = 6000
_CACHE_LIMIT = 6
_POSTER_URL = "poster.mp4"


class PosterGrabber(QObject):
    """按需抓取视频首帧；结果通过 ``poster_ready(key, QImage)`` 返回。"""

    poster_ready = Signal(str, object)

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._logger = get_logger("poster")
        self._player: QMediaPlayer | None = None
        self._sink: QVideoSink | None = None
        self._audio: QAudioOutput | None = None
        self._device: TailDevice | None = None
        self._key = ""
        self._pending = False
        self._cache: OrderedDict[str, QImage] = OrderedDict()
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.setInterval(_TIMEOUT_MS)
        self._timer.timeout.connect(self._on_timeout)

    # ------------------------------------------------------------------ 对外接口
    def cached(self, key: str) -> QImage | None:
        """取已抓好的封面。"""
        return self._cache.get(key)

    def request(self, key: str, path: Path, span: VideoSpan | None = None) -> None:
        """请求抓取封面；同一 key 命中缓存时立即回发。"""
        if not key:
            return
        hit = self._cache.get(key)
        if hit is not None:
            self._cache.move_to_end(key)
            self.poster_ready.emit(key, hit)
            return
        self._ensure_player()
        self._teardown()
        self._key = key
        self._pending = True
        if span is not None:
            device = TailDevice(path, span)
            self._device = device
            self._player.setSourceDevice(device, QUrl(_POSTER_URL))  # type: ignore[union-attr]
        else:
            self._player.setSource(QUrl.fromLocalFile(str(path)))  # type: ignore[union-attr]
        self._player.setPosition(_GRAB_POSITION_MS)  # type: ignore[union-attr]
        self._player.play()  # type: ignore[union-attr]
        self._logger.debug("开始抓取封面：%s", path.name)
        self._timer.start()

    def cancel(self) -> None:
        """放弃当前抓取（例如用户已切走），不回调。"""
        if not self._pending:
            return
        self._pending = False
        self._timer.stop()
        self._teardown()

    def shutdown(self) -> None:
        """退出前释放资源。"""
        self.cancel()
        self._cache.clear()
        if self._player is not None:
            with contextlib.suppress(RuntimeError, TypeError):
                self._player.setVideoOutput(None)  # type: ignore[arg-type]
            self._player = None
        self._sink = None
        self._audio = None

    # ------------------------------------------------------------------ 内部实现
    def _ensure_player(self) -> None:
        if self._player is not None:
            return
        self._player = QMediaPlayer(self)
        self._sink = QVideoSink(self)
        self._player.setVideoSink(self._sink)
        self._sink.videoFrameChanged.connect(self._on_frame)
        self._audio = QAudioOutput(self)
        self._audio.setMuted(True)
        self._audio.setVolume(0.0)
        self._player.setAudioOutput(self._audio)

    def _teardown(self) -> None:
        if self._player is not None:
            try:
                self._player.stop()
                self._player.setSource(QUrl())
            except RuntimeError as exc:  # pragma: no cover - 播放器已销毁
                self._logger.debug("重置封面播放器失败：%s", exc)
        if self._device is not None:
            with contextlib.suppress(OSError):
                self._device.close()
            self._device = None

    def _on_frame(self, frame: object) -> None:
        if not self._pending:
            return
        is_valid = getattr(frame, "isValid", None)
        if not callable(is_valid) or not is_valid():
            return
        image = frame.toImage()  # type: ignore[attr-defined]
        if image is None or image.isNull():
            return
        self._finish(image)

    def _on_timeout(self) -> None:
        self._logger.warning("抓取封面超时：%s", self._key)
        self._finish(None)

    def _finish(self, image: object) -> None:
        if not self._pending:
            return
        self._pending = False
        self._timer.stop()
        key = self._key
        self._teardown()
        if isinstance(image, QImage) and not image.isNull():
            self._cache[key] = image
            self._cache.move_to_end(key)
            while len(self._cache) > _CACHE_LIMIT:
                self._cache.popitem(last=False)
        self.poster_ready.emit(key, image)
