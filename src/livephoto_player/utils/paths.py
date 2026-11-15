"""路径解析：统一开发态与冻结态的运行目录。

所有目录解析都必须经过本模块，禁止在别处拼接固定盘符或开发机绝对路径。
"""

from __future__ import annotations

import os
import sys
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Literal

APP_ID = "LivePhotoPlayer"

EXPORT_PHOTO_DIRNAME = "照片"
EXPORT_VIDEO_DIRNAME = "视频"
FAVORITE_DIRNAME = "收藏"

DirKind = Literal["logs", "config", "cache", "photo_export", "video_export", "favorites"]


@dataclass(frozen=True, slots=True)
class ResolvedDir:
    """解析后的目录及其是否发生了回退。"""

    path: Path
    fallback: bool
    reason: str = ""


def is_frozen() -> bool:
    """是否运行在 PyInstaller 冻结态。"""
    return bool(getattr(sys, "frozen", False))


def project_root() -> Path:
    """开发态仓库根目录；冻结态返回 exe 所在目录。"""
    if is_frozen():
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parents[3]


def app_dir() -> Path:
    """程序主目录：配置、日志、导出目录的首选父目录。"""
    return project_root()


def resource_path(relative: str) -> Path:
    """资源文件路径，兼容冻结态（``sys._MEIPASS``）与开发态。"""
    base = Path(getattr(sys, "_MEIPASS", str(project_root()))) if is_frozen() else project_root()
    return base / relative


def package_resource(relative: str) -> Path:
    """包内资源路径（开发态与冻结态都指向 ``livephoto_player/resources``）。"""
    return Path(__file__).resolve().parents[1] / "resources" / relative


def local_appdata_dir() -> Path:
    """``%LOCALAPPDATA%``，取不到时退回用户主目录。"""
    raw = os.environ.get("LOCALAPPDATA")
    if raw:
        return Path(raw)
    return Path.home() / "AppData" / "Local"


def _probe_writable(path: Path) -> bool:
    """真实建目录并写一个探针文件，避免只靠权限位判断。"""
    try:
        path.mkdir(parents=True, exist_ok=True)
        probe = path / f".probe_{os.getpid()}"
        probe.write_bytes(b"")
        probe.unlink()
    except OSError:
        return False
    return True


def _resolve(preferred: Path, fallback: Path) -> ResolvedDir:
    if _probe_writable(preferred):
        return ResolvedDir(preferred, False)
    if _probe_writable(fallback):
        return ResolvedDir(fallback, True, f"{preferred} 不可写，已回退到 {fallback}")
    return ResolvedDir(fallback, True, f"{preferred} 与 {fallback} 均不可写")


@lru_cache(maxsize=16)
def _resolve_kind(kind: DirKind) -> ResolvedDir:
    base = app_dir()
    local = local_appdata_dir() / APP_ID
    if kind == "logs":
        return _resolve(base / "logs", local / "logs")
    if kind == "config":
        return _resolve(base / "config", local / "config")
    if kind == "cache":
        return _resolve(local / "cache", base / "cache")
    if kind == "photo_export":
        return _resolve(base / EXPORT_PHOTO_DIRNAME, local / EXPORT_PHOTO_DIRNAME)
    if kind == "video_export":
        return _resolve(base / EXPORT_VIDEO_DIRNAME, local / EXPORT_VIDEO_DIRNAME)
    return _resolve(base / FAVORITE_DIRNAME, local / FAVORITE_DIRNAME)


def logs_dir() -> ResolvedDir:
    """日志目录：exe 同级 ``logs/``，不可写时回退 ``%LOCALAPPDATA%``。"""
    return _resolve_kind("logs")


def config_dir() -> ResolvedDir:
    """配置目录：exe 同级 ``config/``，不可写时回退 ``%LOCALAPPDATA%``。"""
    return _resolve_kind("config")


def cache_dir() -> ResolvedDir:
    """缓存目录：优先 ``%LOCALAPPDATA%``，避免占用安装目录。"""
    return _resolve_kind("cache")


def export_dir(kind: Literal["photo", "video"]) -> Path:
    """导出目录：``照片/`` 与 ``视频/``。"""
    resolved = _resolve_kind("photo_export" if kind == "photo" else "video_export")
    return resolved.path


def favorite_dir() -> Path:
    """收藏副本目录：exe 同级 ``收藏/``，不可写时回退 ``%LOCALAPPDATA%``。"""
    return _resolve_kind("favorites").path


def catalog_path() -> Path:
    """结构化索引数据库位置（放在缓存目录，不污染安装目录）。"""
    return cache_dir().path / "catalog.db"


def clear_cached_resolutions() -> None:
    """清空目录解析缓存（仅供测试与运行期重试使用）。"""
    _resolve_kind.cache_clear()
