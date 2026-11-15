"""预览浮层：贴在主窗口内部的单张查看器（不跑到父框架外）。

- 覆盖父窗口，半透明背景，点击背景或 ✕ / Esc 关闭；
- 中央卡片可上下翻页，空格播放实况，播完自动回到照片；
- 「返回时间线」直接关闭浮层回到原来的界面。
"""

from __future__ import annotations

from PySide6.QtCore import QSize, Qt, Signal
from PySide6.QtGui import QCloseEvent, QColor, QKeyEvent, QMouseEvent, QPainter, QPaintEvent
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from livephoto_player.core.models import ImagePayload, MediaItem, MediaKind, PlaybackState
from livephoto_player.services.image_loader import ImageLoader
from livephoto_player.services.media_engine import MediaEngine
from livephoto_player.ui import theme
from livephoto_player.ui.image_canvas import ImageCanvas
from livephoto_player.ui.video_surface import VideoSurface

HEADER_HEIGHT = 42
FOOTER_HEIGHT = 46
CARD_WIDTH_RATIO = 0.86
CARD_HEIGHT_RATIO = 0.88
BACKDROP_ALPHA = 190


class PreviewWindow(QWidget):
    """父窗口内的预览浮层。"""

    closed = Signal()
    index_changed = Signal(int)

    def __init__(self, items: list[MediaItem], index: int, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._items = list(items)
        self._index = max(0, min(index, len(self._items) - 1))
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, False)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)

        self._loader = ImageLoader(self)
        self._loader.loaded.connect(self._on_image_loaded)
        self._engine = MediaEngine(self)
        self._engine.state_changed.connect(self._on_engine_state)

        self._card = QFrame(self)
        self._card.setObjectName("previewCard")
        self._card.setStyleSheet(
            f"#previewCard {{ background-color: {theme.COLOR_WINDOW};"
            f" border: 1px solid {theme.COLOR_BORDER}; border-radius: 12px; }}"
            f"#previewCard QLabel {{ color: {theme.COLOR_TEXT}; }}"
        )

        self._canvas = ImageCanvas(self._card)
        self._surface = VideoSurface(self._card)
        self._engine.attach_video_output(self._surface.video_widget())
        self._stack = QStackedWidget(self._card)
        self._stack.addWidget(self._canvas)
        self._stack.addWidget(self._surface)

        self._title = QLabel("", self._card)
        self._title.setStyleSheet("font-weight: 600; padding: 0 6px;")
        self._close_button = QPushButton("✕", self._card)
        self._close_button.setFixedSize(34, 28)
        # 全局 QSS 给按钮留了 7px/14px 内边距，会把 ✕ 挤没，这里单独重置
        self._close_button.setStyleSheet(
            "QPushButton { padding: 0; min-height: 0; border-radius: 6px;"
            f" background-color: {theme.COLOR_PANEL_ALT}; color: {theme.COLOR_TEXT};"
            f" border: 1px solid {theme.COLOR_BORDER}; }}"
            f"QPushButton:hover {{ border-color: {theme.COLOR_DANGER};"
            f" color: {theme.COLOR_DANGER}; }}"
        )
        self._close_button.clicked.connect(self.close)

        header = QWidget(self._card)
        header.setFixedHeight(HEADER_HEIGHT)
        header.setStyleSheet(
            f"background-color: {theme.COLOR_PANEL}; border-top-left-radius: 11px;"
            f" border-top-right-radius: 11px;"
        )
        header_layout = QHBoxLayout(header)
        header_layout.setContentsMargins(14, 0, 8, 0)
        header_layout.addWidget(self._title, 1)
        header_layout.addWidget(self._close_button)

        self._prev_button = QPushButton("◀ 上一张", self._card)
        self._prev_button.clicked.connect(self.previous)
        self._next_button = QPushButton("下一张 ▶", self._card)
        self._next_button.clicked.connect(self.next)
        self._play_button = QPushButton("播放实况", self._card)
        self._play_button.clicked.connect(self.toggle_play)
        self._back_button = QPushButton("关闭预览", self._card)
        self._back_button.clicked.connect(self.close)
        self._counter = QLabel("", self._card)
        self._counter.setStyleSheet(f"color: {theme.COLOR_TEXT_MUTED};")

        footer = QWidget(self._card)
        footer.setFixedHeight(FOOTER_HEIGHT)
        footer.setStyleSheet(
            f"background-color: {theme.COLOR_PANEL}; border-bottom-left-radius: 11px;"
            f" border-bottom-right-radius: 11px;"
        )
        footer_layout = QHBoxLayout(footer)
        footer_layout.setContentsMargins(14, 4, 14, 4)
        footer_layout.setSpacing(8)
        for widget in (self._prev_button, self._next_button, self._play_button, self._back_button):
            footer_layout.addWidget(widget)
        footer_layout.addStretch(1)
        footer_layout.addWidget(self._counter)

        card_layout = QVBoxLayout(self._card)
        card_layout.setContentsMargins(0, 0, 0, 0)
        card_layout.setSpacing(0)
        card_layout.addWidget(header)
        card_layout.addWidget(self._stack, 1)
        card_layout.addWidget(footer)

        self.load(self._index)

    # ------------------------------------------------------------------ 对外接口
    def load(self, index: int) -> None:
        """载入并显示第 ``index`` 张。"""
        if not (0 <= index < len(self._items)):
            return
        self._index = index
        item = self._items[index]
        self._title.setText(f"{item.name}    {item.place_text}")
        self._counter.setText(f"{index + 1} / {len(self._items)}")
        self._play_button.setEnabled(item.has_video)
        self._prev_button.setEnabled(index > 0)
        self._next_button.setEnabled(index < len(self._items) - 1)
        self._engine.clear()
        self._stack.setCurrentWidget(self._canvas)
        if item.kind is MediaKind.VIDEO:
            self._surface.set_cover_pixmap(None)
            self._surface.set_cover_visible(True)
            self._stack.setCurrentWidget(self._surface)
            self._canvas.clear()
        else:
            self._canvas.set_loading(True)
            self._loader.request(item.path, max(900, self.width()), self._loader.next_generation())
        self.index_changed.emit(index)

    def previous(self) -> None:
        """上一张。"""
        if self._index > 0:
            self.load(self._index - 1)

    def next(self) -> None:
        """下一张。"""
        if self._index < len(self._items) - 1:
            self.load(self._index + 1)

    def toggle_play(self) -> None:
        """播放/暂停实况。"""
        item = self._items[self._index] if self._items else None
        if item is None or not item.has_video:
            return
        if self._engine.is_playing:
            self._engine.pause()
            return
        if item.kind is MediaKind.VIDEO:
            self._engine.open_path(item.path)
        elif item.span is not None:
            self._engine.open_span(item.path, item.span)
        else:
            return
        self._stack.setCurrentWidget(self._surface)
        self._surface.set_cover_visible(False)
        self._engine.play()

    def sync_geometry(self) -> None:
        """跟随父窗口尺寸。"""
        parent = self.parentWidget()
        if parent is None:
            return
        self.setGeometry(parent.rect())
        card_w = int(self.width() * CARD_WIDTH_RATIO)
        card_h = int(self.height() * CARD_HEIGHT_RATIO)
        self._card.setGeometry(
            (self.width() - card_w) // 2,
            (self.height() - card_h) // 2,
            card_w,
            card_h,
        )
        self.raise_()

    def shutdown(self) -> None:
        """释放资源。"""
        self._engine.shutdown()
        self._loader.shutdown()

    # ------------------------------------------------------------------ 绘制
    def paintEvent(self, event: QPaintEvent) -> None:
        painter = QPainter(self)
        painter.fillRect(self.rect(), QColor(0, 0, 0, BACKDROP_ALPHA))
        painter.end()

    # ------------------------------------------------------------------ 事件
    def showEvent(self, event: object) -> None:
        self.sync_geometry()
        super().showEvent(event)  # type: ignore[arg-type]

    def keyPressEvent(self, event: QKeyEvent) -> None:
        key = event.key()
        if key in (Qt.Key.Key_Left, Qt.Key.Key_Up):
            self.previous()
            return
        if key in (Qt.Key.Key_Right, Qt.Key.Key_Down):
            self.next()
            return
        if key in (Qt.Key.Key_Space, Qt.Key.Key_Return):
            self.toggle_play()
            return
        if key == Qt.Key.Key_Escape:
            self.close()
            return
        super().keyPressEvent(event)

    def mousePressEvent(self, event: QMouseEvent) -> None:
        # 点击半透明背景即关闭
        if not self._card.geometry().contains(event.position().toPoint()):
            self.close()
            return
        super().mousePressEvent(event)

    def closeEvent(self, event: QCloseEvent) -> None:
        self.shutdown()
        self.closed.emit()
        super().closeEvent(event)

    # ------------------------------------------------------------------ 内部
    def _on_image_loaded(self, payload: object) -> None:
        if not isinstance(payload, ImagePayload):
            return
        self._canvas.set_loading(False)
        image = payload.image
        if payload.error or image is None or getattr(image, "isNull", lambda: True)():
            return
        size = QSize(
            payload.source_width or payload.display_width,
            payload.source_height or payload.display_height,
        )
        self._canvas.set_image(image, size, fit=True)  # type: ignore[arg-type]

    def _on_engine_state(self, state: object) -> None:
        self._canvas.set_playing(state is PlaybackState.PLAYING)
        if state is PlaybackState.PLAYING:
            self._stack.setCurrentWidget(self._surface)
            self._surface.set_cover_visible(False)
            self._play_button.setText("暂停")
        elif state in (PlaybackState.ENDED, PlaybackState.STOPPED):
            self._play_button.setText("播放实况")
            self._stack.setCurrentWidget(self._canvas)
        else:
            self._play_button.setText("播放实况")


__all__ = ["PreviewWindow"]
