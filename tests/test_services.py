"""内嵌视频设备与图片解码服务测试（需要 QApplication）。"""

from __future__ import annotations

from pathlib import Path

import pytest
from PySide6.QtCore import QIODevice
from PySide6.QtGui import QImage

from livephoto_player.core.models import VideoSpan
from livephoto_player.services.image_loader import bucket_for, decode_image
from livephoto_player.services.tail_device import TailDevice


def test_tail_device_reads_span(qapp: object, tmp_path: Path) -> None:
    payload = b"H" * 100 + bytes(range(256)) + b"T" * 100
    path = tmp_path / "live.jpg"
    path.write_bytes(payload)
    device = TailDevice(path, VideoSpan(100, 256))
    try:
        assert device.isSequential() is False
        assert device.size() == 256
        assert device.pos() == 0
        assert device.readData(16) == payload[100:116]
        assert device.pos() == 16
        assert device.seek(200) is True
        assert device.readData(100) == payload[300:356]
        assert device.atEnd() is True
        assert device.readData(10) == b""
        assert device.seek(9999) is False
        assert device.writeData(b"x", 1) == -1
        assert device.bytesAvailable() >= 0
    finally:
        device.close()
    assert device.isOpen() is False


def test_tail_device_open_flag(qapp: object, tmp_path: Path) -> None:
    path = tmp_path / "a.jpg"
    path.write_bytes(b"x" * 200)
    device = TailDevice(path, VideoSpan(0, 100))
    try:
        assert device.isOpen() is True
        assert device.openMode() == QIODevice.OpenModeFlag.ReadOnly
    finally:
        device.close()


def test_decode_image_scales_to_target(qapp: object, sample_image: Path) -> None:
    image, source = decode_image(sample_image, 100)
    assert isinstance(image, QImage)
    assert not image.isNull()
    assert image.width() <= 100
    assert source.width() == 320


def test_decode_image_full_resolution(qapp: object, sample_image: Path) -> None:
    image, source = decode_image(sample_image, 100, full=True)
    assert image.width() == 320
    assert source.width() == 320


def test_decode_image_missing_file_returns_null(qapp: object, tmp_path: Path) -> None:
    image, _ = decode_image(tmp_path / "nope.jpg", 100)
    assert image.isNull()


@pytest.mark.parametrize(
    ("width", "expected"),
    [(0, 0), (1, 256), (256, 256), (257, 512), (1000, 1024)],
)
def test_bucket_for(width: int, expected: int) -> None:
    assert bucket_for(width) == expected


def test_decode_matches_full_decode_then_smooth_scale(qapp: object, tmp_path: Path) -> None:
    """预览解码必须等价于「全解码 + 平滑缩放」。

    历史上这里用了 ``QImageReader.setScaledSize``，Qt 的 JPEG 解码器会走
    libjpeg 低质量采样，实测锐度低 20~40%，画面明显发糊。
    """
    import math

    from PIL import Image
    from PySide6.QtCore import Qt
    from PySide6.QtGui import QImageReader

    # 高频棋盘格最能暴露缩放质量差异
    source = tmp_path / "checker.jpg"
    image = Image.new("RGB", (1200, 900))
    pixels = image.load()
    for y in range(900):
        for x in range(1200):
            pixels[x, y] = (255, 255, 255) if (x // 6 + y // 6) % 2 else (0, 0, 0)
    image.save(source, "JPEG", quality=95)

    decoded, src_size = decode_image(source, 400)
    reader = QImageReader(str(source))
    full = reader.read()
    reference = full.scaled(
        400,
        round(400 * src_size.height() / src_size.width()),
        Qt.AspectRatioMode.IgnoreAspectRatio,
        Qt.TransformationMode.SmoothTransformation,
    )

    assert decoded.size() == reference.size()
    a = decoded.convertToFormat(QImage.Format.Format_RGB32)
    b = reference.convertToFormat(QImage.Format.Format_RGB32)
    error = 0
    for y in range(0, a.height(), 4):
        pa = bytes(a.constScanLine(y))
        pb = bytes(b.constScanLine(y))
        for x in range(0, a.width() * 4, 8):
            for k in range(3):
                delta = pa[x + k] - pb[x + k]
                error += delta * delta
    samples = ((a.height() + 3) // 4) * ((a.width() * 4 + 7) // 8) * 3
    mse = error / max(1, samples)
    psnr = 99.0 if mse <= 1e-9 else 10 * math.log10((255.0**2) / mse)
    assert psnr > 40, f"预览解码与参考实现差异过大，PSNR={psnr:.1f}dB（画面会发糊）"


def test_huge_image_uses_integer_prescale(
    qapp: object, sample_image: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """超大图走整数分之一预缩小分支，结果仍应缩放到目标宽度。"""
    from livephoto_player.services import image_loader

    monkeypatch.setattr(image_loader, "HUGE_IMAGE_PIXELS", 1000)
    image, source = decode_image(sample_image, 100)
    assert not image.isNull()
    assert image.width() == 100
    assert source.width() == 320
