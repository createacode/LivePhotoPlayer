#!/usr/bin/env python3
"""从唯一真源生成 Windows 版本资源 ``scripts/version_info.txt``。

版本号只允许出现在 ``src/livephoto_player/core/version.py``，本脚本用 AST
读取，不 import 包，因此在任何环境下都能独立运行。
"""

from __future__ import annotations

import ast
import contextlib
import sys
from pathlib import Path

# 控制台可能使用 GBK 代码页，统一改成 UTF-8，避免中文与 © 无法输出
with contextlib.suppress(AttributeError, ValueError):
    for _stream in (sys.stdout, sys.stderr):
        _stream.reconfigure(encoding="utf-8", errors="replace")

ROOT = Path(__file__).resolve().parents[1]
VERSION_FILE = ROOT / "src" / "livephoto_player" / "core" / "version.py"
OUTPUT = ROOT / "scripts" / "version_info.txt"

_COMPANY = "XAF Studio"
_PRODUCT = "实况照片播放器"
_ORIGINAL_NAME = "LivePhotoPlayer.exe"


def read_version_source(path: Path = VERSION_FILE) -> dict[str, str]:
    """用 AST 读取版本模块里的四个常量。"""
    tree = ast.parse(path.read_text(encoding="utf-8"))
    wanted = {"__version__", "__author__", "__copyright_ym__", "__software_name__"}
    found: dict[str, str] = {}
    for node in tree.body:
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name) and target.id in wanted:
                    value = ast.literal_eval(node.value)
                    if isinstance(value, str):
                        found[target.id] = value
    missing = wanted - found.keys()
    if missing:
        raise SystemExit(f"版本真源缺少字段：{sorted(missing)}")
    return found


def build_version_info(version: str, author: str, year_month: str) -> str:
    """生成 PyInstaller ``--version-file`` 内容。"""
    parts = [int(item) for item in version.split(".")]
    while len(parts) < 4:
        parts.append(0)
    file_version = ", ".join(str(item) for item in parts[:4])
    copyright_text = f"Copyright © {author} {year_month}"
    return f"""# UTF-8
# 由 scripts/gen_version_info.py 生成，请勿手工修改
VSVersionInfo(
  ffi=FixedFileInfo(
    filevers=({file_version}),
    prodvers=({file_version}),
    mask=0x3f,
    flags=0x0,
    OS=0x40004,
    fileType=0x1,
    subtype=0x0,
    date=(0, 0)
  ),
  kids=[
    StringFileInfo(
      [
        StringTable(
          '040904B0',
          [
            StringStruct('CompanyName', '{_COMPANY}'),
            StringStruct('FileDescription', '{_PRODUCT}'),
            StringStruct('FileVersion', '{version}'),
            StringStruct('InternalName', 'LivePhotoPlayer'),
            StringStruct('LegalCopyright', '{copyright_text}'),
            StringStruct('OriginalFilename', '{_ORIGINAL_NAME}'),
            StringStruct('ProductName', '{_PRODUCT}'),
            StringStruct('ProductVersion', '{version}')
          ]
        )
      ]
    ),
    VarFileInfo([VarStruct('Translation', [0x0409, 0x04B0])])
  ]
)
"""


def main() -> int:
    """生成版本资源并打印摘要。"""
    info = read_version_source()
    text = build_version_info(info["__version__"], info["__author__"], info["__copyright_ym__"])
    OUTPUT.write_text(text, encoding="utf-8", newline="\n")
    print(f"已生成 {OUTPUT.relative_to(ROOT)}（版本 {info['__version__']}）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
