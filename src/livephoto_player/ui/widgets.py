"""通用小控件。"""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QLabel, QSizePolicy, QWidget


class ElidedLabel(QLabel):
    """单行文本，超出宽度时显示省略号，完整内容放在 tooltip 里。"""

    def __init__(self, text: str = "", parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._full_text = text
        self.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        self.setText(text)

    def setText(self, text: str) -> None:
        self._full_text = text
        super().setToolTip(text)
        self._apply_elide()

    def full_text(self) -> str:
        """返回未被截断的原始文本。"""
        return self._full_text

    def resizeEvent(self, event: object) -> None:
        super().resizeEvent(event)  # type: ignore[arg-type]
        self._apply_elide()

    def _apply_elide(self) -> None:
        available = max(16, self.width() - 6)
        elided = self.fontMetrics().elidedText(
            self._full_text, Qt.TextElideMode.ElideRight, available
        )
        super().setText(elided)
