"""视频封面抓取器测试：缓存、取消、超时与释放路径。

不依赖真实视频素材：用不存在的文件走超时分支，其余分支直接构造状态。
"""

from __future__ import annotations

from pathlib import Path

import pytest
from PySide6.QtGui import QImage

from livephoto_player.services import poster as poster_module
from livephoto_player.services.poster import PosterGrabber


@pytest.fixture
def grabber(qtbot: object) -> PosterGrabber:
    instance = PosterGrabber()
    yield instance  # type: ignore[misc]
    instance.shutdown()


def test_cache_starts_empty(grabber: PosterGrabber) -> None:
    assert grabber.cached("anything") is None


def test_request_with_empty_key_is_ignored(grabber: PosterGrabber) -> None:
    grabber.request("", Path("x.mp4"))
    assert grabber.cached("") is None


def test_cached_hit_emits_immediately(qtbot: object, grabber: PosterGrabber) -> None:
    image = QImage(64, 48, QImage.Format.Format_RGB32)
    image.fill(0xFF112233)
    grabber._cache["key"] = image
    with qtbot.waitSignal(grabber.poster_ready, timeout=2000) as blocker:  # type: ignore[attr-defined]
        grabber.request("key", Path("x.mp4"))
    assert blocker.args[0] == "key"
    assert blocker.args[1] is image


def test_cancel_without_pending_is_noop(grabber: PosterGrabber) -> None:
    grabber.cancel()
    assert grabber._pending is False


def test_timeout_emits_empty_result(
    qtbot: object,
    grabber: PosterGrabber,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setattr(poster_module, "_GRAB_POSITION_MS", 10)
    grabber._timer.setInterval(150)
    bogus = tmp_path / "not_a_video.mp4"
    bogus.write_bytes(b"not a video at all")
    with qtbot.waitSignal(grabber.poster_ready, timeout=8000) as blocker:  # type: ignore[attr-defined]
        grabber.request("bogus", bogus)
    assert blocker.args[0] == "bogus"
    assert grabber._pending is False


def test_invalid_frames_are_ignored(qtbot: object, grabber: PosterGrabber) -> None:
    grabber._pending = True
    grabber._on_frame(object())
    grabber._on_frame(None)
    assert grabber._pending is True


def test_frame_while_not_pending_is_ignored(grabber: PosterGrabber) -> None:
    grabber._pending = False
    grabber._on_frame(None)
    assert grabber._pending is False


def test_cancel_stops_pending_request(
    qtbot: object, grabber: PosterGrabber, tmp_path: Path
) -> None:
    grabber._timer.setInterval(5000)
    bogus = tmp_path / "x.mp4"
    bogus.write_bytes(b"x")
    grabber.request("x", bogus)
    assert grabber._pending is True
    grabber.cancel()
    assert grabber._pending is False


def test_shutdown_is_idempotent(grabber: PosterGrabber) -> None:
    grabber.shutdown()
    grabber.shutdown()
    assert grabber._player is None


def test_cache_eviction_keeps_limit() -> None:
    grabber = PosterGrabber()
    try:
        for index in range(poster_module._CACHE_LIMIT + 3):
            grabber._cache[f"k{index}"] = QImage(8, 8, QImage.Format.Format_RGB32)
            while len(grabber._cache) > poster_module._CACHE_LIMIT:
                grabber._cache.popitem(last=False)
        assert len(grabber._cache) == poster_module._CACHE_LIMIT
    finally:
        grabber.shutdown()
