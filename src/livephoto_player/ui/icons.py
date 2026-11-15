"""界面图标：用 QPainter 现画，避免依赖外部图标资源。"""

from __future__ import annotations

import math

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import (
    QColor,
    QCursor,
    QIcon,
    QPainter,
    QPainterPath,
    QPen,
    QPixmap,
)

from livephoto_player.ui import theme


def _star_path(size: float) -> QPainterPath:
    """五角星路径。"""
    path = QPainterPath()
    center = size / 2.0
    outer = size / 2.0 - 0.6
    inner = outer * 0.44
    for index in range(10):
        radius = outer if index % 2 == 0 else inner
        angle = math.radians(-90 + index * 36)
        point = QPointF(
            center + radius * math.cos(angle),
            center + radius * math.sin(angle),
        )
        if index == 0:
            path.moveTo(point)
        else:
            path.lineTo(point)
    path.closeSubpath()
    return path


def star_icon(filled: bool, size: int = 18, color: str = "") -> QIcon:
    """实心/空心星标图标。"""
    pixmap = QPixmap(size, size)
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    path = _star_path(float(size))
    tint = QColor(color or theme.COLOR_WARNING)
    if filled:
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(tint)
        painter.drawPath(path)
    else:
        pen = QPen(tint, max(1.4, size / 11.0))
        pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
        painter.setPen(pen)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawPath(path)
    painter.end()
    return QIcon(pixmap)


def star_pixmap(filled: bool, size: int = 14, color: str = "") -> QPixmap:
    """星标位图（用于自绘委托）。"""
    return star_icon(filled, size, color).pixmap(size, size)


def rounded_rect_path(rect: QRectF | object, radius: float = 8.0) -> QPainterPath:
    """圆角矩形路径。"""
    path = QPainterPath()
    path.addRoundedRect(rect, radius, radius)  # type: ignore[arg-type]
    return path


_ZONE_CURSORS: dict[str, QCursor] = {}
CURSOR_SIZE = 36


def _zone_pixmap(kind: str) -> QPixmap:
    """只画符号本身，不加圆底；用一层淡描边保证在亮背景上也能看清。"""
    size = CURSOR_SIZE
    pixmap = QPixmap(size, size)
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    center = size / 2.0

    halo = QColor(15, 20, 26, 130)  # 淡描边，只在轮廓外露一点点
    white = QColor(255, 255, 255, 245)

    if kind == "play":
        path = QPainterPath()
        path.moveTo(center - 4.0, center - 7.0)
        path.lineTo(center + 8.0, center)
        path.lineTo(center - 4.0, center + 7.0)
        path.closeSubpath()
        painter.setPen(QPen(halo, 2.4))
        painter.setBrush(halo)
        painter.drawPath(path)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(white)
        painter.drawPath(path)
    elif kind == "pause":
        bar_w, bar_h, gap = 3.8, 13.0, 3.8
        left = center - gap / 2 - bar_w
        right = center + gap / 2
        painter.setPen(QPen(halo, 2.4))
        painter.setBrush(halo)
        painter.drawRoundedRect(
            QRectF(left - 1.0, center - bar_h / 2 - 1.0, bar_w + 2.0, bar_h + 2.0), 2, 2
        )
        painter.drawRoundedRect(
            QRectF(right - 1.0, center - bar_h / 2 - 1.0, bar_w + 2.0, bar_h + 2.0), 2, 2
        )
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(white)
        painter.drawRoundedRect(QRectF(left, center - bar_h / 2, bar_w, bar_h), 1.6, 1.6)
        painter.drawRoundedRect(QRectF(right, center - bar_h / 2, bar_w, bar_h), 1.6, 1.6)
    else:  # prev / next：圆头折线 <>
        direction = -1.0 if kind == "prev" else 1.0
        half_w, half_h = 5.0, 8.6
        chevron = QPainterPath()
        chevron.moveTo(center - direction * half_w, center - half_h)
        chevron.lineTo(center + direction * half_w, center)
        chevron.lineTo(center - direction * half_w, center + half_h)

        halo_pen = QPen(halo, 6.0)
        halo_pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        halo_pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
        painter.setPen(halo_pen)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawPath(chevron)

        pen = QPen(white, 3.4)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
        painter.setPen(pen)
        painter.drawPath(chevron)

    painter.end()
    return pixmap


def zone_cursor(kind: str) -> QCursor:
    """按区域返回光标：左右折线箭头 / 播放 / 暂停。"""
    cached = _ZONE_CURSORS.get(kind)
    if cached is not None:
        return cached
    pixmap = _zone_pixmap(kind)
    cursor = QCursor(pixmap, CURSOR_SIZE // 2, CURSOR_SIZE // 2)
    _ZONE_CURSORS[kind] = cursor
    return cursor


def zone_at(ratio: float) -> str:
    """按横向比例判断区域。"""
    if ratio < 0.32:
        return "prev"
    if ratio > 0.68:
        return "next"
    return "play"
