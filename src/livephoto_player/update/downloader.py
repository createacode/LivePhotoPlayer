"""更新包下载与校验（规范 L6.8）。

下载到临时目录，先按 ``assets[].digest`` 校验 SHA-256，缺失时退回同批
``SHA256SUMS.txt``，并核对文件大小；校验失败删除文件并提示手动下载。
"""

from __future__ import annotations

import hashlib
import tempfile
import urllib.request
from collections.abc import Callable
from pathlib import Path
from typing import Any, Final

from livephoto_player.update.gitee import USER_AGENT, ReleaseAsset, UpdateError

_CHUNK = 1 << 16
SUMS_NAME: Final = "SHA256SUMS.txt"


def _sha256_of(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while True:
            block = handle.read(_CHUNK)
            if not block:
                break
            digest.update(block)
    return digest.hexdigest()


def parse_sums(text: str) -> dict[str, str]:
    """解析 ``SHA256SUMS.txt``，返回 ``文件名 -> 摘要``。"""
    mapping: dict[str, str] = {}
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        parts = line.split()
        if len(parts) < 2:
            continue
        digest, name = parts[0].lower(), parts[-1].lstrip("*")
        if len(digest) == 64:
            mapping[name] = digest
    return mapping


def expected_digest(asset: ReleaseAsset, sums: dict[str, str]) -> str:
    """优先使用附件自带 digest，其次使用 SHA256SUMS.txt。"""
    digest = asset.digest.strip().lower()
    if digest.startswith("sha256:"):
        digest = digest.split(":", 1)[1]
    if len(digest) == 64:
        return digest
    return sums.get(asset.name, "")


def download_asset(
    asset: ReleaseAsset,
    *,
    target_dir: Path | None = None,
    sums_url: str | None = None,
    progress: Callable[[int, int], None] | None = None,
    opener: Callable[..., Any] | None = None,
) -> Path:
    """下载并校验附件，返回本地路径；任何校验失败都会删除文件并抛错。"""
    directory = target_dir or (Path(tempfile.gettempdir()) / "LivePhotoPlayer" / "update")
    directory.mkdir(parents=True, exist_ok=True)
    target = directory / asset.name
    open_call = opener if opener is not None else urllib.request.urlopen

    request = urllib.request.Request(asset.url, headers={"User-Agent": USER_AGENT})
    try:
        with open_call(request, timeout=30) as response, target.open("wb") as handle:
            total = int(response.headers.get("Content-Length") or asset.size or 0)
            received = 0
            while True:
                block = response.read(_CHUNK)
                if not block:
                    break
                handle.write(block)
                received += len(block)
                if progress is not None:
                    progress(received, total)
    except OSError as exc:
        target.unlink(missing_ok=True)
        raise UpdateError(f"下载失败：{exc}") from exc

    if asset.size and target.stat().st_size != asset.size:
        target.unlink(missing_ok=True)
        raise UpdateError("下载文件大小与发行说明不一致")

    sums: dict[str, str] = {}
    if sums_url:
        sums = _fetch_sums(sums_url, open_call)
    digest = expected_digest(asset, sums)
    if not digest:
        return target
    actual = _sha256_of(target)
    if actual != digest:
        target.unlink(missing_ok=True)
        raise UpdateError("SHA-256 校验失败，已删除下载文件，请手动下载")
    return target


def _fetch_sums(url: str, open_call: Callable[..., Any]) -> dict[str, str]:
    try:
        request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
        with open_call(request, timeout=15) as response:
            return parse_sums(response.read().decode("utf-8", "replace"))
    except OSError:
        return {}
