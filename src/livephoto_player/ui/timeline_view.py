"""时间线模式：全屏独立界面。

结构：顶部工具条（返回 / 上一天 / 日期下拉 / 下一天 / 日历 / 缩放）＋ 竖轴时间线。
每行「时间 → 大图 → 地点」，长按竖轴可上下拖动按日期跨度跳转。
"""

from __future__ import annotations

from PySide6.QtCore import (
    QAbstractListModel,
    QDate,
    QModelIndex,
    QPersistentModelIndex,
    QPoint,
    QRect,
    QSize,
    Qt,
    QTimer,
    Signal,
)
from PySide6.QtGui import (
    QColor,
    QFont,
    QFontMetrics,
    QPainter,
    QPen,
    QPixmap,
    QTextCharFormat,
)
from PySide6.QtWidgets import (
    QCalendarWidget,
    QComboBox,
    QDialog,
    QHBoxLayout,
    QLabel,
    QListView,
    QMenu,
    QPushButton,
    QSlider,
    QStyle,
    QStyledItemDelegate,
    QStyleOptionViewItem,
    QVBoxLayout,
    QWidget,
)

from livephoto_player.core.models import MediaItem, MediaKind
from livephoto_player.ui import theme
from livephoto_player.ui.icons import rounded_rect_path, star_pixmap
from livephoto_player.ui.thumbnails import ThumbnailCache

ROLE_ITEM = int(Qt.ItemDataRole.UserRole) + 1

AXIS_X = 26
DAY_HEADER_HEIGHT = 44
BASE_THUMB_W = 190
BASE_THUMB_H = 128
PADDING_LEFT = 54
TIME_WIDTH = 64
SCRUB_HOLD_MS = 600
SCRUB_STEP_PX = 56
COMPACT_HEIGHT = 30


class TimelineModel(QAbstractListModel):
    """只提供数据。"""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._items: list[MediaItem] = []

    def set_items(self, items: list[MediaItem]) -> None:
        self.beginResetModel()
        self._items = list(items)
        self.endResetModel()

    def items(self) -> list[MediaItem]:
        return list(self._items)

    def item_at(self, row: int) -> MediaItem | None:
        if 0 <= row < len(self._items):
            return self._items[row]
        return None

    def day_rows(self) -> list[tuple[str, int]]:
        """每一天的第一个行号，供日期跳转使用。"""
        result: list[tuple[str, int]] = []
        for row, item in enumerate(self._items):
            day = item.day_text or "时间未知"
            if not result or result[-1][0] != day:
                result.append((day, row))
        return result

    def rowCount(self, parent: QModelIndex | QPersistentModelIndex | None = None) -> int:
        if parent is not None and parent.isValid():
            return 0
        return len(self._items)

    def data(
        self,
        index: QModelIndex | QPersistentModelIndex,
        role: int = int(Qt.ItemDataRole.DisplayRole),
    ) -> object:
        if not index.isValid() or not (0 <= index.row() < len(self._items)):
            return None
        item = self._items[index.row()]
        if role == ROLE_ITEM:
            return item
        if role == int(Qt.ItemDataRole.DisplayRole):
            return item.name
        return None


class TimelineDelegate(QStyledItemDelegate):
    """滑轮式时间线。

    - 只有"当前项"展开：显示大图 + 右侧固定文字栏（照片在扣除文字栏后的区域居中，
      两者永不重叠）；
    - 其余项折叠成一行：只有时间和地点，便于一眼扫过整段行程；
    - 滚动/点击都会改变当前项，展开位置随之移动。
    """

    def __init__(self, cache: ThumbnailCache, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._cache = cache
        self._scale = 1.0
        self._view_width = 900
        self._view_height = 600
        self._current_row = 0

    def set_scale(self, scale: float) -> None:
        """缩放展开后的照片尺寸；下限放到 0.15。"""
        self._scale = max(0.15, min(2.4, scale))

    def set_view_size(self, width: int, height: int) -> None:
        """由列表在 resize 时同步。"""
        self._view_width = max(320, width)
        self._view_height = max(240, height)

    def set_current_row(self, row: int) -> None:
        """设置展开的那一行。"""
        self._current_row = max(0, row)

    def is_expanded(self, row: int) -> bool:
        """该行是否展开。"""
        return row == self._current_row

    # ------------------------------------------------------------------ 尺寸
    def layout_metrics(self) -> tuple[int, int, int]:
        """返回 (时间列宽, 右侧文字栏宽, 间距)。"""
        content = max(240, self._view_width - (AXIS_X + 26) - 26)
        text_w = int(min(280, max(140, content * 0.22)))
        return 60, text_w, 18

    def photo_area(self) -> tuple[int, int]:
        """照片可用区域（内容起点、宽度）——已扣除时间列与文字栏。"""
        content_left = AXIS_X + 26
        content = max(240, self._view_width - content_left - 26)
        time_w, text_w, gap = self.layout_metrics()
        left = content_left + time_w
        width = max(80, content - time_w - text_w - gap)
        return left, width

    def photo_size(self, item: MediaItem) -> QSize:
        """按原比例放进"内容区减去左右各一个文字栏"，从而在内容区里绝对居中。"""
        content_left = AXIS_X + 26
        _time_w, text_w, _gap = self.layout_metrics()
        area_w = max(120, self._view_width - content_left - 26)
        box_w = int(max(60, area_w - text_w * 2) * min(1.0, self._scale))
        box_h = int(self._view_height * 0.62 * self._scale)
        width, height = item.pixel_width, item.pixel_height
        if width <= 0 or height <= 0:
            cached = self._cache.get(item.path, item.kind)
            if cached is not None and not cached.isNull():
                width, height = cached.width(), cached.height()
        if width <= 0 or height <= 0:
            width, height = 4, 3
        ratio = width / height
        target_w = max(24, box_w)
        target_h = int(target_w / ratio)
        if target_h > box_h:
            target_h = max(18, box_h)
            target_w = int(target_h * ratio)
        return QSize(max(24, target_w), max(18, target_h))

    def expanded_height(self, item: MediaItem | None) -> int:
        photo = self.photo_size(item) if item is not None else QSize(400, 300)
        # 上下留白相等，配合 scrollTo(PositionAtCenter) 让照片落在窗口正中
        return max(photo.height(), 96) + 96

    def row_height(self, item: MediaItem | None, row: int) -> int:
        if self.is_expanded(row):
            return self.expanded_height(item)
        return COMPACT_HEIGHT

    def _is_day_start(self, index: QModelIndex) -> bool:
        row = index.row()
        if row <= 0:
            return True
        model = index.model()
        current = model.data(index, ROLE_ITEM)
        previous = model.data(model.index(row - 1, 0), ROLE_ITEM)
        if not isinstance(current, MediaItem) or not isinstance(previous, MediaItem):
            return True
        return current.day_text != previous.day_text

    def sizeHint(self, option: QStyleOptionViewItem, index: QModelIndex) -> QSize:
        item = index.model().data(index, ROLE_ITEM)
        row = index.row()
        extra = DAY_HEADER_HEIGHT if self._is_day_start(index) else 0
        height = self.row_height(item if isinstance(item, MediaItem) else None, row)
        return QSize(option.rect.width(), height + extra)

    # ------------------------------------------------------------------ 绘制
    def paint(self, painter: QPainter, option: QStyleOptionViewItem, index: QModelIndex) -> None:
        item = index.model().data(index, ROLE_ITEM)
        if not isinstance(item, MediaItem):
            return
        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        painter.setRenderHint(QPainter.RenderHint.TextAntialiasing, True)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)

        rect = option.rect
        row = index.row()
        day_start = self._is_day_start(index)
        selected = self.is_expanded(row)
        hovered = bool(option.state & QStyle.StateFlag.State_MouseOver)
        content_left = rect.left() + AXIS_X + 26

        top = rect.top()
        if day_start:
            font = QFont(painter.font())
            font.setPointSizeF(11.5)
            font.setBold(True)
            painter.setFont(font)
            painter.setPen(QColor(theme.COLOR_ACCENT))
            painter.drawText(
                QRect(content_left, top + 10, max(120, rect.width() - content_left - 20), 22),
                int(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter),
                item.day_text or "时间未知",
            )
            top += DAY_HEADER_HEIGHT

        if self.is_expanded(row):
            self._paint_expanded(painter, item, rect, top, selected, hovered)
        else:
            self._paint_compact(painter, item, rect, top, hovered)
        painter.restore()

    def _paint_compact(
        self, painter: QPainter, item: MediaItem, rect: QRect, top: int, hovered: bool
    ) -> None:
        """折叠态：一行 时间 + 地点。"""
        content_left = rect.left() + AXIS_X + 26
        content_right = rect.right() - 26
        mid_y = top + COMPACT_HEIGHT // 2

        painter.setPen(QPen(QColor(theme.COLOR_BORDER), 2))
        painter.drawLine(AXIS_X, top, AXIS_X, top + COMPACT_HEIGHT)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(theme.COLOR_ACCENT if hovered else "#3a4450"))
        painter.drawEllipse(AXIS_X - 4, mid_y - 4, 8, 8)

        time_font = QFont(painter.font())
        time_font.setPointSizeF(10.5)
        time_font.setBold(True)
        painter.setFont(time_font)
        painter.setPen(QColor(theme.COLOR_TEXT_MUTED))
        painter.drawText(
            QRect(content_left, mid_y - 10, 52, 20),
            int(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter),
            item.time_text or "--:--",
        )

        place_font = QFont(painter.font())
        place_font.setPointSizeF(10)
        painter.setFont(place_font)
        painter.setPen(QColor("#8c7856" if not hovered else theme.COLOR_WARNING))
        place_rect = QRect(content_left + 58, mid_y - 10, content_right - content_left - 58, 20)
        painter.drawText(
            place_rect,
            int(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter),
            QFontMetrics(place_font).elidedText(
                item.place_text, Qt.TextElideMode.ElideRight, place_rect.width()
            ),
        )

    def _paint_expanded(
        self,
        painter: QPainter,
        item: MediaItem,
        rect: QRect,
        top: int,
        selected: bool,
        hovered: bool,
    ) -> None:
        content_left = rect.left() + AXIS_X + 26
        content_right = rect.right() - 26
        time_w, text_w, _gap = self.layout_metrics()
        row_h = self.expanded_height(item)
        photo = self.photo_size(item)

        # 照片以"内容区中心"为基准水平居中；左右各留一个文字栏宽度，故与文字不重叠
        content_center = (content_left + content_right) // 2
        photo_x = content_center - photo.width() // 2
        photo_y = top + (row_h - photo.height()) // 2

        painter.setPen(QPen(QColor(theme.COLOR_BORDER), 2))
        painter.drawLine(AXIS_X, top, AXIS_X, top + row_h)
        node_y = photo_y + photo.height() // 2
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(theme.COLOR_ACCENT))
        painter.drawEllipse(AXIS_X - 6, node_y - 6, 12, 12)

        time_font = QFont(painter.font())
        time_font.setPointSizeF(13.5)
        time_font.setBold(True)
        painter.setFont(time_font)
        painter.setPen(QColor(theme.COLOR_ACCENT))
        painter.drawText(
            QRect(content_left, photo_y + 4, time_w - 8, 22),
            int(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter),
            item.time_text or "--:--",
        )

        self._paint_photo(
            painter, QRect(photo_x, photo_y, photo.width(), photo.height()), item, selected
        )

        # 文字栏：固定最右侧，独占一列
        text_x = content_right - text_w
        block_h = 104  # 地点最多两行 + 文件名 + 星标
        text_y = photo_y + max(0, (photo.height() - block_h) // 2)

        place_font = QFont(painter.font())
        place_font.setPointSizeF(11.5)
        place_font.setBold(True)
        painter.setFont(place_font)
        painter.setPen(QColor(theme.COLOR_WARNING))
        painter.drawText(
            QRect(text_x, text_y, text_w, 40),
            int(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop | Qt.TextFlag.TextWordWrap),
            item.place_text,
        )

        name_font = QFont(painter.font())
        name_font.setPointSizeF(9.5)
        painter.setFont(name_font)
        painter.setPen(QColor(theme.COLOR_TEXT_MUTED))
        painter.drawText(
            QRect(text_x, text_y + 50, text_w, 18),
            int(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop),
            QFontMetrics(name_font).elidedText(item.name, Qt.TextElideMode.ElideMiddle, text_w),
        )
        if item.favorite:
            painter.drawPixmap(QRect(text_x, text_y + 72, 14, 14), star_pixmap(True, 14))

    def _paint_photo(self, painter: QPainter, rect: QRect, item: MediaItem, selected: bool) -> None:
        image = self._cache.get(item.path, item.kind)
        painter.setPen(Qt.PenStyle.NoPen)
        if image is None or image.isNull():
            painter.setBrush(QColor("#242b33"))
            painter.drawRoundedRect(rect, 10, 10)
            painter.setPen(QColor(theme.COLOR_TEXT_MUTED))
            font = QFont(painter.font())
            font.setPointSizeF(9.5)
            painter.setFont(font)
            painter.drawText(
                rect,
                int(Qt.AlignmentFlag.AlignCenter),
                "▶ 视频，载入封面…" if item.kind is MediaKind.VIDEO else "载入中…",
            )
            return
        pixmap = QPixmap.fromImage(image).scaled(
            rect.size(),
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        )
        target = QRect(
            rect.left() + (rect.width() - pixmap.width()) // 2,
            rect.top() + (rect.height() - pixmap.height()) // 2,
            pixmap.width(),
            pixmap.height(),
        )
        painter.save()
        painter.setClipPath(rounded_rect_path(target, 8))
        painter.drawPixmap(target, pixmap)
        painter.restore()
        if item.kind is MediaKind.VIDEO:
            painter.setPen(QColor("#ffffff"))
            badge = QFont(painter.font())
            badge.setPointSizeF(10)
            painter.setFont(badge)
            painter.drawText(
                target.adjusted(8, 0, -8, -8),
                int(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignBottom),
                "▶",
            )


class TimelineListView(QListView):
    """滚轮一格走一张、拖动后自动吸附到整张照片的列表。"""

    scrub_requested = Signal(int)  # 目标行号

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        # 拖动/惯性结束后吸附到最近的照片顶部，避免停在"半截"位置
        self._snap_timer = QTimer(self)
        self._snap_timer.setSingleShot(True)
        self._snap_timer.setInterval(70)
        self._snap_timer.timeout.connect(self._snap_to_row)
        self.verticalScrollBar().valueChanged.connect(lambda _v: self._snap_timer.start())
        self.verticalScrollBar().sliderReleased.connect(self._snap_to_row)
        self._suppress_snap = False
        self._expanded_row = 0
        self._hold = QTimer(self)
        self._hold.setSingleShot(True)
        self._hold.setInterval(SCRUB_HOLD_MS)
        self._hold.timeout.connect(self._begin_scrub)
        self._scrubbing = False
        self._press_y = 0
        self._scrub_origin_row = 0
        self._day_rows: list[tuple[str, int]] = []

    expand_requested = Signal(int)

    def set_day_rows(self, rows: list[tuple[str, int]]) -> None:
        self._day_rows = rows

    def set_expanded_row(self, row: int) -> None:
        """记录当前展开行，供滚轮计算基准。"""
        self._expanded_row = max(0, row)

    def begin_programmatic_scroll(self) -> None:
        """程序化滚动开始：暂时屏蔽吸附，避免把展开项又弹回顶部那行。"""
        self._suppress_snap = True

    def end_programmatic_scroll(self) -> None:
        """程序化滚动结束（留足时间让滚动条稳定）。"""
        self._suppress_snap = False

    def _snap_to_row(self) -> None:
        """滚动停止后，把最靠上的一行设为展开项。"""
        if self._suppress_snap:
            return
        index = self.indexAt(QPoint(2, 2))
        if index.isValid():
            self.expand_requested.emit(index.row())

    def wheelEvent(self, event: object) -> None:
        """滚轮一格 = 一张照片，整节对齐，不停在半截。"""
        delta = getattr(event, "angleDelta", lambda: None)()
        if delta is None or delta.y() == 0:
            super().wheelEvent(event)  # type: ignore[arg-type]
            return
        if self._scrubbing:
            event.accept()  # type: ignore[attr-defined]
            return
        direction = -1 if delta.y() > 0 else 1
        target = max(0, min(self.model().rowCount() - 1, self._expanded_row + direction))
        self.expand_requested.emit(target)
        event.accept()  # type: ignore[attr-defined]

    def mousePressEvent(self, event: object) -> None:
        if getattr(event, "button", lambda: None)() == Qt.MouseButton.LeftButton:
            self._press_y = getattr(event, "pos", lambda: QPoint())().y()
            self._hold.start()
        super().mousePressEvent(event)  # type: ignore[arg-type]

    def mouseMoveEvent(self, event: object) -> None:
        if self._scrubbing:
            self._update_scrub(getattr(event, "pos", lambda: QPoint())().y())
            event.accept()  # type: ignore[attr-defined]
            return
        super().mouseMoveEvent(event)  # type: ignore[arg-type]

    def mouseReleaseEvent(self, event: object) -> None:
        self._hold.stop()
        was_scrubbing = self._scrubbing
        self._scrubbing = False
        super().mouseReleaseEvent(event)  # type: ignore[arg-type]
        if not was_scrubbing:
            position = getattr(event, "pos", lambda: QPoint())()
            index = self.indexAt(position)
            if index.isValid():
                self.expand_requested.emit(index.row())

    def _begin_scrub(self) -> None:
        if not self._day_rows:
            return
        index = self.indexAt(self.mapFromGlobal(self.cursor().pos()))
        row = index.row() if index.isValid() else 0
        # 找到当前行所属的日期序号
        self._scrub_origin_row = 0
        for position, (_, day_row) in enumerate(self._day_rows):
            if day_row <= row:
                self._scrub_origin_row = position
            else:
                break
        self._scrubbing = True
        self.setCursor(Qt.CursorShape.SizeVerCursor)

    def _update_scrub(self, y: int) -> None:
        if not self._day_rows:
            return
        delta_steps = int((self._press_y - y) / SCRUB_STEP_PX)
        target = max(0, min(len(self._day_rows) - 1, self._scrub_origin_row + delta_steps))
        row = self._day_rows[target][1]
        self.scrub_requested.emit(row)


class TimelineView(QWidget):
    """独立的时间线模式。"""

    open_requested = Signal(int)
    preview_requested = Signal(int)
    favorite_requested = Signal(int)
    reveal_requested = Signal(int)
    close_requested = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._thumbs = ThumbnailCache(self)
        self._model = TimelineModel(self)
        self._delegate = TimelineDelegate(self._thumbs, self)
        self._list = TimelineListView(self)
        self._list.setModel(self._model)
        self._list.setItemDelegate(self._delegate)
        # 按整项滚动，永远停在一张照片的边界上，不会"松"到半截
        self._list.setVerticalScrollMode(QListView.ScrollMode.ScrollPerItem)
        self._list.setSelectionMode(QListView.SelectionMode.SingleSelection)
        self._list.setEditTriggers(QListView.EditTrigger.NoEditTriggers)
        self._list.setMouseTracking(True)
        self._list.setUniformItemSizes(False)
        self._list.setSpacing(0)
        self._list.setStyleSheet(f"background-color: {theme.COLOR_CANVAS};")
        self._list.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)

        self._list.activated.connect(self._on_open)
        self._list.doubleClicked.connect(self._on_preview)
        self._list.customContextMenuRequested.connect(self._on_menu)
        self._list.scrub_requested.connect(self._jump_row)
        self._list.expand_requested.connect(self._set_current)
        self._thumbs.updated.connect(self._list.viewport().update)
        self._list.viewport().installEventFilter(self)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.addWidget(self._build_header())
        layout.addWidget(self._list, 1)

    # ------------------------------------------------------------------ 头部
    def _build_header(self) -> QWidget:
        header = QWidget(self)
        header.setStyleSheet(
            f"background-color: {theme.COLOR_PANEL}; border-bottom: 1px solid {theme.COLOR_BORDER};"
        )
        row = QHBoxLayout(header)
        row.setContentsMargins(10, 8, 10, 8)
        row.setSpacing(8)

        back = QPushButton("← 返回浏览", header)
        back.clicked.connect(self.close_requested.emit)
        row.addWidget(back)

        self._prev_day = QPushButton("上一天", header)
        self._prev_day.clicked.connect(lambda: self._step_day(-1))
        row.addWidget(self._prev_day)

        self._day_combo = QComboBox(header)
        self._day_combo.setMinimumWidth(220)
        self._day_combo.currentIndexChanged.connect(self._on_day_selected)
        row.addWidget(self._day_combo, 0)

        self._next_day = QPushButton("下一天", header)
        self._next_day.clicked.connect(lambda: self._step_day(1))
        row.addWidget(self._next_day)

        self._calendar_button = QPushButton("选日期", header)
        self._calendar_button.clicked.connect(self._show_calendar)
        row.addWidget(self._calendar_button)

        row.addStretch(1)

        row.addWidget(QLabel("缩放", header))
        self._zoom = QSlider(Qt.Orientation.Horizontal, header)
        self._zoom.setRange(15, 240)
        self._zoom.setValue(130)
        self._zoom.setFixedWidth(140)
        self._zoom.valueChanged.connect(self._on_zoom)
        row.addWidget(self._zoom)

        self._count_label = QLabel("", header)
        self._count_label.setStyleSheet(f"color: {theme.COLOR_TEXT_MUTED};")
        row.addWidget(self._count_label)
        return header

    def eventFilter(self, obj: object, event: object) -> bool:
        if (
            obj is self._list.viewport()
            and getattr(event, "type", lambda: None)() == event.Type.Resize
        ):  # type: ignore[attr-defined]
            self._delegate.set_view_size(
                self._list.viewport().width(), self._list.viewport().height()
            )
            self._list.doItemsLayout()
        return super().eventFilter(obj, event)  # type: ignore[arg-type]

    # ------------------------------------------------------------------ 数据
    def set_items(self, items: list[MediaItem]) -> None:
        """装载数据并展开第一项。"""
        self._delegate.set_view_size(self._list.viewport().width(), self._list.viewport().height())
        self._model.set_items(items)
        self._refresh_days()
        self._delegate.set_current_row(0)
        self._list.set_expanded_row(0)
        self._list.doItemsLayout()
        self._list.scrollToTop()
        self._count_label.setText(f"{len(items)} 条")

    def set_current(self, row: int) -> None:
        self._set_current(row)

    def _set_current(self, row: int) -> None:
        """切换展开项：重排行高并把它滚到顶部。"""
        if not (0 <= row < self._model.rowCount()):
            return
        self._list.begin_programmatic_scroll()
        self._delegate.set_current_row(row)
        self._list.set_expanded_row(row)
        self._list.doItemsLayout()
        index = self._model.index(row, 0)
        self._list.setCurrentIndex(index)
        self._list.scrollTo(index, QListView.ScrollHint.PositionAtCenter)
        QTimer.singleShot(320, self._list.end_programmatic_scroll)

    def shutdown(self) -> None:
        self._thumbs.shutdown()

    # ------------------------------------------------------------------ 内部
    def _refresh_days(self) -> None:
        days = self._model.day_rows()
        self._list.set_day_rows(days)
        self._day_combo.blockSignals(True)
        self._day_combo.clear()
        for day, row in days:
            self._day_combo.addItem(f"{day}", row)
        self._day_combo.blockSignals(False)
        enabled = bool(days)
        self._prev_day.setEnabled(enabled)
        self._next_day.setEnabled(enabled)
        self._day_combo.setEnabled(enabled)

    def _current_day_index(self) -> int:
        index = self._list.indexAt(self._list.viewport().rect().center())
        row = index.row() if index.isValid() else 0
        result = 0
        for position, (_, day_row) in enumerate(self._model.day_rows()):
            if day_row <= row:
                result = position
            else:
                break
        return result

    def _step_day(self, delta: int) -> None:
        days = self._model.day_rows()
        if not days:
            return
        target = max(0, min(len(days) - 1, self._current_day_index() + delta))
        self._jump_row(days[target][1])
        self._day_combo.blockSignals(True)
        self._day_combo.setCurrentIndex(target)
        self._day_combo.blockSignals(False)

    def _on_day_selected(self, index: int) -> None:
        row = self._day_combo.itemData(index)
        if isinstance(row, int):
            self._jump_row(row)

    def _jump_row(self, row: int) -> None:
        if 0 <= row < self._model.rowCount():
            index = self._model.index(row, 0)
            self._list.scrollTo(index, QListView.ScrollHint.PositionAtTop)
            self._list.setCurrentIndex(index)

    def _show_calendar(self) -> None:
        """弹出日历对话框选日期（独立窗口，不会被主界面遮挡）。"""
        dialog = QDialog(self)
        dialog.setWindowTitle("选择日期")
        dialog.setModal(True)
        dialog.resize(380, 320)
        layout = QVBoxLayout(dialog)
        layout.setContentsMargins(8, 8, 8, 8)
        calendar = QCalendarWidget(dialog)
        calendar.setGridVisible(True)
        calendar.setVerticalHeaderFormat(QCalendarWidget.VerticalHeaderFormat.NoVerticalHeader)
        # 周末不再用默认的红色；有照片的日期用强调色标出来
        normal = QTextCharFormat()
        normal.setForeground(QColor(theme.COLOR_TEXT))
        weekend_off = QTextCharFormat()
        weekend_off.setForeground(QColor(theme.COLOR_TEXT_MUTED))
        for weekday in (
            Qt.DayOfWeek.Saturday,
            Qt.DayOfWeek.Sunday,
        ):
            calendar.setWeekdayTextFormat(weekday, weekend_off)
        photo_days: set[QDate] = set()
        for day_text, _row in self._model.day_rows():
            if len(day_text) >= 10:
                parsed = QDate.fromString(day_text[:10], "yyyy-MM-dd")
                if parsed.isValid():
                    photo_days.add(parsed)
        highlight = QTextCharFormat()
        highlight.setForeground(QColor(theme.COLOR_ACCENT))
        highlight.setFontWeight(75)
        highlight.setBackground(QColor(theme.COLOR_ACCENT_SOFT))
        for day in photo_days:
            calendar.setDateTextFormat(day, highlight)
        calendar.setCurrentPage(
            next(iter(sorted(photo_days))).year() if photo_days else QDate.currentDate().year(),
            next(iter(sorted(photo_days))).month() if photo_days else QDate.currentDate().month(),
        )
        layout.addWidget(calendar, 1)

        def on_clicked(date: QDate) -> None:
            text = date.toString("yyyy-MM-dd")
            for row, (day, row_index) in enumerate(self._model.day_rows()):
                if day.startswith(text):
                    self._jump_row(row_index)
                    self._day_combo.setCurrentIndex(row)
                    break
            dialog.accept()

        calendar.clicked.connect(on_clicked)
        dialog.exec()

    def _on_zoom(self, value: int) -> None:
        self._delegate.set_scale(value / 100.0)
        self._delegate.set_view_size(self._list.viewport().width(), self._list.viewport().height())
        self._list.doItemsLayout()

    def _on_open(self, index: QModelIndex) -> None:
        if index.isValid():
            self.open_requested.emit(index.row())

    def _on_preview(self, index: QModelIndex) -> None:
        if index.isValid():
            self.preview_requested.emit(index.row())

    def _on_menu(self, position: QPoint) -> None:
        index = self._list.indexAt(position)
        if not index.isValid():
            return
        row = index.row()
        item = self._model.item_at(row)
        if item is None:
            return
        menu = QMenu(self)
        menu.addAction("预览", lambda: self.preview_requested.emit(row))
        if item.has_video:
            menu.addAction("播放实况", lambda: self.open_requested.emit(row))
        menu.addSeparator()
        menu.addAction(
            "取消收藏" if item.favorite else "收藏",
            lambda: self.favorite_requested.emit(row),
        )
        menu.addAction("在文件夹中显示", lambda: self.reveal_requested.emit(row))
        menu.exec(self._list.viewport().mapToGlobal(position))


__all__ = ["TimelineDelegate", "TimelineListView", "TimelineModel", "TimelineView"]
