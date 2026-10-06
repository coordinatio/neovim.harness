"""Create the git repository for a long-running session."""

from __future__ import annotations

import logging
import os
import subprocess
from collections.abc import Mapping
from pathlib import Path
from typing import NoReturn, Protocol

logger = logging.getLogger(__name__)

_GIT_LOCATION = frozenset(
    {
        "GIT_DIR",
        "GIT_WORK_TREE",
        "GIT_INDEX_FILE",
        "GIT_OBJECT_DIRECTORY",
        "GIT_COMMON_DIR",
        "GIT_NAMESPACE",
    }
)


def without_git_location(
    updates: Mapping[str, str] | None = None,
) -> dict[str, str]:
    """Child environment. Git location variables stay in this process."""
    environ = {
        key: value for key, value in os.environ.items() if key not in _GIT_LOCATION
    }
    if updates:
        environ.update(updates)
    return environ


class InitializesGit(Protocol):
    def init(self, directory: Path) -> None: ...


class GitInitError(Exception):
    """``git init`` failed. The message is the log text."""


class GitRepository:
    """``git init -b main``. No commit and no gitignore."""

    def init(self, directory: Path) -> None:
        command = ["git", "init", "-b", "main"]
        logger.debug("Initializing git repository in %s", directory)
        try:
            completed = subprocess.run(
                command,
                check=False,
                cwd=directory,
                env=without_git_location(),
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.PIPE,
                text=True,
                errors="replace",
            )
        except FileNotFoundError:
            _fail("The git command is not on PATH. Is it installed and in your PATH?")
        except Exception as exc:
            _fail(f"Failed to create the git repository: {exc}")
        if completed.returncode != 0 or not (directory / ".git").exists():
            detail = (completed.stderr or "").rstrip()
            message = "Failed to create the git repository."
            if detail:
                message = f"{message}\n{detail}"
            _fail(message)


def _fail(message: str) -> NoReturn:
    logger.error("%s", message)
    raise GitInitError(message)
