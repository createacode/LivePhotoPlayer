"""轻量提示条：单实例、可打断、带淡入淡出。"""

from __future__ import annotations

from PySide6.QtCore import QEasingCurve, QPropertyAnimation, Qt, QTimer
from PySide6.QtGui import QColor
from PySide6.QtWidgets import QGraphicsOpacityEffect, QLabel, QWidget

from livephoto_player.ui import theme


class Toast(QLabel):
    """浮在父窗口底部居中的提示条。"""

    def __init__(self, parent: QWidget) -> None:
        super().__init__(parent)
        self._generation = 0
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self.setWordWrap(False)
        self.setStyleSheet(
            f"""
            QLabel {{
                background-color: {theme.COLOR_PANEL_ALT};
                color: {theme.COLOR_TEXT};
                border: 1px solid {theme.COLOR_BORDER};
                border-radius: 10px;
                padding: 9px 18px;
                font-size: 12.5px;
            }}
            """
        )
        self._effect = QGraphicsOpacityEffect(self)
        self._effect.setOpacity(0.0)
        self.setGraphicsEffect(self._effect)
        self._animation = QPropertyAnimation(self._effect, b"opacity", self)
        self._animation.setDuration(160)
        self._animation.setEasingCurve(QEasingCurve.Type.OutCubic)
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.timeout.connect(self._fade_out)
        self.setVisible(False)

    def show_message(self, text: str, timeout: int = 2600, color: str | None = None) -> None:
        """显示一条提示；新提示会立即顶替旧提示并重置计时。"""
        self._generation += 1
        generation = self._generation
        border = color or theme.COLOR_BORDER
        self.setStyleSheet(
            f"""
            QLabel {{
                background-color: {theme.COLOR_PANEL_ALT};
                color: {theme.COLOR_TEXT};
                border: 1px solid {border};
                border-radius: 10px;
                padding: 9px 18px;
                font-size: 12.5px;
            }}
            """
        )
        metrics = self.fontMetrics()
        maximum = max(240, int(self.parentWidget().width() * 0.72)) if self.parentWidget() else 720
        self.setText(metrics.elidedText(text, Qt.TextElideMode.ElideRight, maximum))
        self.setToolTip(text)
        self.adjustSize()
        self.reposition()
        self.setVisible(True)
        self.raise_()
        self._fade_to(1.0)
        self._timer.start(timeout)
        if generation != self._generation:  # pragma: no cover - 并发保护
            return

    def show_success(self, text: str, timeout: int = 2600) -> None:
        """成功提示。"""
        self.show_message(text, timeout, theme.COLOR_SUCCESS)

    def show_error(self, text: str, timeout: int = 3600) -> None:
        """失败提示。"""
        self.show_message(text, timeout, theme.COLOR_DANGER)

    def reposition(self) -> None:
        """父窗口尺寸变化后重新居中到靠下位置。"""
        parent = self.parentWidget()
        if parent is None:
            return
        width = min(self.width(), max(240, int(parent.width() * 0.72)))
        height = self.height()
        x = (parent.width() - width) // 2
        y = parent.height() - height - 32
        self.setGeometry(x, max(0, y), width, height)

    def _fade_out(self) -> None:
        self._fade_to(0.0)
        QTimer.singleShot(180, self._hide_if_transparent)

    def _hide_if_transparent(self) -> None:
        if self._effect.opacity() <= 0.02:
            self.setVisible(False)

    def _fade_to(self, value: float) -> None:
        self._animation.stop()
        self._animation.setStartValue(self._effect.opacity())
        self._animation.setEndValue(value)
        self._animation.start()


__all__ = ["QColor", "Toast"]
