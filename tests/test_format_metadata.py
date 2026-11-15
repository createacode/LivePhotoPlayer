"""时间/地点格式化与元数据抽取测试。"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

import pytest
from PIL import Image

from livephoto_player.core.format import (
    UNKNOWN_PLACE,
    format_coords,
    format_datetime,
    format_day,
    format_place,
    format_relative_day,
    format_size,
    format_time,
)
from livephoto_player.services.metadata import (
    _dms_to_degrees,
    read_metadata,
    timestamp_from_name,
)

STAMP = int(datetime(2026, 9, 27, 16, 49, 37).timestamp())


def test_time_and_day_format() -> None:
    assert format_time(STAMP) == "16:49"
    assert format_day(STAMP) == "2026-09-27 周日"
    assert format_datetime(STAMP) == "2026-09-27 16:49:37"


def test_unknown_time_is_blank() -> None:
    assert format_time(0) == ""
    assert format_day(0) == ""
    assert format_datetime(0) == ""


def test_relative_day() -> None:
    now = datetime(2026, 9, 28, 10, 0, 0)
    assert format_relative_day(STAMP, now=now).startswith("昨天")
    assert format_relative_day(int(datetime(2026, 9, 28, 9, 0).timestamp()), now=now).startswith(
        "今天"
    )
    assert format_relative_day(int(datetime(2026, 9, 1).timestamp()), now=now).startswith(
        "2026-09-01"
    )


def test_coords_formatting() -> None:
    assert format_coords(41.5731, 116.0094) == "41.5731°N 116.0094°E"
    assert format_coords(-33.5, -70.6) == "33.5000°S 70.6000°W"
    assert format_coords(None, 1.0) == ""
    assert format_coords(999.0, 1.0) == ""


def test_place_prefers_name_then_coords() -> None:
    assert format_place("张家口", 41.5, 116.0) == "张家口"
    assert format_place("", 41.5731, 116.0094) == "41.5731°N 116.0094°E"
    assert format_place("", None, None) == UNKNOWN_PLACE


def test_size_formatting() -> None:
    assert format_size(1024) == "1 KB"
    assert format_size(5 * 1024 * 1024) == "5.0 MB"


@pytest.mark.parametrize(
    ("name", "expected"),
    [
        ("IMG20260927164937.jpg", "2026-09-27 16:49:37"),
        ("VID20260809154030.mp4", "2026-08-09 15:40:30"),
        ("PXL_20260927_164937123.jpg", "2026-09-27 16:49:37"),
        ("holiday.jpg", ""),
        ("IMG99999999999999.jpg", ""),
    ],
)
def test_timestamp_from_name(name: str, expected: str) -> None:
    stamp = timestamp_from_name(Path(name))
    assert (format_datetime(stamp) if stamp else "") == expected


def test_dms_to_degrees() -> None:
    assert _dms_to_degrees((41, 34, 23.05), "N") == pytest.approx(41.57307, rel=1e-4)
    assert _dms_to_degrees((41, 34, 23.05), "S") < 0
    assert _dms_to_degrees("bad", "N") is None
    assert _dms_to_degrees((1, 2), "N") is None


def test_read_metadata_uses_exif_datetime(tmp_path: Path) -> None:
    path = tmp_path / "shot.jpg"
    image = Image.new("RGB", (64, 48), (10, 20, 30))
    exif = image.getexif()
    exif[36867] = "2026:09:27 16:49:37"
    image.save(path, "JPEG", exif=exif)

    meta = read_metadata(path)
    assert meta.time_source == "exif"
    assert format_datetime(meta.taken_ts) == "2026-09-27 16:49:37"
    assert meta.width == 64
    assert meta.height == 48


def test_read_metadata_falls_back_to_filename(tmp_path: Path) -> None:
    path = tmp_path / "IMG20260927164937.jpg"
    Image.new("RGB", (32, 32)).save(path, "JPEG")
    meta = read_metadata(path)
    assert meta.time_source in {"filename", "exif"}
    assert format_datetime(meta.taken_ts) == "2026-09-27 16:49:37"


def test_read_metadata_video_uses_filename(tmp_path: Path) -> None:
    path = tmp_path / "VID20260809154030.mp4"
    path.write_bytes(b"\x00" * 32)
    meta = read_metadata(path)
    assert meta.kind == "video"
    assert meta.time_source == "filename"
    assert format_datetime(meta.taken_ts) == "2026-08-09 15:40:30"


def test_read_metadata_missing_file(tmp_path: Path) -> None:
    meta = read_metadata(tmp_path / "nope.jpg")
    assert meta.taken_ts == 0
    assert meta.kind == "photo"


def test_join_camera_avoids_duplicate_brand() -> None:
    from livephoto_player.services.metadata import _join_camera

    assert _join_camera("OnePlus", "OnePlus 11") == "OnePlus 11"
    assert _join_camera("OnePlus", "11") == "OnePlus 11"
    assert _join_camera("", "11 Pro") == "11 Pro"
    assert _join_camera("Sony", "") == "Sony"
