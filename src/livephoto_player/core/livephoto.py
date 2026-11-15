"""实况照片解析：从照片尾部定位内嵌视频区间。

策略与 v3 一致但改为流式扫描，避免把整个文件读进内存：

1. 优先读 XMP 元数据里的长度（``Item:Length`` / ``MicroVideoOffset``）；
2. 按长度反推偏移，并在偏移附近校验 ``ftyp`` 魔数；
3. 元数据缺失或校验失败时，从文件尾部向前分块搜索最后一个 ``ftyp``。
"""

from __future__ import annotations

import re
import struct
from pathlib import Path

from livephoto_player.core.models import VideoSpan

FTYP_MAGIC = b"ftyp"
CHUNK_SIZE = 1 << 20
SEARCH_TOLERANCE = 4096
MAX_METADATA_SCAN = 64 << 20
MIN_SPAN_LENGTH = 64
_OVERLAP = 64

_LENGTH_PATTERNS = (
    re.compile(rb'Item:Length="(\d+)"'),
    re.compile(rb'MicroVideoOffset="(\d+)"'),
)

_MP4_BOX_MIN = 8


def _iter_chunks(path: Path, limit: int) -> list[bytes]:
    """按块读取前 ``limit`` 字节，块之间保留重叠以便跨块匹配。"""
    chunks: list[bytes] = []
    consumed = 0
    with path.open("rb") as handle:
        while consumed < limit:
            block = handle.read(CHUNK_SIZE)
            if not block:
                break
            chunks.append(block)
            consumed += len(block)
    return chunks


def find_declared_length(path: Path, total_size: int) -> int:
    """从文件头部元数据里读取声明的视频长度，找不到返回 ``0``。"""
    limit = min(total_size, MAX_METADATA_SCAN)
    tail = b""
    consumed = 0
    try:
        with path.open("rb") as handle:
            while consumed < limit:
                block = handle.read(CHUNK_SIZE)
                if not block:
                    break
                window = tail + block
                for pattern in _LENGTH_PATTERNS:
                    match = pattern.search(window)
                    if match is not None:
                        value = int(bytes(match.group(1)))
                        return value if 0 < value < total_size else 0
                tail = window[-_OVERLAP:]
                consumed += len(block)
    except OSError:
        return 0
    return 0


def _box_size_at(path: Path, offset: int) -> int:
    """读取 ``offset`` 处的 MP4 box 长度字段，非法时返回 ``0``。"""
    try:
        with path.open("rb") as handle:
            handle.seek(offset)
            raw = handle.read(4)
    except OSError:
        return 0
    if len(raw) < 4:
        return 0
    return int(struct.unpack(">I", raw)[0])


def _valid_ftyp_offset(path: Path, offset: int, total_size: int) -> bool:
    """确认 ``offset`` 处是一个可用的 ``ftyp`` box。"""
    if offset < 0 or total_size - offset < MIN_SPAN_LENGTH:
        return False
    box_size = _box_size_at(path, offset)
    if box_size == 1:
        return True
    return _MP4_BOX_MIN <= box_size <= total_size - offset


def _locate_near(path: Path, expected: int, total_size: int) -> int | None:
    """在期望偏移附近容错搜索 ``ftyp``，命中时返回 box 起始偏移。"""
    if _valid_ftyp_offset(path, expected, total_size):
        return expected
    start = max(0, expected - SEARCH_TOLERANCE)
    end = min(total_size, expected + SEARCH_TOLERANCE + len(FTYP_MAGIC))
    try:
        with path.open("rb") as handle:
            handle.seek(start)
            window = handle.read(end - start)
    except OSError:
        return None
    position = window.find(FTYP_MAGIC)
    best: int | None = None
    best_distance = 0
    while position != -1:
        candidate = start + position - 4
        distance = abs(candidate - expected)
        if _valid_ftyp_offset(path, candidate, total_size) and (
            best is None or distance < best_distance
        ):
            best = candidate
            best_distance = distance
        position = window.find(FTYP_MAGIC, position + 1)
    return best


def find_last_ftyp(path: Path, total_size: int) -> int | None:
    """从尾部向前分块查找最后一个可用的 ``ftyp`` box。"""
    end = total_size
    while end > 0:
        start = max(0, end - CHUNK_SIZE)
        try:
            with path.open("rb") as handle:
                handle.seek(start)
                window = handle.read(end - start)
        except OSError:
            return None
        position = window.rfind(FTYP_MAGIC)
        while position != -1:
            candidate = start + position - 4
            if candidate >= 0 and _valid_ftyp_offset(path, candidate, total_size):
                return candidate
            position = window.rfind(FTYP_MAGIC, 0, position)
        if start == 0:
            break
        end = start + len(FTYP_MAGIC) - 1
    return None


def find_video_span(path: Path) -> VideoSpan | None:
    """定位照片内嵌视频的字节区间；普通照片返回 ``None``。"""
    try:
        total_size = path.stat().st_size
    except OSError:
        return None
    if total_size < MIN_SPAN_LENGTH:
        return None

    declared = find_declared_length(path, total_size)
    if declared:
        expected = total_size - declared
        located = _locate_near(path, expected, total_size)
        if located is not None:
            return VideoSpan(located, total_size - located)

    fallback = find_last_ftyp(path, total_size)
    if fallback is not None:
        return VideoSpan(fallback, total_size - fallback)
    return None
