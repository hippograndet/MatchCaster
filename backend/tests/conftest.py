# backend/tests/conftest.py
"""Root conftest: add backend to sys.path so 'player' module is importable."""

from __future__ import annotations

import sys
from pathlib import Path

# Add backend/ to sys.path (one level up from tests/)
_backend_dir = Path(__file__).parent.parent
if str(_backend_dir) not in sys.path:
    sys.path.insert(0, str(_backend_dir))