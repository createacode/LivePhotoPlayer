"""在线反查地名：支持天地图与 OpenStreetMap 两个公开源。

- 天地图需要用户自己申请 key（不内置），走官方 geocoder 接口；
- OpenStreetMap 的 Nominatim 不需要 key，但要求限速（每秒最多 1 次）。
两者都只读 ``addressComponent`` / ``address`` 里的省市区，不执行返回内容中的任何标记。
"""

from __future__ import annotations

import json
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from typing import Any, Final

from livephoto_player.services.geodb import PlaceName

TIANDITU_URL: Final = "https://api.tianditu.gov.cn/geocoder"
NOMINATIM_URL: Final = "https://nominatim.openstreetmap.org/reverse"
USER_AGENT: Final = "LivePhotoPlayer/4.2 (photo viewer; local geocoding)"
DEFAULT_TIMEOUT: Final = 10


@dataclass(frozen=True, slots=True)
class ProviderInfo:
    """一个在线解析源。"""

    key: str
    label: str
    needs_key: bool
    min_interval: float
    hint: str


PROVIDERS: Final = (
    ProviderInfo(
        key="tianditu",
        label="天地图（需自备 key）",
        needs_key=True,
        min_interval=1.0,
        hint=(
            "到 https://cloudcenter.tianditu.gov.cn/center/development/myApp "
            "申请「服务端（Web 服务 API）」key 后填入。"
            "免费 key 有并发/每日配额，触发限流时本软件会自动放慢并重试。"
        ),
    ),
    ProviderInfo(
        key="nominatim",
        label="OpenStreetMap（免 key）",
        needs_key=False,
        min_interval=1.1,
        hint="公开服务，限速每秒 1 次；数据为社区维护，地名可能不如国内地图细致。",
    ),
)


class GeocodeError(RuntimeError):
    """在线反查失败（网络、配额、key 无效、返回格式异常）。"""


def provider_info(key: str) -> ProviderInfo:
    """按 key 取源信息，未知时退回天地图。"""
    for item in PROVIDERS:
        if item.key == key:
            return item
    return PROVIDERS[0]


def _open_json(url: str, *, timeout: int, opener: Any = None) -> Any:
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    open_call = opener if opener is not None else urllib.request.urlopen
    try:
        with open_call(request, timeout=timeout) as response:
            raw = response.read()
    except urllib.error.HTTPError as exc:
        raise GeocodeError(f"接口返回 HTTP {exc.code}") from exc
    except urllib.error.URLError as exc:
        raise GeocodeError(f"网络不可用：{exc.reason}") from exc
    except TimeoutError as exc:
        raise GeocodeError("请求超时") from exc
    except OSError as exc:
        raise GeocodeError(f"请求失败：{exc}") from exc
    try:
        return json.loads(raw.decode("utf-8", "replace"))
    except json.JSONDecodeError as exc:
        raise GeocodeError("接口返回了非 JSON 内容") from exc


def parse_tianditu(payload: Any) -> PlaceName:
    """解析天地图 geocoder 返回。"""
    if not isinstance(payload, dict):
        raise GeocodeError("天地图返回格式异常")
    status = str(payload.get("status", ""))
    if status not in {"0", "200"}:
        message = payload.get("msg") or payload.get("message") or "未知错误"
        raise GeocodeError(f"天地图返回错误：{message}")
    result = payload.get("result")
    if not isinstance(result, dict):
        raise GeocodeError("天地图没有返回地址信息")
    component = result.get("addressComponent")
    if not isinstance(component, dict) or not component:
        formatted = _text(result.get("formatted_address"))
        if formatted:
            return PlaceName(province=formatted, source="tianditu", detail=formatted)
        raise GeocodeError("天地图返回缺少地址信息")
    place = PlaceName(
        province=_text(component.get("province")),
        city=_text(component.get("city")),
        district=_text(component.get("county")) or _text(component.get("town")),
        source="tianditu",
        detail=_text(result.get("formatted_address")),
    )
    if not place.text:
        formatted = _text(result.get("formatted_address"))
        if not formatted:
            raise GeocodeError("天地图返回的地址为空")
        return PlaceName(province=formatted, source="tianditu", detail=formatted)
    return place


def parse_nominatim(payload: Any) -> PlaceName:
    """解析 Nominatim reverse 返回。"""
    if not isinstance(payload, dict):
        raise GeocodeError("OSM 返回格式异常")
    if payload.get("error"):
        raise GeocodeError(f"OSM 返回错误：{payload.get('error')}")
    address = payload.get("address")
    if not isinstance(address, dict) or not address:
        display = _text(payload.get("display_name"))
        if display:
            return PlaceName(province=display, source="nominatim")
        raise GeocodeError("OSM 没有返回地址信息")
    province = _text(address.get("state")) or _text(address.get("province"))
    city = (
        _text(address.get("city"))
        or _text(address.get("town"))
        or _text(address.get("municipality"))
    )
    district = (
        _text(address.get("county"))
        or _text(address.get("district"))
        or _text(address.get("city_district"))
        or _text(address.get("suburb"))
    )
    place = PlaceName(province=province, city=city, district=district, source="nominatim")
    if not place.text:
        display = _text(payload.get("display_name"))
        if not display:
            raise GeocodeError("OSM 返回的地址为空")
        return PlaceName(province=display, source="nominatim")
    return place


def _text(value: object) -> str:
    return value.strip() if isinstance(value, str) else ""


def reverse_geocode(
    latitude: float,
    longitude: float,
    *,
    provider: str = "tianditu",
    key: str = "",
    timeout: int = DEFAULT_TIMEOUT,
    opener: Any = None,
) -> PlaceName:
    """按坐标反查地名。"""
    info = provider_info(provider)
    if info.key == "tianditu":
        if not key:
            raise GeocodeError("天地图需要先在设置里填入 key")
        payload = json.dumps({"lon": longitude, "lat": latitude, "ver": 1}, ensure_ascii=False)
        query = urllib.parse.urlencode({"postStr": payload, "type": "geocode", "tk": key})
        return parse_tianditu(_open_json(f"{TIANDITU_URL}?{query}", timeout=timeout, opener=opener))

    query = urllib.parse.urlencode(
        {
            "format": "jsonv2",
            "lat": f"{latitude:.6f}",
            "lon": f"{longitude:.6f}",
            "zoom": 14,
            "addressdetails": 1,
            "accept-language": "zh-CN",
        }
    )
    return parse_nominatim(_open_json(f"{NOMINATIM_URL}?{query}", timeout=timeout, opener=opener))


def check_provider(provider: str, key: str = "", *, opener: Any = None) -> str:
    """用北京天安门坐标测试配置，返回可读结果。"""
    place = reverse_geocode(39.9087, 116.3975, provider=provider, key=key, opener=opener)
    return place.text or "解析成功但地址为空"
