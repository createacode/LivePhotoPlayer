"""``python -m livephoto_player`` 入口，仅做薄包装。"""

from __future__ import annotations

import sys

from livephoto_player.app.main import main

if __name__ == "__main__":
    sys.exit(main())
