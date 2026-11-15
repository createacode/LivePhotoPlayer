"""时间与地点的显示格式（纯函数，便于单元测试）。"""

from __future__ import annotations

from datetime import datetime

WEEKDAYS = ("周一", "周二", "周三", "周四", "周五", "周六", "周日")

UNKNOWN_TIME = "时间未知"
UNKNOWN_PLACE = "地点未知"


def to_datetime(timestamp: int) -> datetime | None:
    """把 Unix 秒转成本地时间；``0`` 或非法值返回 ``None``。"""
    if timestamp <= 0:
        return None
    try:
        return datetime.fromtimestamp(timestamp)
    except (OverflowError, OSError, ValueError):
        return None


def format_day(timestamp: int) -> str:
    """``2026-09-27 周日``；未知时返回空串。"""
    moment = to_datetime(timestamp)
    if moment is None:
        return ""
    return f"{moment:%Y-%m-%d} {WEEKDAYS[moment.weekday()]}"


def format_time(timestamp: int) -> str:
    """``16:49``；未知时返回空串。"""
    moment = to_datetime(timestamp)
    return f"{moment:%H:%M}" if moment else ""


def format_short_day(timestamp: int) -> str:
    """``09-28``：状态栏用的简写日期。"""
    moment = to_datetime(timestamp)
    return f"{moment:%m-%d}" if moment else ""


def format_datetime(timestamp: int) -> str:
    """``2026-09-27 16:49:37``；未知时返回空串。"""
    moment = to_datetime(timestamp)
    return f"{moment:%Y-%m-%d %H:%M:%S}" if moment else ""


def format_relative_day(timestamp: int, *, now: datetime | None = None) -> str:
    """今天/昨天/具体日期。"""
    moment = to_datetime(timestamp)
    if moment is None:
        return ""
    today = (now or datetime.now()).date()
    delta = (today - moment.date()).days
    if delta == 0:
        return f"今天 {WEEKDAYS[moment.weekday()]}"
    if delta == 1:
        return f"昨天 {WEEKDAYS[moment.weekday()]}"
    if delta == 2:
        return f"前天 {WEEKDAYS[moment.weekday()]}"
    return format_day(timestamp)


def format_coords(latitude: float | None, longitude: float | None) -> str:
    """把经纬度格式化成可读坐标；缺失返回空串。"""
    if latitude is None or longitude is None:
        return ""
    if not (-90.0 <= latitude <= 90.0) or not (-180.0 <= longitude <= 180.0):
        return ""
    ns = "N" if latitude >= 0 else "S"
    ew = "E" if longitude >= 0 else "W"
    return f"{abs(latitude):.4f}°{ns} {abs(longitude):.4f}°{ew}"


def format_place(place: str, latitude: float | None, longitude: float | None) -> str:
    """优先使用地名，其次坐标，都没有则返回"地点未知"。"""
    if place:
        return place
    coords = format_coords(latitude, longitude)
    return coords or UNKNOWN_PLACE


def format_size(size_bytes: int) -> str:
    """人类可读的文件大小。"""
    size = size_bytes / 1024
    if size < 1024:
        return f"{size:.0f} KB"
    return f"{size / 1024:.1f} MB"
