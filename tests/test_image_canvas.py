"""画布几何测试：缩放必须以原图像素为基准，且升级分辨率不能跳变。

这两条正是用户反馈"照片很糊 / 比例不对"的根因，必须锁死。
"""

from __future__ import annotations

import pytest
from PySide6.QtCore import QPointF, QSize
from PySide6.QtGui import QColor, QImage

from livephoto_player.ui.image_canvas import ImageCanvas

SOURCE_W = 2000
SOURCE_H = 1500
PREVIEW_W = 1000
PREVIEW_H = 750
VIEW_W = 800
VIEW_H = 600


def make_image(width: int, height: int, color: str = "#335577") -> QImage:
    image = QImage(width, height, QImage.Format.Format_RGB32)
    image.fill(QColor(color))
    return image


@pytest.fixture
def canvas(qtbot: object) -> ImageCanvas:
    widget = ImageCanvas()
    qtbot.addWidget(widget)  # type: ignore[attr-defined]
    widget.resize(VIEW_W, VIEW_H)
    return widget


@pytest.fixture
def loaded(canvas: ImageCanvas) -> ImageCanvas:
    preview = make_image(PREVIEW_W, PREVIEW_H)
    canvas.set_image(preview, QSize(SOURCE_W, SOURCE_H), fit=True)
    return canvas


def test_fit_uses_source_size(loaded: ImageCanvas) -> None:
    expected = min(VIEW_W / SOURCE_W, VIEW_H / SOURCE_H)
    assert loaded.fit_zoom == pytest.approx(expected)
    rect = loaded._image_rect()
    assert rect.width() == pytest.approx(SOURCE_W * expected)
    assert rect.height() == pytest.approx(SOURCE_H * expected)


def test_hundred_percent_equals_source_pixels(loaded: ImageCanvas) -> None:
    loaded.zoom_to_percent(100)
    assert loaded.zoom_percent() == 100
    rect = loaded._image_rect()
    assert rect.width() == pytest.approx(SOURCE_W)
    assert rect.height() == pytest.approx(SOURCE_H)


def test_hundred_percent_is_not_limited_by_preview(loaded: ImageCanvas) -> None:
    """预览只有 1000px 宽，但 100% 必须显示到 2000px（原图宽度）。"""
    loaded.zoom_to_percent(100)
    assert loaded._image_rect().width() > loaded.loaded_width


def test_upgrade_keeps_geometry(loaded: ImageCanvas) -> None:
    loaded.zoom_to_percent(100)
    before = loaded._image_rect().width()
    full = make_image(SOURCE_W, SOURCE_H)
    loaded.upgrade_image(full)
    after = loaded._image_rect().width()
    assert after == pytest.approx(before)
    assert loaded.loaded_width == SOURCE_W


def test_upgrade_ignores_same_size(loaded: ImageCanvas) -> None:
    original = loaded.image
    loaded.upgrade_image(make_image(PREVIEW_W, PREVIEW_H, "#ff0000"))
    assert loaded.image is original


def test_needs_full_resolution_flags(loaded: ImageCanvas) -> None:
    assert loaded.needs_full_resolution() is False
    loaded.zoom_to_percent(220)
    assert loaded.needs_full_resolution() is True


def test_needs_full_resolution_false_when_already_full(loaded: ImageCanvas) -> None:
    loaded.upgrade_image(make_image(SOURCE_W, SOURCE_H))
    loaded.zoom_to_percent(220)
    assert loaded.needs_full_resolution() is False


def test_clear_resets_state(loaded: ImageCanvas) -> None:
    loaded.clear()
    assert loaded.has_image is False
    assert loaded.source_width == 0
    assert loaded.loaded_width == 0


def test_zoom_is_clamped(loaded: ImageCanvas) -> None:
    loaded.zoom_to_percent(100000)
    assert loaded.zoom <= 16.0
    loaded.zoom_to_percent(1)
    assert loaded.zoom >= 0.02


def test_set_image_without_source_size_uses_image_size(qtbot: object) -> None:
    widget = ImageCanvas()
    qtbot.addWidget(widget)  # type: ignore[attr-defined]
    widget.resize(VIEW_W, VIEW_H)
    widget.set_image(make_image(400, 300), QSize())
    assert widget.source_width == 400


def test_pan_is_clamped_to_image_edges(loaded: ImageCanvas) -> None:
    loaded.zoom_to_percent(200)
    loaded._pan = QPointF(1e9, 1e9)
    loaded._clamp_pan()
    rect = loaded._image_rect()
    assert rect.left() <= 0.5
    assert rect.top() <= 0.5
