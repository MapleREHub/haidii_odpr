"""pytest 配置：把 ``crawler`` 目录加入导入路径。

这样 ``tests/test_crawler.py`` 里的 ``from oald10... import ...``
无需额外设置 ``PYTHONPATH`` 即可工作。
"""

from __future__ import annotations

import os
import sys

ROOT = os.path.dirname(os.path.abspath(__file__))
CRAWLER = os.path.join(ROOT, "crawler")

if CRAWLER not in sys.path:
    sys.path.insert(0, CRAWLER)
