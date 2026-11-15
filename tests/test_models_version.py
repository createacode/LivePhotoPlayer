"""领域模型与版本信息测试。"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from livephoto_player.core.models import (
    MediaItem,
    MediaKind,
    PlaybackState,
    SessionState,
    VideoSpan,
)
from livephoto_player.core.version import (
    COPYRIGHT_SUFFIX,
    __author__,
    __copyright_ym__,
    __software_name__,
    __version__,
    copyright_suffix,
    window_title,
)


def test_video_span_validates_input() -> None:
    with pytest.raises(ValueError):
        VideoSpan(-1, 10)
    with pytest.raises(ValueError):
        VideoSpan(0, 0)


def test_video_span_end() -> None:
    span = VideoSpan(100, 50)
    assert span.end == 150


def test_media_item_has_video() -> None:
    photo = MediaItem(path=Path("a.jpg"), kind=MediaKind.PHOTO)
    live = MediaItem(path=Path("b.jpg"), kind=MediaKind.LIVE_PHOTO, span=VideoSpan(10, 90))
    live_without_span = MediaItem(path=Path("c.jpg"), kind=MediaKind.LIVE_PHOTO)
    video = MediaItem(path=Path("d.mp4"), kind=MediaKind.VIDEO)
    assert photo.has_video is False
    assert live.has_video is True
    assert live_without_span.has_video is False
    assert video.has_video is True


def test_media_kind_labels() -> None:
    assert MediaKind.PHOTO.label == "照片"
    assert MediaKind.LIVE_PHOTO.label == "实况照片"
    assert MediaKind.VIDEO.label == "视频"
    assert MediaKind.PHOTO.is_video_source is False


def test_session_state_navigation(tmp_path: Path) -> None:
    items = [MediaItem(path=tmp_path / f"{i}.jpg", kind=MediaKind.PHOTO) for i in range(3)]
    session = SessionState(directory=tmp_path, items=items, index=0)
    assert session.current is items[0]
    assert session.has_previous is False
    assert session.has_next is True
    session.index = 2
    assert session.has_next is False
    assert session.has_previous is True
    session.index = 9
    assert session.current is None


def test_session_index_of(tmp_path: Path) -> None:
    target = tmp_path / "b.jpg"
    session = SessionState(
        directory=tmp_path,
        items=[
            MediaItem(path=tmp_path / "a.jpg", kind=MediaKind.PHOTO),
            MediaItem(path=target, kind=MediaKind.PHOTO),
        ],
    )
    assert session.index_of(target) == 1
    assert session.index_of(tmp_path / "missing.jpg") == -1


def test_playback_state_values() -> None:
    assert PlaybackState.PLAYING.value == "playing"
    assert PlaybackState.ERROR.value == "error"


def test_version_format_matches_semver() -> None:
    assert re.fullmatch(r"\d+\.\d+\.\d+", __version__)


def test_copyright_and_titles() -> None:
    assert f"Copyright © {__author__} {__copyright_ym__}" == COPYRIGHT_SUFFIX
    assert re.fullmatch(r"\d{4}\.\d{2}", __copyright_ym__)
    assert copyright_suffix().startswith("- Copyright ©")
    title = window_title()
    assert __software_name__ in title
    assert f"v{__version__}" in title
    assert __author__ in title
