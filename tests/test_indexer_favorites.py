"""索引线程与收藏服务测试：增量、续扫、副本复制与清理。"""

from __future__ import annotations

from pathlib import Path

import pytest
from PIL import Image

from livephoto_player.services.catalog import Catalog
from livephoto_player.services.favorites import FavoritesService
from livephoto_player.services.indexer import IndexWorker


def make_photo(path: Path, color: tuple[int, int, int] = (10, 20, 30)) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", (32, 24), color).save(path, "JPEG")
    return path


# ------------------------------------------------------------------ 索引线程
def test_indexer_scans_directory(qtbot: object, tmp_path: Path) -> None:
    album = tmp_path / "album"
    make_photo(album / "IMG20260927164937.jpg")
    make_photo(album / "IMG20260928163110.jpg")
    (album / "note.txt").write_text("ignore me", encoding="utf-8")

    db = tmp_path / "catalog.db"
    worker = IndexWorker(db)
    worker.enqueue(album)
    try:
        with qtbot.waitSignal(worker.directory_done, timeout=20000):  # type: ignore[attr-defined]
            worker.start()
        worker.stop()

        catalog = Catalog(db)
        try:
            assert catalog.count() == 2
            records = catalog.by_directory(album)
            for record in records.values():
                assert record.taken_ts > 0
                assert record.camera == ""
        finally:
            catalog.close()
    finally:
        worker.stop()


def test_indexer_is_incremental(qtbot: object, tmp_path: Path) -> None:
    album = tmp_path / "album"
    make_photo(album / "IMG20260927164937.jpg")
    db = tmp_path / "catalog.db"

    first = IndexWorker(db)
    first.enqueue(album)
    with qtbot.waitSignal(first.directory_done, timeout=20000) as blocker:  # type: ignore[attr-defined]
        first.start()
    first.stop()
    assert blocker.args[1] == 1

    second = IndexWorker(db)
    second.enqueue(album)
    with qtbot.waitSignal(second.directory_done, timeout=20000) as blocker2:  # type: ignore[attr-defined]
        second.start()
    second.stop()
    # 大小与修改时间都没变 -> 不应重复索引
    assert blocker2.args[1] == 0


def test_indexer_picks_up_new_file(qtbot: object, tmp_path: Path) -> None:
    album = tmp_path / "album"
    make_photo(album / "IMG20260927164937.jpg")
    db = tmp_path / "catalog.db"

    first = IndexWorker(db)
    first.enqueue(album)
    with qtbot.waitSignal(first.directory_done, timeout=20000):  # type: ignore[attr-defined]
        first.start()
    first.stop()

    make_photo(album / "IMG20260928163110.jpg")
    second = IndexWorker(db)
    second.enqueue(album)
    with qtbot.waitSignal(second.directory_done, timeout=20000) as blocker:  # type: ignore[attr-defined]
        second.start()
    second.stop()
    assert blocker.args[1] == 1

    catalog = Catalog(db)
    try:
        assert catalog.count() == 2
    finally:
        catalog.close()


def test_indexer_prunes_deleted_file(qtbot: object, tmp_path: Path) -> None:
    album = tmp_path / "album"
    keep = make_photo(album / "IMG20260927164937.jpg")
    drop = make_photo(album / "IMG20260928163110.jpg")
    db = tmp_path / "catalog.db"

    first = IndexWorker(db)
    first.enqueue(album)
    with qtbot.waitSignal(first.directory_done, timeout=20000):  # type: ignore[attr-defined]
        first.start()
    first.stop()

    drop.unlink()
    second = IndexWorker(db)
    second.enqueue(album)
    with qtbot.waitSignal(second.directory_done, timeout=20000):  # type: ignore[attr-defined]
        second.start()
    second.stop()

    catalog = Catalog(db)
    try:
        assert catalog.count() == 1
        assert catalog.get(keep) is not None
    finally:
        catalog.close()


def test_indexer_ignores_missing_directory(tmp_path: Path) -> None:
    worker = IndexWorker(tmp_path / "catalog.db")
    worker.enqueue(tmp_path / "does-not-exist")
    assert worker.queued() == 0
    worker.stop()


def test_indexer_deduplicates_queue(tmp_path: Path) -> None:
    album = tmp_path / "album"
    album.mkdir()
    worker = IndexWorker(tmp_path / "catalog.db")
    worker.enqueue(album)
    worker.enqueue(album)
    assert worker.queued() == 1
    worker.stop()


# ------------------------------------------------------------------ 收藏
@pytest.fixture
def favorites(tmp_path: Path) -> FavoritesService:
    catalog = Catalog(tmp_path / "catalog.db")
    service = FavoritesService(catalog, tmp_path / "favorites")
    yield service  # type: ignore[misc]
    catalog.close()


def test_toggle_creates_and_removes_copy(favorites: FavoritesService, tmp_path: Path) -> None:
    source = make_photo(tmp_path / "src" / "IMG20260927164937.jpg")
    assert favorites.is_favorite(source) is False

    assert favorites.toggle(source, 1790000000) is True
    assert favorites.is_favorite(source) is True
    copies = list(favorites.copy_dir.glob("*"))
    assert len(copies) == 1
    assert copies[0].read_bytes() == source.read_bytes()
    assert "20260927" in copies[0].name

    assert favorites.toggle(source, 1790000000) is False
    assert favorites.is_favorite(source) is False
    assert list(favorites.copy_dir.glob("*")) == []


def test_toggle_reuses_existing_copy(favorites: FavoritesService, tmp_path: Path) -> None:
    source = make_photo(tmp_path / "src" / "IMG20260927164937.jpg")
    favorites.toggle(source, 1790000000)
    first = next(iter(favorites.copy_dir.glob("*")))
    favorites.toggle(source, 1790000000)
    favorites.toggle(source, 1790000000)
    second = next(iter(favorites.copy_dir.glob("*")))
    assert first == second
    assert first.read_bytes() == source.read_bytes()


def test_toggle_survives_copy_failure(favorites: FavoritesService, tmp_path: Path) -> None:
    """副本复制失败也要记录收藏状态，只是没有副本。"""
    ghost = tmp_path / "ghost.jpg"
    ghost.write_bytes(b"x")
    ghost.unlink()
    assert favorites.toggle(ghost, 0) is True
    assert favorites.is_favorite(ghost) is True
    assert favorites.count() == 1


def test_removing_favorite_keeps_foreign_files(favorites: FavoritesService, tmp_path: Path) -> None:
    source = make_photo(tmp_path / "src" / "IMG20260927164937.jpg")
    favorites.toggle(source, 1790000000)
    copy = next(iter(favorites.copy_dir.glob("*")))
    # 把副本搬出收藏目录后取消收藏，不应删除收藏目录之外的文件
    outside = tmp_path / "outside_copy.jpg"
    copy.rename(outside)
    favorites.toggle(source, 1790000000)
    assert outside.exists()
