"""离线地点解析：内置区县坐标表，最近中心点匹配。

数据来自 `scripts/build_geo_dataset.py` 生成的 `resources/china_districts.json`
（名称 + 中心点坐标 + adcode，约 2800 条、130KB）。运行时**不联网**。

局限：按"最近区县中心点"判断，边界附近可能落到隔壁区县；地级市中心距离
几十公里时仍能给出正确的市与省。需要街道级精度时改用在线 API 模式。
"""

from __future__ import annotations

import json
import math
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from livephoto_player.utils.logger import get_logger
from livephoto_player.utils.paths import package_resource

EARTH_RADIUS_KM = 6371.0
MAX_MATCH_KM = 300.0
_GRID_DEG = 1.0


@dataclass(frozen=True, slots=True)
class PlaceName:
    """一个可展示的地点。"""

    province: str = ""
    city: str = ""
    district: str = ""
    adcode: int = 0
    distance_km: float = 0.0
    source: str = "offline"
    # 在线接口返回的完整地址串（含乡镇/村/方位距离等多级细节），有就优先显示
    detail: str = ""

    @property
    def text(self) -> str:
        """在线结果优先用完整地址；离线则拼``省 市 区``（重复层级只留一次）。"""
        if self.detail:
            return self.detail
        parts: list[str] = []
        for part in (self.province, self.city, self.district):
            if part and part not in parts:
                parts.append(part)
        return " ".join(parts)

    @property
    def brief(self) -> str:
        """只管到区县的简写，用于状态栏等窄位置。"""
        parts: list[str] = []
        for part in (self.province, self.city, self.district):
            if part and part not in parts:
                parts.append(part)
        return " ".join(parts) or self.detail


@dataclass(frozen=True, slots=True)
class _Entry:
    latitude: float
    longitude: float
    province: str
    city: str
    district: str
    adcode: int


def haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """两点间球面距离（公里）。"""
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    d_phi = phi2 - phi1
    d_lambda = math.radians(lon2 - lon1)
    a = math.sin(d_phi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(d_lambda / 2) ** 2
    return 2 * EARTH_RADIUS_KM * math.asin(math.sqrt(min(1.0, a)))


class GeoDB:
    """区县坐标表；首次使用时才读文件。"""

    def __init__(self, dataset_path: Path | None = None) -> None:
        self._logger = get_logger("geo")
        self._path = dataset_path or package_resource("china_districts.json")
        self._entries: list[_Entry] = []
        self._grid: dict[tuple[int, int], list[int]] = {}
        self._loaded = False

    @property
    def available(self) -> bool:
        """内置数据是否可用。"""
        self._ensure_loaded()
        return bool(self._entries)

    @property
    def count(self) -> int:
        """区县条目数。"""
        self._ensure_loaded()
        return len(self._entries)

    def lookup(self, latitude: float, longitude: float) -> PlaceName | None:
        """按坐标找最近的区县；数据缺失或超出范围返回 ``None``。"""
        self._ensure_loaded()
        if not self._entries:
            return None
        if not (-90.0 <= latitude <= 90.0 and -180.0 <= longitude <= 180.0):
            return None

        cell = (math.floor(latitude / _GRID_DEG), math.floor(longitude / _GRID_DEG))
        best_index = -1
        best_distance = float("inf")
        # 由近及远搜索网格环，找到第一条命中即可停止
        for ring in range(0, 4):
            for dx in range(-ring, ring + 1):
                for dy in range(-ring, ring + 1):
                    if max(abs(dx), abs(dy)) != ring:
                        continue
                    for index in self._grid.get((cell[0] + dx, cell[1] + dy), ()):
                        entry = self._entries[index]
                        distance = haversine_km(
                            latitude, longitude, entry.latitude, entry.longitude
                        )
                        if distance < best_distance:
                            best_distance = distance
                            best_index = index
            if best_index >= 0 and ring >= 1:
                break
        if best_index < 0:
            best_index, best_distance = self._brute_force(latitude, longitude)
        if best_index < 0 or best_distance > MAX_MATCH_KM:
            return None
        entry = self._entries[best_index]
        return PlaceName(
            province=entry.province,
            city=entry.city,
            district=entry.district,
            adcode=entry.adcode,
            distance_km=best_distance,
            source="offline",
        )

    # ------------------------------------------------------------------ 内部实现
    def _brute_force(self, latitude: float, longitude: float) -> tuple[int, float]:
        best_index, best_distance = -1, float("inf")
        for index, entry in enumerate(self._entries):
            distance = haversine_km(latitude, longitude, entry.latitude, entry.longitude)
            if distance < best_distance:
                best_index, best_distance = index, distance
        return best_index, best_distance

    def _ensure_loaded(self) -> None:
        if self._loaded:
            return
        self._loaded = True
        try:
            raw = json.loads(self._path.read_text(encoding="utf-8"))
            items = raw.get("items") if isinstance(raw, dict) else None
            if not isinstance(items, list):
                raise ValueError("资源格式不正确")
        except (OSError, json.JSONDecodeError, ValueError) as exc:
            self._logger.warning("内置区县数据不可用（%s），地点将显示坐标", exc)
            return
        for row in items:
            if not isinstance(row, list) or len(row) < 6:
                continue
            name, city, province, lng, lat, adcode = row[:6]
            if not isinstance(lat, (int, float)) or not isinstance(lng, (int, float)):
                continue
            self._entries.append(
                _Entry(
                    latitude=float(lat),
                    longitude=float(lng),
                    province=str(province),
                    city=str(city),
                    district=str(name),
                    adcode=int(adcode) if isinstance(adcode, int) else 0,
                )
            )
        for index, entry in enumerate(self._entries):
            key = (
                math.floor(entry.latitude / _GRID_DEG),
                math.floor(entry.longitude / _GRID_DEG),
            )
            self._grid.setdefault(key, []).append(index)
        self._logger.info("内置区县数据已载入：%s 条", len(self._entries))


@lru_cache(maxsize=1)
def default_geo_db() -> GeoDB:
    """进程内共享的离线地点库。"""
    return GeoDB()
