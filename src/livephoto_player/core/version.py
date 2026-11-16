"""版本、作者与版权的唯一真源。

本模块是全工程唯一允许出现版本号、作者名与版权年月字面量的位置；
其余产物（exe 属性、VERSION.txt、三份文档标题、窗口标题、关于对话框）
一律由 ``scripts/`` 下的脚本或本模块的函数派生。
"""

from __future__ import annotations

__all__ = [
    "COPYRIGHT_SUFFIX",
    "__author__",
    "__copyright_ym__",
    "__software_name__",
    "__version__",
    "copyright_suffix",
    "window_title",
]

__software_name__ = "实况照片播放器"
__version__ = "4.8.0"
__author__ = "XAF"
__copyright_ym__ = "2026.11"

COPYRIGHT_SUFFIX = f"Copyright © {__author__} {__copyright_ym__}"


def copyright_suffix() -> str:
    """返回标准版权后缀：``- Copyright © 作者 年月``。"""
    return f"- {COPYRIGHT_SUFFIX}"


def window_title() -> str:
    """返回主窗口/托盘/关于对话框统一使用的标题。"""
    return f"{__software_name__} v{__version__} {copyright_suffix()}"
