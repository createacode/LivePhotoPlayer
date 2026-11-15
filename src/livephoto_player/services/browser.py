"""目录浏览：扫描受支持的媒体文件，带 mtime 缓存与自然排序。"""

from __future__ import annotations

import os
import re
from pathlib import Path

from livephoto_player.core.models import MediaKind

IMAGE_EXTENSIONS: frozenset[str] = frozenset(
    {".jpg", ".jpeg", ".heic", ".heif", ".png", ".bmp", ".tif", ".tiff", ".webp"}
)
VIDEO_EXTENSIONS: frozenset[str] = frozenset(
    {".mp4", ".mov", ".avi", ".mkv", ".m4v", ".wmv", ".webm", ".3gp"}
)
SUPPORTED_EXTENSIONS: frozenset[str] = IMAGE_EXTENSIONS | VIDEO_EXTENSIONS

_DIGITS = re.compile(r"(\d+)")


def natural_key(name: str) -> tuple[object, ...]:
    """自然排序键：``IMG2`` 排在 ``IMG10`` 之前。"""
    parts = _DIGITS.split(name.lower())
    return tuple(int(part) if part.isdigit() else part for part in parts)


def file_kind(path: Path) -> MediaKind:
    """按扩展名给出初步种类；照片是否为实况由加载器进一步确认。"""
    return MediaKind.VIDEO if path.suffix.lower() in VIDEO_EXTENSIONS else MediaKind.PHOTO


def is_supported(path: Path) -> bool:
    """扩展名是否受支持。"""
    return path.suffix.lower() in SUPPORTED_EXTENSIONS


class DirectoryBrowser:
    """按目录扫描媒体文件，目录 mtime 未变时直接复用上次结果。"""

    def __init__(self) -> None:
        self._cache: dict[Path, tuple[int, list[Path]]] = {}

    def scan(self, directory: Path) -> list[Path]:
        """返回目录下受支持的媒体文件（自然排序）。"""
        try:
            resolved = directory.resolve()
            mtime = int(resolved.stat().st_mtime)
        except OSError:
            return []
        cached = self._cache.get(resolved)
        if cached is not None and cached[0] == mtime:
            return list(cached[1])

        found: list[Path] = []
        try:
            with os.scandir(resolved) as entries:
                for entry in entries:
                    try:
                        if not entry.is_file(follow_symlinks=False):
                            continue
                    except OSError:
                        continue
                    name = entry.name
                    if Path(name).suffix.lower() in SUPPORTED_EXTENSIONS:
                        found.append(resolved / name)
        except OSError:
            return []
        found.sort(key=lambda item: natural_key(item.name))
        self._cache[resolved] = (mtime, found)
        return list(found)

    def invalidate(self, directory: Path | None = None) -> None:
        """丢弃缓存；不传目录时清空全部。"""
        if directory is None:
            self._cache.clear()
            return
        try:
            self._cache.pop(directory.resolve(), None)
        except OSError:
            return
