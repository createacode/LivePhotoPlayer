"""收藏服务：加入/取消收藏，并把原图另复制一份到独立文件夹。"""

from __future__ import annotations

import shutil
import time
from pathlib import Path

from livephoto_player.core.format import format_datetime
from livephoto_player.services.catalog import Catalog
from livephoto_player.utils.logger import get_logger


class FavoritesService:
    """收藏状态与副本文件的管理者。"""

    def __init__(self, catalog: Catalog, copy_dir: Path) -> None:
        self._catalog = catalog
        self._copy_dir = copy_dir
        self._logger = get_logger("favorites")

    @property
    def copy_dir(self) -> Path:
        """收藏副本目录。"""
        return self._copy_dir

    def is_favorite(self, path: Path) -> bool:
        """是否已收藏。"""
        return self._catalog.is_favorite(path)

    def toggle(self, path: Path, taken_ts: int = 0) -> bool:
        """切换收藏状态，返回切换后的状态。"""
        if self._catalog.is_favorite(path):
            self._remove(path)
            return False
        self._add(path, taken_ts)
        return True

    def count(self) -> int:
        """收藏总数。"""
        return self._catalog.favorite_count()

    # ------------------------------------------------------------------ 内部实现
    def _add(self, path: Path, taken_ts: int) -> None:
        copy_path: Path | None = None
        try:
            copy_path = self._copy_source(path, taken_ts)
        except OSError as exc:
            self._logger.error("收藏副本复制失败 %s：%s", path.name, exc)
        self._catalog.add_favorite(path, copy_path, taken_ts)
        self._catalog.commit()
        self._logger.info("已收藏 %s -> %s", path.name, copy_path)

    def _remove(self, path: Path) -> None:
        copy_path = self._catalog.remove_favorite(path)
        self._catalog.commit()
        if copy_path is not None:
            # 只删除本服务自己管理的副本，避免误删用户文件
            try:
                if copy_path.exists() and copy_path.parent.resolve() == self._copy_dir.resolve():
                    copy_path.unlink()
            except OSError as exc:
                self._logger.warning("删除收藏副本失败 %s：%s", copy_path, exc)
        self._logger.info("已取消收藏 %s", path.name)

    def _copy_source(self, path: Path, taken_ts: int) -> Path:
        self._copy_dir.mkdir(parents=True, exist_ok=True)
        stamp = format_datetime(taken_ts or int(path.stat().st_mtime)).replace(" ", "_")
        stamp = stamp.replace(":", "")
        target = self._copy_dir / f"{stamp}_{path.name}"
        try:
            same = (
                target.exists()
                and target.stat().st_size == path.stat().st_size
                and target.stat().st_mtime >= path.stat().st_mtime
            )
        except OSError:
            same = False
        if not same:
            shutil.copy2(path, target)
        return target


def favorite_stamp(timestamp: int) -> str:
    """收藏/拍摄时间的紧凑时间戳（测试用）。"""
    return format_datetime(timestamp or int(time.time())).replace(" ", "_").replace(":", "")
