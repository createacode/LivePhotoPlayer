#!/usr/bin/env python3
"""同步版本派生产物：版权年月、``VERSION.txt``、三份文档标题与修订记录。

唯一真源是 ``src/livephoto_player/core/version.py``，本脚本只做派生，
不会在别处写死第二份版本号。
"""

from __future__ import annotations

import argparse
import contextlib
import re
import sys
from datetime import datetime
from pathlib import Path

# 控制台可能使用 GBK 代码页，统一改成 UTF-8，避免中文与 © 无法输出
with contextlib.suppress(AttributeError, ValueError):
    for _stream in (sys.stdout, sys.stderr):
        _stream.reconfigure(encoding="utf-8", errors="replace")

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from gen_version_info import read_version_source  # noqa: E402

VERSION_TXT = ROOT / "VERSION.txt"
DOCS = (
    ROOT / "README.md",
    ROOT / "docs" / "readme.md",
    ROOT / "docs" / "develop-readme.md",
)
TITLE_PATTERN = re.compile(r"^#\s+(?P<name>.+?)\s+v(?P<version>\d+\.\d+\.\d+)\s+-")


def update_copyright_ym(year_month: str) -> None:
    """把版本真源里的版权年月改为指定值。"""
    path = ROOT / "src" / "livephoto_player" / "core" / "version.py"
    text = path.read_text(encoding="utf-8")
    updated = re.sub(
        r'__copyright_ym__\s*=\s*"[^"]*"',
        f'__copyright_ym__ = "{year_month}"',
        text,
        count=1,
    )
    if updated != text:
        path.write_text(updated, encoding="utf-8")


def write_version_txt(name: str, version: str, author: str, year_month: str) -> None:
    """生成发布包根目录的 ``VERSION.txt``。"""
    content = (
        f"软件名称：{name}\n"
        f"版本号：{version}\n"
        f"作者：{author}\n"
        f"版权：Copyright © {author} {year_month}\n"
        f"构建日期：{datetime.now():%Y-%m-%d}\n"
        "目标平台：Windows 10 / 11 x64\n"
        "许可：本软件生成物归使用者所有，第三方组件许可见 THIRD-PARTY-NOTICES.md\n"
    )
    VERSION_TXT.write_text(content, encoding="utf-8", newline="\n")


def sync_document(doc: Path, name: str, version: str, author: str, year_month: str) -> bool:
    """更新文档标题与修订记录，返回是否有改动。"""
    if not doc.exists():
        return False
    text = doc.read_text(encoding="utf-8")
    original = text
    title = f"# {name} v{version} - Copyright © {author} {year_month}"
    lines = text.splitlines()
    for index, line in enumerate(lines):
        if TITLE_PATTERN.match(line):
            lines[index] = title
            break
    else:
        lines.insert(0, title)
    text = "\n".join(lines)
    text = _ensure_revision(text, version, year_month)
    if not text.endswith("\n"):
        text += "\n"
    if text != original:
        doc.write_text(text, encoding="utf-8", newline="\n")
        return True
    return False


def _is_table_separator(line: str) -> bool:
    """判断是否为 Markdown 表格分隔行（必须有 ``-``，空行不算）。"""
    stripped = line.strip()
    if not stripped.startswith("|") or "-" not in stripped:
        return False
    chars = set(stripped.replace("|", "").replace(" ", ""))
    return bool(chars) and chars <= {"-", ":"}


def _ensure_revision(text: str, version: str, year_month: str) -> str:
    """确保修订记录表格里有当前版本的一行（幂等）。"""
    lines = text.splitlines()
    header_index = None
    for index, line in enumerate(lines):
        if line.strip().startswith("## ") and "修订记录" in line:
            header_index = index
            break
    if header_index is None:
        lines.extend(["", "## 修订记录", "", "| 日期 | 版本号 | 说明 |", "| --- | --- | --- |"])
        lines.append(f"| {datetime.now():%Y-%m-%d} | {version} | 由 sync_version.py 同步版本号 |")
        return "\n".join(lines)

    separator = None
    for index in range(header_index + 1, min(header_index + 10, len(lines))):
        if _is_table_separator(lines[index]):
            separator = index
            break
    if separator is None:
        lines[header_index + 1 : header_index + 1] = [
            "",
            "| 日期 | 版本号 | 说明 |",
            "| --- | --- | --- |",
            f"| {datetime.now():%Y-%m-%d} | {version} | 由 sync_version.py 同步版本号 |",
        ]
        return "\n".join(lines)

    row = f"| {datetime.now():%Y-%m-%d} | {version} | 由 sync_version.py 同步版本号 |"
    for index in range(separator + 1, len(lines)):
        if not lines[index].strip().startswith("|"):
            break
        if f"| {version} |" in lines[index]:
            return "\n".join(lines)
    lines.insert(separator + 1, row)
    return "\n".join(lines)


def main() -> int:
    """执行同步并打印发布包名。"""
    parser = argparse.ArgumentParser(description="同步版本派生产物")
    parser.add_argument("--year-month", default=None, help="覆盖版权年月，如 2026.11")
    parser.add_argument("--no-date", action="store_true", help="不修改版权年月")
    args = parser.parse_args()

    year_month = args.year_month or datetime.now().strftime("%Y.%m")
    if not args.no_date:
        update_copyright_ym(year_month)

    info = read_version_source()
    year_month = info["__copyright_ym__"]
    name, version, author = info["__software_name__"], info["__version__"], info["__author__"]

    write_version_txt(name, version, author, year_month)
    print(f"已生成 VERSION.txt（{version}）")
    for doc in DOCS:
        changed = sync_document(doc, name, version, author, year_month)
        print(f"{'已更新' if changed else '无变化'}  {doc.relative_to(ROOT)}")
    print(f"发布包名建议：LivePhotoPlayer_v{version}_win-x64_{datetime.now():%Y%m%d}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
