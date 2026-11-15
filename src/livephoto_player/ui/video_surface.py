"""视频显示区：封面与视频画面二选一（栈式切换，不做叠加）。

为什么不用「QVideoWidget + 覆盖 QLabel」：QVideoWidget 在 Windows 上是原生子窗口
（独立 HWND），Qt 绘制的兄弟控件永远压在它下面，封面会被盖住、整块显示为黑色。
这里改用 ``QStackedLayout`` 在两个页面之间切换，天然没有层叠问题。
"""

from __future__ import annotations

from PySide6.QtCore import QPoint, QRect, QSize, Qt, Signal
from PySide6.QtGui import QMouseEvent, QPaintEvent, QPixmap, QResizeEvent
from PySide6.QtMultimediaWidgets import QVideoWidget
from PySide6.QtWidgets import QLabel, QStackedLayout, QWidget

from livephoto_player.ui import theme
from livephoto_player.ui.icons import zone_at, zone_cursor


class VideoSurface(QWidget):
    """视频画面与封面共用的显示容器。"""

    clicked = Signal()
    zone_clicked = Signal(int)  # 0=上一张 1=播放/暂停 2=下一张
    context_menu_requested = Signal(QPoint)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._video = QVideoWidget(self)
        self._video.setStyleSheet(f"background-color: {theme.COLOR_CANVAS};")

        self._cover = QLabel(self)
        self._cover.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._cover.setStyleSheet(
            f"background-color: {theme.COLOR_CANVAS}; color: {theme.COLOR_TEXT_MUTED};"
        )

        self._stack = QStackedLayout(self)
        self._stack.setContentsMargins(0, 0, 0, 0)
        self._stack.addWidget(self._cover)
        self._stack.addWidget(self._video)

        self._cover_pixmap: QPixmap | None = None
        self._cover_scaled: QPixmap | None = None
        self._cover_key: tuple[int, int, int] | None = None
        self._cover.setText("点击开始播放")

        # 鼠标事件统一由容器处理，子控件不抢事件
        for child in (self._video, self._cover):
            child.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)

        self._stack.setCurrentWidget(self._cover)

    # ------------------------------------------------------------------ 对外接口
    def video_widget(self) -> QVideoWidget:
        """返回底层 QVideoWidget，供播放器绑定输出。"""
        return self._video

    def set_cover_pixmap(self, pixmap: QPixmap | None) -> None:
        """设置封面图；``None`` 表示使用纯色兜底。"""
        self._cover_pixmap = pixmap
        self._cover_scaled = None
        self._cover_key = None
        if pixmap is None or pixmap.isNull():
            self._cover.setText("点击开始播放")
        else:
            self._cover.setText("")
        self._refresh_cover()

    def set_cover_visible(self, visible: bool) -> None:
        """显示封面（True）还是显示视频画面（False）。"""
        if visible:
            self._stack.setCurrentWidget(self._cover)
            self._refresh_cover()
        else:
            self._stack.setCurrentWidget(self._video)

    def cover_visible(self) -> bool:
        """封面当前是否可见。"""
        return self._stack.currentWidget() is self._cover

    def set_background(self) -> None:
        """回到纯色背景（无视频、无封面）。"""
        self._cover.setPixmap(QPixmap())
        self._cover_pixmap = None
        self._cover.setText("")
        self._stack.setCurrentWidget(self._cover)

    # ------------------------------------------------------------------ 内部实现
    def _refresh_cover(self) -> None:
        if self._cover_pixmap is None or self._cover_pixmap.isNull():
            self._cover.setPixmap(QPixmap())
            return
        size = self._cover.size()
        if size.width() <= 0 or size.height() <= 0:
            return
        dpr = self.devicePixelRatioF() or 1.0
        key = (size.width(), size.height(), int(dpr * 100))
        if self._cover_scaled is not None and self._cover_key == key:
            self._cover.setPixmap(self._cover_scaled)
            return
        target = QSize(int(size.width() * dpr), int(size.height() * dpr))
        # 完整显示首帧（不裁剪），便于用户辨认是哪个视频
        scaled = self._cover_pixmap.scaled(
            target,
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        )
        scaled.setDevicePixelRatio(dpr)
        self._cover_scaled = scaled
        self._cover_key = key
        self._cover.setPixmap(scaled)

    def resizeEvent(self, event: QResizeEvent) -> None:
        super().resizeEvent(event)
        self._cover_key = None
        if self.cover_visible():
            self._refresh_cover()

    def paintEvent(self, event: QPaintEvent) -> None:
        super().paintEvent(event)

    def mouseMoveEvent(self, event: QMouseEvent) -> None:
        width = max(1, self.width())
        self.setCursor(zone_cursor(zone_at(event.position().x() / width)))

    def leaveEvent(self, event: object) -> None:
        self.setCursor(Qt.CursorShape.ArrowCursor)
        super().leaveEvent(event)  # type: ignore[arg-type]

    def mousePressEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            # 左三分之一上一张、右三分之一下一张、中间暂停
            width = max(1, self.width())
            ratio = event.position().x() / width
            self.zone_clicked.emit(0 if ratio < 0.33 else (2 if ratio > 0.67 else 1))
            self.clicked.emit()
            event.accept()
            return
        super().mousePressEvent(event)

    def contextMenuEvent(self, event: object) -> None:
        position = getattr(event, "pos", lambda: QPoint(0, 0))()
        self.context_menu_requested.emit(position)
        accept = getattr(event, "accept", None)
        if callable(accept):
            accept()


__all__ = ["QRect", "VideoSurface"]
