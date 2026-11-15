"""结构化目录（Catalog）测试：增量判断、搜索、收藏、进度与清理。"""

from __future__ import annotations

from pathlib import Path

import pytest

from livephoto_player.core.models import PhotoRecord
from livephoto_player.services.catalog import Catalog


@pytest.fixture
def catalog(tmp_path: Path) -> Catalog:
    instance = Catalog(tmp_path / "catalog.db")
    yield instance  # type: ignore[misc]
    instance.close()


def make_record(
    path: Path, *, taken_ts: int = 0, place: str = "", lat: float | None = None
) -> PhotoRecord:
    return PhotoRecord(
        path=path,
        name=path.name,
        directory=str(path.parent),
        kind="photo",
        size_bytes=100,
        mtime=1000,
        taken_ts=taken_ts,
        time_source="exif" if taken_ts else "file",
        latitude=lat,
        longitude=lat,
        place=place,
        camera="OnePlus 11",
        width=4000,
        height=3000,
    )


def test_upsert_and_get(catalog: Catalog, tmp_path: Path) -> None:
    path = tmp_path / "a.jpg"
    catalog.upsert(make_record(path, taken_ts=1790000000, place="张家口"))
    catalog.commit()
    record = catalog.get(path)
    assert record is not None
    assert record.place == "张家口"
    assert record.camera == "OnePlus 11"
    assert catalog.count() == 1


def test_need_index_detects_changes(catalog: Catalog, tmp_path: Path) -> None:
    path = tmp_path / "a.jpg"
    assert catalog.need_index(path, 100, 1000) is True
    catalog.upsert(make_record(path))
    assert catalog.need_index(path, 100, 1000) is False
    assert catalog.need_index(path, 101, 1000) is True
    assert catalog.need_index(path, 100, 2000) is True


def test_search_matches_name_place_date_camera(catalog: Catalog, tmp_path: Path) -> None:
    catalog.upsert(
        make_record(tmp_path / "IMG20260927164937.jpg", taken_ts=1790000000, place="张家口")
    )
    catalog.upsert(
        make_record(tmp_path / "IMG20261001123328.jpg", taken_ts=1791000000, place="承德")
    )
    catalog.commit()

    assert [r.name for r in catalog.search("2026-09")] == ["IMG20260927164937.jpg"]
    assert {r.name for r in catalog.search("张家口")} == {"IMG20260927164937.jpg"}
    assert len(catalog.search("OnePlus")) == 2
    assert catalog.search("") == []
    assert catalog.search("不存在的词") == []


def test_search_orders_newest_first(catalog: Catalog, tmp_path: Path) -> None:
    catalog.upsert(make_record(tmp_path / "old.jpg", taken_ts=1000000))
    catalog.upsert(make_record(tmp_path / "new.jpg", taken_ts=2000000))
    catalog.commit()
    assert [r.name for r in catalog.search("jpg")] == ["new.jpg", "old.jpg"]


def test_by_directory_and_by_paths(catalog: Catalog, tmp_path: Path) -> None:
    first = tmp_path / "a.jpg"
    second = tmp_path / "b.jpg"
    catalog.upsert(make_record(first))
    catalog.upsert(make_record(second))
    catalog.commit()

    by_dir = catalog.by_directory(tmp_path)
    assert len(by_dir) == 2
    subset = catalog.by_paths([first])
    assert list(subset) == [str(first)]
    assert catalog.by_paths([]) == {}


def test_prune_removes_missing(catalog: Catalog, tmp_path: Path) -> None:
    first = tmp_path / "a.jpg"
    second = tmp_path / "b.jpg"
    catalog.upsert(make_record(first))
    catalog.upsert(make_record(second))
    catalog.commit()
    removed = catalog.prune_directory(str(tmp_path), {str(first)})
    assert removed == 1
    assert catalog.get(second) is None
    assert catalog.get(first) is not None


def test_scan_cursor_roundtrip(catalog: Catalog, tmp_path: Path) -> None:
    assert catalog.get_scan_cursor(str(tmp_path)) == ""
    catalog.set_scan_cursor(str(tmp_path), "b.jpg")
    assert catalog.get_scan_cursor(str(tmp_path)) == "b.jpg"
    catalog.set_scan_cursor(str(tmp_path), "")
    assert catalog.get_scan_cursor(str(tmp_path)) == ""


def test_favorite_lifecycle(catalog: Catalog, tmp_path: Path) -> None:
    path = tmp_path / "a.jpg"
    catalog.upsert(make_record(path, taken_ts=1790000000))
    copy = tmp_path / "copy" / "a.jpg"
    catalog.add_favorite(path, copy, 1790000000)
    catalog.commit()

    assert catalog.is_favorite(path) is True
    assert catalog.favorite_count() == 1
    assert str(path) in catalog.favorite_paths()

    by_favorited = catalog.list_favorites("favorited")
    assert len(by_favorited) == 1
    assert by_favorited[0].copy_path == copy
    assert by_favorited[0].photo is not None
    assert by_favorited[0].photo.place_text

    by_taken = catalog.list_favorites("taken")
    assert len(by_taken) == 1

    removed = catalog.remove_favorite(path)
    assert removed == copy
    assert catalog.is_favorite(path) is False
    assert catalog.favorite_count() == 0


def test_favorite_without_photo_row(catalog: Catalog, tmp_path: Path) -> None:
    path = tmp_path / "missing.jpg"
    catalog.add_favorite(path, None, 0)
    catalog.commit()
    records = catalog.list_favorites("taken")
    assert len(records) == 1
    assert records[0].photo is None
    assert records[0].sort_ts > 0


def test_remove_unknown_favorite(catalog: Catalog, tmp_path: Path) -> None:
    assert catalog.remove_favorite(tmp_path / "nope.jpg") is None


def test_set_place(catalog: Catalog, tmp_path: Path) -> None:
    path = tmp_path / "a.jpg"
    catalog.upsert(make_record(path))
    catalog.set_place(path, "北京")
    catalog.commit()
    record = catalog.get(path)
    assert record is not None and record.place == "北京"


def test_forget(catalog: Catalog, tmp_path: Path) -> None:
    path = tmp_path / "a.jpg"
    catalog.upsert(make_record(path))
    catalog.forget(path)
    assert catalog.get(path) is None
