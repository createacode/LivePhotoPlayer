"""更新提示对话框：展示版本差异、下载校验与用户确认安装。"""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt, QThread, QUrl, Signal
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QApplication,
    QDialog,
    QDialogButtonBox,
    QLabel,
    QMessageBox,
    QProgressDialog,
    QPushButton,
    QTextBrowser,
    QVBoxLayout,
    QWidget,
)

from livephoto_player.core.version import __software_name__, __version__
from livephoto_player.ui import theme
from livephoto_player.update.downloader import download_asset
from livephoto_player.update.gitee import ReleaseAsset, UpdateInfo
from livephoto_player.utils.logger import get_logger


class _DownloadThread(QThread):
    progress = Signal(int, int)
    succeeded = Signal(str)
    failed = Signal(str)

    def __init__(self, asset: ReleaseAsset, sums_url: str | None) -> None:
        super().__init__()
        self._asset = asset
        self._sums_url = sums_url

    def run(self) -> None:
        try:
            path = download_asset(
                self._asset,
                sums_url=self._sums_url,
                progress=lambda received, total: self.progress.emit(received, total),
            )
        except Exception as exc:  # noqa: BLE001 - 下载失败必须回到界面提示
            get_logger("update").error("更新下载失败：%s", exc)
            self.failed.emit(str(exc))
            return
        self.succeeded.emit(str(path))


class UpdateDialog(QDialog):
    """有新版时展示更新说明并引导下载。"""

    def __init__(self, info: UpdateInfo, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._info = info
        self._thread: _DownloadThread | None = None
        self._progress: QProgressDialog | None = None
        self.setWindowTitle(f"{__software_name__} 有新版本")
        self.setMinimumSize(560, 460)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 20, 24, 18)
        layout.setSpacing(10)

        head = QLabel(f"发现新版本 {info.version_text}")
        head.setStyleSheet(f"font-size: 18px; font-weight: 600; color: {theme.COLOR_TEXT};")
        layout.addWidget(head)

        meta = QLabel(f"当前版本 {__version__} · 发布于 {info.created_at[:10] or '未知'}")
        meta.setStyleSheet(f"color: {theme.COLOR_TEXT_MUTED};")
        layout.addWidget(meta)

        notes = QTextBrowser()
        notes.setPlainText(info.body or "该版本未提供更新说明。")
        notes.setOpenExternalLinks(False)
        notes.setStyleSheet(
            f"background-color: {theme.COLOR_PANEL}; border: 1px solid {theme.COLOR_BORDER};"
            f"border-radius: 8px; padding: 8px; color: {theme.COLOR_TEXT};"
        )
        layout.addWidget(notes, 1)

        asset = info.preferred_asset()
        hint = QLabel(
            f"下载包：{asset.name}"
            if asset is not None
            else "该版本未提供可下载的安装包，请到发行页手动下载。"
        )
        hint.setStyleSheet(f"color: {theme.COLOR_TEXT_MUTED};")
        layout.addWidget(hint)

        buttons = QDialogButtonBox(self)
        self._download_button = QPushButton("下载并安装")
        self._download_button.setEnabled(asset is not None)
        self._download_button.clicked.connect(self._start_download)
        buttons.addButton(self._download_button, QDialogButtonBox.ButtonRole.ActionRole)

        later = QPushButton("稍后")
        later.clicked.connect(self.reject)
        buttons.addButton(later, QDialogButtonBox.ButtonRole.RejectRole)

        ignore = QPushButton("忽略此版本")
        ignore.clicked.connect(self._ignore_version)
        buttons.addButton(ignore, QDialogButtonBox.ButtonRole.DestructiveRole)
        layout.addWidget(buttons)

        self._asset = asset
        self._sums_url = self._find_sums_url(info)

    # ------------------------------------------------------------------ 内部实现
    @staticmethod
    def _find_sums_url(info: UpdateInfo) -> str | None:
        for asset in info.assets:
            if asset.name.lower() == "sha256sums.txt":
                return asset.url
        return None

    def _ignore_version(self) -> None:
        self.done(2)

    def _start_download(self) -> None:
        if self._asset is None:
            QDesktopServices.openUrl(QUrl("https://gitee.com"))
            return
        self._progress = QProgressDialog("正在下载更新…", "取消", 0, 100, self)
        self._progress.setWindowTitle("下载更新")
        self._progress.setWindowModality(Qt.WindowModality.WindowModal)
        self._progress.setMinimumDuration(0)
        self._progress.canceled.connect(self._cancel_download)
        self._progress.setValue(0)

        self._thread = _DownloadThread(self._asset, self._sums_url)
        self._thread.progress.connect(self._on_progress)
        self._thread.succeeded.connect(self._on_downloaded)
        self._thread.failed.connect(self._on_failed)
        self._thread.start()

    def _cancel_download(self) -> None:
        if self._thread is not None and self._thread.isRunning():
            self._thread.requestInterruption()
            self._thread.wait(1500)
        self._thread = None
        if self._progress is not None:
            self._progress.close()
            self._progress = None

    def _on_progress(self, received: int, total: int) -> None:
        if self._progress is None:
            return
        if total > 0:
            self._progress.setValue(int(received * 100 / total))
        else:
            self._progress.setValue(0)

    def _on_downloaded(self, path: str) -> None:
        if self._progress is not None:
            self._progress.close()
            self._progress = None
        self._thread = None
        answer = QMessageBox.question(
            self,
            "下载完成",
            "更新包已下载并通过校验。\n是否立即打开安装？程序将先退出。",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.Yes,
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(Path(path))))
        QApplication.quit()

    def _on_failed(self, message: str) -> None:
        if self._progress is not None:
            self._progress.close()
            self._progress = None
        self._thread = None
        box = QMessageBox(self)
        box.setIcon(QMessageBox.Icon.Warning)
        box.setWindowTitle("更新失败")
        box.setText(message)
        box.setInformativeText("是否打开发行页手动下载？")
        box.setStandardButtons(QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
        if box.exec() == QMessageBox.StandardButton.Yes and self._asset is not None:
            QDesktopServices.openUrl(QUrl(self._asset.url))
