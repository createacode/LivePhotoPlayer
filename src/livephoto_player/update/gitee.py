"""Gitee Release 更新检查（规范 L6.8）。

只使用标准库 ``urllib.request`` + ``json``，网络请求在后台线程执行；
本模块保持纯逻辑，便于用 mock 响应做单元测试。
"""

from __future__ import annotations

import json
import re
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any, Final

from livephoto_player.core.version import __version__

API_TEMPLATE: Final = "https://gitee.com/api/v5/repos/{owner}/{repo}/releases/latest"
# HTTP 头只能是 latin-1，因此 User-Agent 用 ASCII 产品标识（软件名 + 版本仍可识别）
USER_AGENT: Final = f"LivePhotoPlayer/{__version__}"
CONNECT_TIMEOUT: Final = 5
TOTAL_TIMEOUT: Final = 10
CHECK_INTERVAL = timedelta(hours=24)

_VERSION_RE = re.compile(r"^[vV]?(\d+)(?:\.(\d+))?(?:\.(\d+))?(?:[-+].*)?$")


class UpdateError(RuntimeError):
    """更新检查失败（网络、协议、数据格式）。"""


@dataclass(frozen=True, slots=True)
class ReleaseAsset:
    """发行版附件。"""

    name: str
    size: int
    digest: str
    url: str


@dataclass(frozen=True, slots=True)
class UpdateInfo:
    """一个发行版的关键信息。"""

    tag: str
    version: tuple[int, int, int]
    name: str
    body: str
    created_at: str
    prerelease: bool
    assets: tuple[ReleaseAsset, ...] = field(default_factory=tuple)

    @property
    def version_text(self) -> str:
        """``MAJOR.MINOR.PATCH`` 形式。"""
        return ".".join(str(part) for part in self.version)

    def preferred_asset(self) -> ReleaseAsset | None:
        """挑一个最适合下载的附件（优先 exe，其次 zip / msi）。"""
        if not self.assets:
            return None
        priorities = (".exe", ".zip", ".msi", ".7z")
        for suffix in priorities:
            for asset in self.assets:
                if asset.name.lower().endswith(suffix):
                    return asset
        return self.assets[0]


def parse_version(text: str) -> tuple[int, int, int] | None:
    """解析版本号，非法返回 ``None``。"""
    match = _VERSION_RE.match(text.strip())
    if match is None:
        return None
    parts = [int(match.group(index) or 0) for index in (1, 2, 3)]
    return parts[0], parts[1], parts[2]


def is_newer(candidate: str, current: str) -> bool:
    """候选版本是否严格新于当前版本（按段数值比较，禁止字符串比较）。"""
    candidate_version = parse_version(candidate)
    current_version = parse_version(current)
    if candidate_version is None or current_version is None:
        return False
    return candidate_version > current_version


def should_check_now(last_check: str, *, now: datetime | None = None) -> bool:
    """是否已过自动检查间隔（默认 24 小时）。"""
    if not last_check:
        return True
    try:
        previous = datetime.fromisoformat(last_check)
    except ValueError:
        return True
    return (now or datetime.now()) - previous >= CHECK_INTERVAL


def build_api_url(owner: str, repo: str) -> str:
    """构造 Release API 地址；只允许 HTTPS。"""
    return API_TEMPLATE.format(owner=owner, repo=repo)


def _asset_from_raw(raw: Any) -> ReleaseAsset | None:
    if not isinstance(raw, dict):
        return None
    name = raw.get("name")
    url = raw.get("browser_download_url")
    if not isinstance(name, str) or not isinstance(url, str):
        return None
    size = raw.get("size")
    digest = raw.get("digest")
    return ReleaseAsset(
        name=name,
        size=size if isinstance(size, int) else 0,
        digest=digest if isinstance(digest, str) else "",
        url=url,
    )


def parse_release(payload: Any) -> UpdateInfo:
    """把 API 返回的 JSON 解析成 ``UpdateInfo``。"""
    if not isinstance(payload, dict):
        raise UpdateError("更新接口返回的不是 JSON 对象")
    tag = payload.get("tag_name")
    if not isinstance(tag, str) or not tag:
        raise UpdateError("更新接口缺少 tag_name")
    version = parse_version(tag)
    if version is None:
        raise UpdateError(f"无法解析版本号：{tag}")

    assets_raw = payload.get("assets")
    assets: list[ReleaseAsset] = []
    if isinstance(assets_raw, list):
        for item in assets_raw:
            asset = _asset_from_raw(item)
            if asset is not None:
                assets.append(asset)

    raw_name = payload.get("name")
    raw_body = payload.get("body")
    raw_created = payload.get("created_at")
    return UpdateInfo(
        tag=tag,
        version=version,
        name=raw_name if isinstance(raw_name, str) else tag,
        body=raw_body if isinstance(raw_body, str) else "",
        created_at=raw_created if isinstance(raw_created, str) else "",
        prerelease=bool(payload.get("prerelease")),
        assets=tuple(assets),
    )


def fetch_latest(
    owner: str,
    repo: str,
    *,
    opener: Any = None,
    timeout: int = TOTAL_TIMEOUT,
) -> UpdateInfo:
    """请求 ``releases/latest`` 并解析；失败统一抛 ``UpdateError``。"""
    url = build_api_url(owner, repo)
    if not url.startswith("https://"):
        raise UpdateError("更新接口必须使用 HTTPS")
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    open_call = opener if opener is not None else urllib.request.urlopen
    try:
        with open_call(request, timeout=timeout) as response:
            charset = "utf-8"
            raw = response.read()
    except urllib.error.HTTPError as exc:
        raise UpdateError(f"更新接口返回 HTTP {exc.code}") from exc
    except urllib.error.URLError as exc:
        raise UpdateError(f"网络不可用：{exc.reason}") from exc
    except TimeoutError as exc:
        raise UpdateError("更新检查超时") from exc
    except OSError as exc:
        raise UpdateError(f"请求更新接口失败：{exc}") from exc

    try:
        payload = json.loads(raw.decode(charset))
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise UpdateError("更新接口返回了非法 JSON") from exc
    return parse_release(payload)
