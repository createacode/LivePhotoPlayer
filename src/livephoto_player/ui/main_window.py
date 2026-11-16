"""主窗口：装配各部件、串联状态机、持久化与托盘。"""

from __future__ import annotations

import contextlib
import subprocess
from datetime import datetime
from pathlib import Path

from PySide6.QtCore import QPoint, QSize, Qt, QThread, QTimer, QUrl
from PySide6.QtGui import (
    QAction,
    QActionGroup,
    QCloseEvent,
    QCursor,
    QDesktopServices,
    QGuiApplication,
    QIcon,
    QImage,
    QKeyEvent,
    QPixmap,
)
from PySide6.QtWidgets import (
    QApplication,
    QComboBox,
    QDialog,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QMenu,
    QProgressBar,
    QPushButton,
    QSizePolicy,
    QSplitter,
    QStackedWidget,
    QStyle,
    QSystemTrayIcon,
    QToolBar,
    QToolButton,
    QWidget,
)

from livephoto_player.core.enhance import QUALITY_LABELS
from livephoto_player.core.format import UNKNOWN_PLACE, format_short_day, format_size
from livephoto_player.core.models import (
    MediaItem,
    MediaKind,
    PhotoRecord,
    PlaybackState,
)
from livephoto_player.core.version import __software_name__, window_title
from livephoto_player.services.browser import (
    DirectoryBrowser,
    file_kind,
    is_supported,
    natural_key,
)
from livephoto_player.services.catalog import Catalog
from livephoto_player.services.exporter import export_photo, export_video
from livephoto_player.services.favorites import FavoritesService
from livephoto_player.services.image_loader import ImageLoader
from livephoto_player.services.indexer import IndexWorker
from livephoto_player.services.media_engine import MediaEngine
from livephoto_player.services.place_resolver import PlaceResolver
from livephoto_player.services.poster import PosterGrabber
from livephoto_player.services.workers import TaskRunner
from livephoto_player.ui import theme
from livephoto_player.ui.about_dialog import AboutDialog
from livephoto_player.ui.favorites_dialog import FavoritesDialog
from livephoto_player.ui.file_panel import FilePanel
from livephoto_player.ui.geo_dialog import GeoDialog
from livephoto_player.ui.icons import star_icon
from livephoto_player.ui.image_canvas import ImageCanvas
from livephoto_player.ui.preview_window import PreviewWindow
from livephoto_player.ui.timeline import MODE_NAME, MODE_TIMELINE
from livephoto_player.ui.timeline_view import TimelineView
from livephoto_player.ui.toast import Toast
from livephoto_player.ui.update_dialog import UpdateDialog
from livephoto_player.ui.video_surface import VideoSurface
from livephoto_player.ui.widgets import ElidedLabel
from livephoto_player.update.gitee import fetch_latest, is_newer, should_check_now
from livephoto_player.utils.config import AppConfig, ConfigStore
from livephoto_player.utils.logger import get_logger
from livephoto_player.utils.paths import (
    catalog_path,
    export_dir,
    favorite_dir,
    project_root,
    resource_path,
)

SPEEDS: tuple[float, ...] = (0.25, 0.5, 0.75, 1.0, 1.25, 1.5, 2.0)
GEOMETRY_SAVE_DELAY_MS = 500
PREVIEW_SUPERSAMPLE = 1.3


class MainWindow(QMainWindow):
    """应用主窗口。"""

    def __init__(
        self,
        store: ConfigStore,
        config: AppConfig,
        startup_path: str | None = None,
        start_timeline: bool = False,
    ) -> None:
        super().__init__()
        self._store = store
        self._config = config
        self._logger = get_logger("window")
        self._browser = DirectoryBrowser()
        self._session_directory: Path | None = None
        self._items: list[MediaItem] = []
        self._index = -1
        self._generation = 0
        self._engine_path: Path | None = None
        self._full_requested: Path | None = None
        self._quitting = False
        self._restoring = True
        self._startup_path = startup_path
        self._pending_timeline = start_timeline
        self._cover_pixmap: QPixmap | None = None
        self._tray: QSystemTrayIcon | None = None
        self._search_query = ""
        self._order_mode = config.order_mode
        self._favorites_dialog: FavoritesDialog | None = None
        self._catalog = Catalog(catalog_path())
        self._favorites = FavoritesService(self._catalog, favorite_dir())
        self._indexer = IndexWorker(catalog_path())
        self._resolver = PlaceResolver(catalog_path())
        self._place_timer = QTimer(self)
        self._place_timer.setSingleShot(True)
        self._place_timer.setInterval(700)
        self._place_timer.timeout.connect(self._refresh_places)

        self._save_timer = QTimer(self)
        self._save_timer.setSingleShot(True)
        self._save_timer.setInterval(GEOMETRY_SAVE_DELAY_MS)
        self._save_timer.timeout.connect(self._persist)

        self._loader = ImageLoader(self)
        self._engine = MediaEngine(self)
        self._poster = PosterGrabber(self)
        self._runner = TaskRunner(self)

        self._build_ui()
        self._build_actions()
        self._build_toolbar()
        self._build_statusbar()
        self._connect_services()
        self._build_tray()
        self._restore_geometry()
        self._apply_config()
        self._restoring = False
        self._update_favorite_action()
        self.setWindowTitle(window_title())
        self._indexer.start(QThread.Priority.LowPriority)
        self._apply_geo_config()
        self._resolver.start(QThread.Priority.LowPriority)

    # ------------------------------------------------------------------ 构建界面
    def _build_ui(self) -> None:
        self.setMinimumSize(720, 520)
        self.setWindowIcon(self._load_icon())
        self.setStyleSheet(theme.STYLE_SHEET)

        self._canvas = ImageCanvas(self)
        self._canvas.set_quality(self._config.quality)
        self._canvas.set_status_text("拖入照片 / 视频，或点击「打开文件」")
        self._surface = VideoSurface(self)
        self._engine.attach_video_output(self._surface.video_widget())
        self._cover_loaded = False

        self._timeline = TimelineView(self)
        self._timeline_active = False
        self._preview: PreviewWindow | None = None
        self._stack = QStackedWidget(self)
        self._stack.addWidget(self._canvas)
        self._stack.addWidget(self._surface)
        self._stack.addWidget(self._timeline)

        self._file_panel = FilePanel(self)
        self._file_panel.setMinimumWidth(260)

        self._splitter = QSplitter(Qt.Orientation.Horizontal, self)
        self._splitter.addWidget(self._file_panel)
        self._splitter.addWidget(self._stack)
        self._splitter.setStretchFactor(0, 0)
        self._splitter.setStretchFactor(1, 1)
        self._splitter.setSizes([268, 812])
        self._splitter.setChildrenCollapsible(False)
        self.setCentralWidget(self._splitter)

        self.setAcceptDrops(True)
        self._toast = Toast(self)

    def _load_icon(self) -> QIcon:
        path = resource_path("app.ico")
        if path.exists():
            return QIcon(str(path))
        self._logger.warning("未找到应用图标：%s", path)
        return QIcon()

    def _ensure_cover(self) -> QPixmap | None:
        """首次需要封面时才解码（3.5MB PNG 解码约占 70ms，不能放在启动路径上）。"""
        if self._cover_loaded:
            return self._cover_pixmap
        self._cover_loaded = True
        path = resource_path("cover/video.png")
        if not path.exists():
            self._logger.warning("未找到视频封面：%s", path)
            return None
        pixmap = QPixmap(str(path))
        if pixmap.isNull():
            self._logger.warning("视频封面解码失败：%s", path)
            return None
        self._cover_pixmap = pixmap
        self._surface.set_cover_pixmap(pixmap)
        return pixmap

    def _build_actions(self) -> None:
        style = self.style()
        self._action_open = QAction(
            style.standardIcon(QStyle.StandardPixmap.SP_DirOpenIcon), "打开文件", self
        )
        self._action_open.setShortcut("Ctrl+O")
        self._action_open.triggered.connect(self._open_dialog)

        self._action_list = QAction(
            style.standardIcon(QStyle.StandardPixmap.SP_FileDialogDetailedView), "文件列表", self
        )
        self._action_list.setCheckable(True)
        self._action_list.setShortcut("Ctrl+L")
        self._action_list.triggered.connect(self._toggle_file_panel)

        self._action_prev = QAction(
            style.standardIcon(QStyle.StandardPixmap.SP_ArrowLeft), "上一张", self
        )
        self._action_prev.triggered.connect(self.previous_item)
        self._action_next = QAction(
            style.standardIcon(QStyle.StandardPixmap.SP_ArrowRight), "下一张", self
        )
        self._action_next.triggered.connect(self.next_item)
        self._action_play = QAction(
            style.standardIcon(QStyle.StandardPixmap.SP_MediaPlay), "播放", self
        )
        self._action_play.triggered.connect(self.toggle_playback)
        self._action_stop = QAction(
            style.standardIcon(QStyle.StandardPixmap.SP_MediaStop), "停止", self
        )
        self._action_stop.triggered.connect(self.stop_playback)

        self._action_favorite = QAction(star_icon(False), "收藏", self)
        self._action_favorite.setCheckable(True)
        self._action_favorite.setShortcut("Ctrl+D")
        self._action_favorite.triggered.connect(self._toggle_favorite)

        self._action_favorites = QAction(
            style.standardIcon(QStyle.StandardPixmap.SP_DirHomeIcon), "收藏夹", self
        )
        self._action_favorites.setShortcut("Ctrl+Shift+D")
        self._action_favorites.triggered.connect(self._show_favorites)

        self._action_fit = QAction("适应窗口", self)
        self._action_fit.setShortcut("Ctrl+0")
        self._action_fit.triggered.connect(self._fit_canvas)
        self._action_actual = QAction("实际大小", self)
        self._action_actual.setShortcut("Ctrl+1")
        self._action_actual.triggered.connect(self._actual_size)

        self._action_export_photo = QAction("导出照片", self)
        self._action_export_photo.triggered.connect(self.export_current_photo)
        self._action_export_video = QAction("导出视频", self)
        self._action_export_video.triggered.connect(self.export_current_video)
        self._action_open_photo = QAction("打开照片文件夹", self)
        self._action_open_photo.triggered.connect(lambda: self._open_export_dir("photo"))
        self._action_open_video = QAction("打开视频文件夹", self)
        self._action_open_video.triggered.connect(lambda: self._open_export_dir("video"))
        self._action_reset = QAction("恢复大小", self)
        self._action_reset.triggered.connect(self._reset_view)
        self._action_initial = QAction("初始状态", self)
        self._action_initial.triggered.connect(self._reset_all)
        self._action_auto_play = QAction("自动播放", self)
        self._action_auto_play.setCheckable(True)
        self._action_auto_play.setChecked(self._config.auto_play)
        self._action_auto_play.triggered.connect(self._toggle_auto_play)
        self._action_timeline = QAction("时间线", self)
        self._action_timeline.setCheckable(True)
        self._action_timeline.setShortcut("Ctrl+T")
        self._action_timeline.triggered.connect(self._toggle_timeline_mode)

        self._action_geo = QAction("地点解析设置", self)
        self._action_geo.triggered.connect(self._show_geo_dialog)

        self._action_update = QAction("检查更新", self)
        self._action_update.triggered.connect(lambda: self.request_update_check(silent=False))
        self._action_about = QAction("关于", self)
        self._action_about.triggered.connect(self._show_about)
        self._action_quit = QAction("退出", self)
        self._action_quit.setShortcut("Ctrl+Q")
        self._action_quit.triggered.connect(self.quit_app)

        for action in (
            self._action_open,
            self._action_list,
            self._action_prev,
            self._action_next,
            self._action_play,
            self._action_stop,
            self._action_timeline,
            self._action_favorite,
            self._action_favorites,
            self._action_fit,
            self._action_actual,
        ):
            action.setShortcutContext(Qt.ShortcutContext.WindowShortcut)

    def _build_toolbar(self) -> None:
        toolbar = QToolBar("主工具栏", self)
        toolbar.setMovable(False)
        toolbar.setFloatable(False)
        toolbar.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        toolbar.setIconSize(QSize(16, 16))
        toolbar.setContextMenuPolicy(Qt.ContextMenuPolicy.PreventContextMenu)
        self.addToolBar(toolbar)
        self._toolbar = toolbar

        for action in (
            self._action_open,
            self._action_list,
        ):
            toolbar.addAction(action)
        toolbar.addSeparator()
        for action in (
            self._action_prev,
            self._action_next,
            self._action_play,
            self._action_stop,
        ):
            toolbar.addAction(action)
        toolbar.addSeparator()
        toolbar.addAction(self._action_timeline)
        toolbar.addAction(self._action_favorite)
        toolbar.addAction(self._action_favorites)
        toolbar.addSeparator()

        self._zoom_label = QLabel("100%")
        self._zoom_label.setMinimumWidth(56)
        self._zoom_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._zoom_label.setStyleSheet(f"color: {theme.COLOR_TEXT_MUTED};")
        toolbar.addWidget(self._zoom_label)

        self._more_button = QToolButton(self)
        self._more_button.setText("更多")
        self._more_button.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        self._more_button.setMenu(self._build_more_menu(self._more_button))
        toolbar.addWidget(self._more_button)

        spacer = QWidget(self)
        spacer.setSizePolicy(
            spacer.sizePolicy().horizontalPolicy().Expanding, spacer.sizePolicy().verticalPolicy()
        )
        toolbar.addWidget(spacer)

        for button in toolbar.findChildren(QToolButton):
            button.setFocusPolicy(Qt.FocusPolicy.NoFocus)

    def _set_quality(self, quality: str) -> None:
        """切换画质档位并持久化。"""
        self._config.quality = quality
        self._canvas.set_quality(quality)
        self._persist()
        self._toast.show_message(f"画质：{QUALITY_LABELS.get(quality, quality)}")

    def _build_more_menu(self, parent: QWidget) -> QMenu:
        menu = QMenu(parent)
        menu.addAction(self._action_timeline)
        menu.addAction(self._action_favorite)
        menu.addAction(self._action_favorites)
        menu.addSeparator()
        menu.addAction(self._action_export_photo)
        menu.addAction(self._action_export_video)
        menu.addSeparator()
        menu.addAction(self._action_open_photo)
        menu.addAction(self._action_open_video)
        menu.addSeparator()
        menu.addAction(self._action_fit)
        menu.addAction(self._action_actual)
        menu.addAction(self._action_reset)
        menu.addAction(self._action_initial)
        menu.addSeparator()
        menu.addAction(self._action_geo)
        menu.addAction(self._action_update)
        menu.addAction(self._action_about)
        menu.addAction(self._action_quit)
        quality_menu = menu.addMenu("画质")
        group = QActionGroup(quality_menu)
        group.setExclusive(True)
        for key, label in QUALITY_LABELS.items():
            action = QAction(label, quality_menu)
            action.setCheckable(True)
            action.setChecked(key == self._config.quality)
            action.triggered.connect(lambda _checked=False, k=key: self._set_quality(k))
            group.addAction(action)
            quality_menu.addAction(action)

        return menu

    def _build_statusbar(self) -> None:
        bar = self.statusBar()
        bar.setSizeGripEnabled(False)

        self._status_label = ElidedLabel("就绪", bar)
        # 固定给"就绪/加载中/搜索…"留出位置，避免被后面的文件名挤没
        # 固定宽度：ElidedLabel 的 size policy 会让布局分配 0 宽，
        # 只设 minimumWidth 时控件被撑开但布局位置不变，会压到后面的文件名上
        self._status_label.setFixedWidth(112)
        self._status_label.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Preferred)
        bar.addWidget(self._status_label, 0)

        self._info_label = ElidedLabel("", bar)
        self._info_label.setMinimumWidth(60)
        self._info_label.setContentsMargins(0, 0, 12, 0)
        bar.addWidget(self._info_label, 1)

        self._place_label = QLabel("", bar)
        self._place_label.setStyleSheet("color: #e8c07d;")
        self._place_label.setContentsMargins(0, 0, 12, 0)
        # 日期/时间/地点是重点信息，给足宽度
        self._place_label.setMinimumWidth(240)
        self._place_label.setMaximumWidth(620)
        bar.addWidget(self._place_label, 0)

        self._size_label = QLabel("", bar)
        self._size_label.setStyleSheet("color: #98a2b1;")
        self._size_label.setMinimumWidth(130)
        bar.addWidget(self._size_label, 0)

        self._speed_label = QLabel("速度", bar)
        self._speed_combo = QComboBox(bar)
        for speed in SPEEDS:
            self._speed_combo.addItem(f"{speed:g}x")
        self._speed_combo.setCurrentIndex(self._config.speed_index)
        self._speed_combo.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self._speed_combo.currentIndexChanged.connect(self._on_speed_changed)

        self._mute_button = QPushButton("有声", bar)
        self._mute_button.setCheckable(True)
        self._mute_button.setChecked(self._config.muted)
        self._mute_button.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self._mute_button.toggled.connect(self._on_mute_toggled)

        self._progress = QProgressBar(bar)
        self._progress.setRange(0, 0)
        self._progress.setFixedWidth(120)
        self._progress.setVisible(False)

        right = QWidget(bar)
        right_layout = QHBoxLayout(right)
        right_layout.setContentsMargins(0, 0, 8, 0)
        right_layout.setSpacing(8)
        right_layout.addWidget(self._progress)
        right_layout.addWidget(self._speed_label)
        right_layout.addWidget(self._speed_combo)
        right_layout.addWidget(self._mute_button)
        bar.addPermanentWidget(right)

    def _connect_services(self) -> None:
        self._canvas.sig_previous.connect(self.previous_item)
        self._canvas.sig_next.connect(self.next_item)
        self._canvas.sig_play.connect(self.toggle_playback)
        self._canvas.sig_open.connect(self._open_dialog)
        self._canvas.zoom_changed.connect(self._on_zoom_changed)
        self._file_panel.item_selected.connect(self._on_list_selected)
        self._surface.clicked.connect(self.toggle_playback)
        self._surface.zone_clicked.connect(self._on_video_zone)
        self._surface.context_menu_requested.connect(self._show_context_menu_at)
        self._loader.loaded.connect(self._on_image_loaded)
        self._engine.state_changed.connect(self._on_engine_state)
        self._engine.error_occurred.connect(self._on_engine_error)
        self._poster.poster_ready.connect(self._on_poster_ready)
        self._file_panel.search_changed.connect(self._on_search_changed)
        self._file_panel.order_changed.connect(self._on_order_changed)
        self._indexer.directory_done.connect(self._on_index_done)
        self._indexer.failed.connect(lambda message: self._logger.warning("索引失败：%s", message))
        self._timeline.open_requested.connect(self._open_from_timeline)
        self._timeline.preview_requested.connect(self._preview_from_timeline)
        self._timeline.favorite_requested.connect(self._favorite_from_timeline)
        self._timeline.reveal_requested.connect(self._reveal_from_timeline)
        self._timeline.close_requested.connect(self._exit_timeline)
        self._resolver.progress.connect(self._on_places_resolved)
        self._resolver.failed.connect(lambda message: self._logger.warning("地名解析：%s", message))

    def _build_tray(self) -> None:
        if not QSystemTrayIcon.isSystemTrayAvailable():
            self._logger.warning("系统托盘不可用，关闭窗口将直接退出")
            self._tray = None
            return
        self._tray = QSystemTrayIcon(self.windowIcon(), self)
        menu = QMenu(self)
        menu.addAction("显示主界面", self.show_window)
        menu.addSeparator()
        menu.addAction(self._action_auto_play)
        menu.addAction(self._action_quit)
        self._tray.setContextMenu(menu)
        self._tray.setToolTip(window_title())
        self._tray.activated.connect(self._on_tray_activated)
        self._tray.show()

    def _apply_config(self) -> None:
        self._order_mode = self._config.order_mode
        self._file_panel.set_order(self._order_mode)
        self._file_panel.setVisible(self._config.show_file_list)
        self._action_list.setChecked(self._config.show_file_list)
        self._action_auto_play.setChecked(self._config.auto_play)
        self._mute_button.setChecked(self._config.muted)
        self._engine.set_muted(self._config.muted)
        self._engine.set_rate(SPEEDS[self._config.speed_index])

    def _restore_geometry(self) -> None:
        screen = self.screen() or QGuiApplication.primaryScreen()
        available = screen.availableGeometry()
        width = min(max(self._config.window_width, 720), available.width())
        height = min(max(self._config.window_height, 520), available.height())
        if self._config.window_x is not None and self._config.window_y is not None:
            x = min(max(self._config.window_x, available.left()), available.right() - width)
            y = min(max(self._config.window_y, available.top()), available.bottom() - height)
            self.setGeometry(x, y, width, height)
            return
        self.resize(width, height)
        frame = self.frameGeometry()
        frame.moveCenter(available.center())
        self.move(frame.topLeft())

    # ------------------------------------------------------------------ 生命周期
    def startup(self) -> None:
        """窗口显示后执行：加载启动文件、预取与更新检查。"""
        if self._startup_path:
            QTimer.singleShot(0, self._open_startup_path)
        QTimer.singleShot(2500, self._auto_check_updates)

    def _open_startup_path(self) -> None:
        assert self._startup_path is not None
        self.open_path(Path(self._startup_path))

    def handle_external_request(self, message: str) -> None:
        """处理第二个实例转发过来的路径。"""
        self.show_window()
        candidate = Path(message)
        if candidate.exists():
            self.open_path(candidate)

    def show_window(self) -> None:
        """显示并激活窗口。"""
        self.showNormal()
        self.raise_()
        self.activateWindow()

    def quit_app(self) -> None:
        """唯一的退出路径（按钮 / 托盘 / 快捷键）。"""
        if self._quitting:
            return
        self._quitting = True
        self._logger.info("开始退出流程")
        self._persist()
        if self._preview is not None:
            with contextlib.suppress(Exception):
                self._preview.close()
            self._preview = None
        with contextlib.suppress(Exception):
            self._timeline.shutdown()
        try:
            self._resolver.stop()
            self._indexer.stop()
            self._catalog.close()
        except Exception as exc:  # noqa: BLE001 - 退出路径不允许抛异常
            self._logger.warning("关闭索引资源失败：%s", exc)
        try:
            self._poster.shutdown()
            self._engine.shutdown()
            self._loader.shutdown()
            self._runner.shutdown()
        except Exception as exc:  # noqa: BLE001 - 退出路径不允许抛异常
            self._logger.error("释放资源时异常：%s", exc)
        if self._tray is not None:
            self._tray.hide()
        QApplication.quit()

    def closeEvent(self, event: QCloseEvent) -> None:
        if self._quitting:
            event.accept()
            return
        if self._tray is not None and self._tray.isVisible():
            event.ignore()
            self.hide()
            if not self._config.tray_hint_shown:
                self._config.tray_hint_shown = True
                self._persist()
                self._tray.showMessage(
                    __software_name__,
                    "程序仍在托盘运行，双击托盘图标可恢复窗口。",
                    QSystemTrayIcon.MessageIcon.Information,
                    3000,
                )
            return
        self.quit_app()
        event.accept()

    def resizeEvent(self, event: object) -> None:
        super().resizeEvent(event)  # type: ignore[arg-type]
        if hasattr(self, "_toast"):
            self._toast.reposition()
        self._schedule_save()

    def moveEvent(self, event: object) -> None:
        super().moveEvent(event)  # type: ignore[arg-type]
        self._schedule_save()

    def _schedule_save(self) -> None:
        if self._restoring or self._save_timer.isActive():
            if not self._restoring:
                self._save_timer.start()
            return
        self._save_timer.start()

    def _persist(self) -> None:
        if self._restoring:
            return
        geometry = self.normalGeometry()
        self._config.window_width = geometry.width()
        self._config.window_height = geometry.height()
        self._config.window_x = geometry.x()
        self._config.window_y = geometry.y()
        if not self._timeline_active:
            self._config.show_file_list = self._file_panel.isVisible()
        self._config.order_mode = self._order_mode
        self._config.auto_play = self._action_auto_play.isChecked()
        self._config.speed_index = self._speed_combo.currentIndex()
        self._config.muted = self._mute_button.isChecked()
        self._store.save(self._config)

    # ------------------------------------------------------------------ 打开文件
    def _open_dialog(self) -> None:
        last = self._config.last_directory
        start_dir = last if last and Path(last).is_dir() else str(Path.home())
        selected, _ = QFileDialog.getOpenFileName(
            self,
            "打开媒体",
            start_dir,
            "媒体文件 (*.jpg *.jpeg *.heic *.heif *.png *.bmp *.tif *.tiff *.webp "
            "*.mp4 *.mov *.avi *.mkv *.m4v);;所有文件 (*)",
        )
        if selected:
            self.open_path(Path(selected))

    def open_path(self, path: Path) -> None:
        """打开一个文件（图片或视频）。"""
        try:
            resolved = path.resolve()
        except OSError:
            self._toast.show_error(f"无法访问：{path}")
            return
        if resolved.is_dir():
            candidates = self._browser.scan(resolved)
            if not candidates:
                self._toast.show_message("该文件夹里没有支持的文件")
                return
            resolved = candidates[0]
        if not resolved.exists():
            self._toast.show_error(f"文件不存在：{resolved}")
            return
        if not is_supported(resolved):
            self._toast.show_error(f"不支持的文件类型：{resolved.suffix}")
            return

        directory = resolved.parent
        if self._session_directory != directory:
            self._rebuild_session(directory, resolved)
        else:
            index = self._index_of(resolved)
            if index >= 0:
                self._index = index
            else:
                self._rebuild_session(directory, resolved)
        self._load_current()
        self._config.last_directory = str(directory)
        self._schedule_save()

    def _rebuild_session(self, directory: Path, focus: Path | None) -> None:
        paths = self._browser.scan(directory)
        items: list[MediaItem] = []
        # 文件夹优先展示，方便逐层进入
        for child in self._subdirectories(directory):
            items.append(MediaItem(path=child, kind=MediaKind.PHOTO, is_folder=True))
        parent = directory.parent
        if parent != directory:
            items.append(
                MediaItem(
                    path=parent, kind=MediaKind.PHOTO, is_folder=True, name_override="上级目录"
                )
            )
        for path in paths:
            try:
                stat = path.stat()
            except OSError:
                stat = None
            items.append(
                MediaItem(
                    path=path,
                    kind=file_kind(path),
                    size_bytes=stat.st_size if stat else 0,
                    # 未索引前先用文件时间占位，索引完成后会被拍摄时间覆盖
                    taken_ts=int(stat.st_mtime) if stat else 0,
                )
            )
        self._session_directory = directory
        self._search_query = ""
        self._enrich(items)
        self._items = self._ordered(items)
        self._index = self._index_of(focus) if focus is not None else -1
        if self._index < 0 and self._items:
            self._index = 0
        self._file_panel.set_items(self._items)
        self._sync_timeline()
        self._logger.info("目录已载入：%s（%s 个文件）", directory, len(self._items))
        # 结构化分析在后台慢慢补，不阻塞界面
        self._indexer.enqueue(directory)

    def _enrich(self, items: list[MediaItem]) -> None:
        """用结构化目录补齐拍摄时间、地点、相机与收藏状态。"""
        if not items:
            return
        try:
            records = self._catalog.by_paths([item.path for item in items])
            favorite_paths = self._catalog.favorite_paths()
        except Exception as exc:  # noqa: BLE001 - 索引不可用不应影响浏览
            self._logger.warning("读取结构化目录失败：%s", exc)
            return
        for item in items:
            record = records.get(str(item.path))
            if record is not None:
                if record.taken_ts:
                    item.taken_ts = record.taken_ts
                item.latitude = record.latitude
                item.longitude = record.longitude
                item.place = record.place
                item.camera = record.camera
                if record.width:
                    item.pixel_width = record.width
                    item.pixel_height = record.height
            item.favorite = str(item.path) in favorite_paths

    def _ordered(self, items: list[MediaItem]) -> list[MediaItem]:
        """按当前排序模式排列：默认按文件名，时间线按拍摄时间倒序。"""
        if self._order_mode == MODE_NAME:
            return sorted(items, key=lambda item: natural_key(item.name))
        return sorted(items, key=lambda item: (item.sort_ts, item.name), reverse=True)

    def _item_from_record(self, record: PhotoRecord) -> MediaItem:
        """把索引记录转成列表条目。"""
        return MediaItem(
            path=record.path,
            kind=MediaKind.VIDEO if record.kind == "video" else MediaKind.PHOTO,
            size_bytes=record.size_bytes,
            taken_ts=record.taken_ts,
            latitude=record.latitude,
            longitude=record.longitude,
            place=record.place,
            camera=record.camera,
            pixel_width=record.width,
            pixel_height=record.height,
            favorite=self._catalog.is_favorite(record.path),
        )

    def _subdirectories(self, directory: Path) -> list[Path]:
        """列出可进入的子目录（跳过隐藏目录）。"""
        try:
            children = [
                child
                for child in directory.iterdir()
                if child.is_dir() and not child.name.startswith(".")
            ]
        except OSError:
            return []
        return sorted(children, key=lambda item: natural_key(item.name))

    def _index_of(self, path: Path) -> int:
        for index, item in enumerate(self._items):
            if item.path == path:
                return index
        return -1

    def _current(self) -> MediaItem | None:
        if 0 <= self._index < len(self._items):
            return self._items[self._index]
        return None

    def _load_current(self) -> None:
        item = self._current()
        if item is None:
            return
        self._engine.clear()
        self._poster.cancel()
        self._engine_path = None
        self._full_requested = None
        self._file_panel.set_current(self._index)
        self._enrich([item])
        self._update_favorite_action()
        self._stack.setCurrentIndex(0)
        self._action_play.setText("播放")
        if item.kind is MediaKind.VIDEO:
            self._load_video_item(item)
        else:
            self._load_image_item(item)

    def _load_image_item(self, item: MediaItem) -> None:
        self._generation = self._loader.next_generation()
        self._canvas.set_loading(True)
        self._set_status(f"加载中… {item.name}")
        self._loader.request(item.path, self._target_width(), self._generation)

    def _load_video_item(self, item: MediaItem) -> None:
        self._canvas.set_loading(False)
        self._stack.setCurrentIndex(1)
        # 先用视频自己的封面；抓不到时再退到通用封面
        poster = self._poster.cached(str(item.path))
        if poster is not None:
            self._surface.set_cover_pixmap(QPixmap.fromImage(poster))
        else:
            self._ensure_cover()
            if self._cover_pixmap is None:
                self._surface.set_cover_pixmap(None)
        self._surface.set_cover_visible(True)
        self._poster.request(str(item.path), item.path)
        self._set_status(f"视频：{item.name}")
        self._update_info(item)
        # 选中即开始解析媒体，让用户点播放时首帧几乎是即时的。
        self._ensure_engine_media(item)

    def _target_width(self) -> int:
        dpr = self.devicePixelRatioF() or 1.0
        width = max(1, self._canvas.width())
        return int(max(900, min(4096, width * dpr * PREVIEW_SUPERSAMPLE)))

    # ------------------------------------------------------------------ 加载回调
    def _on_image_loaded(self, payload: object) -> None:
        from livephoto_player.core.models import ImagePayload

        if not isinstance(payload, ImagePayload):
            return
        if payload.prefetch or payload.generation != self._generation:
            return
        item = self._current()
        if item is None or payload.path != item.path:
            return
        image = payload.image
        if payload.error or not hasattr(image, "isNull") or image.isNull():
            self._canvas.set_loading(False)
            self._canvas.clear()
            self._canvas.set_status_text("这张图片无法显示")
            self._set_status("无法显示该图片")
            self._toast.show_error(f"无法显示 {item.name}：{payload.error or '解码失败'}")
            return

        if payload.full:
            self._canvas.upgrade_image(image)
            return

        self._canvas.set_loading(False)
        item.taken_at = payload.taken_at
        item.span = payload.span
        item.pixel_width = payload.source_width or payload.display_width
        item.pixel_height = payload.source_height or payload.display_height
        # 画布以原图像素为坐标基准：100% 恒等于原图 1:1
        self._canvas.set_image(image, QSize(item.pixel_width, item.pixel_height), fit=True)
        item.kind = MediaKind.LIVE_PHOTO if payload.span is not None else MediaKind.PHOTO
        self._update_info(item)
        self._set_status("实况照片" if item.span is not None else "照片")
        self._file_panel.refresh_row(self._index)
        self._logger.info(
            "已显示 %s（%sx%s%s）",
            item.name,
            item.pixel_width,
            item.pixel_height,
            "，含内嵌视频" if item.span is not None else "",
        )
        self._prefetch_neighbours()
        if self._pending_timeline:
            self._pending_timeline = False
            self._action_timeline.setChecked(True)
            self._toggle_timeline_mode(True)
        if self._config.auto_play and item.has_video:
            QTimer.singleShot(0, self.toggle_playback)

    def _prefetch_neighbours(self) -> None:
        width = self._target_width()
        candidates: list[Path] = []
        for offset in (1, -1, 2, -2):
            index = self._index + offset
            if 0 <= index < len(self._items):
                candidate = self._items[index]
                if candidate.kind is not MediaKind.VIDEO:
                    candidates.append(candidate.path)
        if candidates:
            self._loader.prefetch(candidates, width)

    # ------------------------------------------------------------------ 导航
    def _neighbour_index(self, step: int) -> int | None:
        """找下一张/上一张照片；跳过文件夹行，走到头返回 None。"""
        index = self._index + step
        while 0 <= index < len(self._items):
            if not self._items[index].is_folder:
                return index
            index += step
        return None

    def next_item(self) -> None:
        """下一张；到最后一张只提示，不跳进文件夹。"""
        target = self._neighbour_index(1)
        if target is None:
            self._toast.show_message("已经是最后一张")
            return
        self._index = target
        self._load_current()

    def previous_item(self) -> None:
        """上一张；到第一张只提示。"""
        target = self._neighbour_index(-1)
        if target is None:
            self._toast.show_message("已经是第一张")
            return
        self._index = target
        self._load_current()

    def _goto(self, index: int) -> None:
        if 0 <= index < len(self._items) and index != self._index:
            self._index = index
            self._load_current()

    def _on_video_zone(self, zone: int) -> None:
        """视频上点左/右切换，点中间交给播放控制。"""
        if zone == 0:
            self.previous_item()
        elif zone == 2:
            self.next_item()

    # ------------------------------------------------------------------ 拖拽打开
    def dragEnterEvent(self, event: object) -> None:
        mime = getattr(event, "mimeData", lambda: None)()
        if mime is not None and mime.hasUrls():
            event.acceptProposedAction()  # type: ignore[attr-defined]
            return
        super().dragEnterEvent(event)  # type: ignore[arg-type]

    def dropEvent(self, event: object) -> None:
        mime = getattr(event, "mimeData", lambda: None)()
        if mime is None or not mime.hasUrls():
            super().dropEvent(event)  # type: ignore[arg-type]
            return
        urls = [url for url in mime.urls() if url.isLocalFile()]
        if not urls:
            return
        event.acceptProposedAction()  # type: ignore[attr-defined]
        self.open_path(Path(urls[0].toLocalFile()))

    def _on_list_selected(self, row: int) -> None:
        if not (0 <= row < len(self._items)):
            return
        item = self._items[row]
        if item.is_folder:
            self._rebuild_session(item.path, None)
            self._index = -1
            self._file_panel.set_items(self._items)
            self._sync_timeline()
            self._set_status(f"文件夹：{item.path.name}")
            return
        if row != self._index:
            self._goto(row)

    # ------------------------------------------------------------------ 时间线模式
    def _toggle_timeline_mode(self, checked: bool) -> None:
        """进入/退出专门的时间线展示。"""
        self._timeline_active = checked
        if checked:
            self.stop_playback()
            self._file_panel.setVisible(False)
            self._timeline.set_items(self._items)
            self._timeline.set_current(self._index)
            self._stack.setCurrentIndex(2)
            self._set_status(f"时间线 · {len(self._items)} 条")
        else:
            # 退出时间线必须把列表恢复成用户原来选择的状态
            self._file_panel.setVisible(self._config.show_file_list)
            self._action_list.setChecked(self._config.show_file_list)
            self._stack.setCurrentWidget(self._canvas)
            self._set_status("就绪")
        self._action_timeline.setChecked(checked)

    def _exit_timeline(self) -> None:
        """从头部的「返回浏览」退出时间线。"""
        self._action_timeline.setChecked(False)
        self._toggle_timeline_mode(False)

    def _preview_from_timeline(self, row: int) -> None:
        """在浮动预览窗里看这张。"""
        if not (0 <= row < len(self._items)):
            return
        if self._preview is None:
            self._preview = PreviewWindow(self._items, row, self)
            self._preview.closed.connect(self._on_preview_closed)
            self._preview.index_changed.connect(self._on_preview_index)
        else:
            self._preview.load(row)
        self._preview.setGeometry(self.rect())
        self._preview.show()
        self._preview.raise_()
        self._index = row

    def _on_preview_closed(self) -> None:
        self._preview = None

    def _on_preview_index(self, index: int) -> None:
        self._index = index
        if self._timeline_active:
            self._timeline.set_current(index)

    def _favorite_from_timeline(self, row: int) -> None:
        if 0 <= row < len(self._items):
            self._index = row
            self._toggle_favorite()

    def _reveal_from_timeline(self, row: int) -> None:
        """在资源管理器中定位文件。"""
        if not (0 <= row < len(self._items)):
            return
        path = self._items[row].path
        try:
            subprocess.Popen(["explorer", "/select,", str(path)])
        except OSError as exc:
            self._logger.warning("定位文件失败：%s", exc)
            self._toast.show_error("无法打开资源管理器")

    def _open_from_timeline(self, row: int) -> None:
        """从时间线点开某张照片，回到浏览模式。"""
        if not (0 <= row < len(self._items)):
            return
        self._index = row
        self._action_timeline.setChecked(False)
        self._timeline_active = False
        self._stack.setCurrentWidget(self._canvas)
        self._load_current()

    def _sync_timeline(self) -> None:
        """列表数据变化时同步给时间线视图。"""
        if self._timeline_active:
            self._timeline.set_items(self._items)
            self._timeline.set_current(self._index)

    # ------------------------------------------------------------------ 地点解析
    def _apply_geo_config(self) -> None:
        """把配置交给解析线程。"""
        self._resolver.configure(
            self._config.geo.mode,
            self._config.geo.provider,
            self._config.geo.tianditu_key,
        )

    def _show_geo_dialog(self) -> None:
        """打开地点解析设置；保存后清空旧地名并重新解析。"""
        dialog = GeoDialog(self._config, self._current(), self)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        mode = dialog.selected_mode()
        provider = dialog.selected_provider()
        key = dialog.tianditu_key()
        changed = (
            mode != self._config.geo.mode
            or provider != self._config.geo.provider
            or key != self._config.geo.tianditu_key
        )
        self._config.geo.mode = mode
        self._config.geo.provider = provider
        self._config.geo.tianditu_key = key
        self._schedule_save()
        if changed:
            try:
                cleared = self._catalog.clear_places()
                self._logger.info("已清空 %s 条旧地名，准备重新解析", cleared)
            except Exception as exc:  # noqa: BLE001 - 数据库异常不应崩溃
                self._logger.warning("清空地名失败：%s", exc)
        self._apply_geo_config()
        self._resolver.request()
        self._toast.show_message("已更新地点解析方式，后台正在重新解析")

    def _on_places_resolved(self, count: int) -> None:
        """解析线程有进展时，节流刷新当前列表。"""
        if count <= 0:
            return
        if not self._place_timer.isActive():
            self._place_timer.start()

    def _refresh_places(self) -> None:
        """把新解析出的地名回填到当前列表与状态栏。"""
        if self._search_query:
            current = self._current()
            if current is not None:
                self._enrich([current])
                self._update_info(current)
            return
        if not self._items:
            return
        current = self._current()
        self._enrich(self._items)
        self._file_panel.refresh_all()
        if current is not None:
            self._update_info(current)

    # ------------------------------------------------------------------ 搜索与排序
    def _on_search_changed(self, text: str) -> None:
        """搜索走结构化目录（全库），清空时回到当前目录。"""
        self._search_query = text.strip()
        if not self._search_query:
            current = self._current()
            if self._session_directory is not None:
                self._rebuild_session(self._session_directory, current.path if current else None)
                self._load_current()
            return
        try:
            records = self._catalog.search(self._search_query)
        except Exception as exc:  # noqa: BLE001 - 搜索失败不应崩溃
            self._logger.error("搜索失败：%s", exc)
            self._toast.show_error("搜索失败，请查看日志")
            return
        if not records:
            self._items = []
            self._index = -1
            self._file_panel.set_items([])
            self._set_status(f"没有匹配「{self._search_query}」的照片")
            self._toast.show_message(
                f"没有匹配「{self._search_query}」的照片（后台索引可能还没扫到）"
            )
            return
        items = [self._item_from_record(record) for record in records]
        self._items = self._ordered(items)
        self._index = 0
        self._file_panel.set_items(self._items)
        self._file_panel.set_current(0)
        self._load_current()
        self._set_status(f"搜索「{self._search_query}」：{len(self._items)} 条")

    def _on_order_changed(self, mode: str) -> None:
        """切换默认排序 / 拍摄时间线，保持当前照片不跳走。"""
        self._order_mode = mode
        current = self._current()
        before = current.path if current else None
        self._items = self._ordered(self._items)
        self._index = self._index_of(before) if before is not None else -1
        if self._index < 0 and self._items:
            self._index = 0
        self._file_panel.set_items(self._items)
        self._file_panel.set_current(self._index)
        self._sync_timeline()
        self._config.order_mode = mode
        self._schedule_save()
        self._set_status("按拍摄时间线排列" if mode == MODE_TIMELINE else "按文件名排列")

    # ------------------------------------------------------------------ 收藏
    def _toggle_favorite(self) -> None:
        """星标 / 取消星标，并把副本复制到收藏文件夹。"""
        item = self._current()
        if item is None:
            self._toast.show_message("没有可收藏的照片")
            return
        try:
            state = self._favorites.toggle(item.path, item.sort_ts)
        except Exception as exc:  # noqa: BLE001 - 磁盘异常不应崩溃
            self._logger.error("收藏操作失败：%s", exc)
            self._toast.show_error(f"收藏失败：{exc}")
            return
        for candidate in self._items:
            if candidate.path == item.path:
                candidate.favorite = state
        self._update_favorite_action()
        self._file_panel.refresh_row(self._index)
        if state:
            self._toast.show_success("已收藏，副本已保存到 收藏 文件夹")
        else:
            self._toast.show_message("已取消收藏")
        if self._favorites_dialog is not None:
            self._favorites_dialog.refresh()

    def _update_favorite_action(self) -> None:
        """同步星标按钮的文案与状态。"""
        item = self._current()
        favorite = bool(item and item.favorite)
        self._action_favorite.blockSignals(True)
        self._action_favorite.setChecked(favorite)
        self._action_favorite.setIcon(star_icon(favorite))
        self._action_favorite.setText("已收藏" if favorite else "收藏")
        self._action_favorite.setEnabled(item is not None)
        self._action_favorite.blockSignals(False)

    def _show_favorites(self) -> None:
        """打开收藏夹（两个时间线标签页）。"""
        if self._favorites_dialog is None:
            self._favorites_dialog = FavoritesDialog(self._catalog, self)
            self._favorites_dialog.open_requested.connect(self._open_from_favorites)
        self._favorites_dialog.refresh()
        self._favorites_dialog.show()
        self._favorites_dialog.raise_()
        self._favorites_dialog.activateWindow()

    def _open_from_favorites(self, path: object) -> None:
        """从收藏夹打开某张照片。"""
        self.open_path(Path(str(path)))

    # ------------------------------------------------------------------ 索引回调
    def _on_index_done(self, directory: str, changed: int) -> None:
        """后台把当前目录索引完后，悄悄刷新时间与地点。"""
        if self._search_query or self._session_directory is None:
            return
        try:
            same = str(self._session_directory) == directory
        except OSError:
            return
        if not same:
            return
        current = self._current()
        before = current.path if current else None
        self._enrich(self._items)
        self._items = self._ordered(self._items)
        self._index = self._index_of(before) if before is not None else -1
        if self._index < 0 and self._items:
            self._index = 0
        self._file_panel.set_items(self._items)
        self._file_panel.set_current(self._index)
        current = self._current()
        if current is not None:
            self._update_info(current)
        self._resolver.request()
        if changed:
            self._logger.info("已补齐 %s 条的拍摄时间与地点", changed)

    # ------------------------------------------------------------------ 播放
    def toggle_playback(self) -> None:
        """播放 / 暂停当前媒体。"""
        item = self._current()
        if item is None or not item.has_video:
            self._toast.show_message("这张照片没有内嵌视频")
            return
        if self._engine.is_playing:
            self._engine.pause()
            return
        if not self._ensure_engine_media(item):
            return
        self._stack.setCurrentIndex(1)
        self._surface.set_cover_visible(False)
        self._engine.play()

    def stop_playback(self) -> None:
        """停止播放并回到照片视图。"""
        self._engine.stop()
        item = self._current()
        if item is not None and item.kind is MediaKind.LIVE_PHOTO:
            self._stack.setCurrentIndex(0)
        elif item is not None and item.kind is MediaKind.VIDEO:
            self._surface.set_cover_visible(True)
        self._action_play.setText("播放")

    def _ensure_engine_media(self, item: MediaItem) -> bool:
        if self._engine_path == item.path:
            return True
        self._engine.set_rate(SPEEDS[self._config.speed_index])
        self._engine.set_muted(self._config.muted)
        if item.kind is MediaKind.VIDEO:
            self._engine.open_path(item.path)
        elif item.span is not None:
            self._engine.open_span(item.path, item.span)
        else:
            self._toast.show_message("这张照片没有内嵌视频")
            return False
        self._engine_path = item.path
        return True

    def _on_engine_state(self, state: object) -> None:
        self._canvas.set_playing(state is PlaybackState.PLAYING)
        if not isinstance(state, PlaybackState):
            return
        if state is PlaybackState.PLAYING:
            self._stack.setCurrentIndex(1)
            self._surface.set_cover_visible(False)
            self._action_play.setText("暂停")
            self._set_status("播放中…")
        elif state is PlaybackState.PAUSED:
            self._action_play.setText("播放")
            self._set_status("已暂停")
        elif state is PlaybackState.ENDED:
            self._action_play.setText("播放")
            item = self._current()
            if item is not None and item.kind is MediaKind.LIVE_PHOTO:
                self._stack.setCurrentIndex(0)
                self._set_status("实况照片")
            else:
                self._surface.set_cover_visible(True)
                self._set_status("播放结束")
        elif state is PlaybackState.ERROR:
            self._action_play.setText("播放")
            item = self._current()
            if item is not None and item.kind is MediaKind.VIDEO:
                self._surface.set_cover_visible(True)
            else:
                self._stack.setCurrentIndex(0)
        elif state in (PlaybackState.STOPPED, PlaybackState.IDLE):
            self._action_play.setText("播放")

    def _on_engine_error(self, message: str) -> None:
        self._toast.show_error(f"播放失败：{message}")

    def _on_poster_ready(self, key: str, image: object) -> None:
        item = self._current()
        if item is None or str(item.path) != key:
            return
        if not isinstance(image, QImage) or image.isNull():
            return
        self._surface.set_cover_pixmap(QPixmap.fromImage(image))
        if item.kind is MediaKind.VIDEO and not self._engine.is_playing:
            self._surface.set_cover_visible(True)

    def _on_speed_changed(self, index: int) -> None:
        self._engine.set_rate(SPEEDS[max(0, min(index, len(SPEEDS) - 1))])
        self._config.speed_index = index
        self._schedule_save()

    def _on_mute_toggled(self, muted: bool) -> None:
        self._engine.set_muted(muted)
        self._mute_button.setText("静音" if muted else "有声")
        self._config.muted = muted
        self._schedule_save()

    def _toggle_auto_play(self, checked: bool) -> None:
        self._config.auto_play = checked
        self._action_auto_play.setChecked(checked)
        self._schedule_save()
        self._toast.show_message("已切换为自动播放" if checked else "已切换为点击播放")

    # ------------------------------------------------------------------ 缩放
    def _fit_canvas(self) -> None:
        self._canvas.fit()

    def _actual_size(self) -> None:
        self._canvas.zoom_to_percent(100)

    def _on_zoom_changed(self, zoom: float) -> None:
        self._zoom_label.setText(f"{round(zoom * 100)}%")
        item = self._current()
        if item is None or item.kind is MediaKind.VIDEO or item.pixel_width <= 0:
            return
        if self._full_requested == item.path:
            return
        if self._canvas.needs_full_resolution():
            self._full_requested = item.path
            self._loader.request_full(item.path, self._generation)

    def _reset_view(self) -> None:
        self._canvas.fit()
        self._toast.show_message("已恢复照片大小")

    def _reset_all(self) -> None:
        self.stop_playback()
        self._engine.clear()
        self._engine_path = None
        self._items = []
        self._index = -1
        self._session_directory = None
        self._generation = self._loader.next_generation()
        self._canvas.clear()
        self._canvas.set_loading(False)
        self._canvas.set_status_text("拖入照片 / 视频，或点击「打开文件」")
        self._file_panel.set_items([])
        self._info_label.setText("")
        self._set_status("就绪")
        self._config.auto_play = False
        self._action_auto_play.setChecked(False)
        self._config.speed_index = 3
        self._speed_combo.setCurrentIndex(3)
        self._config.muted = False
        self._mute_button.setChecked(False)
        self.resize(1080, 760)
        screen = self.screen() or QGuiApplication.primaryScreen()
        frame = self.frameGeometry()
        frame.moveCenter(screen.availableGeometry().center())
        self.move(frame.topLeft())
        self._schedule_save()
        self._toast.show_message("已恢复初始状态")

    def _toggle_file_panel(self) -> None:
        visible = not self._file_panel.isVisible()
        self._file_panel.setVisible(visible)
        self._action_list.setChecked(visible)
        self._config.show_file_list = visible
        self._schedule_save()

    # ------------------------------------------------------------------ 导出
    def export_current_photo(self) -> None:
        """导出当前照片。"""
        item = self._current()
        if item is None or item.kind is MediaKind.VIDEO:
            self._toast.show_message("当前没有可导出的照片")
            return
        target = export_dir("photo")
        self._set_busy(True)
        self._set_status("正在导出照片…")
        self._runner.submit(
            lambda: export_photo(item, target),
            on_success=lambda result: self._on_export_done(result, "照片"),
            on_error=self._on_export_failed,
        )

    def export_current_video(self) -> None:
        """导出当前视频（实况照片按区间抽取）。"""
        item = self._current()
        if item is None or not item.has_video:
            self._toast.show_message("当前没有可导出的视频")
            return
        target = export_dir("video")
        self._set_busy(True)
        self._set_status("正在导出视频…")
        self._runner.submit(
            lambda: export_video(item, target),
            on_success=lambda result: self._on_export_done(result, "视频"),
            on_error=self._on_export_failed,
        )

    def _on_export_done(self, result: object, label: str) -> None:
        self._set_busy(False)
        path = Path(str(result))
        self._set_status(f"{label}已导出")
        self._toast.show_success(f"{label}已导出：{path.name}")

    def _on_export_failed(self, message: str) -> None:
        self._set_busy(False)
        self._set_status("导出失败")
        self._toast.show_error(f"导出失败：{message}")

    def _open_export_dir(self, kind: str) -> None:
        directory = export_dir("photo" if kind == "photo" else "video")
        directory.mkdir(parents=True, exist_ok=True)
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(directory)))

    # ------------------------------------------------------------------ 菜单
    def contextMenuEvent(self, event: object) -> None:
        # 直接用全局坐标，避免"主窗口坐标 -> 子控件坐标"二次换算造成的漂移
        self._show_context_menu_global(getattr(event, "globalPos", lambda: QCursor.pos())())

    def _show_context_menu_at(self, position: QPoint) -> None:
        """视频区给的是局部坐标，转成全局后再弹菜单。"""
        target = self._surface if self._stack.currentIndex() == 1 else self._canvas
        self._show_context_menu_global(target.mapToGlobal(position))

    def _show_context_menu_global(self, global_pos: QPoint) -> None:
        menu = QMenu(self)
        menu.addAction(self._action_open)
        menu.addAction(self._action_prev)
        menu.addAction(self._action_next)
        menu.addSeparator()
        play_text = "暂停" if self._engine.is_playing else "播放"
        menu.addAction(play_text, self.toggle_playback)
        menu.addAction(self._action_stop)
        menu.addSeparator()
        auto_text = "切换为点击播放" if self._config.auto_play else "切换为自动播放"
        menu.addAction(auto_text, lambda: self._action_auto_play.trigger())
        menu.addSeparator()
        menu.addAction(self._action_timeline)
        menu.addAction(self._action_favorite)
        menu.addAction(self._action_favorites)
        menu.addSeparator()
        menu.addAction(self._action_export_photo)
        menu.addAction(self._action_export_video)
        menu.addAction(self._action_open_photo)
        menu.addAction(self._action_open_video)
        menu.addSeparator()
        menu.addAction(self._action_fit)
        menu.addAction(self._action_actual)
        menu.addAction(self._action_reset)
        menu.addAction(self._action_initial)
        menu.addSeparator()
        menu.addAction(self._action_list)
        menu.addAction(self._action_geo)
        menu.addAction(self._action_update)
        menu.addAction(self._action_about)
        menu.addAction(self._action_quit)
        menu.exec(global_pos)

    # ------------------------------------------------------------------ 其它
    def _set_status(self, text: str) -> None:
        self._status_label.setText(text)

    def _set_busy(self, busy: bool) -> None:
        self._progress.setVisible(busy)
        if busy:
            QApplication.setOverrideCursor(QCursor(Qt.CursorShape.BusyCursor))
        elif QApplication.overrideCursor() is not None:
            QApplication.restoreOverrideCursor()

    def _update_info(self, item: MediaItem) -> None:
        """状态栏：名称 · 类型 | 简写日期 时间 · 地点（完整） | 大小 · 像素。

        相机型号按需求去掉；地点单独一列且不省略，宽度不够时优先压缩文件名。
        """
        self._info_label.setText(f"{item.name} · {item.kind.label}")
        when = f"{format_short_day(item.display_ts)} {item.time_text}".strip()
        place = item.place_text
        place = "" if place == UNKNOWN_PLACE else place
        detail = " · ".join(part for part in (when, place) if part)
        self._place_label.setText(detail)
        size = format_size(item.size_bytes)
        pixels = f"{item.pixel_width}×{item.pixel_height}" if item.pixel_width else ""
        self._size_label.setText(" · ".join(part for part in (size, pixels) if part))

    def _on_tray_activated(self, reason: QSystemTrayIcon.ActivationReason) -> None:
        if reason in (
            QSystemTrayIcon.ActivationReason.DoubleClick,
            QSystemTrayIcon.ActivationReason.Trigger,
        ):
            self.show_window()

    def _show_about(self) -> None:
        dialog = AboutDialog(project_root() / "docs" / "THIRD-PARTY-NOTICES.md", self)
        dialog.check_update_requested.connect(lambda: self.request_update_check(silent=False))
        dialog.exec()

    def show_path_warning(self, reason: str) -> None:
        """目录回退等一次性提示。"""
        self._toast.show_message(reason, 5000, theme.COLOR_WARNING)

    # ------------------------------------------------------------------ 更新检查
    def _auto_check_updates(self) -> None:
        if should_check_now(self._config.update.last_check):
            self.request_update_check(silent=True)

    def request_update_check(self, *, silent: bool) -> None:
        """检查更新；``silent=True`` 时失败不打扰用户。"""
        owner = self._config.update.owner
        repo = self._config.update.repo
        if not silent:
            self._toast.show_message("正在检查更新…")
        self._runner.submit(
            lambda: fetch_latest(owner, repo),
            on_success=lambda info: self._on_update_ready(info, silent),
            on_error=lambda message: self._on_update_failed(message, silent),
        )

    def _on_update_ready(self, info: object, silent: bool) -> None:
        from livephoto_player.core.version import __version__

        self._config.update.last_check = datetime.now().isoformat(timespec="seconds")
        self._schedule_save()
        version_text = getattr(info, "version_text", "")
        prerelease = bool(getattr(info, "prerelease", False))
        if silent and prerelease:
            return
        ignored = self._config.update.ignored_version
        if is_newer(version_text, __version__) and version_text != ignored:
            dialog = UpdateDialog(info, self)  # type: ignore[arg-type]
            result = dialog.exec()
            if result == 2:
                self._config.update.ignored_version = version_text
                self._schedule_save()
                self._toast.show_message(f"已忽略版本 {version_text}")
            return
        if not silent:
            self._toast.show_success(f"已是最新版本 {__version__}")

    def _on_update_failed(self, message: str, silent: bool) -> None:
        self._logger.warning("检查更新失败：%s", message)
        if not silent:
            self._toast.show_error(f"检查更新失败：{message}")

    # ------------------------------------------------------------------ 键盘
    def keyPressEvent(self, event: QKeyEvent) -> None:
        key = event.key()
        modifiers = event.modifiers()
        if modifiers & Qt.KeyboardModifier.ControlModifier:
            if key == Qt.Key.Key_0:
                self._fit_canvas()
                return
            if key == Qt.Key.Key_1:
                self._actual_size()
                return
            if key in (Qt.Key.Key_Plus, Qt.Key.Key_Equal):
                self._canvas.zoom_step(1.2)
                return
            if key == Qt.Key.Key_Minus:
                self._canvas.zoom_step(1 / 1.2)
                return
        if key in (Qt.Key.Key_Left, Qt.Key.Key_Up):
            self.previous_item()
            return
        if key in (Qt.Key.Key_Right, Qt.Key.Key_Down):
            self.next_item()
            return
        if key in (Qt.Key.Key_Return, Qt.Key.Key_Enter, Qt.Key.Key_Space):
            self.toggle_playback()
            return
        if key == Qt.Key.Key_Escape:
            self.stop_playback()
            return
        if key == Qt.Key.Key_Home:
            self._goto(0)
            return
        if key == Qt.Key.Key_End:
            self._goto(len(self._items) - 1)
            return
        super().keyPressEvent(event)
