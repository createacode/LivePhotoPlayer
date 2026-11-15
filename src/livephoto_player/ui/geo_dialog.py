"""地点解析设置：离线内置 / 在线 API（天地图、OpenStreetMap）。"""

from __future__ import annotations

from PySide6.QtCore import Qt, QThread, QUrl, Signal
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QRadioButton,
    QVBoxLayout,
    QWidget,
)

from livephoto_player.core.models import MediaItem
from livephoto_player.services.geocode import PROVIDERS, GeocodeError, check_provider
from livephoto_player.services.geodb import default_geo_db
from livephoto_player.ui import theme
from livephoto_player.utils.config import AppConfig

TIANDITU_CONSOLE = "https://cloudcenter.tianditu.gov.cn/center/development/myApp"


# 明确画出单选框的选中态：默认调色板在深色底上几乎看不见选中圆点
RADIO_QSS = """
QRadioButton { spacing: 8px; }
QRadioButton::indicator {
    width: 15px; height: 15px; border-radius: 8px;
    border: 2px solid #77828f; background: transparent;
}
QRadioButton::indicator:hover { border-color: #9fb0c2; }
QRadioButton::indicator:checked {
    border: 2px solid #4c8dff; background: #4c8dff;
}
QRadioButton::indicator:checked:disabled { border-color: #55606d; background: #55606d; }
"""


class _ProbeThread(QThread):
    """后台测试在线源，避免阻塞对话框。"""

    done = Signal(bool, str)

    def __init__(self, provider: str, key: str, parent: object | None = None) -> None:
        super().__init__(parent)  # type: ignore[arg-type]
        self._provider = provider
        self._key = key

    def run(self) -> None:
        try:
            place = check_provider(self._provider, self._key)
        except GeocodeError as exc:
            self.done.emit(False, str(exc))
            return
        except Exception as exc:  # noqa: BLE001 - 测试失败也要回到界面
            self.done.emit(False, str(exc))
            return
        self.done.emit(True, place)


class GeoDialog(QDialog):
    """选择解析方式；保存后由主窗口触发重新解析。"""

    def __init__(
        self, config: AppConfig, sample: MediaItem | None = None, parent: QWidget | None = None
    ) -> None:
        super().__init__(parent)
        self.setStyleSheet(self.styleSheet() + RADIO_QSS)
        self._config = config
        self._probe: _ProbeThread | None = None
        self.setWindowTitle("地点解析设置")
        self.setMinimumWidth(520)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 18, 20, 16)
        layout.setSpacing(12)

        # ---- 模式
        mode_box = QGroupBox("解析方式")
        mode_layout = QVBoxLayout(mode_box)
        geo = default_geo_db()
        geo_text = (
            f"本地查表，覆盖 {geo.count} 个区县，不联网"
            if geo.available
            else "内置数据缺失，将退回显示坐标；可运行 scripts/build_geo_dataset.py 生成"
        )
        self._radio_offline = QRadioButton(f"内置离线（推荐）—— {geo_text}")
        self._radio_api = QRadioButton("在线 API —— 更精确，需要联网；天地图需自备 key")
        self._radio_off = QRadioButton("关闭 —— 只显示经纬度坐标")
        for radio in (self._radio_offline, self._radio_api, self._radio_off):
            radio.setEnabled(True)
            mode_layout.addWidget(radio)
        if config.geo.mode == "api":
            self._radio_api.setChecked(True)
        elif config.geo.mode == "off":
            self._radio_off.setChecked(True)
        else:
            self._radio_offline.setChecked(True)
        layout.addWidget(mode_box)

        # ---- 在线参数
        api_box = QGroupBox("在线参数")
        form = QFormLayout(api_box)
        self._provider = QComboBox()
        for info in PROVIDERS:
            self._provider.addItem(info.label, info.key)
        index = self._provider.findData(config.geo.provider)
        if index >= 0:
            self._provider.setCurrentIndex(index)

        self._key_edit = QLineEdit(config.geo.tianditu_key)
        self._key_edit.setPlaceholderText(
            "天地图 key（服务端 · Web 服务 API），不内置、只保存在本机 config.json"
        )
        self._key_edit.setEchoMode(QLineEdit.EchoMode.Password)
        self._key_visible = QPushButton("显示")
        self._key_visible.setCheckable(True)
        self._key_visible.toggled.connect(self._toggle_key_echo)
        key_row = QWidget()
        key_layout = QHBoxLayout(key_row)
        key_layout.setContentsMargins(0, 0, 0, 0)
        key_layout.addWidget(self._key_edit, 1)
        key_layout.addWidget(self._key_visible)

        self._test_button = QPushButton("测试")
        self._test_button.clicked.connect(self._test)
        self._apply_button = QPushButton("申请天地图 key")
        self._apply_button.clicked.connect(lambda: QDesktopServices.openUrl(QUrl(TIANDITU_CONSOLE)))
        test_row = QWidget()
        test_layout = QHBoxLayout(test_row)
        test_layout.setContentsMargins(0, 0, 0, 0)
        test_layout.addWidget(self._test_button)
        test_layout.addWidget(self._apply_button)
        test_layout.addStretch(1)

        form.addRow("数据源", self._provider)
        form.addRow("天地图 key", key_row)
        form.addRow("", test_row)
        self._hint = QLabel("")
        self._hint.setWordWrap(True)
        self._hint.setStyleSheet(f"color: {theme.COLOR_TEXT_MUTED};")
        form.addRow("", self._hint)
        layout.addWidget(api_box)

        if sample is not None:
            layout.addWidget(self._sample_label(sample))

        buttons = QDialogButtonBox(self)
        ok = QPushButton("保存并重新解析")
        ok.clicked.connect(self.accept)
        buttons.addButton(ok, QDialogButtonBox.ButtonRole.AcceptRole)
        cancel = QPushButton("取消")
        cancel.clicked.connect(self.reject)
        buttons.addButton(cancel, QDialogButtonBox.ButtonRole.RejectRole)
        layout.addWidget(buttons)

        self._provider.currentIndexChanged.connect(self._on_provider_changed)
        self._radio_api.toggled.connect(self._sync_enabled)
        self._on_provider_changed()
        self._sync_enabled()

    # ------------------------------------------------------------------ 结果
    def selected_mode(self) -> str:
        """用户选择的模式。"""
        if self._radio_off.isChecked():
            return "off"
        if self._radio_api.isChecked():
            return "api"
        return "offline"

    def selected_provider(self) -> str:
        """选中的在线源。"""
        return str(self._provider.currentData())

    def tianditu_key(self) -> str:
        """填写的 key。"""
        return self._key_edit.text().strip()

    # ------------------------------------------------------------------ 内部
    def _sample_label(self, item: MediaItem) -> QLabel:
        coords = ""
        if item.latitude is not None and item.longitude is not None:
            coords = f"{item.latitude:.4f}, {item.longitude:.4f}"
        text = f"用当前照片试算：{coords or '该照片没有 GPS'} → {item.place_text}"
        label = QLabel(text)
        label.setWordWrap(True)
        label.setStyleSheet(f"color: {theme.COLOR_WARNING};")
        return label

    def _toggle_key_echo(self, visible: bool) -> None:
        self._key_edit.setEchoMode(
            QLineEdit.EchoMode.Normal if visible else QLineEdit.EchoMode.Password
        )

    def _on_provider_changed(self, *_: object) -> None:
        info = next((p for p in PROVIDERS if p.key == self.selected_provider()), PROVIDERS[0])
        self._key_edit.setEnabled(info.needs_key)
        self._hint.setText(info.hint)

    def _sync_enabled(self, *_: object) -> None:
        api = self._radio_api.isChecked()
        self._provider.setEnabled(api)
        self._key_edit.setEnabled(api and self.selected_provider() == "tianditu")
        self._test_button.setEnabled(api)
        self._apply_button.setEnabled(api)

    def _test(self) -> None:
        if self._probe is not None and self._probe.isRunning():
            return
        self._test_button.setEnabled(False)
        self._hint.setText("正在测试（用北京天安门坐标）…")
        self._hint.setStyleSheet(f"color: {theme.COLOR_TEXT_MUTED};")
        probe = _ProbeThread(self.selected_provider(), self.tianditu_key(), self)
        probe.done.connect(self._on_probe_done)
        # 线程真正结束后再释放；在 done 槽里置空会让 QThread 在运行中被回收，直接崩溃
        probe.finished.connect(self._on_probe_finished)
        self._probe = probe
        probe.start()

    def _on_probe_finished(self) -> None:
        """线程已退出，这里才允许释放引用。"""
        probe = self._probe
        self._probe = None
        if probe is not None:
            probe.deleteLater()

    def _on_probe_done(self, ok: bool, message: str) -> None:
        self._test_button.setEnabled(self._radio_api.isChecked())
        if ok:
            self._hint.setText(f"测试成功：天安门 → {message}")
            self._hint.setStyleSheet(f"color: {theme.COLOR_SUCCESS};")
        else:
            self._hint.setText(f"测试失败：{message}")
            self._hint.setStyleSheet(f"color: {theme.COLOR_DANGER};")

    def closeEvent(self, event: object) -> None:
        probe = self._probe
        if probe is not None and probe.isRunning():
            probe.requestInterruption()
            probe.wait(5000)
        self._probe = None
        super().closeEvent(event)  # type: ignore[arg-type]


__all__ = ["GeoDialog", "Qt"]
