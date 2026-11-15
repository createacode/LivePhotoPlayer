"""解码调度器、播放引擎与后台任务的测试（需要 QApplication）。"""

from __future__ import annotations

from pathlib import Path

import pytest

from livephoto_player.core.models import ImagePayload, PlaybackState, VideoSpan
from livephoto_player.services.image_loader import ImageLoader
from livephoto_player.services.media_engine import MediaEngine
from livephoto_player.services.workers import TaskRunner


# --------------------------------------------------------------- ImageLoader
def test_loader_request_emits_payload(qtbot: object, sample_image: Path) -> None:
    loader = ImageLoader()
    try:
        with qtbot.waitSignal(loader.loaded, timeout=8000) as blocker:  # type: ignore[attr-defined]
            loader.request(sample_image, 120, 7)
        payload: ImagePayload = blocker.args[0]
        assert payload.error == ""
        assert payload.generation == 7
        # 目标宽度会量化到 256 的桶，因此实际解码宽度不超过该桶且不大于原图
        assert payload.display_width <= 256
        assert payload.source_width == 320
    finally:
        loader.shutdown()


def test_loader_cache_hit_updates_generation(qtbot: object, sample_image: Path) -> None:
    loader = ImageLoader()
    try:
        with qtbot.waitSignal(loader.loaded, timeout=8000) as first:  # type: ignore[attr-defined]
            loader.request(sample_image, 120, 1)
        assert first.args[0].generation == 1
        with qtbot.waitSignal(loader.loaded, timeout=3000) as second:  # type: ignore[attr-defined]
            loader.request(sample_image, 120, 2)
        assert second.args[0].generation == 2
        assert loader.cached(sample_image, 120) is not None
    finally:
        loader.shutdown()


def test_loader_reports_decode_failure(qtbot: object, tmp_path: Path) -> None:
    loader = ImageLoader()
    try:
        with qtbot.waitSignal(loader.loaded, timeout=8000) as blocker:  # type: ignore[attr-defined]
            loader.request(tmp_path / "missing.jpg", 120, 3)
        payload: ImagePayload = blocker.args[0]
        assert payload.error
        assert payload.display_width == 0
    finally:
        loader.shutdown()


def test_loader_prefetch_fills_cache(qtbot: object, sample_image: Path) -> None:
    loader = ImageLoader()
    try:
        loader.prefetch([sample_image], 120)
        qtbot.waitUntil(lambda: loader.cached(sample_image, 120) is not None, timeout=8000)  # type: ignore[attr-defined]
        assert loader.cached(sample_image, 120) is not None
    finally:
        loader.shutdown()


def test_loader_generation_increments(sample_image: Path) -> None:
    loader = ImageLoader()
    try:
        assert loader.next_generation() == 1
        assert loader.next_generation() == 2
        assert loader.generation == 2
    finally:
        loader.shutdown()


# --------------------------------------------------------------- MediaEngine
def test_engine_initial_state() -> None:
    engine = MediaEngine()
    try:
        assert engine.state is PlaybackState.IDLE
        assert engine.is_playing is False
        assert engine.position == 0
    finally:
        engine.shutdown()


def test_engine_controls_without_source() -> None:
    engine = MediaEngine()
    try:
        engine.play()
        engine.pause()
        engine.stop()
        engine.seek(1000)
        engine.set_muted(True)
        assert engine.is_playing is False
    finally:
        engine.shutdown()


def test_engine_rate_is_clamped() -> None:
    engine = MediaEngine()
    try:
        engine.set_rate(99.0)
        assert engine.rate == 4.0
        engine.set_rate(0.0)
        assert engine.rate == 0.1
    finally:
        engine.shutdown()


def test_engine_open_span_creates_and_releases_device(tmp_path: Path) -> None:
    path = tmp_path / "live.jpg"
    path.write_bytes(b"\x00" * 800)
    engine = MediaEngine()
    try:
        engine.open_span(path, VideoSpan(100, 400))
        assert engine._device is not None
        engine.clear()
        assert engine._device is None
    finally:
        engine.shutdown()


def test_engine_open_path_marks_source(tmp_path: Path) -> None:
    path = tmp_path / "clip.mp4"
    path.write_bytes(b"\x00" * 400)
    engine = MediaEngine()
    try:
        engine.open_path(path)
        assert engine.state in (PlaybackState.IDLE, PlaybackState.LOADING, PlaybackState.ERROR)
    finally:
        engine.shutdown()


# --------------------------------------------------------------- TaskRunner
def test_task_runner_success(qtbot: object) -> None:
    runner = TaskRunner()
    try:
        with qtbot.waitSignal(runner.succeeded, timeout=8000) as blocker:  # type: ignore[attr-defined]
            runner.submit(lambda: 42)
        assert blocker.args[0] == 42
    finally:
        runner.shutdown()


def test_task_runner_failure(qtbot: object) -> None:
    runner = TaskRunner()
    try:

        def boom() -> None:
            raise ValueError("bad")

        with qtbot.waitSignal(runner.failed, timeout=8000) as blocker:  # type: ignore[attr-defined]
            runner.submit(boom)
        assert "bad" in blocker.args[0]
    finally:
        runner.shutdown()


def test_task_runner_callback(qtbot: object) -> None:
    runner = TaskRunner()
    results: list[object] = []
    try:
        runner.submit(lambda: "ok", on_success=results.append)
        qtbot.waitUntil(lambda: results == ["ok"], timeout=8000)  # type: ignore[attr-defined]
    finally:
        runner.shutdown()


@pytest.mark.parametrize("value", [0, 1, "x"])
def test_task_runner_ignores_unknown_task_finish(value: object) -> None:
    runner = TaskRunner()
    try:
        runner._on_finished(9999, value, "")
    finally:
        runner.shutdown()
