"""元数据抽取：拍摄时间、GPS 坐标、相机型号、像素尺寸。

只在后台索引线程里调用，不占用 UI 线程；失败一律降级而不是抛错。
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from livephoto_player.services.browser import VIDEO_EXTENSIONS
from livephoto_player.utils.logger import get_logger

_EXIF_DATETIME_ORIGINAL = 36867
_EXIF_DATETIME = 306
_EXIF_MAKE = 271
_EXIF_MODEL = 272
_GPS_IFD = 34853

# 手机相机常把拍摄时间写进文件名：IMG20260927164937 / VID20260809154030 / PXL_20260927_164937
_NAME_DATETIME = re.compile(r"(20\d{2})(\d{2})(\d{2})[_\-\s]?(\d{2})(\d{2})(\d{2})")

# MP4 的 ©xyz 原子存 ISO-6709 坐标，形如 "+39.6254+114.7208/"
_ISO6709 = re.compile(r"([+-]\d{1,3}(?:\.\d+)?)([+-]\d{1,3}(?:\.\d+)?)")
_XYZ_ATOM = b"\xa9xyz"
_SCAN_HEAD = 2 << 20
_SCAN_TAIL = 4 << 20


@dataclass(frozen=True, slots=True)
class PhotoMetadata:
    """从文件里能读到的结构化信息。"""

    taken_ts: int = 0
    time_source: str = "file"
    latitude: float | None = None
    longitude: float | None = None
    camera: str = ""
    width: int = 0
    height: int = 0
    kind: str = "photo"


def _parse_exif_datetime(value: object) -> int:
    """把 EXIF 的 ``YYYY:MM:DD HH:MM:SS`` 转成 Unix 秒。"""
    if not isinstance(value, str) or len(value) < 19:
        return 0
    text = value.strip().replace("\x00", "")
    for pattern in ("%Y:%m:%d %H:%M:%S", "%Y-%m-%d %H:%M:%S"):
        try:
            return int(datetime.strptime(text[:19], pattern).timestamp())
        except ValueError:
            continue
    return 0


def _dms_to_degrees(value: object, reference: object) -> float | None:
    """GPS 的度分秒转十进制度。"""
    if not isinstance(value, (tuple, list)) or len(value) < 3:
        return None
    try:
        degrees, minutes, seconds = (float(item) for item in value[:3])
    except (TypeError, ValueError):
        return None
    result = degrees + minutes / 60.0 + seconds / 3600.0
    if isinstance(reference, str) and reference.upper() in {"S", "W"}:
        result = -result
    return result


def timestamp_from_name(path: Path) -> int:
    """从文件名里提取拍摄时间；没有则返回 0。

    视频没有 EXIF，若直接退回文件修改时间，会把所有视频顶到时间线最前面
    （文件是什么时候拷进电脑的，就显示成什么时候拍的）。手机生成的文件名
    本身带时间戳，优先用它更可信。
    """
    match = _NAME_DATETIME.search(path.stem)
    if match is None:
        return 0
    year, month, day, hour, minute, second = (int(part) for part in match.groups())
    try:
        return int(datetime(year, month, day, hour, minute, second).timestamp())
    except ValueError:
        return 0


def _join_camera(make: str, model: str) -> str:
    """合并厂商与型号；型号已经包含厂商时不重复前缀。"""
    if not make:
        return model
    if not model:
        return make
    if model.lower().startswith(make.lower()):
        return model
    return f"{make} {model}"


def parse_iso6709(text: str) -> tuple[float, float] | None:
    """解析 ISO-6709 坐标串（``+39.6254+114.7208/``）。"""
    match = _ISO6709.search(text)
    if match is None:
        return None
    try:
        latitude = float(match.group(1))
        longitude = float(match.group(2))
    except ValueError:
        return None
    if not (-90.0 <= latitude <= 90.0 and -180.0 <= longitude <= 180.0):
        return None
    return latitude, longitude


def read_mp4_location(path: Path) -> tuple[float, float] | None:
    """从 MP4 的 ``©xyz`` 原子读拍摄坐标；视频没有 EXIF，这条路才是对的。"""
    try:
        size = path.stat().st_size
        with path.open("rb") as handle:
            for start, length in (
                (0, min(size, _SCAN_HEAD)),
                (max(0, size - _SCAN_TAIL), _SCAN_TAIL),
            ):
                handle.seek(start)
                chunk = handle.read(length)
                index = chunk.find(_XYZ_ATOM)
                if index < 0:
                    continue
                payload = chunk[index + len(_XYZ_ATOM) + 4 : index + len(_XYZ_ATOM) + 40]
                text = payload.split(b"\x00")[0].decode("ascii", "ignore").strip()
                coords = parse_iso6709(text)
                if coords is not None:
                    return coords
    except OSError as exc:
        get_logger("metadata").debug("读取视频坐标失败 %s：%s", path.name, exc)
    return None


def kind_for_path(path: Path) -> str:
    """按扩展名给出种类（实况照片在打开时会另外标记）。"""
    return "video" if path.suffix.lower() in VIDEO_EXTENSIONS else "photo"


def read_metadata(path: Path, *, fallback_ts: int = 0) -> PhotoMetadata:
    """读取元数据；任何异常都降级为"只有文件时间"。"""
    kind = kind_for_path(path)
    file_ts = fallback_ts or int(path.stat().st_mtime) if path.exists() else fallback_ts
    named_ts = timestamp_from_name(path)
    base_ts = named_ts or file_ts
    base_source = "filename" if named_ts else "file"
    if kind == "video":
        coords = read_mp4_location(path)
        return PhotoMetadata(
            taken_ts=base_ts,
            time_source=base_source,
            latitude=coords[0] if coords else None,
            longitude=coords[1] if coords else None,
            kind=kind,
        )
    try:
        from PIL import Image

        with Image.open(path) as image:
            width, height = image.size
            exif = image.getexif()
            taken = _parse_exif_datetime(
                exif.get(_EXIF_DATETIME_ORIGINAL) or exif.get(_EXIF_DATETIME)
            )
            make = str(exif.get(_EXIF_MAKE) or "").strip()
            model = str(exif.get(_EXIF_MODEL) or "").strip()
            camera = _join_camera(make, model)
            latitude = longitude = None
            gps = exif.get_ifd(_GPS_IFD) if hasattr(exif, "get_ifd") else {}
            if gps:
                latitude = _dms_to_degrees(gps.get(2), gps.get(1))
                longitude = _dms_to_degrees(gps.get(4), gps.get(3))
            return PhotoMetadata(
                taken_ts=taken or base_ts,
                time_source="exif" if taken else base_source,
                latitude=latitude,
                longitude=longitude,
                camera=camera,
                width=width,
                height=height,
                kind=kind,
            )
    except Exception as exc:  # noqa: BLE001 - 元数据失败不能影响索引
        get_logger("metadata").debug("读取元数据失败 %s：%s", path.name, exc)
        return PhotoMetadata(taken_ts=base_ts, time_source=base_source, kind=kind)
