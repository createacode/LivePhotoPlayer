"""pytest 公共夹具。

必须在任何 QApplication 创建之前设置离屏平台，否则测试会尝试打开真实窗口。
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))


@pytest.fixture
def sample_image(tmp_path: Path) -> Path:
    """生成一张 320x240 的真实 JPEG。"""
    from PIL import Image

    path = tmp_path / "sample.jpg"
    Image.new("RGB", (320, 240), (30, 90, 160)).save(path, "JPEG", quality=90)
    return path


@pytest.fixture
def sample_video_bytes() -> bytes:
    """构造一段带 ``ftyp`` 与 ``mdat`` 的伪 MP4。"""
    import struct

    ftyp = struct.pack(">I", 24) + b"ftypisom" + b"\x00\x00\x02\x00" + b"isom" + b"\x00" * 8
    mdat = struct.pack(">I", 8 + 200) + b"mdat" + bytes(range(200))
    return ftyp + mdat


@pytest.fixture
def make_live_photo(tmp_path: Path, sample_video_bytes: bytes):
    """构造实况照片：JPEG 头部 + 尾部内嵌 MP4，可选写入 XMP 长度。"""

    def _make(
        name: str = "live.jpg",
        *,
        xmp: str = "length",
        declared_delta: int = 0,
    ) -> Path:
        import struct

        mp4 = sample_video_bytes
        declared = len(mp4) + declared_delta
        if xmp == "length":
            meta = f'Item:Length="{declared}"'.encode()
        elif xmp == "micro":
            meta = f'MicroVideoOffset="{declared}"'.encode()
        else:
            meta = b""
        jpeg = b"\xff\xd8\xff\xe0" + struct.pack(">H", 4) + b"\x00\x00" + b"\x00" * 800
        if meta:
            jpeg += b"\xff\xe1" + struct.pack(">H", len(meta) + 2) + meta
        jpeg += b"\x00" * 400 + b"\xff\xd9"
        path = tmp_path / name
        path.write_bytes(jpeg + mp4)
        return path

    return _make
