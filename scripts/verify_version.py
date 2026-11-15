#!/usr/bin/env python3
"""校验版本一致性：真源、版本资源、VERSION.txt 与三份文档必须完全一致。

不一致时返回非零退出码，供 ``scripts/build.ps1`` 与 CI 使用。
"""

from __future__ import annotations

import contextlib
import re
import sys
from pathlib import Path

# 控制台可能使用 GBK 代码页，统一改成 UTF-8，避免中文与 © 无法输出
with contextlib.suppress(AttributeError, ValueError):
    for _stream in (sys.stdout, sys.stderr):
        _stream.reconfigure(encoding="utf-8", errors="replace")

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from gen_version_info import read_version_source  # noqa: E402

VERSION_INFO = ROOT / "scripts" / "version_info.txt"
VERSION_TXT = ROOT / "VERSION.txt"
DOCS = (
    ROOT / "README.md",
    ROOT / "docs" / "readme.md",
    ROOT / "docs" / "develop-readme.md",
)


def _check(label: str, expected: str, actual: str, problems: list[str]) -> None:
    if expected not in actual:
        problems.append(f"{label} 未包含 {expected!r}")


def main() -> int:
    """执行一致性校验。"""
    info = read_version_source()
    name = info["__software_name__"]
    version = info["__version__"]
    author = info["__author__"]
    year_month = info["__copyright_ym__"]
    problems: list[str] = []

    if not re.fullmatch(r"\d+\.\d+\.\d+", version):
        problems.append(f"版本号格式不合法：{version}")
    if not re.fullmatch(r"\d{4}\.\d{2}", year_month):
        problems.append(f"版权年月格式不合法：{year_month}")

    if VERSION_INFO.exists():
        _check(
            "scripts/version_info.txt", version, VERSION_INFO.read_text(encoding="utf-8"), problems
        )
    else:
        problems.append("缺少 scripts/version_info.txt，请先运行 gen_version_info.py")

    if VERSION_TXT.exists():
        content = VERSION_TXT.read_text(encoding="utf-8")
        _check("VERSION.txt", f"版本号：{version}", content, problems)
        _check("VERSION.txt", f"作者：{author}", content, problems)
        _check("VERSION.txt", f"{name}", content, problems)
    else:
        problems.append("缺少 VERSION.txt，请先运行 sync_version.py")

    title = f"# {name} v{version} - Copyright © {author} {year_month}"
    for doc in DOCS:
        if not doc.exists():
            problems.append(f"缺少文档：{doc.relative_to(ROOT)}")
            continue
        first_lines = "\n".join(doc.read_text(encoding="utf-8").splitlines()[:5])
        if title not in first_lines:
            problems.append(f"{doc.relative_to(ROOT)} 标题与真源不一致，应为：{title}")

    if problems:
        print("版本一致性校验失败：")
        for item in problems:
            print(f"  - {item}")
        return 1
    print(f"版本一致性校验通过：{name} v{version} - Copyright © {author} {year_month}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
