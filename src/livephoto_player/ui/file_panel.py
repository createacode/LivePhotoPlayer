"""文件列表面板：搜索框 + 排序切换 + 时间线渲染。

列表数据统一用 ``MediaItem``，时间/地点来自结构化目录（未索引时退化为文件名）。
切换排序或搜索只重置模型数据，不重建控件，保持滚动与焦点行为稳定。
"""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import (
    QAbstractListModel,
    QModelIndex,
    QPersistentModelIndex,
    Qt,
    QTimer,
    Signal,
)
from PySide6.QtWidgets import (
    QButtonGroup,
    QHBoxLayout,
    QLineEdit,
    QListView,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from livephoto_player.core.format import format_size
from livephoto_player.core.models import MediaItem
from livephoto_player.ui.timeline import (
    MODE_NAME,
    MODE_TIMELINE,
    ROLE_DAY,
    ROLE_FAVORITE,
    ROLE_ITEM,
    ROLE_PLACE,
    ROLE_TIME,
    TimelineDelegate,
)

SEARCH_DELAY_MS = 260


class MediaListModel(QAbstractListModel):
    """只为行提供数据，不创建任何控件。"""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._items: list[MediaItem] = []

    def set_items(self, items: list[MediaItem]) -> None:
        """整体替换数据。"""
        self.beginResetModel()
        self._items = list(items)
        self.endResetModel()

    def item_at(self, row: int) -> MediaItem | None:
        """按行取条目。"""
        if 0 <= row < len(self._items):
            return self._items[row]
        return None

    def row_of(self, path: Path) -> int:
        """按路径找行号。"""
        for row, item in enumerate(self._items):
            if item.path == path:
                return row
        return -1

    def items(self) -> list[MediaItem]:
        """当前全部条目。"""
        return list(self._items)

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
        if role == int(Qt.ItemDataRole.DisplayRole):
            return f"📁 {item.name}" if item.is_folder else item.name
        if role == ROLE_ITEM:
            return item
        if role == ROLE_DAY:
            return "" if item.is_folder else item.day_text
        if role == ROLE_TIME:
            return "" if item.is_folder else item.time_text
        if role == ROLE_PLACE:
            return item.place_text
        if role == ROLE_FAVORITE:
            return item.favorite
        if role == int(Qt.ItemDataRole.ToolTipRole):
            parts = [item.name, item.kind.label, format_size(item.size_bytes)]
            if item.pixel_width:
                parts.append(f"{item.pixel_width}×{item.pixel_height}")
            if item.day_text:
                parts.append(f"{item.day_text} {item.time_text}")
            if item.place_text:
                parts.append(item.place_text)
            if item.camera:
                parts.append(item.camera)
            parts.append(str(item.path))
            return " · ".join(parts)
        return None


class FilePanel(QWidget):
    """左侧文件列表：搜索、排序、时间线。"""

    item_selected = Signal(int)
    search_changed = Signal(str)
    order_changed = Signal(str)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._model = MediaListModel(self)
        self._delegate = TimelineDelegate(MODE_NAME, self)
        self._delegate.set_day_headers(True)

        self._search = QLineEdit(self)
        self._search.setPlaceholderText("搜索 文件名 / 地点 / 日期")
        self._search.setClearButtonEnabled(True)
        self._search.setMinimumHeight(28)

        # 左右两个标签，替代原来的下拉框：一眼可见、一次点中
        self._order_group = QButtonGroup(self)
        self._order_group.setExclusive(True)
        self._order_buttons: list[QPushButton] = []
        for index, (label, mode) in enumerate(
            (("默认排序", MODE_NAME), ("拍摄时间", MODE_TIMELINE))
        ):
            button = QPushButton(label, self)
            button.setCheckable(True)
            button.setMinimumHeight(26)
            button.setCursor(Qt.CursorShape.PointingHandCursor)
            button.setProperty("orderMode", mode)
            button.setStyleSheet("QPushButton { border-radius: 6px; padding: 3px 10px; }")
            self._order_group.addButton(button, index)
            self._order_buttons.append(button)
            if mode == MODE_TIMELINE:
                button.setChecked(True)

        header = QWidget(self)
        header_layout = QVBoxLayout(header)
        header_layout.setContentsMargins(6, 6, 6, 4)
        header_layout.setSpacing(4)
        header_layout.addWidget(self._search)
        order_row = QHBoxLayout()
        order_row.setContentsMargins(0, 0, 0, 0)
        order_row.setSpacing(6)
        for button in self._order_buttons:
            order_row.addWidget(button, 1)
        header_layout.addLayout(order_row)

        self._view = QListView(self)
        self._view.setModel(self._model)
        self._view.setItemDelegate(self._delegate)
        self._view.setUniformItemSizes(False)
        self._view.setVerticalScrollMode(QListView.ScrollMode.ScrollPerPixel)
        # 选中底色由委托只画在照片行上，避免连日期标题一起变蓝
        self._view.setStyleSheet(
            "QListView { background-color: transparent; }"
            "QListView::item:selected { background: transparent; }"
        )
        self._view.setSelectionMode(QListView.SelectionMode.SingleSelection)
        self._view.setEditTriggers(QListView.EditTrigger.NoEditTriggers)
        self._view.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self._view.setMouseTracking(True)
        self._view.setSpacing(0)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.addWidget(header)
        layout.addWidget(self._view, 1)

        self.setMinimumWidth(240)
        self.setMaximumWidth(380)

        self._syncing = False
        self._search_timer = QTimer(self)
        self._search_timer.setSingleShot(True)
        self._search_timer.setInterval(SEARCH_DELAY_MS)
        self._search_timer.timeout.connect(self._emit_search)

        self._search.textChanged.connect(lambda _text: self._search_timer.start())
        self._order_group.idClicked.connect(self._on_order_clicked)
        self._view.selectionModel().currentChanged.connect(self._on_current_changed)

    # ------------------------------------------------------------------ 对外接口
    def set_items(self, items: list[MediaItem]) -> None:
        """替换列表数据。"""
        self._model.set_items(items)
        self._view.doItemsLayout()

    def items(self) -> list[MediaItem]:
        """当前列表数据。"""
        return self._model.items()

    def set_current(self, row: int) -> None:
        """选中并滚动到指定行，不反向触发 ``item_selected``。"""
        if row < 0 or row >= self._model.rowCount():
            self._view.clearSelection()
            self._view.setCurrentIndex(QModelIndex())
            return
        index = self._model.index(row, 0)
        self._syncing = True
        try:
            self._view.setCurrentIndex(index)
            self._view.selectionModel().select(
                index, self._view.selectionModel().SelectionFlag.ClearAndSelect
            )
            self._view.scrollTo(index, QListView.ScrollHint.EnsureVisible)
        finally:
            self._syncing = False

    def refresh_row(self, row: int) -> None:
        """通知某行数据已变化。"""
        if 0 <= row < self._model.rowCount():
            index = self._model.index(row, 0)
            self._model.dataChanged.emit(index, index)

    def refresh_all(self) -> None:
        """整表重绘（时间/地点批量补齐后调用）。"""
        self._model.layoutChanged.emit()
        self._view.doItemsLayout()

    def current_row(self) -> int:
        """当前选中行。"""
        return self._view.currentIndex().row()

    def order(self) -> str:
        """当前排序模式。"""
        for button in self._order_buttons:
            if button.isChecked():
                return str(button.property("orderMode"))
        return MODE_TIMELINE

    def set_order(self, mode: str) -> None:
        """设置排序模式但不触发回发信号。"""
        for button in self._order_buttons:
            checked = button.property("orderMode") == mode
            button.blockSignals(True)
            button.setChecked(checked)
            button.blockSignals(False)

    def search_text(self) -> str:
        """当前搜索词。"""
        return self._search.text().strip()

    def set_search_text(self, text: str) -> None:
        """程序化设置搜索词。"""
        self._search.setText(text)

    # ------------------------------------------------------------------ 内部实现
    def _emit_search(self) -> None:
        self.search_changed.emit(self._search.text().strip())

    def _on_order_clicked(self, _index: int) -> None:
        mode = self.order()
        self._delegate.set_day_headers(mode == MODE_TIMELINE)
        self._view.doItemsLayout()
        self.order_changed.emit(mode)

    def _on_current_changed(self, current: QModelIndex, _previous: QModelIndex) -> None:
        if self._syncing or not current.isValid():
            return
        self.item_selected.emit(current.row())
