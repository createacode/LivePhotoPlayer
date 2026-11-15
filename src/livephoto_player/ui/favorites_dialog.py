"""收藏夹：两个标签页分别按"收藏时间"和"拍摄时间"排成时间线。"""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt, QUrl, Signal
from PySide6.QtGui import QDesktopServices, QKeyEvent
from PySide6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListView,
    QPushButton,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from livephoto_player.core.format import format_datetime
from livephoto_player.core.models import FavoriteRecord, MediaItem, MediaKind
from livephoto_player.services.catalog import Catalog
from livephoto_player.ui.timeline import MODE_TIMELINE, TimelineDelegate
from livephoto_player.utils.paths import favorite_dir


class _EntryList(QWidget):
    """一个带搜索的时间线列表。"""

    activated = Signal(object)

    def __init__(self, mode_hint: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        from livephoto_player.ui.file_panel import MediaListModel

        self._mode_hint = mode_hint
        self._all: list[MediaItem] = []
        self._model = MediaListModel(self)
        self._view = QListView(self)
        self._view.setModel(self._model)
        self._view.setItemDelegate(TimelineDelegate(MODE_TIMELINE, self))
        self._view.setVerticalScrollMode(QListView.ScrollMode.ScrollPerPixel)
        self._view.setSelectionMode(QListView.SelectionMode.SingleSelection)
        self._view.setEditTriggers(QListView.EditTrigger.NoEditTriggers)
        self._view.setMouseTracking(True)
        self._view.activated.connect(self._on_activated)

        self._search = QLineEdit(self)
        self._search.setPlaceholderText("在收藏中搜索 文件名 / 地点 / 日期")
        self._search.setClearButtonEnabled(True)
        self._search.textChanged.connect(self._apply_filter)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(6)
        layout.addWidget(self._search)
        layout.addWidget(self._view, 1)

    def set_items(self, items: list[MediaItem]) -> None:
        """设置全部条目（搜索在其上过滤）。"""
        self._all = list(items)
        self._apply_filter(self._search.text())

    def _apply_filter(self, text: str) -> None:
        query = text.strip().lower()
        if not query:
            filtered = list(self._all)
        else:
            filtered = [
                item
                for item in self._all
                if query in item.name.lower()
                or query in item.place_text.lower()
                or query in item.day_text.lower()
                or query in item.time_text.lower()
            ]
        self._model.set_items(filtered)
        self._view.doItemsLayout()

    def _on_activated(self, index: object) -> None:
        row = getattr(index, "row", lambda: -1)()
        item = self._model.item_at(row)
        if item is not None:
            self.activated.emit(item.path)


class FavoritesDialog(QDialog):
    """收藏夹窗口：两个时间线标签页。"""

    open_requested = Signal(object)

    def __init__(self, catalog: Catalog, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._catalog = catalog
        self.setWindowTitle("收藏夹")
        self.resize(460, 620)
        self.setModal(False)

        self._tabs = QTabWidget(self)
        self._favorited_tab = _EntryList("favorited", self)
        self._taken_tab = _EntryList("taken", self)
        self._tabs.addTab(self._favorited_tab, "收藏时间线")
        self._tabs.addTab(self._taken_tab, "拍摄时间线")

        hint = QLabel("双击条目可在主界面打开；收藏副本保存在:")
        hint.setStyleSheet("color: #98a2b1;")
        self._path_label = QLabel(str(favorite_dir()))
        self._path_label.setStyleSheet("color: #98a2b1;")

        self._open_dir_button = QPushButton("打开收藏文件夹")
        self._open_dir_button.clicked.connect(self._open_folder)

        bottom = QHBoxLayout()
        bottom.setContentsMargins(0, 0, 0, 0)
        bottom.addWidget(hint)
        bottom.addStretch(1)
        bottom.addWidget(self._open_dir_button)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(8)
        layout.addWidget(self._tabs, 1)
        layout.addWidget(self._path_label)
        layout.addLayout(bottom)

        self._favorited_tab.activated.connect(self._on_open)
        self._taken_tab.activated.connect(self._on_open)
        self.refresh()

    # ------------------------------------------------------------------ 对外接口
    def refresh(self) -> None:
        """重新从索引库读取收藏并刷新两个标签页。"""
        favorited = self._catalog.list_favorites("favorited")
        taken = self._catalog.list_favorites("taken")
        self._favorited_tab.set_items(
            [_to_item(record, prefer_favorited_time=True) for record in favorited]
        )
        self._taken_tab.set_items(
            [_to_item(record, prefer_favorited_time=False) for record in taken]
        )
        self._tabs.setTabText(0, f"收藏时间线 ({len(favorited)})")
        self._tabs.setTabText(1, f"拍摄时间线 ({len(taken)})")
        self._path_label.setText(
            f"{favorite_dir()}    最近收藏："
            f"{format_datetime(favorited[0].favorited_ts) if favorited else '暂无'}"
        )

    def keyPressEvent(self, event: QKeyEvent) -> None:
        if event.key() == Qt.Key.Key_Escape:
            self.close()
            return
        super().keyPressEvent(event)

    # ------------------------------------------------------------------ 内部实现
    def _on_open(self, path: object) -> None:
        self.open_requested.emit(Path(str(path)))

    def _open_folder(self) -> None:
        directory = favorite_dir()
        directory.mkdir(parents=True, exist_ok=True)
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(directory)))


def _to_item(record: FavoriteRecord, *, prefer_favorited_time: bool) -> MediaItem:
    """把收藏记录转成列表项；决定时间线按哪个时间分组。"""
    photo = record.photo
    kind = MediaKind.VIDEO if record.path.suffix.lower() in {".mp4", ".mov"} else MediaKind.PHOTO
    item = MediaItem(
        path=record.path,
        kind=kind,
        size_bytes=photo.size_bytes if photo else 0,
        taken_ts=photo.taken_ts if photo else 0,
        latitude=photo.latitude if photo else None,
        longitude=photo.longitude if photo else None,
        place=photo.place if photo else "",
        camera=photo.camera if photo else "",
        favorite=True,
        pixel_width=photo.width if photo else 0,
        pixel_height=photo.height if photo else 0,
    )
    item.timeline_ts = (
        record.favorited_ts if prefer_favorited_time else (photo.sort_ts if photo else 0)
    )
    return item


__all__ = ["FavoritesDialog", "_to_item"]
