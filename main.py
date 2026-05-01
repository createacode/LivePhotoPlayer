#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
实况照片播放器 - 最终版（居中启动 + 延迟加载）
版本: 3.18.0
"""

import sys
import os
import re
import ctypes
import tempfile
import random
import string
import shutil
import json
from datetime import datetime
from typing import Optional, Tuple

# ==================== 必须在导入 vlc 之前配置 VLC 环境 ====================
def setup_vlc_environment():
    if getattr(sys, 'frozen', False):
        base_dir = sys._MEIPASS
    else:
        base_dir = os.path.dirname(os.path.abspath(__file__))

    vlc_dir = os.path.join(base_dir, 'vlc')
    if not os.path.exists(vlc_dir):
        vlc_dir = os.path.join(os.getcwd(), 'vlc')
        if not os.path.exists(vlc_dir):
            raise FileNotFoundError("未找到 vlc 目录")

    os.environ['PATH'] = vlc_dir + os.pathsep + os.environ.get('PATH', '')
    libvlc_core = os.path.join(vlc_dir, 'libvlccore.dll')
    libvlc = os.path.join(vlc_dir, 'libvlc.dll')
    if os.path.exists(libvlc_core):
        ctypes.CDLL(libvlc_core)
    if os.path.exists(libvlc):
        ctypes.CDLL(libvlc)
    plugins_path = os.path.join(vlc_dir, 'plugins')
    if os.path.exists(plugins_path):
        os.environ['VLC_PLUGIN_PATH'] = plugins_path
    return vlc_dir

vlc_dir = setup_vlc_environment()
import vlc
from PyQt5 import QtWidgets, QtCore, QtGui
from PyQt5.QtCore import Qt, QPoint, QTimer, QRect, QThread, pyqtSignal
from PyQt5.QtGui import QPixmap, QImage, QPainter, QWheelEvent, QMouseEvent, QFont, QCursor, QColor
from PyQt5.QtWidgets import (QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
                             QToolBar, QStatusBar, QLabel, QPushButton, QComboBox,
                             QListWidget, QListWidgetItem, QStackedWidget, QFrame,
                             QFileDialog, QMenu, QAction, QShortcut,
                             QSizePolicy, QDockWidget, QScrollArea, QProgressBar)

# ==================== 配置管理 ====================
class ConfigManager:
    def __init__(self):
        if getattr(sys, 'frozen', False):
            base_dir = os.path.dirname(sys.executable)
        else:
            base_dir = os.path.dirname(os.path.abspath(__file__))
        self.config_dir = os.path.join(base_dir, 'config')
        self.config_file = os.path.join(self.config_dir, 'config.json')
        os.makedirs(self.config_dir, exist_ok=True)
        self.data = self.load()
        logger.info(f"配置加载: {self.data}")

    def load(self):
        if os.path.exists(self.config_file):
            try:
                with open(self.config_file, 'r', encoding='utf-8') as f:
                    return json.load(f)
            except Exception as e:
                logger.error(f"加载配置失败: {e}")
                return {}
        return {}

    def save(self):
        try:
            with open(self.config_file, 'w', encoding='utf-8') as f:
                json.dump(self.data, f, indent=2)
        except Exception as e:
            logger.error(f"保存配置失败: {e}")

    def get_last_dir(self):
        return self.data.get('last_directory', '')

    def set_last_dir(self, path):
        if path and os.path.isdir(path):
            self.data['last_directory'] = path
            self.save()

    def get_window_size(self):
        return self.data.get('window_width', 800), self.data.get('window_height', 600)

    def set_window_size(self, width, height):
        self.data['window_width'] = width
        self.data['window_height'] = height
        self.save()

    def get_speed_index(self):
        return self.data.get('speed_index', 3)

    def set_speed_index(self, idx):
        self.data['speed_index'] = idx
        self.save()

    def get_mute_state(self):
        return self.data.get('mute_state', False)

    def set_mute_state(self, muted):
        self.data['mute_state'] = muted
        self.save()

    def get_auto_play(self):
        return self.data.get('auto_play', False)

    def set_auto_play(self, enabled):
        self.data['auto_play'] = enabled
        self.save()


# ==================== 日志系统 ====================
def setup_logging():
    if getattr(sys, 'frozen', False):
        base_dir = os.path.dirname(sys.executable)
    else:
        base_dir = os.path.dirname(os.path.abspath(__file__))
    log_dir = os.path.join(base_dir, 'logs')
    os.makedirs(log_dir, exist_ok=True)
    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    rand_suffix = ''.join(random.choices(string.digits, k=6))
    log_filename = f"{timestamp}_{rand_suffix}.log"
    log_path = os.path.join(log_dir, log_filename)
    global logger
    import logging
    logger = logging.getLogger('LivePhotoPlayer')
    logger.setLevel(logging.DEBUG)
    fh = logging.FileHandler(log_path, encoding='utf-8')
    fh.setLevel(logging.DEBUG)
    formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
    fh.setFormatter(formatter)
    logger.addHandler(fh)
    ch = logging.StreamHandler()
    ch.setLevel(logging.INFO)
    ch.setFormatter(formatter)
    logger.addHandler(ch)
    logger.info(f"日志系统初始化: {log_path}")
    return logger

logger = setup_logging()
config = ConfigManager()

# 全局异常钩子
def excepthook(exc_type, exc_value, exc_tb):
    logger.critical("未捕获异常", exc_info=(exc_type, exc_value, exc_tb))
    sys.__excepthook__(exc_type, exc_value, exc_tb)
sys.excepthook = excepthook


# ==================== 实况图视频提取 ====================
def get_video_length_from_xmp(file_path: str) -> int:
    try:
        with open(file_path, 'rb') as f:
            data = f.read(1024 * 1024)
            pattern = rb'Item:Length="(\d+)"'
            match = re.search(pattern, data)
            if match:
                return int(match.group(1))
            with open(file_path, 'rb') as f2:
                whole = f2.read()
                match2 = re.search(pattern, whole)
                if match2:
                    return int(match2.group(1))
    except Exception as e:
        logger.error(f"解析XMP失败: {e}")
    return 0

def find_last_ftyp_offset(file_path: str) -> int:
    try:
        with open(file_path, 'rb') as f:
            data = f.read()
        pattern = rb'....ftyp'
        matches = list(re.finditer(pattern, data))
        if matches:
            return matches[-1].start()
    except Exception as e:
        logger.error(f"搜索ftyp失败: {e}")
    return -1

def extract_video_data(file_path: str) -> Tuple[Optional[bytes], int]:
    if not os.path.exists(file_path):
        return None, 0
    total_size = os.path.getsize(file_path)
    video_len = get_video_length_from_xmp(file_path)
    if video_len > 0 and video_len < total_size:
        offset = total_size - video_len
        with open(file_path, 'rb') as f:
            f.seek(offset)
            video_data = f.read(video_len)
        if len(video_data) > 8 and video_data[4:8] == b'ftyp':
            return video_data, offset
        else:
            search_range = 1000
            start = max(0, offset - search_range)
            end = min(total_size, offset + search_range)
            with open(file_path, 'rb') as f:
                f.seek(start)
                chunk = f.read(end - start)
                pos = chunk.find(b'ftyp')
                if pos != -1:
                    real_offset = start + pos
                    with open(file_path, 'rb') as f2:
                        f2.seek(real_offset)
                        video_data = f2.read(total_size - real_offset)
                    return video_data, real_offset
    ftyp_offset = find_last_ftyp_offset(file_path)
    if ftyp_offset != -1:
        with open(file_path, 'rb') as f:
            f.seek(ftyp_offset)
            video_data = f.read(total_size - ftyp_offset)
        return video_data, ftyp_offset
    return None, 0

def save_temp_video(video_data: bytes) -> Optional[str]:
    try:
        fd, path = tempfile.mkstemp(suffix='.mp4', prefix='livephoto_')
        os.close(fd)
        with open(path, 'wb') as f:
            f.write(video_data)
        return path
    except Exception as e:
        logger.error(f"保存临时视频失败: {e}")
        return None


# ==================== 异步加载线程 ====================
class LoadImageThread(QThread):
    image_loaded = pyqtSignal(QPixmap, str)
    video_prepared = pyqtSignal(str, bool)
    finished_signal = pyqtSignal()

    def __init__(self, file_path):
        super().__init__()
        self.file_path = file_path

    def run(self):
        try:
            pixmap = QPixmap(self.file_path)
            if pixmap.isNull():
                from PIL import Image
                img = Image.open(self.file_path)
                img = img.convert("RGB")
                data = img.tobytes("raw", "RGB")
                qimage = QImage(data, img.width, img.height, QImage.Format_RGB888)
                pixmap = QPixmap.fromImage(qimage)
            if not pixmap.isNull():
                self.image_loaded.emit(pixmap, self.file_path)
            else:
                self.image_loaded.emit(QPixmap(), "")
        except Exception as e:
            logger.error(f"加载图片失败: {e}")
            self.image_loaded.emit(QPixmap(), "")

        video_data, _ = extract_video_data(self.file_path)
        if video_data:
            temp_path = save_temp_video(video_data)
            if temp_path:
                self.video_prepared.emit(temp_path, True)
            else:
                self.video_prepared.emit("", False)
        else:
            self.video_prepared.emit("", False)

        self.finished_signal.emit()


# ==================== 图片滚动视图 ====================
class ImageScrollView(QWidget):
    sig_previous = pyqtSignal()
    sig_next = pyqtSignal()
    sig_play_video = pyqtSignal()
    sig_open_file = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.zoom = 1.0
        self.image_pixmap = QPixmap()
        self.image_rect = QRect()
        self.drag_start = QPoint()
        self.dragging = False
        self.scroll_area = None
        self.setMinimumSize(100, 100)
        self.setMouseTracking(True)
        self.setStyleSheet("background-color: #2b2b2b;")
        self.setAcceptDrops(False)

    def set_pixmap(self, pixmap: QPixmap):
        self.image_pixmap = pixmap
        self.fit_to_window()
        self.update()

    def fit_to_window(self):
        if not self.scroll_area or self.image_pixmap.isNull():
            return
        view_size = self.scroll_area.viewport().size()
        self.zoom = min(view_size.width() / self.image_pixmap.width(),
                        view_size.height() / self.image_pixmap.height())
        self.update_image_rect()
        h_bar = self.scroll_area.horizontalScrollBar()
        v_bar = self.scroll_area.verticalScrollBar()
        h_bar.setValue(self.image_rect.center().x() - view_size.width() // 2)
        v_bar.setValue(self.image_rect.center().y() - view_size.height() // 2)

    def update_image_rect(self):
        if self.image_pixmap.isNull():
            return
        scaled = self.image_pixmap.scaled(self.image_pixmap.size() * self.zoom,
                                          Qt.KeepAspectRatio, Qt.SmoothTransformation)
        w, h = scaled.width(), scaled.height()
        x = (self.width() - w) // 2
        y = (self.height() - h) // 2
        self.image_rect = QRect(x, y, w, h)

    def wheelEvent(self, event: QWheelEvent):
        if self.image_pixmap.isNull() or not self.scroll_area:
            return
        mouse_pos = event.pos()
        h_bar = self.scroll_area.horizontalScrollBar()
        v_bar = self.scroll_area.verticalScrollBar()
        old_h = h_bar.value()
        old_v = v_bar.value()
        view_x = old_h + mouse_pos.x()
        view_y = old_v + mouse_pos.y()
        img_x = view_x - self.image_rect.x()
        img_y = view_y - self.image_rect.y()
        if self.image_rect.width() > 0 and self.image_rect.height() > 0:
            norm_x = max(0.0, min(1.0, img_x / self.image_rect.width()))
            norm_y = max(0.0, min(1.0, img_y / self.image_rect.height()))
        else:
            norm_x, norm_y = 0.5, 0.5
        factor = 1.05
        if event.angleDelta().y() > 0:
            self.zoom *= factor
        else:
            self.zoom /= factor
        self.zoom = max(0.1, min(self.zoom, 10.0))
        self.update_image_rect()
        new_img_x = norm_x * self.image_rect.width()
        new_img_y = norm_y * self.image_rect.height()
        new_view_x = self.image_rect.x() + new_img_x
        new_view_y = self.image_rect.y() + new_img_y
        new_h = new_view_x - mouse_pos.x()
        new_v = new_view_y - mouse_pos.y()
        h_bar.setValue(int(new_h))
        v_bar.setValue(int(new_v))
        self.update()
        event.accept()

    def mouseDoubleClickEvent(self, event: QMouseEvent):
        if event.button() == Qt.LeftButton and not self.image_pixmap.isNull():
            self.fit_to_window()
        super().mouseDoubleClickEvent(event)

    def mousePressEvent(self, event: QMouseEvent):
        if event.button() == Qt.LeftButton:
            if self.image_pixmap.isNull():
                self.sig_open_file.emit()
                return
            if self.scroll_area:
                auto_zoom = min(self.scroll_area.viewport().width() / max(1, self.image_pixmap.width()),
                                self.scroll_area.viewport().height() / max(1, self.image_pixmap.height()))
            else:
                auto_zoom = 1.0
            if abs(self.zoom - auto_zoom) < 0.01:
                pos = event.pos()
                if self.image_rect.contains(pos):
                    rel_x = (pos.x() - self.image_rect.x()) / self.image_rect.width()
                    if rel_x < 0.33:
                        self.sig_previous.emit()
                        return
                    elif rel_x > 0.67:
                        self.sig_next.emit()
                        return
                    else:
                        self.sig_play_video.emit()
                        return
            if self.zoom > auto_zoom:
                self.drag_start = event.pos()
                self.dragging = True
                self.setCursor(Qt.ClosedHandCursor)
        elif event.button() == Qt.RightButton:
            event.ignore()
            return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event: QMouseEvent):
        if self.dragging and self.scroll_area and not self.image_pixmap.isNull():
            delta = event.pos() - self.drag_start
            h_bar = self.scroll_area.horizontalScrollBar()
            v_bar = self.scroll_area.verticalScrollBar()
            h_bar.setValue(h_bar.value() - delta.x())
            v_bar.setValue(v_bar.value() - delta.y())
            self.drag_start = event.pos()
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event: QMouseEvent):
        if self.dragging:
            self.dragging = False
            self.setCursor(Qt.ArrowCursor)
        super().mouseReleaseEvent(event)

    def resizeEvent(self, event):
        if not self.scroll_area or self.image_pixmap.isNull():
            return
        auto_zoom = min(self.scroll_area.viewport().width() / max(1, self.image_pixmap.width()),
                        self.scroll_area.viewport().height() / max(1, self.image_pixmap.height()))
        if abs(self.zoom - auto_zoom) < 0.01:
            self.fit_to_window()
        else:
            self.update_image_rect()
        super().resizeEvent(event)

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.fillRect(self.rect(), self.palette().window())
        if not self.image_pixmap.isNull():
            scaled = self.image_pixmap.scaled(self.image_pixmap.size() * self.zoom,
                                              Qt.KeepAspectRatio, Qt.SmoothTransformation)
            painter.drawPixmap(self.image_rect.topLeft(), scaled)
        else:
            painter.setPen(Qt.white)
            painter.setBrush(QColor(0, 0, 0, 180))
            painter.setPen(Qt.NoPen)
            painter.drawRect(self.rect())
            painter.setPen(Qt.white)
            text_font = QFont("Microsoft YaHei", 10)
            painter.setFont(text_font)
            instructions = (
                "✨ 便捷操作指南 ✨\n\n"
                "📌 打开图片：拖拽文件 或 点击「打开文件」\n"
                "▶️ 播放实况：单击图片中间区域 / 点击「播放」按钮\n"
                "🖱️ 切换图片：单击图片左/右 1/3 区域\n"
                "🔍 缩放图片：鼠标滚轮（以光标为中心）\n"
                "✋ 拖动图片：放大后按住左键移动\n"
                "🔄 恢复大小：点击「恢复大小」\n"
                "🧹 初始状态：点击「初始状态」\n"
                "📋 文件列表：点击「显示列表」\n"
                "⚙️ 更多功能：右键菜单"
            )
            painter.drawText(self.rect(), Qt.AlignCenter, instructions)


# ==================== 主窗口 ====================
class LivePhotoPlayer(QMainWindow):
    def __init__(self, initial_file: Optional[str] = None):
        super().__init__()
        self.current_file = None
        self.current_dir = None
        self.file_list = []
        self.current_index = -1
        self.temp_video_path = None
        self.vlc_instance = None
        self.vlc_player = None
        self.is_playing = False
        self.video_extracted = False
        self.video_duration = 0
        self.photo_export_dir = "照片"
        self.video_export_dir = "视频"
        self.load_thread = None
        self.is_loading = False
        self.right_controls_fully_hidden = False
        self.load_seq = 0
        self._initializing = False
        self.video_cover_label = None
        self.is_live_photo = False
        self.auto_play_mode = config.get_auto_play()

        self.init_ui()
        self.init_tray()
        self.setup_vlc()
        self.create_shortcuts()
        self.setAcceptDrops(True)

        # 读取窗口大小（不读取位置）
        win_w, win_h = config.get_window_size()
        self.resize(win_w, win_h)
        # 强制居中显示
        screen_geom = QApplication.primaryScreen().geometry()
        center_x = (screen_geom.width() - win_w) // 2
        center_y = (screen_geom.height() - win_h) // 2
        self.move(center_x, center_y)
        logger.info(f"窗口居中: ({center_x}, {center_y}), 大小: {win_w}x{win_h}")

        speed_idx = config.get_speed_index()
        if hasattr(self, 'speed_combo') and self.speed_combo.count() > speed_idx:
            self.speed_combo.setCurrentIndex(speed_idx)
        mute_state = config.get_mute_state()
        if hasattr(self, 'mute_btn'):
            self.mute_btn.setChecked(mute_state)

        # 延迟加载初始文件（防止卡死）
        if initial_file and os.path.isfile(initial_file):
            QTimer.singleShot(100, lambda: self.load_file(initial_file))

        QTimer.singleShot(0, self._fix_initial_statusbar_layout)

    # ---------------------- UI 构建 ----------------------
    def init_ui(self):
        self.setWindowTitle("实况照片播放器 Copyright © XAF 2026.4")
        self.setMinimumSize(600, 480)
        self.set_window_icon()

        self.setStyleSheet("""
            QMainWindow {
                background-color: #f0f0f0;
            }
            QLabel, QPushButton, QComboBox, QListWidget {
                font-family: "Microsoft YaHei", "Segoe UI", "Segoe UI Emoji";
            }
            QPushButton {
                min-height: 32px;
                padding: 4px 12px;
            }
        """)

        self.stacked = QStackedWidget()
        self.setCentralWidget(self.stacked)

        self.image_scroll = QScrollArea()
        self.image_scroll.setWidgetResizable(True)
        self.image_scroll.setAlignment(Qt.AlignCenter)
        self.image_scroll.setStyleSheet("background-color: #e8e8e8; border: none;")
        self.image_view = ImageScrollView()
        self.image_view.scroll_area = self.image_scroll
        self.image_scroll.setWidget(self.image_view)
        self.stacked.addWidget(self.image_scroll)

        self.video_frame = QFrame()
        self.video_frame.setStyleSheet("background-color: black; border: none;")
        self.video_cover_label = QLabel(self.video_frame)
        self.video_cover_label.setAlignment(Qt.AlignCenter)
        self.video_cover_label.setStyleSheet("""
            background-color: black;
            color: white;
            font-size: 24px;
            font-weight: bold;
            qproperty-alignment: AlignCenter;
        """)
        self.video_cover_label.setScaledContents(True)
        self.load_video_cover_image()
        self.video_cover_label.mousePressEvent = self.on_cover_mouse_press
        self.video_cover_label.mouseDoubleClickEvent = self.on_cover_mouse_double_click
        self.video_cover_label.setContextMenuPolicy(Qt.CustomContextMenu)
        self.video_cover_label.customContextMenuRequested.connect(self.show_cover_context_menu)
        self.video_cover_label.setVisible(False)

        self.video_frame.mousePressEvent = self.on_video_frame_mouse_press
        self.video_frame.setContextMenuPolicy(Qt.CustomContextMenu)
        self.video_frame.customContextMenuRequested.connect(self.show_video_context_menu)

        self.stacked.addWidget(self.video_frame)

        self.file_dock = QDockWidget("文件列表", self)
        self.file_dock.setAllowedAreas(Qt.LeftDockWidgetArea | Qt.RightDockWidgetArea)
        self.file_dock.setFixedWidth(160)
        self.file_list_widget = QListWidget()
        self.file_list_widget.itemClicked.connect(self.on_file_list_clicked)
        self.file_list_widget.setSelectionMode(QListWidget.SingleSelection)
        self.file_dock.setWidget(self.file_list_widget)
        self.addDockWidget(Qt.LeftDockWidgetArea, self.file_dock)
        self.file_dock.hide()

        self.create_toolbar()
        self.create_statusbar()

        self.image_view.sig_previous.connect(self.previous_image)
        self.image_view.sig_next.connect(self.next_image)
        self.image_view.sig_play_video.connect(self.toggle_play)
        self.image_view.sig_open_file.connect(self.open_file_dialog)

    def load_video_cover_image(self):
        if not self.video_cover_label:
            return
        self.video_cover_label.resize(self.video_frame.size())
        cover_path = self.resource_path("cover/video.png")
        if os.path.exists(cover_path):
            pixmap = QPixmap(cover_path)
            if not pixmap.isNull():
                scaled = pixmap.scaled(self.video_cover_label.size(), Qt.IgnoreAspectRatio, Qt.SmoothTransformation)
                self.video_cover_label.setPixmap(scaled)
                self.video_cover_label.setText("")
                return
        self.video_cover_label.setPixmap(QPixmap())
        self.video_cover_label.setText("🎬 点击播放视频")

    def on_cover_mouse_press(self, event):
        if event.button() == Qt.LeftButton:
            if self.video_extracted and self.temp_video_path:
                self.toggle_play()
        elif event.button() == Qt.RightButton:
            event.ignore()
        super().mousePressEvent(event)

    def on_cover_mouse_double_click(self, event):
        if event.button() == Qt.RightButton:
            self.close_current_video()
        event.accept()

    def show_cover_context_menu(self, pos):
        menu = QMenu()
        menu.addAction("打开文件", self.open_file_dialog)
        menu.addAction("初始状态", self.initialize_app)
        menu.addAction("关闭视频", self.close_current_video)
        menu.addAction("退出", self.quit_app)
        menu.exec_(self.video_cover_label.mapToGlobal(pos))

    def on_video_frame_mouse_press(self, event):
        if event.button() == Qt.LeftButton:
            self.toggle_play()
        elif event.button() == Qt.RightButton:
            self.stop_playback_async()
        event.accept()

    def show_video_context_menu(self, pos):
        menu = QMenu()
        menu.addAction("打开文件", self.open_file_dialog)
        menu.addAction("初始状态", self.initialize_app)
        menu.addAction("关闭视频", self.close_current_video)
        menu.addAction("退出", self.quit_app)
        menu.exec_(self.video_frame.mapToGlobal(pos))

    def close_current_video(self):
        if self.video_extracted:
            self.stop_playback_async()
            self.cleanup_video()
            self.current_file = None
            self.video_extracted = False
            self.is_live_photo = False
            self.temp_video_path = None
            self.stacked.setCurrentWidget(self.image_scroll)
            self.status_text.setText("✅ 已关闭视频")
            self.show_temp_message("已关闭视频", 1500)
            self.play_pause_btn.setEnabled(False)
            self.play_pause_btn.setText("▶️ 播放")
        else:
            self.show_temp_message("没有打开的视频", 1000)

    def _fix_initial_statusbar_layout(self):
        width = self.statusBar().width()
        self._update_right_controls_visibility(width)

    def _update_right_controls_visibility(self, width):
        if getattr(self, 'loading_hide_right', False):
            return
        speed_visible = width >= 650
        mute_visible = width >= 750
        if hasattr(self, 'speed_label'):
            self.speed_label.setVisible(speed_visible)
        if hasattr(self, 'speed_combo'):
            self.speed_combo.setVisible(speed_visible)
        if hasattr(self, 'mute_btn'):
            self.mute_btn.setVisible(mute_visible)
        self.right_controls_fully_hidden = (not speed_visible) and (not mute_visible)

    def set_window_icon(self):
        icon_path = self.resource_path("app.ico")
        if os.path.exists(icon_path):
            icon = QtGui.QIcon(icon_path)
            self.setWindowIcon(icon)
            QApplication.setWindowIcon(icon)
            if sys.platform == 'win32':
                try:
                    ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID('LivePhotoPlayer.1.0')
                except:
                    pass
            logger.info("图标已加载")
        else:
            logger.warning(f"未找到图标: {icon_path}")

    def resource_path(self, relative):
        if getattr(sys, 'frozen', False):
            return os.path.join(sys._MEIPASS, relative)
        return os.path.join(os.path.dirname(os.path.abspath(__file__)), relative)

    def create_toolbar(self):
        toolbar = self.addToolBar("工具栏")
        toolbar.setMovable(False)
        toolbar.setStyleSheet("QToolBar { spacing: 8px; }")

        self.open_file_btn = QAction("打开文件", self)
        self.open_file_btn.triggered.connect(self.open_file_dialog)
        toolbar.addAction(self.open_file_btn)

        self.toggle_list_btn = QAction("显示列表", self)
        self.toggle_list_btn.triggered.connect(self.toggle_file_list)
        toolbar.addAction(self.toggle_list_btn)

        toolbar.addSeparator()

        self.export_photo_btn = QAction("导出照片", self)
        self.export_photo_btn.triggered.connect(self.export_photo)
        toolbar.addAction(self.export_photo_btn)

        self.export_video_btn = QAction("导出视频", self)
        self.export_video_btn.triggered.connect(self.export_video)
        toolbar.addAction(self.export_video_btn)

        self.open_photo_btn = QAction("打开照片", self)
        self.open_photo_btn.triggered.connect(self.open_photo_folder)
        toolbar.addAction(self.open_photo_btn)

        self.open_video_btn = QAction("打开视频", self)
        self.open_video_btn.triggered.connect(self.open_video_folder)
        toolbar.addAction(self.open_video_btn)

        toolbar.addSeparator()

        self.reset_size_btn = QAction("恢复大小", self)
        self.reset_size_btn.triggered.connect(self.reset_to_initial_state)
        toolbar.addAction(self.reset_size_btn)

        self.init_state_btn = QAction("初始状态", self)
        self.init_state_btn.triggered.connect(self.initialize_app)
        toolbar.addAction(self.init_state_btn)

        toolbar.addSeparator()

        self.msg_label = QLabel("")
        self.msg_label.setFixedWidth(150)
        toolbar.addWidget(self.msg_label)

        self.file_info_label = QLabel("")
        self.file_info_label.setFixedWidth(360)
        toolbar.addWidget(self.file_info_label)

        spacer = QWidget()
        spacer.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        toolbar.addWidget(spacer)

    def create_statusbar(self):
        status = self.statusBar()
        status.setStyleSheet("QStatusBar { background-color: #dcdcdc; } QStatusBar::item { border: none; }")
        self.status_text = QLabel("✅ 就绪")
        self.status_text.setFixedWidth(220)
        status.addWidget(self.status_text)

        btn_widget = QWidget()
        btn_layout = QHBoxLayout()
        btn_layout.setContentsMargins(10, 8, 10, 8)
        btn_layout.setSpacing(20)

        self.prev_btn = QPushButton("上一张")
        self.prev_btn.setMinimumHeight(36)
        self.prev_btn.clicked.connect(self.previous_image)
        self.next_btn = QPushButton("下一张")
        self.next_btn.setMinimumHeight(36)
        self.next_btn.clicked.connect(self.next_image)
        emoji_font = QFont("Segoe UI Emoji", 10)
        self.play_pause_btn = QPushButton("▶️ 播放")
        self.play_pause_btn.setFont(emoji_font)
        self.play_pause_btn.setMinimumHeight(36)
        self.play_pause_btn.clicked.connect(self.toggle_play)
        self.stop_btn = QPushButton("⏹️ 停止")
        self.stop_btn.setFont(emoji_font)
        self.stop_btn.setMinimumHeight(36)
        self.stop_btn.clicked.connect(self.stop_playback_async)

        btn_layout.addWidget(self.prev_btn)
        btn_layout.addWidget(self.next_btn)
        btn_layout.addWidget(self.play_pause_btn)
        btn_layout.addWidget(self.stop_btn)
        btn_widget.setLayout(btn_layout)
        status.addWidget(btn_widget, 1)

        self.right_container = QWidget()
        right_layout = QHBoxLayout()
        right_layout.setContentsMargins(0, 0, 10, 0)
        right_layout.setSpacing(8)

        self.right_controls_widget = QWidget()
        controls_layout = QHBoxLayout()
        controls_layout.setContentsMargins(0, 0, 0, 0)
        controls_layout.setSpacing(8)

        self.speed_label = QLabel("速度:")
        self.speed_label.setObjectName("speed_label")
        self.speed_combo = QComboBox()
        self.speed_combo.setObjectName("speed_combo")
        for s in ["0.25", "0.5", "0.75", "1", "1.25", "1.5", "2"]:
            self.speed_combo.addItem(s)
        self.speed_combo.setCurrentText("1")
        self.speed_combo.currentTextChanged.connect(self.on_speed_changed)

        self.mute_btn = QPushButton("🔊 有声")
        self.mute_btn.setObjectName("mute_btn")
        self.mute_btn.setCheckable(True)
        self.mute_btn.toggled.connect(self.on_mute_toggled)

        controls_layout.addWidget(self.speed_label)
        controls_layout.addWidget(self.speed_combo)
        controls_layout.addWidget(self.mute_btn)
        self.right_controls_widget.setLayout(controls_layout)

        self.progress_bar = QProgressBar()
        self.progress_bar.setMaximum(0)
        self.progress_bar.setMinimum(0)
        self.progress_bar.setFixedHeight(8)
        self.progress_bar.setVisible(False)

        right_layout.addWidget(self.right_controls_widget)
        right_layout.addWidget(self.progress_bar)
        self.right_container.setLayout(right_layout)
        status.addPermanentWidget(self.right_container)

        self.statusBar().installEventFilter(self)

    def eventFilter(self, obj, event):
        if obj == self.statusBar() and event.type() == event.Resize:
            width = self.statusBar().width()
            if not getattr(self, 'loading_hide_right', False):
                self._update_right_controls_visibility(width)
        return super().eventFilter(obj, event)

    def _hide_right_controls_for_loading(self):
        self.loading_hide_right = True
        if self.right_controls_fully_hidden:
            self.progress_bar.setVisible(False)
            self.right_controls_widget.setVisible(False)
            return
        ctrl_width = self.right_controls_widget.width()
        if ctrl_width > 0:
            self.progress_bar.setMinimumWidth(ctrl_width)
            self.progress_bar.setMaximumWidth(ctrl_width)
        else:
            self.progress_bar.setMinimumWidth(0)
            self.progress_bar.setMaximumWidth(16777215)
        self.right_controls_widget.setVisible(False)
        self.progress_bar.setVisible(True)

    def _restore_right_controls_after_loading(self):
        self.loading_hide_right = False
        self.progress_bar.setVisible(False)
        self.progress_bar.setMinimumWidth(0)
        self.progress_bar.setMaximumWidth(16777215)
        self.right_controls_widget.setVisible(True)
        width = self.statusBar().width()
        self._update_right_controls_visibility(width)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if not self._initializing:
            config.set_window_size(self.width(), self.height())
        if self.video_cover_label:
            self.video_cover_label.resize(self.video_frame.size())
            if self.video_cover_label.isVisible():
                self.load_video_cover_image()

    # 不再保存窗口位置
    # def moveEvent(self, event):
    #     super().moveEvent(event)
    #     if not self._initializing:
    #         config.set_window_pos(self.x(), self.y())

    def on_speed_changed(self, text):
        idx = self.speed_combo.currentIndex()
        config.set_speed_index(idx)
        if self.vlc_player:
            rate = float(text)
            self.vlc_player.set_rate(rate)

    def on_mute_toggled(self, checked):
        config.set_mute_state(checked)
        if self.vlc_player:
            self.vlc_player.audio_set_mute(checked)
            self.mute_btn.setText("🔇 静音" if checked else "🔊 有声")

    # ---------------------- 初始状态 ----------------------
    def initialize_app(self):
        QTimer.singleShot(0, self._do_initialize)

    def _do_initialize(self):
        self._initializing = True
        self.load_seq += 1
        if self.load_thread and self.load_thread.isRunning():
            try:
                self.load_thread.image_loaded.disconnect()
                self.load_thread.video_prepared.disconnect()
                self.load_thread.finished_signal.disconnect()
            except:
                pass
            self.load_thread.quit()
            self.load_thread.wait(500)
        self.load_thread = None
        self.is_loading = False

        self.cleanup_video()
        self.current_file = None
        self.current_dir = None
        self.file_list = []
        self.current_index = -1
        self.temp_video_path = None
        self.is_playing = False
        self.video_extracted = False
        self.is_live_photo = False
        self.video_duration = 0

        self.file_list_widget.clear()
        if self.file_dock.isVisible():
            self.file_dock.hide()
            self.toggle_list_btn.setText("显示列表")

        self.image_view.set_pixmap(QPixmap())
        self.file_info_label.setText("")
        self.status_text.setText("✅ 就绪")
        self.play_pause_btn.setEnabled(False)
        self.play_pause_btn.setText("▶️ 播放")
        self.msg_label.setText("")
        self.stacked.setCurrentWidget(self.image_scroll)

        # 重置窗口大小到默认并居中
        default_w, default_h = 800, 600
        self.resize(default_w, default_h)
        screen = QApplication.primaryScreen().geometry()
        default_x = (screen.width() - default_w) // 2
        default_y = (screen.height() - default_h) // 2
        self.move(default_x, default_y)
        config.set_window_size(default_w, default_h)
        # 不保存位置

        default_speed_idx = 3
        self.speed_combo.setCurrentIndex(default_speed_idx)
        config.set_speed_index(default_speed_idx)
        self.mute_btn.setChecked(False)
        config.set_mute_state(False)
        self.mute_btn.setText("🔊 有声")

        self.setup_vlc()
        self.setCursor(QCursor(Qt.ArrowCursor))
        self.update()
        self._initializing = False
        logger.info("软件已初始化到刚打开状态")
        self.show_temp_message("已初始化为初始状态", 2000)

    # ---------------------- 恢复大小 ----------------------
    def reset_to_initial_state(self):
        if self.stacked.currentWidget() == self.video_frame and not self.is_live_photo:
            if self.is_playing:
                self.stop_playback_async()
            else:
                self.stacked.setCurrentWidget(self.image_scroll)
        if self.image_view.image_pixmap and not self.image_view.image_pixmap.isNull():
            self.image_view.fit_to_window()
            self.status_text.setText("✅ 已恢复照片大小")
            self.show_temp_message("已恢复照片大小", 1500)
            self.image_view.update()
        else:
            self.show_temp_message("没有照片可恢复", 1000)

    # ---------------------- 系统托盘 ----------------------
    def init_tray(self):
        self.tray_icon = QtWidgets.QSystemTrayIcon(self)
        icon_path = self.resource_path("app.ico")
        if os.path.exists(icon_path):
            self.tray_icon.setIcon(QtGui.QIcon(icon_path))
        tray_menu = QMenu()
        restore = QAction("显示主窗口", self)
        restore.triggered.connect(self.show_window)
        quit_act = QAction("退出", self)
        quit_act.triggered.connect(lambda: QTimer.singleShot(0, self.quit_app))
        tray_menu.addAction(restore)
        tray_menu.addAction(quit_act)
        self.tray_icon.setContextMenu(tray_menu)
        self.tray_icon.activated.connect(self.on_tray_activated)
        self.tray_icon.show()
        logger.info("系统托盘已初始化")

    def on_tray_activated(self, reason):
        if reason == QtWidgets.QSystemTrayIcon.DoubleClick:
            self.show_window()

    def show_window(self):
        self.showNormal()
        self.activateWindow()
        self.raise_()

    def quit_app(self):
        self.cleanup_video()
        QApplication.quit()

    def closeEvent(self, event):
        event.ignore()
        self.hide()
        self.tray_icon.showMessage("实况照片播放器", "程序已最小化到系统托盘",
                                   QtWidgets.QSystemTrayIcon.Information, 1000)

    # ---------------------- VLC 相关（异步停止） ----------------------
    def setup_vlc(self):
        try:
            if self.vlc_player:
                self.vlc_player.stop()
                self.vlc_player.release()
            if self.vlc_instance:
                self.vlc_instance.release()
            plugins_path = os.path.join(vlc_dir, 'plugins')
            self.vlc_instance = vlc.Instance(f'--plugin-path={plugins_path}')
            self.vlc_player = self.vlc_instance.media_player_new()
            if self.video_frame.winId():
                self.vlc_player.set_hwnd(int(self.video_frame.winId()))
        except Exception as e:
            logger.error(f"VLC初始化失败: {e}")
            self.status_text.setText("❌ VLC引擎错误")

    def cleanup_video(self):
        if self.vlc_player:
            self.vlc_player.stop()
        if self.temp_video_path and os.path.exists(self.temp_video_path):
            try:
                os.unlink(self.temp_video_path)
            except:
                pass
            self.temp_video_path = None
        self.setup_vlc()
        self.is_playing = False
        self.video_extracted = False
        self.play_pause_btn.setText("▶️ 播放")
        if self.video_cover_label:
            self.video_cover_label.setVisible(False)

    def stop_playback_async(self):
        QTimer.singleShot(0, self._do_stop_playback)

    def _do_stop_playback(self):
        try:
            if self.vlc_player:
                self.vlc_player.stop()
                self.vlc_player.set_position(0.0)
            self.is_playing = False
            self.play_pause_btn.setText("▶️ 播放")
            if self.is_live_photo:
                self.stacked.setCurrentWidget(self.image_scroll)
                self.status_text.setText("✅ 已停止")
            else:
                self.stacked.setCurrentWidget(self.video_frame)
                self.status_text.setText("⏹️ 已停止")
                if self.video_cover_label:
                    self.video_cover_label.setVisible(True)
                    self.load_video_cover_image()
        except Exception as e:
            logger.error(f"停止播放异常: {e}")

    def toggle_play(self):
        if not self.video_extracted or not self.temp_video_path:
            self.show_temp_message("无视频", 2000)
            return

        if self.is_live_photo:
            if self.is_playing:
                self.vlc_player.pause()
                self.is_playing = False
                self.play_pause_btn.setText("▶️ 播放")
                self.status_text.setText("⏸️ 已暂停")
            else:
                self.stacked.setCurrentWidget(self.video_frame)
                if self.video_frame.winId():
                    self.vlc_player.set_hwnd(int(self.video_frame.winId()))
                state = self.vlc_player.get_state()
                if state in (vlc.State.Ended, vlc.State.Stopped):
                    media = self.vlc_instance.media_new(self.temp_video_path)
                    self.vlc_player.set_media(media)
                    self.vlc_player.set_position(0.0)
                self.vlc_player.play()
                self.is_playing = True
                self.play_pause_btn.setText("⏸️ 暂停")
                self.status_text.setText("▶️ 播放中...")
                self.vlc_player.event_manager().event_attach(vlc.EventType.MediaPlayerEndReached, self.on_playback_end)
            return

        # 外部视频
        if self.video_cover_label.isVisible():
            self.video_cover_label.setVisible(False)
            self.vlc_player.play()
            self.is_playing = True
            self.play_pause_btn.setText("⏸️ 暂停")
            self.status_text.setText("▶️ 播放中...")
            self.vlc_player.event_manager().event_attach(vlc.EventType.MediaPlayerEndReached, self.on_playback_end)
        else:
            if self.is_playing:
                self.vlc_player.pause()
                self.is_playing = False
                self.play_pause_btn.setText("▶️ 播放")
                self.status_text.setText("⏸️ 已暂停")
            else:
                self.stacked.setCurrentWidget(self.video_frame)
                if self.video_frame.winId():
                    self.vlc_player.set_hwnd(int(self.video_frame.winId()))
                state = self.vlc_player.get_state()
                if state in (vlc.State.Ended, vlc.State.Stopped):
                    media = self.vlc_instance.media_new(self.temp_video_path)
                    self.vlc_player.set_media(media)
                    self.vlc_player.set_position(0.0)
                self.vlc_player.play()
                self.is_playing = True
                self.play_pause_btn.setText("⏸️ 暂停")
                self.status_text.setText("▶️ 播放中...")
                self.vlc_player.event_manager().event_attach(vlc.EventType.MediaPlayerEndReached, self.on_playback_end)

    def on_playback_end(self, event):
        QtCore.QMetaObject.invokeMethod(self, "_on_playback_end_ui", QtCore.Qt.QueuedConnection)

    @QtCore.pyqtSlot()
    def _on_playback_end_ui(self):
        self.is_playing = False
        self.play_pause_btn.setText("▶️ 播放")
        if self.is_live_photo:
            self.stacked.setCurrentWidget(self.image_scroll)
            self.status_text.setText("✅ 播放结束")
        else:
            self.stop_playback_async()

    # ---------------------- 关闭照片（保留） ----------------------
    def close_current_photo(self):
        if self.current_file:
            self.cleanup_video()
            self.current_file = None
            self.current_dir = None
            self.file_list = []
            self.current_index = -1
            self.file_list_widget.clear()
            self.image_view.set_pixmap(QPixmap())
            self.file_info_label.setText("")
            self.status_text.setText("✅ 已关闭照片")
            self.show_temp_message("已关闭照片", 1500)
            self.play_pause_btn.setEnabled(False)
            self.is_live_photo = False
        else:
            self.show_temp_message("没有打开的照片", 1000)

    # ---------------------- 打开文件夹 ----------------------
    def open_photo_folder(self):
        base_dir = os.path.dirname(sys.executable) if getattr(sys, 'frozen', False) else os.getcwd()
        folder = os.path.join(base_dir, self.photo_export_dir)
        if not os.path.exists(folder):
            os.makedirs(folder)
        os.startfile(folder)
        self.show_temp_message("已打开照片文件夹")

    def open_video_folder(self):
        base_dir = os.path.dirname(sys.executable) if getattr(sys, 'frozen', False) else os.getcwd()
        folder = os.path.join(base_dir, self.video_export_dir)
        if not os.path.exists(folder):
            os.makedirs(folder)
        os.startfile(folder)
        self.show_temp_message("已打开视频文件夹")

    # ---------------------- 文件加载（图片） ----------------------
    def load_file(self, path):
        if self.video_extracted:
            self.stop_playback_async()
            self.cleanup_video()
            self.current_file = None
            self.video_extracted = False
            self.is_live_photo = False
            self.stacked.setCurrentWidget(self.image_scroll)
        if self.is_loading:
            self.show_temp_message("正在加载中，请稍后...")
            return
        path = os.path.abspath(path)
        if not os.path.exists(path):
            return
        self.load_seq += 1
        current_seq = self.load_seq

        self.current_file = path
        self.current_dir = os.path.dirname(path)
        config.set_last_dir(self.current_dir)
        self.refresh_file_list()
        self.is_loading = True
        self._hide_right_controls_for_loading()
        self.setCursor(QCursor(Qt.WaitCursor))
        self.status_text.setText("⏳ 加载中...")
        self.is_live_photo = True

        self.load_thread = LoadImageThread(path)
        self.load_thread.image_loaded.connect(lambda pixmap, fp, seq=current_seq: self._on_image_loaded(pixmap, fp, seq))
        self.load_thread.video_prepared.connect(lambda tp, ok, seq=current_seq: self._on_video_prepared(tp, ok, seq))
        self.load_thread.finished_signal.connect(lambda seq=current_seq: self._on_load_finished(seq))
        self.load_thread.start()

    def _on_image_loaded(self, pixmap, file_path, seq):
        if seq != self.load_seq:
            return
        # 自动播放模式下，仍然设置图片（但不切换到图片视图），以便播放结束后能显示
        if self.auto_play_mode and self.is_live_photo:
            if not pixmap.isNull():
                self.image_view.set_pixmap(pixmap)  # 设置图片，但不切换页面
                self.update_file_info_label(file_path)
            else:
                self.status_text.setText("❌ 图片加载失败")
            return
        # 手动播放模式，正常显示图片
        if not pixmap.isNull():
            self.image_view.set_pixmap(pixmap)
            self.stacked.setCurrentWidget(self.image_scroll)
            self.update_file_info_label(file_path)
        else:
            self.status_text.setText("❌ 图片加载失败")

    def _on_video_prepared(self, temp_path, success, seq):
        if seq != self.load_seq:
            if temp_path and os.path.exists(temp_path) and temp_path != self.current_file:
                try:
                    os.unlink(temp_path)
                except:
                    pass
            return
        if success:
            self.temp_video_path = temp_path
            self.video_extracted = True
            self.play_pause_btn.setEnabled(True)
            media = self.vlc_instance.media_new(self.temp_video_path)
            self.vlc_player.set_media(media)
            media.parse()
            self.video_duration = media.get_duration()
            self.status_text.setText(f"✅ 实况视频就绪 ({self.video_duration//1000}秒)")
            # 自动播放模式下，直接播放视频
            if self.auto_play_mode and self.is_live_photo:
                QTimer.singleShot(10, self.toggle_play)  # 极短延迟确保UI稳定
        else:
            self.video_extracted = False
            self.play_pause_btn.setEnabled(False)
            self.status_text.setText("⚠️ 未检测到实况视频")
            # 如果自动播放模式下无视频，且之前没有显示图片，则显示图片
            if self.auto_play_mode and self.is_live_photo:
                self.stacked.setCurrentWidget(self.image_scroll)

    def _on_load_finished(self, seq):
        if seq != self.load_seq:
            return
        self.is_loading = False
        self._restore_right_controls_after_loading()
        self.setCursor(QCursor(Qt.ArrowCursor))
        self.load_thread = None

    def refresh_file_list(self):
        if not self.current_dir:
            return
        extensions = ('.jpg', '.jpeg', '.heic', '.png', '.bmp', '.tiff')
        files = [f for f in os.listdir(self.current_dir) if f.lower().endswith(extensions)]
        files.sort()
        self.file_list = [os.path.join(self.current_dir, f) for f in files]
        self.file_list_widget.clear()
        current_base = os.path.basename(self.current_file) if self.current_file else ""
        for idx, full in enumerate(self.file_list):
            item = QListWidgetItem(os.path.basename(full))
            if os.path.basename(full) == current_base:
                item.setSelected(True)
                self.current_index = idx
            self.file_list_widget.addItem(item)

    def on_file_list_clicked(self, item):
        idx = self.file_list_widget.row(item)
        if 0 <= idx < len(self.file_list):
            self.load_file(self.file_list[idx])

    def previous_image(self):
        if self.current_index > 0:
            self.load_file(self.file_list[self.current_index - 1])
        else:
            self.show_temp_message("已是第一张图片")

    def next_image(self):
        if self.current_index < len(self.file_list) - 1:
            self.load_file(self.file_list[self.current_index + 1])
        else:
            self.show_temp_message("已是最后一张图片")

    def update_file_info_label(self, path):
        try:
            name = os.path.basename(path)
            size = os.path.getsize(path) / 1024
            size_str = f"{size:.1f} KB" if size < 1024 else f"{size/1024:.1f} MB"
            from PIL import Image
            from PIL.ExifTags import TAGS
            img = Image.open(path)
            exif = img._getexif()
            date = ""
            if exif:
                for tag, val in exif.items():
                    if TAGS.get(tag) == 'DateTime':
                        date = val
                        break
            info = f"{name} | {size_str}"
            if date:
                info += f" | {date}"
            self.file_info_label.setText(info)
        except Exception as e:
            self.file_info_label.setText(os.path.basename(path))

    # ---------------------- 导出功能 ----------------------
    def _generate_export_filename(self, original_path, suffix_type):
        base = os.path.splitext(os.path.basename(original_path))[0]
        now = datetime.now().strftime("%H%M%S")
        rand4 = ''.join(random.choices(string.digits, k=4))
        if suffix_type == "photo":
            ext = os.path.splitext(original_path)[1]
            if ext.lower() == '.heic':
                ext = '.jpg'
            return f"{base}_photo_{now}_{rand4}{ext}"
        else:
            return f"{base}_video_{now}_{rand4}.mp4"

    def export_photo(self):
        if not self.current_file:
            self.show_temp_message("没有打开的照片")
            return
        base_dir = os.path.dirname(sys.executable) if getattr(sys, 'frozen', False) else os.getcwd()
        export_dir = os.path.join(base_dir, self.photo_export_dir)
        os.makedirs(export_dir, exist_ok=True)
        src = self.current_file
        ext = os.path.splitext(src)[1].lower()
        dest_filename = self._generate_export_filename(src, "photo")
        dest = os.path.join(export_dir, dest_filename)
        try:
            if ext == '.heic':
                from PIL import Image
                img = Image.open(src)
                img = img.convert("RGB")
                img.save(dest, "JPEG")
            else:
                shutil.copy2(src, dest)
            self.show_temp_message(f"照片已导出: {dest_filename}")
            logger.info(f"导出照片: {dest}")
        except Exception as e:
            logger.error(f"导出照片失败: {e}")
            self.show_temp_message("导出照片失败")

    def export_video(self):
        if not self.video_extracted or not self.temp_video_path:
            self.show_temp_message("无视频可导出")
            return
        base_dir = os.path.dirname(sys.executable) if getattr(sys, 'frozen', False) else os.getcwd()
        export_dir = os.path.join(base_dir, self.video_export_dir)
        os.makedirs(export_dir, exist_ok=True)
        dest_filename = self._generate_export_filename(self.current_file, "video")
        dest = os.path.join(export_dir, dest_filename)
        try:
            shutil.copy2(self.temp_video_path, dest)
            self.show_temp_message(f"视频已导出: {dest_filename}")
            logger.info(f"导出视频: {dest}")
        except Exception as e:
            logger.error(f"导出视频失败: {e}")
            self.show_temp_message("导出视频失败")

    def toggle_file_list(self):
        if self.file_dock.isVisible():
            self.file_dock.hide()
            self.toggle_list_btn.setText("显示列表")
        else:
            self.file_dock.show()
            self.toggle_list_btn.setText("隐藏列表")

    def show_temp_message(self, msg, timeout=3000):
        self.msg_label.setText(msg)
        QTimer.singleShot(timeout, lambda: self.msg_label.setText(""))

    # ---------------------- 快捷键 ----------------------
    def create_shortcuts(self):
        QShortcut(Qt.Key_Left, self, self.previous_image, context=Qt.ApplicationShortcut)
        QShortcut(Qt.Key_Up, self, self.previous_image, context=Qt.ApplicationShortcut)
        QShortcut(Qt.Key_Right, self, self.next_image, context=Qt.ApplicationShortcut)
        QShortcut(Qt.Key_Down, self, self.next_image, context=Qt.ApplicationShortcut)
        QShortcut(Qt.Key_Return, self, self.toggle_play, context=Qt.ApplicationShortcut)
        QShortcut(Qt.Key_Enter, self, self.toggle_play, context=Qt.ApplicationShortcut)

    # ---------------------- 右键菜单 ----------------------
    def contextMenuEvent(self, event):
        menu = QMenu(self)

        menu.addAction("打开文件", self.open_file_dialog)
        menu.addAction("恢复大小", self.reset_to_initial_state)
        menu.addAction("初始状态", self.initialize_app)
        menu.addAction("关闭照片", self.close_current_photo)
        menu.addSeparator()
        menu.addAction("上一张", self.previous_image)
        menu.addAction("下一张", self.next_image)

        # 自动播放/点击播放切换项
        if self.auto_play_mode:
            auto_play_action = QAction("点击播放", self)
            auto_play_action.setToolTip("切换为点击播放（手动播放）")
            auto_play_action.triggered.connect(self.toggle_auto_play)
        else:
            auto_play_action = QAction("自动播放", self)
            auto_play_action.setToolTip("切换为自动播放（切换照片时自动播放实况）")
            auto_play_action.triggered.connect(self.toggle_auto_play)
        menu.addAction(auto_play_action)

        menu.addSeparator()
        menu.addAction("导出照片", self.export_photo)
        menu.addAction("导出视频", self.export_video)
        menu.addSeparator()
        menu.addAction("打开照片", self.open_photo_folder)
        menu.addAction("打开视频", self.open_video_folder)
        menu.addSeparator()
        menu.addAction("显示列表" if not self.file_dock.isVisible() else "隐藏列表", self.toggle_file_list)
        menu.addAction("退出", self.quit_app)
        menu.exec_(event.globalPos())

    def toggle_auto_play(self):
        self.auto_play_mode = not self.auto_play_mode
        config.set_auto_play(self.auto_play_mode)
        mode_text = "自动播放" if self.auto_play_mode else "点击播放"
        self.show_temp_message(f"已切换为{mode_text}模式", 2000)
        logger.info(f"自动播放模式切换为: {mode_text}")

    # ---------------------- 文件对话框 ----------------------
    def open_file_dialog(self):
        last_dir = config.get_last_dir()
        if not last_dir or not os.path.exists(last_dir):
            last_dir = ""
        path, _ = QFileDialog.getOpenFileName(self, "打开媒体", last_dir,
                                               "图片文件 (*.jpg *.jpeg *.heic *.png *.bmp *.tiff);;视频文件 (*.mp4 *.avi *.mkv *.mov)")
        if path:
            ext = os.path.splitext(path)[1].lower()
            if ext in ('.mp4', '.avi', '.mkv', '.mov'):
                self.load_video_file(path)
            else:
                self.load_file(path)

    # ---------------------- 拖拽事件 ----------------------
    def dragEnterEvent(self, event):
        if event.mimeData().hasUrls():
            event.acceptProposedAction()

    def dropEvent(self, event):
        urls = event.mimeData().urls()
        if urls:
            file_path = urls[0].toLocalFile()
            if file_path and os.path.isfile(file_path):
                ext = os.path.splitext(file_path)[1].lower()
                if ext in ('.mp4', '.avi', '.mkv', '.mov'):
                    self.load_video_file(file_path)
                else:
                    self.load_file(file_path)

    # ---------------------- 直接加载视频文件（外部视频） ----------------------
    def load_video_file(self, path):
        if self.video_extracted or self.current_file:
            self.stop_playback_async()
            self.cleanup_video()
            self.current_file = None
            self.video_extracted = False
            self.image_view.set_pixmap(QPixmap())
            self.is_live_photo = False

        self.current_file = path
        self.current_dir = os.path.dirname(path)
        config.set_last_dir(self.current_dir)
        self.temp_video_path = path
        self.video_extracted = True
        self.is_live_photo = False
        self.play_pause_btn.setEnabled(True)
        media = self.vlc_instance.media_new(path)
        self.vlc_player.set_media(media)
        media.parse()
        self.video_duration = media.get_duration()
        self.status_text.setText(f"✅ 视频已加载 ({self.video_duration//1000}秒)")
        self.show_temp_message(f"已加载视频: {os.path.basename(path)}", 2000)
        self.stacked.setCurrentWidget(self.video_frame)
        self.video_cover_label.setVisible(True)
        self.load_video_cover_image()
        self.play_pause_btn.setText("▶️ 播放")
        self.is_playing = False


def main():
    app = QApplication(sys.argv)
    app.setQuitOnLastWindowClosed(False)
    if sys.platform == 'win32':
        try:
            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID('LivePhotoPlayer.1.0')
        except:
            pass
    font = QFont("Segoe UI", 9)
    app.setFont(font)

    # 支持命令行参数（拖拽文件到 EXE 图标）
    initial_file = sys.argv[1] if len(sys.argv) > 1 else None
    window = LivePhotoPlayer(initial_file)
    window.show()
    window.raise_()
    window.activateWindow()
    app.processEvents()
    sys.exit(app.exec_())


if __name__ == '__main__':
    import re
    main()
