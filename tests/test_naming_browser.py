"""导出命名与目录浏览测试。"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

from livephoto_player.core.models import MediaKind
from livephoto_player.core.naming import build_export_name, unique_path
from livephoto_player.services.browser import (
    DirectoryBrowser,
    file_kind,
    is_supported,
    natural_key,
)


def test_photo_name_keeps_extension() -> None:
    name = build_export_name(
        Path(r"D:\a\IMG_001.jpg"),
        "photo",
        now=datetime(2026, 5, 2, 13, 14, 15),
        digits="0042",
    )
    assert name == "IMG_001_photo_131415_0042.jpg"


def test_heic_photo_becomes_jpg() -> None:
    name = build_export_name(Path("x.HEIC"), "photo", now=datetime(2026, 1, 1), digits="0001")
    assert name.endswith(".jpg")
    assert name.startswith("x_photo_")


def test_video_name_is_mp4() -> None:
    name = build_export_name(
        Path("clip.mov"), "video", now=datetime(2026, 1, 1, 1, 2, 3), digits="0009"
    )
    assert name == "clip_video_010203_0009.mp4"


def test_unique_path_appends_suffix(tmp_path: Path) -> None:
    first = unique_path(tmp_path, "a.jpg")
    assert first.name == "a.jpg"
    first.write_bytes(b"x")
    second = unique_path(tmp_path, "a.jpg")
    assert second.name == "a_01.jpg"
    second.write_bytes(b"x")
    third = unique_path(tmp_path, "a.jpg")
    assert third.name == "a_02.jpg"


def test_natural_key_orders_numbers() -> None:
    names = ["IMG10.jpg", "IMG2.jpg", "IMG1.jpg"]
    assert sorted(names, key=natural_key) == ["IMG1.jpg", "IMG2.jpg", "IMG10.jpg"]


def test_file_kind_and_support() -> None:
    assert file_kind(Path("a.mp4")) is MediaKind.VIDEO
    assert file_kind(Path("a.jpg")) is MediaKind.PHOTO
    assert is_supported(Path("a.HEIC")) is True
    assert is_supported(Path("a.txt")) is False


def test_browser_scan_filters_and_sorts(tmp_path: Path) -> None:
    for name in ("b.jpg", "a.png", "c.mp4", "note.txt", "d.heic"):
        (tmp_path / name).write_bytes(b"x")
    (tmp_path / "subdir").mkdir()
    browser = DirectoryBrowser()
    found = [path.name for path in browser.scan(tmp_path)]
    assert found == ["a.png", "b.jpg", "c.mp4", "d.heic"]


def test_browser_cache_reused_until_invalidated(tmp_path: Path) -> None:
    (tmp_path / "a.jpg").write_bytes(b"x")
    browser = DirectoryBrowser()
    assert len(browser.scan(tmp_path)) == 1
    browser.invalidate(tmp_path)
    assert len(browser.scan(tmp_path)) == 1


def test_browser_missing_directory_returns_empty(tmp_path: Path) -> None:
    browser = DirectoryBrowser()
    assert browser.scan(tmp_path / "nope") == []


def test_browser_ignores_directories(tmp_path: Path) -> None:
    (tmp_path / "folder.jpg").mkdir()
    (tmp_path / "real.jpg").write_bytes(b"x")
    assert [p.name for p in DirectoryBrowser().scan(tmp_path)] == ["real.jpg"]
