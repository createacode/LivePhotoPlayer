"""结构化目录：用 SQLite 保存照片的元数据、收藏与扫描进度。

为什么需要它：搜索、按拍摄时间线排序、收藏时间线、地点展示都需要"不用打开
文件就能拿到时间和地点"。这些数据由后台索引线程慢慢补齐，UI 只读结果。

线程模型：一个连接 + 可重入锁，``check_same_thread=False`` 并开启 WAL，
索引线程与 UI 线程可以安全共用同一个实例。
"""

from __future__ import annotations

import sqlite3
import threading
import time
from pathlib import Path
from typing import Final, Literal

from livephoto_player.core.format import format_day
from livephoto_player.core.models import FavoriteRecord, PhotoRecord
from livephoto_player.utils.logger import get_logger

FavoriteOrder = Literal["favorited", "taken"]

SCHEMA_VERSION: Final = 1

_SCHEMA = """
CREATE TABLE IF NOT EXISTS photos (
    path        TEXT PRIMARY KEY,
    name        TEXT NOT NULL,
    directory   TEXT NOT NULL,
    kind        TEXT NOT NULL DEFAULT 'photo',
    size_bytes  INTEGER NOT NULL DEFAULT 0,
    mtime       INTEGER NOT NULL DEFAULT 0,
    taken_ts    INTEGER NOT NULL DEFAULT 0,
    taken_day   TEXT NOT NULL DEFAULT '',
    time_source TEXT NOT NULL DEFAULT 'file',
    latitude    REAL,
    longitude   REAL,
    place       TEXT NOT NULL DEFAULT '',
    camera      TEXT NOT NULL DEFAULT '',
    width       INTEGER NOT NULL DEFAULT 0,
    height      INTEGER NOT NULL DEFAULT 0,
    indexed_at  INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_photos_taken ON photos(taken_ts DESC);
CREATE INDEX IF NOT EXISTS idx_photos_dir ON photos(directory);

CREATE TABLE IF NOT EXISTS favorites (
    path         TEXT PRIMARY KEY,
    favorited_ts INTEGER NOT NULL,
    copy_path    TEXT,
    taken_ts     INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_favorites_time ON favorites(favorited_ts DESC);

CREATE TABLE IF NOT EXISTS scan_state (
    directory  TEXT PRIMARY KEY,
    last_path  TEXT NOT NULL DEFAULT '',
    updated_at INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS meta (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
"""

_COLUMNS = (
    "path, name, directory, kind, size_bytes, mtime, taken_ts, taken_day, "
    "time_source, latitude, longitude, place, camera, width, height"
)


class Catalog:
    """元数据与收藏的持久化入口。"""

    def __init__(self, db_path: Path) -> None:
        self._logger = get_logger("catalog")
        self._lock = threading.RLock()
        db_path.parent.mkdir(parents=True, exist_ok=True)
        self._connection = sqlite3.connect(str(db_path), check_same_thread=False)
        self._connection.row_factory = sqlite3.Row
        with self._lock:
            self._connection.execute("PRAGMA journal_mode=WAL")
            self._connection.execute("PRAGMA synchronous=NORMAL")
            self._connection.executescript(_SCHEMA)
            self._connection.execute(
                "INSERT OR REPLACE INTO meta(key, value) VALUES('schema_version', ?)",
                (str(SCHEMA_VERSION),),
            )
            self._connection.commit()

    # ------------------------------------------------------------------ 生命周期
    def close(self) -> None:
        """关闭连接。"""
        with self._lock:
            try:
                self._connection.commit()
                self._connection.close()
            except sqlite3.Error as exc:  # pragma: no cover - 关闭期异常
                self._logger.warning("关闭索引库失败：%s", exc)

    def commit(self) -> None:
        """提交事务（索引线程分批调用）。"""
        with self._lock:
            try:
                self._connection.commit()
            except sqlite3.Error as exc:
                self._logger.error("提交索引事务失败：%s", exc)

    # ------------------------------------------------------------------ 写入
    def need_index(self, path: Path, size_bytes: int, mtime: int) -> bool:
        """是否需要（重新）索引：新文件或大小/修改时间变化。"""
        with self._lock:
            row = self._connection.execute(
                "SELECT size_bytes, mtime FROM photos WHERE path = ?", (str(path),)
            ).fetchone()
        if row is None:
            return True
        return int(row["size_bytes"]) != size_bytes or int(row["mtime"]) != mtime

    def upsert(self, record: PhotoRecord) -> None:
        """写入或更新一条记录。"""
        taken_day = format_day(record.taken_ts) if record.taken_ts else ""
        with self._lock:
            self._connection.execute(
                """
                INSERT INTO photos (
                    path, name, directory, kind, size_bytes, mtime, taken_ts, taken_day,
                    time_source, latitude, longitude, place, camera, width, height, indexed_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(path) DO UPDATE SET
                    name=excluded.name, directory=excluded.directory, kind=excluded.kind,
                    size_bytes=excluded.size_bytes, mtime=excluded.mtime,
                    taken_ts=excluded.taken_ts, taken_day=excluded.taken_day,
                    time_source=excluded.time_source, latitude=excluded.latitude,
                    longitude=excluded.longitude, place=excluded.place,
                    camera=excluded.camera, width=excluded.width, height=excluded.height,
                    indexed_at=excluded.indexed_at
                """,
                (
                    str(record.path),
                    record.name,
                    record.directory,
                    record.kind,
                    record.size_bytes,
                    record.mtime,
                    record.taken_ts,
                    taken_day,
                    record.time_source,
                    record.latitude,
                    record.longitude,
                    record.place,
                    record.camera,
                    record.width,
                    record.height,
                    int(time.time()),
                ),
            )

    def pending_places(self, limit: int = 200) -> list[tuple[Path, float, float]]:
        """取出有坐标但还没有地名的记录。"""
        with self._lock:
            rows = self._connection.execute(
                """
                SELECT path, latitude, longitude FROM photos
                WHERE latitude IS NOT NULL AND longitude IS NOT NULL AND place = ''
                LIMIT ?
                """,
                (limit,),
            ).fetchall()
        return [
            (Path(str(row["path"])), float(row["latitude"]), float(row["longitude"]))
            for row in rows
        ]

    def pending_place_count(self) -> int:
        """还有多少条记录等待地点解析。"""
        with self._lock:
            row = self._connection.execute(
                "SELECT COUNT(*) AS total FROM photos "
                "WHERE latitude IS NOT NULL AND longitude IS NOT NULL AND place = ''"
            ).fetchone()
        return int(row["total"]) if row else 0

    def clear_places(self) -> int:
        """清空全部地名（切换解析方式后重新解析）。"""
        with self._lock:
            cursor = self._connection.execute("UPDATE photos SET place = ''")
            self._connection.commit()
        return int(cursor.rowcount or 0)

    def set_place(self, path: Path, place: str) -> None:
        """更新地名（供地名解析使用）。"""
        with self._lock:
            self._connection.execute(
                "UPDATE photos SET place = ? WHERE path = ?", (place, str(path))
            )

    def forget(self, path: Path) -> None:
        """删除一条记录（文件已不存在）。"""
        with self._lock:
            self._connection.execute("DELETE FROM photos WHERE path = ?", (str(path),))

    def prune_directory(self, directory: str, existing: set[str]) -> int:
        """删除某目录下已不存在的记录，返回删除条数。"""
        with self._lock:
            rows = self._connection.execute(
                "SELECT path FROM photos WHERE directory = ?", (directory,)
            ).fetchall()
            stale = [row["path"] for row in rows if row["path"] not in existing]
            for path in stale:
                self._connection.execute("DELETE FROM photos WHERE path = ?", (path,))
        return len(stale)

    # ------------------------------------------------------------------ 扫描进度
    def set_scan_cursor(self, directory: str, last_path: str) -> None:
        """记录目录扫描进度，便于中断后续扫。"""
        with self._lock:
            self._connection.execute(
                "INSERT INTO scan_state(directory, last_path, updated_at) VALUES(?, ?, ?) "
                "ON CONFLICT(directory) DO UPDATE SET last_path=excluded.last_path, "
                "updated_at=excluded.updated_at",
                (directory, last_path, int(time.time())),
            )

    def get_scan_cursor(self, directory: str) -> str:
        """取上次扫到哪个文件；没有记录返回空串。"""
        with self._lock:
            row = self._connection.execute(
                "SELECT last_path FROM scan_state WHERE directory = ?", (directory,)
            ).fetchone()
        return str(row["last_path"]) if row else ""

    # ------------------------------------------------------------------ 读取
    def get(self, path: Path) -> PhotoRecord | None:
        """按路径取一条记录。"""
        with self._lock:
            row = self._connection.execute(
                f"SELECT {_COLUMNS} FROM photos WHERE path = ?", (str(path),)
            ).fetchone()
        return _row_to_record(row) if row else None

    def by_directory(self, directory: Path) -> dict[str, PhotoRecord]:
        """取某个目录下已索引的记录，键为绝对路径字符串。"""
        with self._lock:
            rows = self._connection.execute(
                f"SELECT {_COLUMNS} FROM photos WHERE directory = ?", (str(directory),)
            ).fetchall()
        return {str(row["path"]): _row_to_record(row) for row in rows}

    def by_paths(self, paths: list[Path]) -> dict[str, PhotoRecord]:
        """批量取记录，键为路径字符串。"""
        if not paths:
            return {}
        result: dict[str, PhotoRecord] = {}
        chunk = 400
        with self._lock:
            for start in range(0, len(paths), chunk):
                batch = [str(item) for item in paths[start : start + chunk]]
                placeholders = ",".join("?" for _ in batch)
                rows = self._connection.execute(
                    f"SELECT {_COLUMNS} FROM photos WHERE path IN ({placeholders})", batch
                ).fetchall()
                for row in rows:
                    result[str(row["path"])] = _row_to_record(row)
        return result

    def search(self, query: str, limit: int = 500) -> list[PhotoRecord]:
        """按文件名 / 地名 / 相机 / 目录 / 日期做全库搜索，新的在前。"""
        text = query.strip()
        if not text:
            return []
        like = f"%{text}%"
        with self._lock:
            rows = self._connection.execute(
                f"""
                SELECT {_COLUMNS} FROM photos
                WHERE name LIKE ? OR place LIKE ? OR camera LIKE ?
                   OR directory LIKE ? OR taken_day LIKE ?
                ORDER BY COALESCE(NULLIF(taken_ts, 0), mtime) DESC
                LIMIT ?
                """,
                (like, like, like, like, like, limit),
            ).fetchall()
        return [_row_to_record(row) for row in rows]

    def recent(self, limit: int = 500) -> list[PhotoRecord]:
        """最近拍摄的记录。"""
        with self._lock:
            rows = self._connection.execute(
                f"""
                SELECT {_COLUMNS} FROM photos
                ORDER BY COALESCE(NULLIF(taken_ts, 0), mtime) DESC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()
        return [_row_to_record(row) for row in rows]

    def count(self) -> int:
        """已索引的记录总数。"""
        with self._lock:
            row = self._connection.execute("SELECT COUNT(*) AS total FROM photos").fetchone()
        return int(row["total"]) if row else 0

    # ------------------------------------------------------------------ 收藏
    def is_favorite(self, path: Path) -> bool:
        """是否已收藏。"""
        with self._lock:
            row = self._connection.execute(
                "SELECT 1 FROM favorites WHERE path = ?", (str(path),)
            ).fetchone()
        return row is not None

    def favorite_paths(self) -> set[str]:
        """一次性取出全部收藏路径，供列表批量标记。"""
        with self._lock:
            rows = self._connection.execute("SELECT path FROM favorites").fetchall()
        return {str(row["path"]) for row in rows}

    def add_favorite(self, path: Path, copy_path: Path | None, taken_ts: int) -> None:
        """加入收藏。"""
        with self._lock:
            self._connection.execute(
                "INSERT OR REPLACE INTO favorites(path, favorited_ts, copy_path, taken_ts) "
                "VALUES(?, ?, ?, ?)",
                (str(path), int(time.time()), str(copy_path) if copy_path else None, taken_ts),
            )

    def remove_favorite(self, path: Path) -> Path | None:
        """取消收藏，返回原副本路径以便删除。"""
        with self._lock:
            row = self._connection.execute(
                "SELECT copy_path FROM favorites WHERE path = ?", (str(path),)
            ).fetchone()
            if row is None:
                return None
            self._connection.execute("DELETE FROM favorites WHERE path = ?", (str(path),))
            raw = row["copy_path"]
        return Path(str(raw)) if raw else None

    def list_favorites(self, order: FavoriteOrder = "favorited") -> list[FavoriteRecord]:
        """列出收藏；``favorited`` 按收藏时间，``taken`` 按拍摄时间。"""
        if order == "taken":
            order_by = "COALESCE(NULLIF(p.taken_ts, 0), NULLIF(f.taken_ts, 0), f.favorited_ts) DESC"
        else:
            order_by = "f.favorited_ts DESC"
        with self._lock:
            rows = self._connection.execute(
                f"""
                SELECT p.path, p.name, p.directory, p.kind, p.size_bytes, p.mtime,
                       p.taken_ts, p.taken_day, p.time_source, p.latitude, p.longitude,
                       p.place, p.camera, p.width, p.height,
                       f.path AS fav_path, f.favorited_ts AS fav_ts, f.copy_path AS copy_path
                FROM favorites f
                LEFT JOIN photos p ON p.path = f.path
                ORDER BY {order_by}
                """,
            ).fetchall()
        records: list[FavoriteRecord] = []
        for row in rows:
            photo = _row_to_record(row) if row["name"] is not None else None
            copy_raw = row["copy_path"]
            records.append(
                FavoriteRecord(
                    path=Path(str(row["fav_path"])),
                    favorited_ts=int(row["fav_ts"]),
                    copy_path=Path(str(copy_raw)) if copy_raw else None,
                    photo=photo,
                )
            )
        return records

    def favorite_count(self) -> int:
        """收藏总数。"""
        with self._lock:
            row = self._connection.execute("SELECT COUNT(*) AS total FROM favorites").fetchone()
        return int(row["total"]) if row else 0


def _row_to_record(row: sqlite3.Row) -> PhotoRecord:
    """把数据库行还原成 ``PhotoRecord``。"""
    return PhotoRecord(
        path=Path(str(row["path"])),
        name=str(row["name"]),
        directory=str(row["directory"]),
        kind=str(row["kind"]),
        size_bytes=int(row["size_bytes"]),
        mtime=int(row["mtime"]),
        taken_ts=int(row["taken_ts"]),
        time_source=str(row["time_source"]),
        latitude=float(row["latitude"]) if row["latitude"] is not None else None,
        longitude=float(row["longitude"]) if row["longitude"] is not None else None,
        place=str(row["place"]),
        camera=str(row["camera"]),
        width=int(row["width"]),
        height=int(row["height"]),
    )
