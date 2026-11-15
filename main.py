#!/usr/bin/env python3
"""薄包装入口：真正的启动逻辑只有一处，位于 ``livephoto_player.app.main:main``。

PyInstaller 与 ``uv run main.py`` 都从这里进入。
"""

from __future__ import annotations

import sys

from livephoto_player.app.main import main

if __name__ == "__main__":
    sys.exit(main())
