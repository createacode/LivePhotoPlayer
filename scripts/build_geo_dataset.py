#!/usr/bin/env python3
"""生成内置的区县坐标表（离线定位用）。

数据来源：**天地图行政区划接口**（`/v2/administrative`）。按省级 adcode 逐省拉取，
一次拿到「省 -> 市 -> 区县」的嵌套结构与每个节点的中心点坐标，全国仅需 34 次请求。

key 由使用者在环境变量 `TIANDITU_KEY` 或 `--key=` 里提供，**不写进仓库**。

产物：`src/livephoto_player/resources/china_districts.json`
该脚本只在需要更新行政区划时手动运行；程序运行时不会联网。
"""

from __future__ import annotations

import json
import os
import sys
import time
import urllib.parse
import urllib.request
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "src" / "livephoto_player" / "resources" / "china_districts.json"
API = "https://api.tianditu.gov.cn/v2/administrative"
ADCODE_PREFIX = "156"  # 天地图用 156 表示中国大陆

PROVINCE_CODES = [
    110000, 120000, 130000, 140000, 150000,
    210000, 220000, 230000,
    310000, 320000, 330000, 340000, 350000, 360000, 370000,
    410000, 420000, 430000, 440000, 450000, 460000,
    500000, 510000, 520000, 530000, 540000,
    610000, 620000, 630000, 640000, 650000,
    710000, 810000, 820000,
]  # fmt: skip

HEADERS = {"User-Agent": "LivePhotoPlayer-geo-builder/1.0"}


def fetch_province(adcode: int, key: str, attempts: int = 3) -> dict | None:
    """拉取一个省的三级行政区划树。"""
    query = urllib.parse.urlencode(
        {"keyword": f"{ADCODE_PREFIX}{adcode}", "childLevel": 3, "tk": key}
    )
    url = f"{API}?{query}"
    last_error: Exception | None = None
    for attempt in range(attempts):
        try:
            request = urllib.request.Request(url, headers=HEADERS)
            with urllib.request.urlopen(request, timeout=30) as response:
                return json.loads(response.read().decode("utf-8"))
        except Exception as exc:  # noqa: BLE001 - 单省失败不应中断整体
            last_error = exc
            time.sleep(1.0 * (attempt + 1))
    print(f"  跳过 {adcode}: {last_error}", file=sys.stderr)
    return None


def _center(node: dict) -> tuple[float, float] | None:
    center = node.get("center")
    if isinstance(center, dict):
        lng, lat = center.get("lng"), center.get("lat")
        if isinstance(lng, (int, float)) and isinstance(lat, (int, float)):
            return float(lng), float(lat)
    return None


def _adcode_of(node: dict) -> int:
    raw = str(node.get("gb") or "")
    digits = raw[3:] if raw.startswith(ADCODE_PREFIX) else raw
    return int(digits) if digits.isdigit() else 0


def collect(payload: dict | None, province_name: str) -> list[list[object]]:
    """把一棵省树摊平成区县行。"""
    rows: list[list[object]] = []
    if not isinstance(payload, dict):
        return rows
    data = payload.get("data")
    districts = data.get("district") if isinstance(data, dict) else None
    if not isinstance(districts, list):
        return rows

    for province_node in districts:
        if not isinstance(province_node, dict):
            continue
        province = str(province_node.get("name") or province_name)
        for city_node in province_node.get("children") or []:
            if not isinstance(city_node, dict):
                continue
            city = str(city_node.get("name") or "")
            city_center = _center(city_node)
            children = city_node.get("children") or []
            if not children and city_center is not None:
                # 省直辖县级市：自身就是区县级
                rows.append(
                    [city, city, province, city_center[0], city_center[1], _adcode_of(city_node)]
                )
                continue
            for county_node in children:
                if not isinstance(county_node, dict):
                    continue
                center = _center(county_node)
                if center is None:
                    continue
                rows.append(
                    [
                        str(county_node.get("name") or ""),
                        city,
                        province,
                        center[0],
                        center[1],
                        _adcode_of(county_node),
                    ]
                )
    return rows


def main() -> int:
    """抓取并写出区县坐标表。"""
    key = os.environ.get("TIANDITU_KEY", "").strip()
    for argument in sys.argv[1:]:
        if argument.startswith("--key="):
            key = argument.split("=", 1)[1].strip()
    if not key:
        print("缺少天地图 key：请设置环境变量 TIANDITU_KEY 或用 --key= 传入", file=sys.stderr)
        return 2

    items: list[list[object]] = []
    seen: set[int] = set()
    failed: list[int] = []
    for index, adcode in enumerate(PROVINCE_CODES, start=1):
        payload = fetch_province(adcode, key)
        if payload is None:
            failed.append(adcode)
            continue
        rows = collect(payload, "")
        for row in rows:
            code = int(row[5]) if isinstance(row[5], int) else 0
            if not row[0] or code in seen:
                continue
            seen.add(code)
            items.append(row)
        print(f"  [{index}/{len(PROVINCE_CODES)}] {adcode}: 累计 {len(items)} 个区县", flush=True)

    items.sort(key=lambda row: (str(row[2]), str(row[1]), str(row[0])))
    payload_out = {
        "source": "天地图行政区划接口 /v2/administrative（省/市/区县中心点）",
        "url": API,
        "generated": date.today().isoformat(),
        "count": len(items),
        "fields": ["name", "city", "province", "lng", "lat", "adcode"],
        "items": items,
    }
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(
        json.dumps(payload_out, ensure_ascii=False, separators=(",", ":")),
        encoding="utf-8",
        newline="\n",
    )
    size_kb = OUTPUT.stat().st_size / 1024
    print(f"已写入 {OUTPUT.relative_to(ROOT)}：{len(items)} 个区县，{size_kb:.0f} KB")
    if failed:
        print(f"警告：{len(failed)} 个省抓取失败：{failed}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
