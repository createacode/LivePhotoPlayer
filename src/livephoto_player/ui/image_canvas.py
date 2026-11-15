"""图片画布：以**原图像素**为坐标基准的自绘视图。

坐标模型
--------
所有几何量（缩放、平移、矩形）都在"原图像素空间"里计算，与当前解码到多少分辨率
无关。这样 ``100%`` 恒等于"一个原图像素对应一个屏幕像素"，而且从预览图升级到
全分辨率时目标矩形不变，画面不会突然放大。

渲染策略
--------
- 适应窗口：把当前可用的位图缩放到目标矩形成功一次并缓存，重绘只 ``drawPixmap``；
- 放大：``drawImage`` + ``SmoothPixmapTransform``，Qt 只采样可见区域；
- 快速缩放时先用 ``FastTransformation``，停止 90ms 后再做一次平滑重采样。
"""

from __future__ import annotations

from PySide6.QtCore import QEvent, QPoint, QPointF, QRectF, QSize, Qt, QTimer, Signal
from PySide6.QtGui import (
    QColor,
    QEnterEvent,
    QFont,
    QHideEvent,
    QImage,
    QMouseEvent,
    QPainter,
    QPaintEvent,
    QPixmap,
    QResizeEvent,
    QShowEvent,
    QWheelEvent,
)
from PySide6.QtWidgets import QWidget

from livephoto_player.ui import theme
from livephoto_player.ui.icons import zone_at, zone_cursor

MIN_ZOOM = 0.02
MAX_ZOOM = 16.0
SMOOTH_DELAY_MS = 90
ZONE_RATIO = 0.33


class ImageCanvas(QWidget):
    """自绘图片视图，支持以光标为锚点的缩放与无级平移。"""

    sig_previous = Signal()
    sig_next = Signal()
    sig_play = Signal()
    sig_open = Signal()
    zoom_changed = Signal(float)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._image: QImage | None = None
        self._source_size = QSize()
        self._zoom = 1.0
        self._fit_zoom = 1.0
        self._pan = QPointF(0.0, 0.0)
        self._scaled: QPixmap | None = None
        self._scaled_key: tuple[int, int, int, bool] | None = None
        self._smooth = True
        self._dragging = False
        self._press_pos = QPoint()
        self._moved = False
        self._loading = False
        self._status_text = ""
        self._pulse = 0.0
        self._hover = False

        self._smooth_timer = QTimer(self)
        self._smooth_timer.setSingleShot(True)
        self._smooth_timer.setInterval(SMOOTH_DELAY_MS)
        self._smooth_timer.timeout.connect(self._enable_smooth)

        self._pulse_timer = QTimer(self)
        self._pulse_timer.setInterval(60)
        self._pulse_timer.timeout.connect(self._tick_pulse)

        self.setMinimumSize(320, 240)
        self.setMouseTracking(True)
        self.setCursor(Qt.CursorShape.ArrowCursor)
        self.setAttribute(Qt.WidgetAttribute.WA_OpaquePaintEvent, True)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)

    # ------------------------------------------------------------------ 只读属性
    @property
    def has_image(self) -> bool:
        """是否已加载图片。"""
        return self._image is not None and not self._image.isNull()

    @property
    def image(self) -> QImage | None:
        """当前可用的位图（可能是预览，也可能是全分辨率）。"""
        return self._image

    @property
    def loaded_width(self) -> int:
        """当前位图的像素宽度；未加载时为 0。"""
        if self._image is None or self._image.isNull():
            return 0
        return self._image.width()

    @property
    def source_width(self) -> int:
        """原图像素宽度；未加载时为 0。"""
        return self._source_size.width() if self._source_size.isValid() else 0

    @property
    def source_height(self) -> int:
        """原图像素高度；未加载时为 0。"""
        return self._source_size.height() if self._source_size.isValid() else 0

    @property
    def zoom(self) -> float:
        """当前缩放倍率（屏幕像素 / 原图像素）。"""
        return self._zoom

    @property
    def fit_zoom(self) -> float:
        """适应当前窗口的缩放倍率。"""
        return self._fit_zoom

    def zoom_percent(self) -> int:
        """以百分比表示的缩放倍率，100% 即原图 1:1。"""
        return round(self._zoom * 100)

    # ------------------------------------------------------------------ 对外接口
    def set_status_text(self, text: str) -> None:
        """设置空状态下的提示文案。"""
        self._status_text = text
        if not self.has_image:
            self.update()

    def set_loading(self, loading: bool) -> None:
        """切换加载骨架屏。"""
        if self._loading == loading:
            return
        self._loading = loading
        if loading:
            self._pulse_timer.start()
        else:
            self._pulse_timer.stop()
        self.update()

    def set_image(self, image: QImage, source_size: QSize, *, fit: bool = True) -> None:
        """设置位图与其原图尺寸；``fit=True`` 时重新适应窗口。"""
        self._image = image
        if source_size.isValid() and source_size.width() > 0:
            self._source_size = source_size
        elif not image.isNull():
            self._source_size = image.size()
        self._invalidate_cache()
        if fit:
            self._apply_fit()
        else:
            self._clamp_pan()
        self.update()

    def upgrade_image(self, image: QImage) -> None:
        """用更高分辨率的同位图替换当前位图，保持缩放与平移不变。"""
        if image.isNull() or self._image is None:
            return
        if image.size() == self._image.size():
            return
        self._image = image
        self._invalidate_cache()
        self.update()

    def clear(self) -> None:
        """清空为占位状态。"""
        self._image = None
        self._source_size = QSize()
        self._invalidate_cache()
        self._zoom = 1.0
        self._fit_zoom = 1.0
        self._pan = QPointF(0.0, 0.0)
        self.set_loading(False)
        self.update()

    def fit(self) -> None:
        """恢复到适应窗口。"""
        if not self.has_image:
            return
        self._apply_fit()
        self.update()

    def zoom_to_percent(self, percent: int, anchor: QPoint | None = None) -> None:
        """缩放到指定百分比（100% = 原图 1:1）。"""
        self._zoom_to(max(1, percent) / 100.0, anchor)

    def zoom_step(self, factor: float, anchor: QPoint | None = None) -> None:
        """按倍率缩放一步。"""
        if not self.has_image:
            return
        self._zoom_to(self._zoom * factor, anchor)

    def is_at_fit(self) -> bool:
        """是否处于适应窗口状态。"""
        return self._is_fit()

    def needs_full_resolution(self, factor: float = 1.1) -> bool:
        """当前显示尺寸是否已超过可用位图，需要请求全分辨率。"""
        if not self.has_image:
            return False
        if self._source_size.width() <= self.loaded_width:
            return False
        return self._source_size.width() * self._zoom > self.loaded_width * factor

    # ------------------------------------------------------------------ 内部：几何
    def _image_size(self) -> tuple[float, float]:
        if not self._source_size.isValid():
            return 0.0, 0.0
        return float(self._source_size.width()), float(self._source_size.height())

    def _invalidate_cache(self) -> None:
        self._scaled = None
        self._scaled_key = None

    def _apply_fit(self) -> None:
        width, height = self._image_size()
        if width <= 0 or height <= 0:
            return
        available_w = max(1, self.width())
        available_h = max(1, self.height())
        self._fit_zoom = min(available_w / width, available_h / height)
        self._zoom = self._fit_zoom
        self._pan = QPointF(0.0, 0.0)
        self._invalidate_cache()
        self.zoom_changed.emit(self._zoom)

    def _image_rect(self) -> QRectF:
        width, height = self._image_size()
        scaled_w = width * self._zoom
        scaled_h = height * self._zoom
        left = (self.width() - scaled_w) / 2.0 + self._pan.x()
        top = (self.height() - scaled_h) / 2.0 + self._pan.y()
        return QRectF(left, top, scaled_w, scaled_h)

    def _clamp_pan(self) -> None:
        width, height = self._image_size()
        if width <= 0 or height <= 0:
            self._pan = QPointF(0.0, 0.0)
            return
        scaled_w = width * self._zoom
        scaled_h = height * self._zoom
        max_x = max(0.0, (scaled_w - self.width()) / 2.0)
        max_y = max(0.0, (scaled_h - self.height()) / 2.0)
        self._pan = QPointF(
            max(-max_x, min(max_x, self._pan.x())),
            max(-max_y, min(max_y, self._pan.y())),
        )

    def _zoom_to(self, target: float, anchor: QPoint | None = None) -> None:
        if not self.has_image:
            return
        clamped = max(MIN_ZOOM, min(MAX_ZOOM, target))
        if abs(clamped - self._zoom) < 1e-6:
            return
        widget_anchor = (
            anchor if anchor is not None else QPoint(self.width() // 2, self.height() // 2)
        )
        before = self._image_rect()
        if before.width() > 0 and before.height() > 0:
            rel_x = (widget_anchor.x() - before.left()) / before.width()
            rel_y = (widget_anchor.y() - before.top()) / before.height()
        else:
            rel_x = rel_y = 0.5
        self._zoom = clamped
        width, height = self._image_size()
        scaled_w = width * self._zoom
        scaled_h = height * self._zoom
        desired_left = widget_anchor.x() - rel_x * scaled_w
        desired_top = widget_anchor.y() - rel_y * scaled_h
        self._pan = QPointF(
            desired_left - (self.width() - scaled_w) / 2.0,
            desired_top - (self.height() - scaled_h) / 2.0,
        )
        self._invalidate_cache()
        self._smooth = False
        self._smooth_timer.start()
        self._clamp_pan()
        self.update()
        self.zoom_changed.emit(self._zoom)

    def _enable_smooth(self) -> None:
        self._smooth = True
        self._invalidate_cache()
        self.update()

    def _tick_pulse(self) -> None:
        self._pulse = (self._pulse + 0.08) % 1.0
        self.update()

    def _is_fit(self) -> bool:
        return abs(self._zoom - self._fit_zoom) <= max(1e-4, self._fit_zoom * 0.002)

    # ------------------------------------------------------------------ 渲染
    def _target_pixels(self) -> tuple[int, int, float]:
        rect = self._image_rect()
        dpr = self.devicePixelRatioF() or 1.0
        return (
            max(1, round(rect.width() * dpr)),
            max(1, round(rect.height() * dpr)),
            dpr,
        )

    def _ensure_scaled(self) -> QPixmap | None:
        """按目标矩形的像素尺寸缓存一张位图；只在图像或几何变化时重算。"""
        if self._image is None or self._image.isNull():
            return None
        target_w, target_h, dpr = self._target_pixels()
        key = (self._image.cacheKey(), target_w, target_h, self._smooth)
        if self._scaled is not None and self._scaled_key == key:
            return self._scaled
        mode = (
            Qt.TransformationMode.SmoothTransformation
            if self._smooth
            else Qt.TransformationMode.FastTransformation
        )
        pixmap = QPixmap.fromImage(
            self._image.scaled(target_w, target_h, Qt.AspectRatioMode.IgnoreAspectRatio, mode)
        )
        pixmap.setDevicePixelRatio(dpr)
        self._scaled = pixmap
        self._scaled_key = key
        return self._scaled

    def paintEvent(self, event: QPaintEvent) -> None:
        painter = QPainter(self)
        painter.fillRect(self.rect(), QColor(theme.COLOR_CANVAS))

        if not self.has_image:
            self._paint_empty(painter)
            return

        rect = self._image_rect()
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, self._smooth)
        if self._zoom <= self._fit_zoom * 1.001:
            pixmap = self._ensure_scaled()
            if pixmap is not None:
                painter.drawPixmap(rect.topLeft(), pixmap)
        elif self._image is not None:
            source = QRectF(0.0, 0.0, float(self._image.width()), float(self._image.height()))
            painter.drawImage(rect, self._image, source)

        if self._loading:
            self._paint_loading(painter)

    def _paint_empty(self, painter: QPainter) -> None:
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        font = QFont(self.font())
        font.setPointSizeF(11.5)
        painter.setFont(font)
        painter.setPen(QColor(theme.COLOR_TEXT_MUTED))
        title = self._status_text or "拖入照片 / 视频，或点击「打开文件」"
        painter.drawText(
            self.rect().adjusted(0, 0, 0, -60),
            Qt.AlignmentFlag.AlignCenter,
            title,
        )
        hint_font = QFont(self.font())
        hint_font.setPointSizeF(9.5)
        painter.setFont(hint_font)
        painter.setPen(QColor("#6b7480"))
        painter.drawText(
            self.rect().adjusted(0, 60, 0, 0),
            Qt.AlignmentFlag.AlignCenter,
            "左右区域切换照片 · 中间区域播放实况 · 滚轮缩放 · 双击还原",
        )

    def _paint_loading(self, painter: QPainter) -> None:
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        radius = 6
        bar_width = int(self.width() * 0.22)
        bar_height = 4
        x = (self.width() - bar_width) // 2
        y = int(self.height() * 0.86)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(255, 255, 255, 18))
        painter.drawRoundedRect(x, y, bar_width, bar_height, radius, radius)
        phase = self._pulse
        progress = int(bar_width * (0.15 + 0.7 * abs(phase - 0.5) * 2))
        painter.setBrush(QColor(theme.COLOR_ACCENT))
        painter.drawRoundedRect(x, y, max(bar_height, progress), bar_height, radius, radius)

    # ------------------------------------------------------------------ 交互
    def wheelEvent(self, event: QWheelEvent) -> None:
        if not self.has_image:
            return
        delta = event.angleDelta().y()
        if delta == 0:
            return
        steps = delta / 120.0
        factor = 1.15**steps
        self._zoom_to(self._zoom * factor, event.position().toPoint())
        event.accept()

    def mousePressEvent(self, event: QMouseEvent) -> None:
        if event.button() != Qt.MouseButton.LeftButton:
            super().mousePressEvent(event)
            return
        if not self.has_image:
            self.sig_open.emit()
            return
        self._press_pos = event.position().toPoint()
        self._moved = False
        self._dragging = True
        self.setCursor(Qt.CursorShape.ClosedHandCursor)

    def mouseMoveEvent(self, event: QMouseEvent) -> None:
        if not self._dragging:
            self._update_zone_cursor(event.position().toPoint())
        if not self._dragging or not self.has_image:
            return
        position = event.position().toPoint()
        delta = position - self._press_pos
        if not self._moved and delta.manhattanLength() > 3:
            self._moved = True
        if self._moved:
            self._pan = QPointF(self._pan.x() + delta.x(), self._pan.y() + delta.y())
            self._press_pos = position
            self._clamp_pan()
            self.update()

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:
        if event.button() != Qt.MouseButton.LeftButton:
            super().mouseReleaseEvent(event)
            return
        was_dragging = self._dragging
        moved = self._moved
        self._dragging = False
        self.setCursor(Qt.CursorShape.ArrowCursor)
        if was_dragging and not moved and self.has_image:
            self._handle_zone_click(event.position().toPoint())

    def mouseDoubleClickEvent(self, event: QMouseEvent) -> None:
        """双击只负责「还原」：已放大时回到适应窗口，适应状态下不做任何事。"""
        if event.button() == Qt.MouseButton.LeftButton and self.has_image and not self._is_fit():
            self.fit()
            event.accept()
            return
        super().mouseDoubleClickEvent(event)

    def _handle_zone_click(self, position: QPoint) -> None:
        """适应窗口时，左/中/右三块分别对应上一张、播放、下一张。"""
        rect = self._image_rect()
        if not rect.contains(QPointF(position)):
            return
        if not self._is_fit():
            return
        ratio = (position.x() - rect.left()) / max(1.0, rect.width())
        if ratio < ZONE_RATIO:
            self.sig_previous.emit()
        elif ratio > 1.0 - ZONE_RATIO:
            self.sig_next.emit()
        else:
            self.sig_play.emit()

    def resizeEvent(self, event: QResizeEvent) -> None:
        super().resizeEvent(event)
        was_fit = self._is_fit()
        self._invalidate_cache()
        if self.has_image and was_fit:
            self._apply_fit()
        else:
            self._clamp_pan()

    def enterEvent(self, event: QEnterEvent) -> None:
        self._hover = True
        super().enterEvent(event)

    def set_playing(self, playing: bool) -> None:
        """记录实况是否在播放，用于把中间区域的光标切成暂停。"""
        self._playing = playing
        self._update_zone_cursor(self.mapFromGlobal(self.cursor().pos()))

    def _update_zone_cursor(self, position: QPoint) -> None:
        """悬停到左/中/右区域时切换成对应的箭头或播放图标。"""
        if not self.has_image or not self._is_fit():
            self.setCursor(Qt.CursorShape.ArrowCursor)
            return
        rect = self._image_rect()
        if not rect.contains(QPointF(position)):
            self.setCursor(Qt.CursorShape.ArrowCursor)
            return
        ratio = (position.x() - rect.left()) / max(1.0, rect.width())
        kind = zone_at(ratio)
        if kind == "play" and getattr(self, "_playing", False):
            kind = "pause"
        self.setCursor(zone_cursor(kind))

    def leaveEvent(self, event: QEvent) -> None:
        self._hover = False
        super().leaveEvent(event)

    def hideEvent(self, event: QHideEvent) -> None:
        self._pulse_timer.stop()
        super().hideEvent(event)

    def showEvent(self, event: QShowEvent) -> None:
        if self._loading:
            self._pulse_timer.start()
        super().showEvent(event)
