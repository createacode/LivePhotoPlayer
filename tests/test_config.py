"""配置读写测试：原子保存、损坏自愈、字段容错与范围钳制。"""

from __future__ import annotations

import json
from pathlib import Path

from livephoto_player.utils.config import (
    SCHEMA_VERSION,
    AppConfig,
    ConfigStore,
)


def test_defaults_when_missing(tmp_path: Path) -> None:
    store = ConfigStore(directory=tmp_path)
    config = store.load()
    assert config.schema_version == SCHEMA_VERSION
    assert config.window_width >= 640
    assert config.auto_play is False


def test_roundtrip(tmp_path: Path) -> None:
    store = ConfigStore(directory=tmp_path)
    config = AppConfig(
        last_directory=r"D:\Photos",
        window_width=1234,
        window_height=777,
        window_x=10,
        window_y=20,
        speed_index=5,
        muted=True,
        auto_play=True,
        show_file_list=False,
        tray_hint_shown=True,
    )
    assert store.save(config) is True
    loaded = store.load()
    assert loaded.last_directory == r"D:\Photos"
    assert loaded.window_width == 1234
    assert loaded.speed_index == 5
    assert loaded.auto_play is True
    assert loaded.show_file_list is False
    assert loaded.window_x == 10


def test_backup_written_on_second_save(tmp_path: Path) -> None:
    store = ConfigStore(directory=tmp_path)
    store.save(AppConfig(window_width=900))
    store.save(AppConfig(window_width=1000))
    assert store.backup_path.exists()
    assert store.load().window_width == 1000


def test_corrupt_file_is_quarantined(tmp_path: Path) -> None:
    store = ConfigStore(directory=tmp_path)
    store.path.write_text("{ this is not json", encoding="utf-8")
    config = store.load()
    assert config.window_width > 0
    assert store.corrupt_path.exists()
    assert not store.path.exists()


def test_unknown_and_invalid_fields_fall_back(tmp_path: Path) -> None:
    store = ConfigStore(directory=tmp_path)
    store.path.write_text(
        json.dumps(
            {
                "window_width": "huge",
                "window_height": None,
                "speed_index": 99,
                "auto_play": "yes",
                "unknown_key": 1,
            }
        ),
        encoding="utf-8",
    )
    config = store.load()
    assert isinstance(config.window_width, int)
    assert config.speed_index == 6
    assert config.auto_play is False


def test_window_size_is_clamped(tmp_path: Path) -> None:
    store = ConfigStore(directory=tmp_path)
    store.path.write_text(
        json.dumps({"window_width": 999999, "window_height": -5}), encoding="utf-8"
    )
    config = store.load()
    assert config.window_width <= 12000
    assert config.window_height >= 480


def test_schema_version_is_upgraded(tmp_path: Path) -> None:
    store = ConfigStore(directory=tmp_path)
    store.path.write_text(json.dumps({"schema_version": 0, "auto_play": True}), encoding="utf-8")
    config = store.load()
    assert config.schema_version == SCHEMA_VERSION
    assert config.auto_play is True


def test_save_creates_directory(tmp_path: Path) -> None:
    target = tmp_path / "nested" / "config"
    store = ConfigStore(directory=target)
    assert store.save(AppConfig()) is True
    assert (target / "config.json").exists()


def test_update_section_roundtrip(tmp_path: Path) -> None:
    store = ConfigStore(directory=tmp_path)
    config = AppConfig()
    config.update.owner = "someone"
    config.update.repo = "repo"
    config.update.ignored_version = "9.9.9"
    store.save(config)
    loaded = store.load()
    assert loaded.update.owner == "someone"
    assert loaded.update.ignored_version == "9.9.9"
