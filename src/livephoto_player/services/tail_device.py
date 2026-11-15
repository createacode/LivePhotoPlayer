"""把文件的一段字节区间包装成可寻址的 ``QIODevice``。

实况照片的内嵌视频位于 JPEG 尾部，把它暴露成 QIODevice 后，
``QMediaPlayer.setSourceDevice`` 可以直接播放，**不再需要写临时文件**。
"""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QIODevice, QObject

from livephoto_player.core.models import VideoSpan
from livephoto_player.utils.logger import get_logger

_READ_CHUNK = 1 << 16


class TailDevice(QIODevice):
    """只读、可随机定位的文件区间视图。"""

    def __init__(self, path: Path, span: VideoSpan, parent: QObject | None = None) -> None:
        super().__init__(parent) if parent is not None else super().__init__()
        self._logger = get_logger("tail")
        self._offset = span.offset
        self._size = span.length
        self._position = 0
        self._handle = path.open("rb")
        self.open(QIODevice.OpenModeFlag.ReadOnly)

    def isSequential(self) -> bool:
        return False

    def size(self) -> int:
        return self._size

    def pos(self) -> int:
        return self._position

    def seek(self, position: int) -> bool:
        if 0 <= position <= self._size:
            self._position = position
            return True
        return False

    def atEnd(self) -> bool:
        return self._position >= self._size

    def bytesAvailable(self) -> int:
        return self._size - self._position + super().bytesAvailable()

    def readData(self, maxlen: int) -> bytes:
        if maxlen <= 0 or self._position >= self._size:
            return b""
        length = min(maxlen, self._size - self._position)
        try:
            self._handle.seek(self._offset + self._position)
            data = self._handle.read(length)
        except OSError as exc:
            self._logger.error("读取内嵌视频失败：%s", exc)
            return b""
        self._position += len(data)
        return data

    def writeData(self, data: bytes | bytearray | memoryview, maxlen: int) -> int:
        return -1

    def close(self) -> None:
        if not self._handle.closed:
            try:
                self._handle.close()
            except OSError as exc:
                self._logger.warning("关闭内嵌视频句柄失败：%s", exc)
        super().close()


__all__ = ["_READ_CHUNK", "TailDevice"]
