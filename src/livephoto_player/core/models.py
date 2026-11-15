"""领域模型：媒体种类、内嵌视频区间与播放状态。"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path

from livephoto_player.core.format import (
    format_datetime,
    format_day,
    format_place,
    format_time,
)


class MediaKind(Enum):
    """媒体种类。"""

    PHOTO = "photo"
    LIVE_PHOTO = "live_photo"
    VIDEO = "video"

    @property
    def is_video_source(self) -> bool:
        """是否具备可播放的视频内容。"""
        return self is not MediaKind.PHOTO

    @property
    def label(self) -> str:
        """界面展示用的中文标签。"""
        return {
            MediaKind.PHOTO: "照片",
            MediaKind.LIVE_PHOTO: "实况照片",
            MediaKind.VIDEO: "视频",
        }[self]


class PlaybackState(Enum):
    """播放器状态机。"""

    IDLE = "idle"
    LOADING = "loading"
    PLAYING = "playing"
    PAUSED = "paused"
    STOPPED = "stopped"
    ENDED = "ended"
    ERROR = "error"


@dataclass(frozen=True, slots=True)
class VideoSpan:
    """照片尾部内嵌视频在文件中的字节区间 ``[offset, offset + length)``。"""

    offset: int
    length: int

    def __post_init__(self) -> None:
        if self.offset < 0:
            msg = "offset 不能为负"
            raise ValueError(msg)
        if self.length <= 0:
            msg = "length 必须为正"
            raise ValueError(msg)

    @property
    def end(self) -> int:
        """区间结束位置（不含）。"""
        return self.offset + self.length


@dataclass(slots=True)
class MediaItem:
    """一个待展示的媒体条目。"""

    path: Path
    kind: MediaKind
    size_bytes: int = 0
    span: VideoSpan | None = None
    taken_at: str = ""
    pixel_width: int = 0
    pixel_height: int = 0
    # ---- 结构化索引带来的字段（来自 Catalog，缺失时保持默认） ----
    taken_ts: int = 0
    latitude: float | None = None
    longitude: float | None = None
    place: str = ""
    camera: str = ""
    favorite: bool = False
    # 时间线展示用的时间；0 时退回 sort_ts（收藏时间线会填收藏时刻）
    timeline_ts: int = 0
    # 列表里的"文件夹"行：点击进入该目录
    is_folder: bool = False
    # 覆盖显示名（例如"上级目录"）
    name_override: str = ""

    @property
    def sort_ts(self) -> int:
        """按拍摄时间排序用的时间；未知时退回 0。"""
        return self.taken_ts or self.timeline_ts

    @property
    def display_ts(self) -> int:
        """时间线展示用的时间。"""
        return self.timeline_ts or self.taken_ts

    @property
    def day_text(self) -> str:
        """``2026-09-27 周日``。"""
        return format_day(self.display_ts)

    @property
    def time_text(self) -> str:
        """``16:49``。"""
        return format_time(self.display_ts)

    @property
    def place_text(self) -> str:
        """地名，其次坐标。"""
        return format_place(self.place, self.latitude, self.longitude)

    @property
    def name(self) -> str:
        """显示名：文件夹可用 ``name_override`` 覆盖。"""
        return self.name_override or self.path.name

    @property
    def has_video(self) -> bool:
        """是否可播放视频。"""
        if self.kind is MediaKind.VIDEO:
            return True
        return self.kind is MediaKind.LIVE_PHOTO and self.span is not None


@dataclass(frozen=True, slots=True)
class ImagePayload:
    """后台线程解码完成的结果，跨线程只传递 QImage 与纯数据。"""

    path: Path
    image: object
    display_width: int
    display_height: int
    taken_at: str = ""
    error: str = ""
    generation: int = 0
    prefetch: bool = False
    cache_bucket: int = 0
    full: bool = False
    span: VideoSpan | None = None
    source_width: int = 0
    source_height: int = 0


@dataclass(slots=True)
class SessionState:
    """当前会话：目录、条目列表与索引。"""

    directory: Path | None = None
    items: list[MediaItem] = field(default_factory=list)
    index: int = -1

    @property
    def current(self) -> MediaItem | None:
        """当前条目，越界或列表为空时返回 ``None``。"""
        if 0 <= self.index < len(self.items):
            return self.items[self.index]
        return None

    @property
    def has_previous(self) -> bool:
        """是否存在上一张。"""
        return self.index > 0

    @property
    def has_next(self) -> bool:
        """是否存在下一张。"""
        return 0 <= self.index < len(self.items) - 1

    def index_of(self, path: Path) -> int:
        """按路径查找索引，未找到返回 ``-1``。"""
        resolved = path.resolve()
        for position, item in enumerate(self.items):
            if item.path == resolved:
                return position
        return -1


@dataclass(frozen=True, slots=True)
class PhotoRecord:
    """结构化索引里的一张照片/视频。"""

    path: Path
    name: str
    directory: str
    kind: str = "photo"
    size_bytes: int = 0
    mtime: int = 0
    taken_ts: int = 0
    time_source: str = "file"
    latitude: float | None = None
    longitude: float | None = None
    place: str = ""
    camera: str = ""
    width: int = 0
    height: int = 0

    @property
    def sort_ts(self) -> int:
        """排序用的时间：优先拍摄时间，缺失时退回文件时间。"""
        return self.taken_ts or self.mtime

    @property
    def time_text(self) -> str:
        """``16:49``。"""
        return format_time(self.sort_ts)

    @property
    def day_text(self) -> str:
        """``2026-09-27 周日``。"""
        return format_day(self.sort_ts)

    @property
    def place_text(self) -> str:
        """地名，其次坐标，都没有则"地点未知"。"""
        return format_place(self.place, self.latitude, self.longitude)

    @property
    def has_location(self) -> bool:
        """是否带位置信息。"""
        return bool(self.place) or (self.latitude is not None and self.longitude is not None)

    @property
    def camera_text(self) -> str:
        """相机型号。"""
        return self.camera


@dataclass(frozen=True, slots=True)
class FavoriteRecord:
    """一条收藏记录。"""

    path: Path
    favorited_ts: int
    copy_path: Path | None = None
    photo: PhotoRecord | None = None

    @property
    def name(self) -> str:
        """文件名。"""
        return self.path.name

    @property
    def sort_ts(self) -> int:
        """按拍摄时间排序时使用的时间。"""
        if self.photo is not None:
            return self.photo.sort_ts
        return self.favorited_ts

    @property
    def favorited_text(self) -> str:
        """收藏时刻。"""
        return format_datetime(self.favorited_ts)

    @property
    def taken_text(self) -> str:
        """拍摄时刻。"""
        if self.photo is not None:
            return format_datetime(self.photo.sort_ts)
        return ""
