"""导出服务测试：照片复制、HEIC 转码、区间抽取与命名冲突。"""

from __future__ import annotations

import json
from pathlib import Path
from urllib.error import HTTPError, URLError

import pytest

from livephoto_player.core.models import MediaItem, MediaKind, VideoSpan
from livephoto_player.services.exporter import export_photo, export_video
from livephoto_player.update import gitee
from livephoto_player.update.downloader import expected_digest, parse_sums
from livephoto_player.update.gitee import (
    ReleaseAsset,
    UpdateError,
    is_newer,
    parse_release,
    parse_version,
    should_check_now,
)


# ----------------------------------------------------------------- 导出
def test_export_photo_copies_file(tmp_path: Path, sample_image: Path) -> None:
    out = tmp_path / "out"
    item = MediaItem(path=sample_image, kind=MediaKind.PHOTO)
    target = export_photo(item, out)
    assert target.exists()
    assert target.read_bytes() == sample_image.read_bytes()
    assert target.name.startswith("sample_photo_")


def test_export_photo_converts_heic_named_file(tmp_path: Path, sample_image: Path) -> None:
    fake_heic = tmp_path / "shot.heic"
    fake_heic.write_bytes(sample_image.read_bytes())
    out = tmp_path / "out"
    target = export_photo(MediaItem(path=fake_heic, kind=MediaKind.PHOTO), out)
    assert target.suffix == ".jpg"
    from PIL import Image

    with Image.open(target) as image:
        assert image.format == "JPEG"


def test_export_photo_avoids_overwrite(tmp_path: Path, sample_image: Path) -> None:
    out = tmp_path / "out"
    item = MediaItem(path=sample_image, kind=MediaKind.PHOTO)
    first = export_photo(item, out)
    second = export_photo(item, out)
    assert first != second


def test_export_video_extracts_span(tmp_path: Path) -> None:
    source = tmp_path / "live.jpg"
    header = b"HEADER" * 20
    video = b"\x00\x00\x00\x18ftypisom" + b"V" * 200
    source.write_bytes(header + video)
    item = MediaItem(
        path=source,
        kind=MediaKind.LIVE_PHOTO,
        span=VideoSpan(offset=len(header), length=len(video)),
    )
    target = export_video(item, tmp_path / "out")
    assert target.read_bytes() == video
    assert target.suffix == ".mp4"


def test_export_video_copies_plain_video(tmp_path: Path) -> None:
    source = tmp_path / "clip.mp4"
    source.write_bytes(b"\x00\x00\x00\x08ftyp" + b"x" * 100)
    target = export_video(MediaItem(path=source, kind=MediaKind.VIDEO), tmp_path / "out")
    assert target.read_bytes() == source.read_bytes()


def test_export_video_without_span_copies_whole_file(tmp_path: Path) -> None:
    source = tmp_path / "odd.mp4"
    source.write_bytes(b"data" * 50)
    target = export_video(MediaItem(path=source, kind=MediaKind.LIVE_PHOTO), tmp_path / "out")
    assert target.read_bytes() == source.read_bytes()


# ----------------------------------------------------------------- 版本比较
@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("v1.2.3", (1, 2, 3)),
        ("4.0.0", (4, 0, 0)),
        ("1.2", (1, 2, 0)),
        ("2", (2, 0, 0)),
        ("1.0.0-rc.1", (1, 0, 0)),
        ("garbage", None),
        ("", None),
    ],
)
def test_parse_version(text: str, expected: tuple[int, int, int] | None) -> None:
    assert parse_version(text) == expected


def test_is_newer_uses_numeric_comparison() -> None:
    assert is_newer("1.10.0", "1.9.9") is True
    assert is_newer("1.9.9", "1.10.0") is False
    assert is_newer("4.0.0", "4.0.0") is False
    assert is_newer("bad", "4.0.0") is False


def test_should_check_now_respects_interval() -> None:
    assert should_check_now("") is True
    assert should_check_now("not-a-date") is True
    from datetime import datetime, timedelta

    recent = (datetime.now() - timedelta(hours=1)).isoformat(timespec="seconds")
    old = (datetime.now() - timedelta(days=2)).isoformat(timespec="seconds")
    assert should_check_now(recent) is False
    assert should_check_now(old) is True


# ----------------------------------------------------------------- Release 解析
def _payload(**overrides: object) -> dict[str, object]:
    base: dict[str, object] = {
        "tag_name": "v4.1.0",
        "name": "4.1.0",
        "body": "修复若干问题",
        "created_at": "2026-11-01T10:00:00Z",
        "prerelease": False,
        "assets": [
            {
                "name": "App_v4.1.0.zip",
                "size": 1024,
                "digest": "sha256:" + "a" * 64,
                "browser_download_url": "https://gitee.com/x/y/releases/download/v4.1.0/App.zip",
            }
        ],
    }
    base.update(overrides)
    return base


def test_parse_release_full() -> None:
    info = parse_release(_payload())
    assert info.version == (4, 1, 0)
    assert info.version_text == "4.1.0"
    assert info.body.startswith("修复")
    asset = info.preferred_asset()
    assert asset is not None
    assert asset.name == "App_v4.1.0.zip"


def test_parse_release_prefers_exe() -> None:
    info = parse_release(
        _payload(
            assets=[
                {"name": "a.zip", "browser_download_url": "https://x/a.zip"},
                {"name": "b.exe", "browser_download_url": "https://x/b.exe"},
            ]
        )
    )
    asset = info.preferred_asset()
    assert asset is not None
    assert asset.name == "b.exe"


def test_parse_release_without_assets() -> None:
    info = parse_release(_payload(assets=[]))
    assert info.preferred_asset() is None


def test_parse_release_missing_tag() -> None:
    with pytest.raises(UpdateError):
        parse_release({"body": "x"})


def test_parse_release_not_a_dict() -> None:
    with pytest.raises(UpdateError):
        parse_release([1, 2, 3])


def test_fetch_latest_success() -> None:
    class FakeResponse:
        def __enter__(self) -> FakeResponse:
            return self

        def __exit__(self, *args: object) -> None:
            return None

        def read(self) -> bytes:
            return json.dumps(_payload()).encode()

    info = gitee.fetch_latest("owner", "repo", opener=lambda request, timeout: FakeResponse())
    assert info.version == (4, 1, 0)


@pytest.mark.parametrize(
    "error",
    [
        HTTPError("u", 404, "not found", {}, None),
        URLError("offline"),
        TimeoutError("slow"),
    ],
)
def test_fetch_latest_transport_errors(error: Exception) -> None:
    def boom(request: object, timeout: int) -> object:
        raise error

    with pytest.raises(UpdateError):
        gitee.fetch_latest("owner", "repo", opener=boom)


def test_fetch_latest_invalid_json() -> None:
    class FakeResponse:
        def __enter__(self) -> FakeResponse:
            return self

        def __exit__(self, *args: object) -> None:
            return None

        def read(self) -> bytes:
            return b"<html>not json</html>"

    with pytest.raises(UpdateError):
        gitee.fetch_latest("owner", "repo", opener=lambda req, timeout: FakeResponse())


def test_build_api_url_is_https() -> None:
    assert gitee.build_api_url("o", "r").startswith("https://gitee.com/api/v5/repos/o/r/releases")


# ----------------------------------------------------------------- 下载器辅助
def test_parse_sums() -> None:
    text = f"{'a' * 64}  file.zip\n{'b' * 64} *other.exe\n# comment\nbadline\n"
    mapping = parse_sums(text)
    assert mapping["file.zip"] == "a" * 64
    assert mapping["other.exe"] == "b" * 64
    assert len(mapping) == 2


def test_expected_digest_prefers_asset_digest() -> None:
    asset = ReleaseAsset("f.zip", 10, "sha256:" + "c" * 64, "https://x")
    assert expected_digest(asset, {"f.zip": "d" * 64}) == "c" * 64
    assert (
        expected_digest(ReleaseAsset("g.zip", 1, "", "https://x"), {"g.zip": "d" * 64}) == "d" * 64
    )
    assert expected_digest(ReleaseAsset("h.zip", 1, "", "https://x"), {}) == ""
