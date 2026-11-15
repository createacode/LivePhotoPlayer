"""User-Agent 与 HTTP 头的编码约束测试。"""

from __future__ import annotations

from livephoto_player.core.version import __version__
from livephoto_player.update import gitee


def test_user_agent_is_ascii() -> None:
    """HTTP 头只能是 latin-1，User-Agent 必须是纯 ASCII。"""
    gitee.USER_AGENT.encode("latin-1")


def test_user_agent_contains_name_and_version() -> None:
    assert gitee.USER_AGENT.startswith("LivePhotoPlayer/")
    assert __version__ in gitee.USER_AGENT


def test_request_headers_are_encodable() -> None:
    """构造真实请求，确认 urllib 不会因编码抛错。"""
    import urllib.request

    url = gitee.build_api_url("owner", "repo")
    request = urllib.request.Request(url, headers={"User-Agent": gitee.USER_AGENT})
    assert request.get_header("User-agent") == gitee.USER_AGENT
