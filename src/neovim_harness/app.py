"""Open a workspace, prepare it, run the editor, then publish."""

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
from neovim_harness.workspace import (
    OpensWorkspace,
    RelocatesWorkspace,
    Workspace,
    discard_rename_request,
)

logger = logging.getLogger(__name__)


class App:
    def __init__(
        self,
        source: OpensWorkspace,
        mode: Workflow,
        clipboard: Clipboard,
        editor: Editor,
        html_to_markdown: ConvertsHtmlToMarkdown,
        markdown_to_html: ConvertsMarkdownToHtml,
        lifecycle: RelocatesWorkspace,
    ) -> None:
        self._source = source
        self._mode = mode
        self._clipboard = clipboard
        self._editor = editor
        self._html_to_markdown = html_to_markdown
        self._markdown_to_html = markdown_to_html
        self._lifecycle = lifecycle

    def run(self) -> None:
        workspace = self._source.open()
        try:
            self._mode.prepare(workspace.file, self._clipboard, self._html_to_markdown)
        except BaseException:
            discard_rename_request(workspace.rename_request)
            raise
        while True:
            try:
                self._editor.open(
                    workspace.directory,
                    self._mode.ex_commands(),
                    workspace.file,
                    workspace.rename_request,
                )
            except BaseException:
                discard_rename_request(workspace.rename_request)
                raise
            relocated = self._lifecycle.relocate(workspace)
            if relocated is None:
                break
            workspace = relocated
        if workspace.publish_clipboard and workspace.file is not None:
            self._publish(workspace.file)

    def _publish(self, path: Path) -> None:
        try:
            content = path.read_text(encoding="utf-8")
        except FileNotFoundError:
            logger.warning(
                "Temporary file not found (maybe editor didn't save?). Exiting."
            )
            return
        self._mode.publish(content, self._clipboard, self._markdown_to_html)
