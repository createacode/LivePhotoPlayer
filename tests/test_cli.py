"""命令行参数处理测试。"""

from __future__ import annotations

from pathlib import Path

import pytest

from livephoto_player.app.main import _handle_cli, _startup_path_from_argv
from livephoto_player.core.version import __software_name__, __version__


def test_version_flag(capsys: pytest.CaptureFixture[str]) -> None:
    assert _handle_cli(["app.exe", "--version"]) == 0
    out = capsys.readouterr().out
    assert __version__ in out
    assert __software_name__ in out
    assert "Copyright" in out


def test_help_flag(capsys: pytest.CaptureFixture[str]) -> None:
    assert _handle_cli(["app.exe", "--help"]) == 0
    out = capsys.readouterr().out
    assert "--version" in out
    assert "用法" in out


def test_no_flag_continues_launch() -> None:
    assert _handle_cli(["app.exe"]) is None
    assert _handle_cli(["app.exe", "C:/tmp/a.jpg"]) is None


def test_startup_path_skips_flags(tmp_path: Path) -> None:
    target = tmp_path / "a.jpg"
    target.write_bytes(b"x")
    assert _startup_path_from_argv(["app.exe", "--verbose", str(target)]) == str(target)


def test_startup_path_missing_file() -> None:
    assert _startup_path_from_argv(["app.exe", "does-not-exist.jpg"]) is None
