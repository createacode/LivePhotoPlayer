"""时间线渲染：日期分组标题 + 醒目时间 + 醒目地点。

同一个委托同时服务"主列表"和"收藏夹"，通过 ``mode`` 切换单行/时间线两种密度。
"""

from __future__ import annotations

from typing import Final

from PySide6.QtCore import QModelIndex, QPersistentModelIndex, QRect, QSize, Qt
from PySide6.QtGui import (
    QColor,
    QFont,
    QFontMetrics,
    QPainter,
    QPalette,
)
from PySide6.QtWidgets import QStyle, QStyledItemDelegate, QStyleOptionViewItem, QWidget

from livephoto_player.core.models import MediaItem
from livephoto_player.ui import theme

ROLE_ITEM: Final = int(Qt.ItemDataRole.UserRole) + 1
ROLE_DAY: Final = int(Qt.ItemDataRole.UserRole) + 2
ROLE_TIME: Final = int(Qt.ItemDataRole.UserRole) + 3
ROLE_PLACE: Final = int(Qt.ItemDataRole.UserRole) + 4
ROLE_FAVORITE: Final = int(Qt.ItemDataRole.UserRole) + 5

MODE_NAME: Final = "name"
MODE_TIMELINE: Final = "timeline"

HEADER_HEIGHT: Final = 26
ROW_HEIGHT: Final = 62
NAME_ROW_HEIGHT: Final = 34
PADDING: Final = 10


class TimelineDelegate(QStyledItemDelegate):
    """按"日期分组 + 时间 + 地点"绘制列表项。"""

    def __init__(self, mode: str = MODE_TIMELINE, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._mode = mode
        self._day_headers = False

    def set_day_headers(self, enabled: bool) -> None:
        """按拍摄时间排序时是否显示"日期分组 + 简写时间"。"""
        self._day_headers = enabled

    def set_mode(self, mode: str) -> None:
        """切换单行/时间线模式。"""
        self._mode = mode

    def mode(self) -> str:
        """当前模式。"""
        return self._mode

    # ------------------------------------------------------------------ 尺寸
    def sizeHint(self, option: QStyleOptionViewItem, index: QModelIndex) -> QSize:
        if self._mode == MODE_NAME:
            # 日期分组标题画在行内，行高必须同步加高，否则文字会溢到下一行
            extra = HEADER_HEIGHT if (self._day_headers and self._is_group_start(index)) else 0
            return QSize(option.rect.width(), NAME_ROW_HEIGHT + extra)
        height = ROW_HEIGHT + (HEADER_HEIGHT if self._is_group_start(index) else 0)
        return QSize(option.rect.width(), height)

    def _is_group_start(self, index: QModelIndex | QPersistentModelIndex) -> bool:
        row = index.row()
        if row <= 0:
            return True
        model = index.model()
        current = model.data(index, ROLE_DAY)
        previous = model.data(model.index(row - 1, 0), ROLE_DAY)
        return bool(current) and current != previous

    # ------------------------------------------------------------------ 绘制
    def paint(self, painter: QPainter, option: QStyleOptionViewItem, index: QModelIndex) -> None:
        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        painter.setRenderHint(QPainter.RenderHint.TextAntialiasing, True)

        item = index.model().data(index, ROLE_ITEM)
        name = item.name if isinstance(item, MediaItem) else str(index.data() or "")
        day = str(index.model().data(index, ROLE_DAY) or "")
        time_text = str(index.model().data(index, ROLE_TIME) or "")
        place = str(index.model().data(index, ROLE_PLACE) or "")
        favorite = bool(index.model().data(index, ROLE_FAVORITE))

        rect = option.rect
        selected = bool(option.state & QStyle.StateFlag.State_Selected)
        hovered = bool(option.state & QStyle.StateFlag.State_MouseOver)

        # 名单模式下底色由 _paint_name_row 只铺在照片行上，日期标题不参与
        if self._mode != MODE_NAME and selected:
            painter.setBrush(QColor(theme.COLOR_ACCENT_SOFT))
            painter.setPen(Qt.PenStyle.NoPen)
            painter.drawRoundedRect(rect.adjusted(4, 3, -4, -3), 8, 8)
        elif self._mode != MODE_NAME and hovered:
            painter.setBrush(QColor(theme.COLOR_PANEL_ALT))
            painter.setPen(Qt.PenStyle.NoPen)
            painter.drawRoundedRect(rect.adjusted(4, 3, -4, -3), 8, 8)

        content = QRect(rect)
        if self._mode == MODE_TIMELINE and day and self._is_group_start(index):
            content = self._paint_header(painter, rect, day)
        elif self._mode == MODE_NAME:
            if self._day_headers and day and self._is_group_start(index):
                content = self._paint_header(painter, rect, day)
            self._paint_name_row(
                painter, content, name, favorite, selected, time_text if self._day_headers else ""
            )
            painter.restore()
            return

        self._paint_timeline_row(painter, content, time_text, place, name, favorite, selected)
        painter.restore()

    def _paint_header(self, painter: QPainter, rect: QRect, day: str) -> QRect:
        header = QRect(rect.left(), rect.top() + 2, rect.width(), HEADER_HEIGHT)
        font = QFont(painter.font())
        font.setPointSizeF(10.5)
        font.setBold(True)
        painter.setFont(font)
        painter.setPen(QColor(theme.COLOR_ACCENT))
        painter.drawText(
            header.adjusted(PADDING + 4, 0, -PADDING, 0),
            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
            day,
        )
        painter.setPen(QColor(theme.COLOR_BORDER))
        painter.drawLine(
            header.left() + PADDING,
            header.bottom() - 2,
            header.right() - PADDING,
            header.bottom() - 2,
        )
        return QRect(
            rect.left(), rect.top() + HEADER_HEIGHT, rect.width(), rect.height() - HEADER_HEIGHT
        )

    def _paint_timeline_row(
        self,
        painter: QPainter,
        rect: QRect,
        time_text: str,
        place: str,
        name: str,
        favorite: bool,
        selected: bool,
    ) -> None:
        left = rect.left() + PADDING
        right = rect.right() - PADDING
        top = rect.top() + 5

        # 第一行：拍摄时刻（粗体、大字号，最醒目）
        time_font = QFont(painter.font())
        time_font.setPointSizeF(12.5)
        time_font.setBold(True)
        painter.setFont(time_font)
        painter.setPen(QColor("#ffffff" if selected else theme.COLOR_TEXT))
        time_metrics = QFontMetrics(time_font)
        time_width = time_metrics.horizontalAdvance(time_text or "--:--") + 4
        painter.drawText(
            QRect(left, top, time_width, 20),
            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
            time_text or "--:--",
        )

        if favorite:
            star_font = QFont(painter.font())
            star_font.setPointSizeF(11.5)
            painter.setFont(star_font)
            painter.setPen(QColor(theme.COLOR_WARNING))
            painter.drawText(
                QRect(right - 16, top, 16, 20),
                Qt.AlignmentFlag.AlignCenter,
                "\u2605",
            )

        # 第二行：拍摄地点（独占整行，不再被时间挤压）
        place_font = QFont(painter.font())
        place_font.setPointSizeF(10.5)
        painter.setFont(place_font)
        painter.setPen(QColor("#dfe7f5" if selected else theme.COLOR_WARNING))
        place_rect = QRect(left, top + 21, right - left, 18)
        painter.drawText(
            place_rect,
            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
            QFontMetrics(place_font).elidedText(
                place or "地点未知", Qt.TextElideMode.ElideRight, place_rect.width()
            ),
        )

        # 第三行：文件名（弱化）
        name_font = QFont(painter.font())
        name_font.setPointSizeF(9.5)
        painter.setFont(name_font)
        painter.setPen(QColor(theme.COLOR_TEXT_MUTED))
        name_rect = QRect(left, top + 39, right - left, 16)
        painter.drawText(
            name_rect,
            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
            QFontMetrics(name_font).elidedText(
                name, Qt.TextElideMode.ElideMiddle, name_rect.width()
            ),
        )

    def _paint_name_row(
        self,
        painter: QPainter,
        rect: QRect,
        name: str,
        favorite: bool,
        selected: bool,
        time_text: str = "",
    ) -> None:
        label = f"{name}  ★" if favorite else name
        font = QFont(painter.font())
        font.setPointSizeF(10)
        painter.setFont(font)
        painter.setPen(
            QColor(
                theme.COLOR_WARNING if time_text else ("#ffffff" if selected else theme.COLOR_TEXT)
            )
        )
        # 选中底色只铺在照片行上（日期标题在 rect 之上，不会被涂到）
        if selected:
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor(theme.COLOR_ACCENT_SOFT))
            painter.save()
            painter.setClipRect(rect)
            painter.drawRoundedRect(rect.adjusted(1, 1, -1, -1), 6, 6)
            painter.restore()
        text_rect = rect.adjusted(PADDING, 0, -PADDING, 0)
        if time_text:
            time_width = QFontMetrics(font).horizontalAdvance(time_text) + 8
            painter.drawText(
                text_rect.adjusted(0, 0, -time_width, 0),
                int(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter),
                time_text,
            )
            text_rect = text_rect.adjusted(time_width, 0, 0, 0)
            painter.setPen(QColor("#ffffff" if selected else theme.COLOR_TEXT))
        painter.drawText(
            text_rect,
            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
            QFontMetrics(font).elidedText(
                label,
                Qt.TextElideMode.ElideMiddle,
                text_rect.width(),
            ),
        )


def palette_text(option: QStyleOptionViewItem) -> QPalette.ColorRole:
    """兼容不同主题下的文本颜色角色。"""
    return option.palette.color(QPalette.ColorRole.WindowText).name()  # type: ignore[return-value]


__all__ = [
    "MODE_NAME",
    "MODE_TIMELINE",
    "ROLE_DAY",
    "ROLE_FAVORITE",
    "ROLE_ITEM",
    "ROLE_PLACE",
    "ROLE_TIME",
    "TimelineDelegate",
]
