"""LetItApply ASGI entrypoint for Vercel (and local `uvicorn app:app`)."""

from __future__ import annotations

import sys
from pathlib import Path

_SRC = Path(__file__).resolve().parent / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from jobsearch_saas.api.app import app  # noqa: E402

__all__ = ["app"]
