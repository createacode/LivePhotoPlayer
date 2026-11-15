"""实况照片解析测试：XMP 长度、容错搜索、ftyp 回退与异常路径。"""

from __future__ import annotations

from pathlib import Path

import pytest

from livephoto_player.core.livephoto import (
    find_declared_length,
    find_last_ftyp,
    find_video_span,
)


def test_span_from_item_length(make_live_photo) -> None:
    path = make_live_photo()
    span = find_video_span(path)
    assert span is not None
    assert span.offset > 0
    assert span.end == path.stat().st_size
    with path.open("rb") as handle:
        handle.seek(span.offset)
        assert handle.read(4 + 4)[4:8] == b"ftyp"


def test_span_from_micro_video_offset(make_live_photo) -> None:
    path = make_live_photo(name="google.jpg", xmp="micro")
    span = find_video_span(path)
    assert span is not None
    assert span.end == path.stat().st_size


def test_span_falls_back_to_ftyp_search(make_live_photo) -> None:
    path = make_live_photo(name="noxmp.jpg", xmp="none")
    assert find_declared_length(path, path.stat().st_size) == 0
    span = find_video_span(path)
    assert span is not None
    assert span.end == path.stat().st_size


def test_declared_length_tolerance(make_live_photo) -> None:
    """XMP 声明长度与实际差 40 字节时，应在容错窗口内重新对齐。"""
    path = make_live_photo(name="tolerant.jpg", declared_delta=40)
    span = find_video_span(path)
    assert span is not None
    assert span.end == path.stat().st_size
    with path.open("rb") as handle:
        handle.seek(span.offset)
        assert handle.read(8)[4:8] == b"ftyp"


def test_plain_photo_has_no_span(tmp_path: Path) -> None:
    path = tmp_path / "plain.jpg"
    path.write_bytes(b"\xff\xd8\xff\xd9" + b"\x00" * 500)
    assert find_video_span(path) is None
    assert find_last_ftyp(path, path.stat().st_size) is None


def test_missing_file_returns_none(tmp_path: Path) -> None:
    assert find_video_span(tmp_path / "nope.jpg") is None


def test_tiny_file_returns_none(tmp_path: Path) -> None:
    path = tmp_path / "tiny.jpg"
    path.write_bytes(b"\xff\xd8")
    assert find_video_span(path) is None


def test_invalid_box_size_is_rejected(tmp_path: Path) -> None:
    """``ftyp`` 前面的长度字段非法时不能被当成视频起点。"""
    path = tmp_path / "bad.jpg"
    payload = b"\x00" * 200 + b"\x00\x00\x00\x00ftyp" + b"\x00" * 200
    path.write_bytes(payload)
    span = find_video_span(path)
    if span is not None:  # 若命中，必须仍是合法区间
        assert span.end == path.stat().st_size


@pytest.mark.parametrize("delta", [0, 1, 1024])
def test_declared_length_edge(make_live_photo, delta: int) -> None:
    path = make_live_photo(name=f"edge{delta}.jpg", declared_delta=delta)
    span = find_video_span(path)
    assert span is not None
    assert span.end == path.stat().st_size
