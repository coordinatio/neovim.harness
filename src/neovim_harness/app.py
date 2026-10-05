"""Create a session, prepare it, open the editor, then publish."""

from __future__ import annotations

import logging
from pathlib import Path

from neovim_harness.clipboard import Clipboard
from neovim_harness.editor import Editor
from neovim_harness.modes import (
    ConvertsHtmlToMarkdown,
    ConvertsMarkdownToHtml,
    Workflow,
)
from neovim_harness.sessions import SessionStore

logger = logging.getLogger(__name__)


class App:
    def __init__(
        self,
        sessions: SessionStore,
        mode: Workflow,
        clipboard: Clipboard,
        editor: Editor,
        html_to_markdown: ConvertsHtmlToMarkdown,
        markdown_to_html: ConvertsMarkdownToHtml,
    ) -> None:
        self._sessions = sessions
        self._mode = mode
        self._clipboard = clipboard
        self._editor = editor
        self._html_to_markdown = html_to_markdown
        self._markdown_to_html = markdown_to_html

    def run(self) -> None:
        path = self._sessions.create()
        self._mode.prepare(path, self._clipboard, self._html_to_markdown)
        self._editor.open(path, self._mode.ex_commands())
        self._publish(path)

    def _publish(self, path: Path) -> None:
        try:
            content = path.read_text(encoding="utf-8")
        except FileNotFoundError:
            logger.warning(
                "Temporary file not found (maybe editor didn't save?). Exiting."
            )
            return
        self._mode.publish(content, self._clipboard, self._markdown_to_html)
