"""Allocate session directories. Nothing in this module deletes them."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from datetime import datetime
from pathlib import Path


def sessions_root(environ: Mapping[str, str], home: Path) -> Path:
    """Return the session root. A relative override is ignored."""
    raw = environ.get("NEOVIM_HARNESS_SESSIONS")
    if raw:
        candidate = Path(raw)
        if candidate.is_absolute():
            return candidate
    return home / ".neovim.harness" / "sessions"


class SessionStore:
    """Create ``doc-YYMMDDHHMMSS`` directories and a mode-0600 Markdown file."""

    def __init__(self, root: Path, clock: Callable[[], datetime] | None = None) -> None:
        self._root = root
        self._clock = clock or datetime.now

    def create(self) -> Path:
        self._root.mkdir(parents=True, exist_ok=True)
        directory = self._claim(self._clock().strftime("%y%m%d%H%M%S"))
        path = directory / f"{directory.name}.md"
        path.touch()
        path.chmod(0o600)
        return path

    def _claim(self, timestamp: str) -> Path:
        """mkdir the doc directory. FileExistsError means that name is taken."""
        stem = f"doc-{timestamp}"
        number = 1
        while True:
            name = stem if number == 1 else f"{stem}-{number}"
            directory = self._root / name
            try:
                directory.mkdir(parents=False, exist_ok=False)
            except FileExistsError:
                number = 2 if number == 1 else number + 1
                continue
            return directory
