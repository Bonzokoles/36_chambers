"""Host-configurable paths for the 36 Chambers engine.

The public repository carries no host-specific absolute paths. Every location
is resolved from an environment variable, optionally loaded from a local
``.env`` file next to the project root (see ``.env.example``). Set real values
on your own host before running.

Resolution order per variable: process environment, then ``.env`` file.
"""

from __future__ import annotations

import os
from pathlib import Path

#: Directory two levels above this file is treated as the project root,
#: so the local ``.env`` is discovered at ``<root>/.env`` both in the live
#: checkout (``The_Buch/.env``) and in the published layout (``<repo>/.env``).
_ENV_FILE = Path(__file__).resolve().parent.parent / ".env"


def load_dotenv(path: Path | None = None) -> None:
    """Load KEY=VALUE lines from a .env file without an external dependency."""
    target = path or _ENV_FILE
    if not target.is_file():
        return
    for line in target.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


def get(name: str) -> str | None:
    """Raw environment value, or None when unset/blank."""
    value = os.environ.get(name, "").strip()
    return value or None


def path(name: str) -> Path | None:
    """Resolve an environment variable to a Path, or None when unset/blank."""
    value = get(name)
    return Path(value) if value else None


def require(name: str) -> Path:
    """Resolve a required path, raising a clear error when it is missing."""
    resolved = path(name)
    if resolved is None:
        raise RuntimeError(
            f"Required environment variable {name} is not set. "
            "Copy .env.example to .env and fill in the real host paths."
        )
    return resolved


# Load once at import time so ``get``/``path``/``require`` see local .env values.
load_dotenv()
