"""Blocking Neovide launch. Standard streams stay detached."""

from __future__ import annotations

import logging
import subprocess
import sys
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import NoReturn, Protocol

from neovim_harness.repository import without_git_location

logger = logging.getLogger(__name__)

# Neovide reads these from the environment and would leave the session directory
# or attach to an existing Neovim. They stay set in this process.
_NEOVIDE_LAUNCH = frozenset({"NEOVIDE_CHDIR", "NEOVIDE_SERVER"})


class Editor(Protocol):
    def open(
        self,
        directory: Path,
        ex_commands: Sequence[str],
        file_path: Path | None,
        rename_request: Path,
    ) -> None: ...

    def pick(self, catalog_path: Path, choice_path: Path) -> int: ...


class NeovideEditor:
    def __init__(self, rename_lua: Path, resume_lua: Path) -> None:
        self._rename_lua = rename_lua
        self._resume_lua = resume_lua

    def open(
        self,
        directory: Path,
        ex_commands: Sequence[str],
        file_path: Path | None,
        rename_request: Path,
    ) -> None:
        command = ["neovide", "--no-fork"]
        if file_path is not None:
            command.append(str(file_path))
        command.extend(
            ["--", *ex_commands, "-c", _lua_dofile(self._rename_lua)]
        )
        target = file_path if file_path is not None else directory
        logger.info("Opening editor: %s", target)
        self._run(
            command,
            directory,
            _child_environ({"NEOVIM_HARNESS_RENAME_FILE": str(rename_request)}),
        )

    def pick(self, catalog_path: Path, choice_path: Path) -> int:
        command = [
            "neovide",
            "--no-fork",
            "--",
            "--noplugin",
            "-i",
            "NONE",
            "-u",
            "NONE",
            "-c",
            _lua_dofile(self._resume_lua),
        ]
        logger.info("Opening session list.")
        return self._run(
            command,
            catalog_path.parent,
            _child_environ(
                {
                    "NEOVIM_HARNESS_CATALOG": str(catalog_path),
                    "NEOVIM_HARNESS_CHOICE": str(choice_path),
                }
            ),
        )

    def _run(self, command: Sequence[str], cwd: Path, environ: Mapping[str, str]) -> int:
        if not cwd.exists():
            _missing_session_directory()
        try:
            completed = subprocess.run(
                command,
                check=False,
                cwd=cwd,
                env=dict(environ),
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
        except FileNotFoundError:
            if not cwd.exists():
                _missing_session_directory()
            logger.error(
                "Neovide executable not found. Is it installed and in your PATH?"
            )
            sys.exit(1)
        except Exception as exc:
            logger.error("Failed to launch editor: %s", exc)
            sys.exit(1)
        return completed.returncode


def _missing_session_directory() -> NoReturn:
    logger.error("The session directory is gone.")
    sys.exit(1)


def _child_environ(updates: Mapping[str, str]) -> dict[str, str]:
    """Environment for a Neovide child. Launch overrides stay in the parent."""
    environ = without_git_location(updates)
    for key in _NEOVIDE_LAUNCH:
        environ.pop(key, None)
    return environ


def _lua_dofile(path: Path) -> str:
    text = str(path)
    equals = "="
    while f"]{equals}]" in text:
        equals += "="
    return f"lua dofile([{equals}[{text}]{equals}])"
