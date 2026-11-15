"""路径解析测试：开发态/冻结态、资源路径与不可写回退。"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

from livephoto_player.utils import paths


def test_app_dir_in_dev_mode(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delattr(sys, "frozen", raising=False)
    assert paths.is_frozen() is False
    assert paths.app_dir() == paths.project_root()
    assert paths.app_dir().is_dir()


def test_frozen_uses_executable_dir(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    fake_exe = tmp_path / "dist" / "App.exe"
    fake_exe.parent.mkdir(parents=True)
    fake_exe.write_text("", encoding="utf-8")
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "executable", str(fake_exe), raising=False)
    assert paths.is_frozen() is True
    assert paths.app_dir() == fake_exe.parent


def test_resource_path_uses_meipass(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "_MEIPASS", str(tmp_path), raising=False)
    assert paths.resource_path("app.ico") == tmp_path / "app.ico"


def test_resolve_falls_back_when_preferred_not_writable(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    blocked = tmp_path / "blocked"
    okay = tmp_path / "okay"
    monkeypatch.setattr(paths, "_probe_writable", lambda path: path == okay)
    resolved = paths._resolve(blocked, okay)
    assert resolved.path == okay
    assert resolved.fallback is True
    assert "回退" in resolved.reason


def test_resolve_returns_preferred_when_writable(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    preferred = tmp_path / "preferred"
    fallback = tmp_path / "fallback"
    monkeypatch.setattr(paths, "_probe_writable", lambda path: True)
    resolved = paths._resolve(preferred, fallback)
    assert resolved.path == preferred
    assert resolved.fallback is False


def test_resolve_reports_when_nothing_is_writable(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(paths, "_probe_writable", lambda path: False)
    resolved = paths._resolve(tmp_path / "a", tmp_path / "b")
    assert resolved.fallback is True
    assert "均不可写" in resolved.reason


def test_probe_writable_creates_and_cleans(tmp_path: Path) -> None:
    target = tmp_path / "probe"
    assert paths._probe_writable(target) is True
    assert target.is_dir()
    assert not list(target.glob(".probe_*"))


def test_export_dir_names(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(paths, "app_dir", lambda: tmp_path)
    monkeypatch.setattr(paths, "local_appdata_dir", lambda: tmp_path / "local")
    paths.clear_cached_resolutions()
    assert paths.export_dir("photo").name == paths.EXPORT_PHOTO_DIRNAME
    assert paths.export_dir("video").name == paths.EXPORT_VIDEO_DIRNAME
    paths.clear_cached_resolutions()
