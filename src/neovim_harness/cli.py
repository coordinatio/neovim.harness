"""Parse arguments and wire the real Wayland, Pandoc, and Neovide implementations."""

from __future__ import annotations

import argparse
import logging
import os
import sys
from collections.abc import Sequence
from pathlib import Path

from neovim_harness.app import App
from neovim_harness.environment import SUCCESS_TEXT, collect_failures, format_report
from neovim_harness.modes import (
    EditFormattedText,
    EditPlainText,
    NamedSession,
    NewFormattedText,
    NewPlainText,
    ResumeSession,
)
from neovim_harness.workspace import OpensWorkspace

_MODES = {
    "new-plain": NewPlainText,
    "edit-plain": EditPlainText,
    "edit-formatted": EditFormattedText,
    "new-formatted": NewFormattedText,
    "new-session": NamedSession,
    "resume-session": ResumeSession,
}


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Edit clipboard text in Neovide and copy the result back, "
            "or start and resume a named session."
        ),
    )
    parser.add_argument(
        "-v",
        "--verbose",
        action="store_true",
        help="Verbose logging",
    )
    parser.add_argument(
        "--check-environment",
        action="store_true",
        help="Check required programs and Python packages, then exit",
    )
    group = parser.add_mutually_exclusive_group()
    group.add_argument(
        "-p",
        dest="mode",
        action="store_const",
        const="edit-plain",
        help="Edit plain text from the clipboard",
    )
    group.add_argument(
        "-m",
        dest="mode",
        action="store_const",
        const="edit-formatted",
        help="Edit formatted HTML from the clipboard as Markdown",
    )
    group.add_argument(
        "-n",
        dest="mode",
        action="store_const",
        const="new-formatted",
        help="Edit a new formatted document",
    )
    group.add_argument(
        "-s",
        "--session",
        dest="mode",
        action="store_const",
        const="new-session",
        help="Start a named session without using the clipboard",
    )
    group.add_argument(
        "-r",
        "--resume",
        dest="mode",
        action="store_const",
        const="resume-session",
        help="Resume a previous session",
    )
    parser.set_defaults(mode="new-plain")
    return parser.parse_args(list(argv) if argv is not None else None)


def configure_logging(verbose: bool) -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
    logging.getLogger("neovim_harness").setLevel(
        logging.DEBUG if verbose else logging.INFO
    )


def main(argv: Sequence[str] | None = None) -> None:
    args = parse_args(argv)
    configure_logging(args.verbose)
    failures = collect_failures()
    if failures:
        sys.stdout.write(format_report(failures))
        raise SystemExit(1)
    if args.check_environment:
        print(SUCCESS_TEXT)
        raise SystemExit(0)
    _run(args.mode)


def _run(mode_name: str) -> None:
    # Converters import optional packages. Load them only after the check passes.
    from neovim_harness.assets import AssetPaths
    from neovim_harness.clipboard import WaylandClipboard
    from neovim_harness.convert import HtmlToMarkdown, MarkdownToHtml
    from neovim_harness.editor import NeovideEditor
    from neovim_harness.prompt import KDialogPrompt
    from neovim_harness.repository import GitRepository
    from neovim_harness.sessions import SessionStore, sessions_root
    from neovim_harness.workspace import (
        ClipboardSessionSource,
        NamedSessionSource,
        ResumeSessionSource,
        SessionLifecycle,
    )

    assets = AssetPaths.load()
    sessions = SessionStore(sessions_root(os.environ, Path.home()))
    editor = NeovideEditor(assets.rename_lua, assets.resume_lua)
    dialog = KDialogPrompt()
    git = GitRepository()
    source: OpensWorkspace
    if mode_name == "new-session":
        source = NamedSessionSource(sessions, dialog, git, dialog)
    elif mode_name == "resume-session":
        source = ResumeSessionSource(sessions, editor, dialog)
    else:
        source = ClipboardSessionSource(sessions)
    app = App(
        source=source,
        mode=_MODES[mode_name](),
        clipboard=WaylandClipboard(),
        editor=editor,
        html_to_markdown=HtmlToMarkdown(assets.lua_filter),
        markdown_to_html=MarkdownToHtml(assets.stylesheet),
        lifecycle=SessionLifecycle(sessions, git, dialog),
    )
    app.run()
