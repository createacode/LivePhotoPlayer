"""画质增强：档位归一、sRGB 转换与教科书式 USM 的行为边界。"""

from __future__ import annotations

from PySide6.QtGui import QColor, QColorSpace, QImage

from livephoto_player.core.enhance import (
    DEFAULT_QUALITY,
    QUALITY_LABELS,
    QUALITY_LEVELS,
    normalize_quality,
    quality_params,
    sharpen,
    to_srgb,
)


def _solid(width: int, height: int, color: QColor) -> QImage:
    image = QImage(width, height, QImage.Format.Format_RGB32)
    image.fill(color)
    return image


def _edge_image() -> QImage:
    image = QImage(64, 64, QImage.Format.Format_RGB32)
    image.fill(QColor(60, 60, 60))
    for y in range(32, 64):
        for x in range(64):
            image.setPixelColor(x, y, QColor(200, 200, 200))
    return image


def _luma_variance(image: QImage) -> float:
    """纯 Python 算拉普拉斯方差（测试图很小，够快且不引入 numpy）。"""
    gray = image.convertToFormat(QImage.Format.Format_Grayscale8)
    width, height = gray.width(), gray.height()
    rows = [[gray.pixelColor(x, y).red() for x in range(width)] for y in range(height)]
    values: list[float] = []
    for y in range(1, height - 1):
        for x in range(1, width - 1):
            lap = rows[y - 1][x] + rows[y + 1][x] + rows[y][x - 1] + rows[y][x + 1] - 4 * rows[y][x]
            values.append(float(lap))
    mean = sum(values) / len(values)
    return sum((v - mean) ** 2 for v in values) / len(values)


def test_normalize_quality_falls_back_to_default() -> None:
    assert normalize_quality("standard") == "standard"
    assert normalize_quality("strong") == "strong"
    assert normalize_quality("raw") == "raw"
    assert normalize_quality("unknown") == DEFAULT_QUALITY
    assert normalize_quality("") == DEFAULT_QUALITY


def test_quality_tables_are_consistent() -> None:
    assert set(QUALITY_LEVELS) == set(QUALITY_LABELS)
    assert QUALITY_LEVELS["raw"] is None
    standard = quality_params("standard")
    strong = quality_params("strong")
    assert standard is not None and strong is not None
    assert standard[1] < strong[1], "增强档的锐化强度必须更大"
    assert standard[0] <= strong[0]


def test_to_srgb_keeps_srgb_image_untouched() -> None:
    image = _solid(8, 8, QColor(10, 20, 30))
    image.setColorSpace(QColorSpace(QColorSpace.NamedColorSpace.SRgb))
    result = to_srgb(image)
    assert result.colorSpace() == QColorSpace(QColorSpace.NamedColorSpace.SRgb)
    assert result.pixelColor(4, 4).red() == 10


def test_to_srgb_converts_wide_gamut() -> None:
    image = _solid(8, 8, QColor(200, 40, 40))
    image.setColorSpace(QColorSpace(QColorSpace.NamedColorSpace.DisplayP3))
    result = to_srgb(image)
    assert result.colorSpace() == QColorSpace(QColorSpace.NamedColorSpace.SRgb)
    assert result.pixelColor(4, 4) != image.pixelColor(4, 4)


def test_raw_quality_is_noop() -> None:
    image = _edge_image()
    assert sharpen(image, "raw") is image


def test_standard_sharpen_increases_acutance_and_keeps_size() -> None:
    image = _edge_image()
    before = _luma_variance(image)
    result = sharpen(image, "standard")
    assert result.size() == image.size()
    assert _luma_variance(result) > before * 1.2


def test_strong_sharpen_sharper_than_standard() -> None:
    image = _edge_image()
    standard = _luma_variance(sharpen(image, "standard"))
    strong = _luma_variance(sharpen(image, "strong"))
    assert strong > standard


def test_sharpen_ignores_tiny_images() -> None:
    tiny = _solid(8, 8, QColor(128, 128, 128))
    assert sharpen(tiny, "standard") is tiny
