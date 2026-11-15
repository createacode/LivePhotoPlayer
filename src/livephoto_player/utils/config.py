"""配置读写：原子写入、损坏自愈、不可写回退与 schema 迁移。"""

from __future__ import annotations

import contextlib
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from livephoto_player.utils.logger import get_logger
from livephoto_player.utils.paths import config_dir

SCHEMA_VERSION = 1

MIN_WIDTH = 640
MAX_WIDTH = 12000
MIN_HEIGHT = 480
MAX_HEIGHT = 12000
SPEED_COUNT = 7

DEFAULT_UPDATE_OWNER = "user_gitee"
DEFAULT_UPDATE_REPO = "LivePhotoPlayer"


@dataclass(slots=True)
class GeoConfig:
    """地点解析配置。"""

    mode: str = "offline"  # offline | api | off
    provider: str = "tianditu"  # tianditu | nominatim
    tianditu_key: str = ""


@dataclass(slots=True)
class UpdateConfig:
    """更新检查相关配置。"""

    owner: str = DEFAULT_UPDATE_OWNER
    repo: str = DEFAULT_UPDATE_REPO
    last_check: str = ""
    ignored_version: str = ""


@dataclass(slots=True)
class AppConfig:
    """全部可持久化的用户配置。"""

    schema_version: int = SCHEMA_VERSION
    last_directory: str = ""
    window_width: int = 1080
    window_height: int = 760
    window_x: int | None = None
    window_y: int | None = None
    speed_index: int = 3
    muted: bool = False
    auto_play: bool = False
    show_file_list: bool = True
    order_mode: str = "timeline"
    log_level: str = "INFO"
    tray_hint_shown: bool = False
    geo: GeoConfig = field(default_factory=GeoConfig)
    update: UpdateConfig = field(default_factory=UpdateConfig)

    def to_dict(self) -> dict[str, Any]:
        """序列化为 JSON 友好的字典。"""
        return {
            "schema_version": self.schema_version,
            "last_directory": self.last_directory,
            "window_width": self.window_width,
            "window_height": self.window_height,
            "window_x": self.window_x,
            "window_y": self.window_y,
            "speed_index": self.speed_index,
            "muted": self.muted,
            "auto_play": self.auto_play,
            "show_file_list": self.show_file_list,
            "order_mode": self.order_mode,
            "log_level": self.log_level,
            "tray_hint_shown": self.tray_hint_shown,
            "geo": {
                "mode": self.geo.mode,
                "provider": self.geo.provider,
                "tianditu_key": self.geo.tianditu_key,
            },
            "update": {
                "owner": self.update.owner,
                "repo": self.update.repo,
                "last_check": self.update.last_check,
                "ignored_version": self.update.ignored_version,
            },
        }

    @classmethod
    def from_dict(cls, raw: Any) -> AppConfig:
        """从字典安全还原；缺失或非法的字段一律回退默认值。"""
        config = cls()
        if not isinstance(raw, dict):
            return config

        config.schema_version = _as_int(raw.get("schema_version"), SCHEMA_VERSION)
        config.last_directory = _as_str(raw.get("last_directory"), "")
        config.window_width = _clamp(
            _as_int(raw.get("window_width"), config.window_width), MIN_WIDTH, MAX_WIDTH
        )
        config.window_height = _clamp(
            _as_int(raw.get("window_height"), config.window_height), MIN_HEIGHT, MAX_HEIGHT
        )
        config.window_x = _as_optional_int(raw.get("window_x"))
        config.window_y = _as_optional_int(raw.get("window_y"))
        config.speed_index = _clamp(_as_int(raw.get("speed_index"), 3), 0, SPEED_COUNT - 1)
        config.muted = _as_bool(raw.get("muted"), False)
        config.auto_play = _as_bool(raw.get("auto_play"), False)
        config.show_file_list = _as_bool(raw.get("show_file_list"), True)
        mode = _as_str(raw.get("order_mode"), "timeline")
        config.order_mode = mode if mode in {"name", "timeline"} else "timeline"
        config.log_level = _as_str(raw.get("log_level"), "INFO").upper()
        config.tray_hint_shown = _as_bool(raw.get("tray_hint_shown"), False)

        geo_raw = raw.get("geo")
        if isinstance(geo_raw, dict):
            mode = _as_str(geo_raw.get("mode"), "offline")
            provider = _as_str(geo_raw.get("provider"), "tianditu")
            config.geo = GeoConfig(
                mode=mode if mode in {"offline", "api", "off"} else "offline",
                provider=provider if provider in {"tianditu", "nominatim"} else "tianditu",
                tianditu_key=_as_str(geo_raw.get("tianditu_key"), "").strip(),
            )

        update_raw = raw.get("update")
        if isinstance(update_raw, dict):
            config.update = UpdateConfig(
                owner=_as_str(update_raw.get("owner"), DEFAULT_UPDATE_OWNER),
                repo=_as_str(update_raw.get("repo"), DEFAULT_UPDATE_REPO),
                last_check=_as_str(update_raw.get("last_check"), ""),
                ignored_version=_as_str(update_raw.get("ignored_version"), ""),
            )
        return config


def _as_int(value: Any, default: int) -> int:
    if isinstance(value, bool):
        return default
    if isinstance(value, int):
        return value
    if isinstance(value, float) and value.is_integer():
        return int(value)
    return default


def _as_optional_int(value: Any) -> int | None:
    if value is None:
        return None
    if isinstance(value, int) and not isinstance(value, bool):
        return value
    return None


def _as_bool(value: Any, default: bool) -> bool:
    return value if isinstance(value, bool) else default


def _as_str(value: Any, default: str) -> str:
    return value if isinstance(value, str) else default


def _clamp(value: int, low: int, high: int) -> int:
    return max(low, min(high, value))


class ConfigStore:
    """负责 ``config.json`` 的加载与原子保存。"""

    def __init__(self, directory: Path | None = None) -> None:
        resolved = config_dir() if directory is None else None
        self.directory = directory if directory is not None else resolved.path  # type: ignore[union-attr]
        self.fallback = resolved.fallback if resolved is not None else False
        self.fallback_reason = resolved.reason if resolved is not None else ""
        self.path = self.directory / "config.json"
        self.backup_path = self.directory / "config.json.bak"
        self.corrupt_path = self.directory / "config.json.corrupt"
        self._logger = get_logger("config")

    def load(self) -> AppConfig:
        """读取配置；文件缺失、损坏或不可读时一律回退默认值。"""
        if not self.path.exists():
            return AppConfig()
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            self._logger.error("配置读取失败，使用默认值：%s", exc)
            self._quarantine()
            return AppConfig()
        config = AppConfig.from_dict(raw)
        if config.schema_version != SCHEMA_VERSION:
            self._logger.warning(
                "配置 schema 版本 %s 与当前 %s 不一致，保留字段并升级",
                config.schema_version,
                SCHEMA_VERSION,
            )
            config.schema_version = SCHEMA_VERSION
        return config

    def _quarantine(self) -> None:
        try:
            self.path.replace(self.corrupt_path)
            self._logger.warning("损坏的配置文件已保留为 %s", self.corrupt_path)
        except OSError as exc:
            self._logger.error("保留损坏配置失败：%s", exc)

    def save(self, config: AppConfig) -> bool:
        """原子保存配置：临时文件 + ``os.replace``，并保留一份 ``.bak``。"""
        self.directory.mkdir(parents=True, exist_ok=True)
        temp_path = self.directory / "config.json.tmp"
        payload = json.dumps(config.to_dict(), ensure_ascii=False, indent=2)
        try:
            temp_path.write_text(payload, encoding="utf-8")
            if self.path.exists():
                try:
                    self.backup_path.write_bytes(self.path.read_bytes())
                except OSError as exc:
                    self._logger.warning("写入配置备份失败：%s", exc)
            temp_path.replace(self.path)
        except OSError as exc:
            self._logger.error("配置保存失败：%s", exc)
            with contextlib.suppress(OSError):
                temp_path.unlink(missing_ok=True)
            return False
        return True
