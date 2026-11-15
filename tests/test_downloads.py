"""更新包下载与校验测试：大小、SHA-256、缺失摘要与 SHA256SUMS 回退。"""

from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from livephoto_player.update.downloader import download_asset
from livephoto_player.update.gitee import ReleaseAsset, UpdateError

CONTENT = b"payload-bytes" * 100
DIGEST = hashlib.sha256(CONTENT).hexdigest()


class FakeResponse:
    def __init__(self, body: bytes, headers: dict[str, str] | None = None) -> None:
        self._body = body
        self._offset = 0
        self.headers = headers or {}

    def __enter__(self) -> FakeResponse:
        return self

    def __exit__(self, *args: object) -> None:
        return None

    def read(self, size: int = -1) -> bytes:
        if size < 0:
            size = len(self._body) - self._offset
        chunk = self._body[self._offset : self._offset + size]
        self._offset += len(chunk)
        return chunk


def test_download_verifies_digest(tmp_path: Path) -> None:
    asset = ReleaseAsset("app.zip", len(CONTENT), f"sha256:{DIGEST}", "https://x/app.zip")
    target = download_asset(
        asset,
        target_dir=tmp_path,
        opener=lambda request, timeout: FakeResponse(CONTENT),
    )
    assert target.read_bytes() == CONTENT


def test_download_size_mismatch_raises_and_cleans(tmp_path: Path) -> None:
    asset = ReleaseAsset("app.zip", len(CONTENT) + 5, "", "https://x/app.zip")
    with pytest.raises(UpdateError):
        download_asset(
            asset,
            target_dir=tmp_path,
            opener=lambda request, timeout: FakeResponse(CONTENT),
        )
    assert not (tmp_path / "app.zip").exists()


def test_download_digest_mismatch_raises_and_cleans(tmp_path: Path) -> None:
    asset = ReleaseAsset("app.zip", len(CONTENT), f"sha256:{'0' * 64}", "https://x/app.zip")
    with pytest.raises(UpdateError):
        download_asset(
            asset,
            target_dir=tmp_path,
            opener=lambda request, timeout: FakeResponse(CONTENT),
        )
    assert not (tmp_path / "app.zip").exists()


def test_download_uses_sums_when_asset_has_no_digest(tmp_path: Path) -> None:
    sums = f"{DIGEST}  app.zip\n".encode()

    def opener(request: object, timeout: int) -> FakeResponse:
        url = request.full_url if hasattr(request, "full_url") else str(request)
        if "SHA256SUMS" in url:
            return FakeResponse(sums)
        return FakeResponse(CONTENT)

    asset = ReleaseAsset("app.zip", len(CONTENT), "", "https://x/app.zip")
    target = download_asset(
        asset,
        target_dir=tmp_path,
        sums_url="https://x/SHA256SUMS.txt",
        opener=opener,
    )
    assert target.exists()


def test_download_without_digest_skips_hash_check(tmp_path: Path) -> None:
    asset = ReleaseAsset("app.zip", len(CONTENT), "", "https://x/app.zip")
    target = download_asset(
        asset,
        target_dir=tmp_path,
        opener=lambda request, timeout: FakeResponse(CONTENT),
    )
    assert target.exists()


def test_download_network_error_raises(tmp_path: Path) -> None:
    def opener(request: object, timeout: int) -> FakeResponse:
        raise OSError("disk full")

    asset = ReleaseAsset("app.zip", 10, "", "https://x/app.zip")
    with pytest.raises(UpdateError):
        download_asset(asset, target_dir=tmp_path, opener=opener)


def test_download_reports_progress(tmp_path: Path) -> None:
    seen: list[tuple[int, int]] = []
    asset = ReleaseAsset("app.zip", len(CONTENT), "", "https://x/app.zip")
    download_asset(
        asset,
        target_dir=tmp_path,
        progress=lambda received, total: seen.append((received, total)),
        opener=lambda request, timeout: FakeResponse(
            CONTENT, {"Content-Length": str(len(CONTENT))}
        ),
    )
    assert seen
    assert seen[-1][0] == len(CONTENT)
