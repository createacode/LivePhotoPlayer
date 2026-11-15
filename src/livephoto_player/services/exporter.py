"""导出服务：照片导出、内嵌视频抽取与独立视频复制。"""

from __future__ import annotations

import shutil
from datetime import datetime
from pathlib import Path

from livephoto_player.core.models import MediaItem
from livephoto_player.core.naming import build_export_name, unique_path
from livephoto_player.utils.logger import get_logger

_COPY_CHUNK = 1 << 20


def export_photo(item: MediaItem, directory: Path, *, now: datetime | None = None) -> Path:
    """导出照片；HEIC 转 JPEG，其它格式原样复制。"""
    directory.mkdir(parents=True, exist_ok=True)
    name = build_export_name(item.path, "photo", now=now)
    target = unique_path(directory, name)
    if item.path.suffix.lower() in {".heic", ".heif"}:
        _convert_to_jpeg(item.path, target)
    else:
        shutil.copy2(item.path, target)
    get_logger("export").info("导出照片 %s -> %s", item.path.name, target.name)
    return target


def export_video(item: MediaItem, directory: Path, *, now: datetime | None = None) -> Path:
    """导出视频；实况照片按区间流式抽取，独立视频直接复制。"""
    directory.mkdir(parents=True, exist_ok=True)
    name = build_export_name(item.path, "video", now=now)
    target = unique_path(directory, name)
    if item.span is not None:
        _copy_span(item.path, item.span.offset, item.span.end, target)
    else:
        shutil.copy2(item.path, target)
    get_logger("export").info("导出视频 %s -> %s", item.path.name, target.name)
    return target


def _convert_to_jpeg(source: Path, target: Path) -> None:
    from PIL import Image

    with Image.open(source) as image:
        image.convert("RGB").save(target, "JPEG", quality=92)


def _copy_span(source: Path, start: int, end: int, target: Path) -> None:
    """按块复制字节区间，避免整段视频进内存。"""
    remaining = end - start
    with source.open("rb") as reader, target.open("wb") as writer:
        reader.seek(start)
        while remaining > 0:
            block = reader.read(min(_COPY_CHUNK, remaining))
            if not block:
                break
            writer.write(block)
            remaining -= len(block)
