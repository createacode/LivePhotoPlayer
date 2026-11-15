"""导出命名规则：``原名_photo_HHMMSS_四位随机数.扩展名``。"""

from __future__ import annotations

import random
from datetime import datetime
from pathlib import Path
from typing import Literal

ExportKind = Literal["photo", "video"]

RANDOM_DIGITS = 4
MAX_UNIQUE_ATTEMPTS = 100


def build_export_name(
    original: Path,
    kind: ExportKind,
    *,
    now: datetime | None = None,
    digits: str | None = None,
) -> str:
    """生成导出文件名，不负责去重。"""
    stamp = (now or datetime.now()).strftime("%H%M%S")
    suffix = digits if digits is not None else f"{random.randint(0, 9999):04d}"
    base = original.stem
    prefix = "photo" if kind == "photo" else "video"
    if kind == "photo":
        extension = original.suffix
        if extension.lower() in {".heic", ".heif"}:
            extension = ".jpg"
    else:
        extension = ".mp4"
    return f"{base}_{prefix}_{stamp}_{suffix}{extension}"


def unique_path(directory: Path, filename: str) -> Path:
    """若目标已存在则追加序号，避免静默覆盖历史导出。"""
    target = directory / filename
    if not target.exists():
        return target
    stem = target.stem
    suffix = target.suffix
    for index in range(1, MAX_UNIQUE_ATTEMPTS + 1):
        candidate = directory / f"{stem}_{index:02d}{suffix}"
        if not candidate.exists():
            return candidate
    raise FileExistsError(f"无法为 {filename} 找到可用文件名")
