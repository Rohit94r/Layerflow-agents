"""Make `app` importable from scripts/ both in the repo (apps/api) and in the container (/app)."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
for candidate in (ROOT / "apps" / "api", Path("/app")):
    if (candidate / "app" / "__init__.py").exists():
        sys.path.insert(0, str(candidate))
        break
