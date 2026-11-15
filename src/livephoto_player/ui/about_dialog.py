"""关于对话框：名称、版本、作者、版权与第三方许可入口。"""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt, QUrl, Signal
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from livephoto_player.core.version import (
    COPYRIGHT_SUFFIX,
    __author__,
    __software_name__,
    __version__,
)
from livephoto_player.ui import theme


class AboutDialog(QDialog):
    """展示软件信息并提供检查更新入口。"""

    check_update_requested = Signal()

    def __init__(self, notices_path: Path, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._notices_path = notices_path
        self.setWindowTitle(f"关于 {__software_name__}")
        self.setModal(True)
        self.setMinimumWidth(460)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(28, 24, 28, 20)
        layout.setSpacing(10)

        title = QLabel(__software_name__)
        title.setStyleSheet(f"font-size: 20px; font-weight: 600; color: {theme.COLOR_TEXT};")
        layout.addWidget(title)

        meta = QLabel(
            f"版本 {__version__}\n作者 {__author__}\n{COPYRIGHT_SUFFIX}",
        )
        meta.setStyleSheet(f"color: {theme.COLOR_TEXT_MUTED}; font-size: 12.5px;")
        layout.addWidget(meta)

        description = QLabel(
            "播放手机实况照片内嵌视频、浏览与整理照片视频的桌面工具。\n"
            "图片与视频均在本机处理，不联网、不上传任何数据。",
        )
        description.setWordWrap(True)
        description.setStyleSheet(f"color: {theme.COLOR_TEXT}; font-size: 12.5px;")
        layout.addWidget(description)

        notices_note = QLabel(
            "第三方组件与许可：[THIRD-PARTY-NOTICES.md](docs/THIRD-PARTY-NOTICES.md)"
        )
        notices_note.setTextFormat(Qt.TextFormat.MarkdownText)
        notices_note.setOpenExternalLinks(False)
        notices_note.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        notices_note.setStyleSheet(f"color: {theme.COLOR_TEXT_MUTED};")
        layout.addWidget(notices_note)

        notices_button = QPushButton("打开第三方声明")
        notices_button.clicked.connect(self._open_notices)
        layout.addWidget(notices_button, alignment=Qt.AlignmentFlag.AlignLeft)

        buttons = QDialogButtonBox(self)
        update_button = QPushButton("检查更新")
        update_button.clicked.connect(self.check_update_requested.emit)
        buttons.addButton(update_button, QDialogButtonBox.ButtonRole.ActionRole)
        close_button = QPushButton("关闭")
        close_button.clicked.connect(self.accept)
        buttons.addButton(close_button, QDialogButtonBox.ButtonRole.AcceptRole)
        layout.addWidget(buttons)

    def _open_notices(self) -> None:
        if self._notices_path.exists():
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(self._notices_path)))
        else:
            self.check_update_requested.emit()
