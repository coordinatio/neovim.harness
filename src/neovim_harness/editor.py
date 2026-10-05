"""Blocking Neovide launch. Standard streams stay detached."""

from __future__ import annotations

import logging
import subprocess
import sys
from collections.abc import Sequence
from pathlib import Path
from typing import Protocol

logger = logging.getLogger(__name__)


class Editor(Protocol):
    def open(self, file_path: Path, ex_commands: Sequence[str]) -> None: ...


class NeovideEditor:
    def open(self, file_path: Path, ex_commands: Sequence[str]) -> None:
        command = ["neovide", "--no-fork", str(file_path), "--", *ex_commands]
        logger.info("Opening editor: %s", file_path)
        try:
            # Detached streams avoid Wayland os error 9.
            subprocess.run(
                command,
                check=False,
                cwd=file_path.parent,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
        except FileNotFoundError:
            logger.error(
                "Neovide executable not found. Is it installed and in your PATH?"
            )
            sys.exit(1)
        except Exception as exc:
            logger.error("Failed to launch editor: %s", exc)
            sys.exit(1)
