"""离线地理库与在线地名解析测试。"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from livephoto_player.services.geocode import (
    GeocodeError,
    check_provider,
    parse_nominatim,
    parse_tianditu,
    provider_info,
    reverse_geocode,
)
from livephoto_player.services.geodb import GeoDB, PlaceName, haversine_km


@pytest.fixture
def dataset(tmp_path: Path) -> Path:
    payload = {
        "count": 4,
        "fields": ["name", "city", "province", "lng", "lat", "adcode"],
        "items": [
            ["东城区", "北京市", "北京市", 116.416, 39.928, 110101],
            ["丰宁满族自治县", "承德市", "河北省", 116.651, 41.209, 130826],
            ["克什克腾旗", "赤峰市", "内蒙古自治区", 117.545, 43.265, 150425],
            ["蔚县", "张家口市", "河北省", 114.589, 39.840, 130726],
        ],
    }
    path = tmp_path / "districts.json"
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    return path


def test_lookup_returns_nearest_district(dataset: Path) -> None:
    geo = GeoDB(dataset)
    assert geo.available is True
    assert geo.count == 4

    place = geo.lookup(41.5731, 116.0094)
    assert place is not None
    assert place.district == "丰宁满族自治县"
    assert place.city == "承德市"
    assert place.province == "河北省"
    assert place.source == "offline"


def test_lookup_city_name_not_duplicated(dataset: Path) -> None:
    place = GeoDB(dataset).lookup(39.9087, 116.3975)
    assert place is not None
    assert place.text == "北京市 东城区"


def test_lookup_out_of_range_returns_none(dataset: Path) -> None:
    geo = GeoDB(dataset)
    assert geo.lookup(0.0, 0.0) is None
    assert geo.lookup(999.0, 0.0) is None


def test_missing_dataset_is_graceful(tmp_path: Path) -> None:
    geo = GeoDB(tmp_path / "nope.json")
    assert geo.available is False
    assert geo.lookup(39.9, 116.4) is None


def test_broken_dataset_is_graceful(tmp_path: Path) -> None:
    path = tmp_path / "bad.json"
    path.write_text("{not json", encoding="utf-8")
    geo = GeoDB(path)
    assert geo.available is False


def test_haversine_reasonable() -> None:
    beijing_tiananmen = (39.9087, 116.3975)
    chengde = (41.5731, 116.0094)
    distance = haversine_km(*beijing_tiananmen, *chengde)
    assert 180 < distance < 220


def test_place_text_dedupes() -> None:
    place = PlaceName(province="北京市", city="北京市", district="东城区")
    assert place.text == "北京市 东城区"
    assert PlaceName().text == ""


# ------------------------------------------------------------------ 在线解析
def test_provider_info_defaults_to_tianditu() -> None:
    assert provider_info("tianditu").needs_key is True
    assert provider_info("nominatim").needs_key is False
    assert provider_info("unknown").key == "tianditu"


def test_parse_tianditu_ok() -> None:
    payload = {
        "status": "0",
        "result": {
            "addressComponent": {
                "province": "河北省",
                "city": "承德市",
                "county": "丰宁满族自治县",
            }
        },
    }
    place = parse_tianditu(payload)
    assert place.text == "河北省 承德市 丰宁满族自治县"
    assert place.source == "tianditu"


def test_parse_tianditu_error() -> None:
    with pytest.raises(GeocodeError):
        parse_tianditu({"status": "101", "msg": "token 无效"})
    with pytest.raises(GeocodeError):
        parse_tianditu({"status": "0", "result": {}})


def test_parse_tianditu_falls_back_to_formatted_address() -> None:
    payload = {"status": "0", "result": {"formatted_address": "北京市东城区天安门"}}
    assert parse_tianditu(payload).text.startswith("北京市东城区")


def test_parse_nominatim_ok() -> None:
    payload = {
        "address": {
            "state": "河北省",
            "city": "承德市",
            "county": "丰宁满族自治县",
        }
    }
    assert parse_nominatim(payload).text == "河北省 承德市 丰宁满族自治县"


def test_parse_nominatim_falls_back_to_display_name() -> None:
    payload = {"display_name": "丰宁满族自治县, 承德市, 河北省, 中国"}
    assert "丰宁" in parse_nominatim(payload).text


def test_parse_nominatim_error() -> None:
    with pytest.raises(GeocodeError):
        parse_nominatim({"error": "Unable to geocode"})
    with pytest.raises(GeocodeError):
        parse_nominatim({})


class _FakeResponse:
    def __init__(self, body: bytes) -> None:
        self._body = body

    def __enter__(self) -> _FakeResponse:
        return self

    def __exit__(self, *args: object) -> None:
        return None

    def read(self) -> bytes:
        return self._body


def _opener(body: dict[str, Any]) -> Any:
    return lambda request, timeout: _FakeResponse(json.dumps(body).encode("utf-8"))


def test_reverse_geocode_tianditu_requires_key() -> None:
    with pytest.raises(GeocodeError):
        reverse_geocode(39.9, 116.4, provider="tianditu", key="")


def test_reverse_geocode_tianditu_with_mock() -> None:
    body = {
        "status": "0",
        "result": {
            "addressComponent": {"province": "北京市", "city": "北京市", "county": "东城区"}
        },
    }
    place = reverse_geocode(39.9087, 116.3975, provider="tianditu", key="k", opener=_opener(body))
    assert place.text == "北京市 东城区"


def test_reverse_geocode_nominatim_with_mock() -> None:
    body = {"address": {"state": "河北省", "city": "承德市", "county": "丰宁县"}}
    place = reverse_geocode(41.5, 116.0, provider="nominatim", opener=_opener(body))
    assert place.province == "河北省"


def test_check_provider_reports_text() -> None:
    body = {"address": {"state": "北京市", "city": "北京市", "county": "东城区"}}
    assert check_provider("nominatim", opener=_opener(body)) == "北京市 东城区"
