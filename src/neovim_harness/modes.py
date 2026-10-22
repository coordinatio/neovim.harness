"""One class per clipboard workflow."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import BinaryIO, Protocol

from neovim_harness.clipboard import Clipboard, ReadsRequiredMime

logger = logging.getLogger(__name__)


class ConvertsHtmlToMarkdown(Protocol):
    def convert(self, html_content: bytes) -> str: ...


class ConvertsMarkdownToHtml(Protocol):
    def convert(self, markdown_content: str) -> str: ...


class ConvertsHtmlStrictly(Protocol):
    def convert_strict(self, html_content: bytes) -> str: ...


class ConvertsMarkdownStrictly(Protocol):
    def convert_strict(self, markdown_content: str) -> str: ...


class Workflow(Protocol):
    def prepare(
        self,
        path: Path | None,
        clipboard: Clipboard,
        html_to_markdown: ConvertsHtmlToMarkdown,
    ) -> None: ...

    def ex_commands(self) -> list[str]: ...

    def publish(
        self,
        content: str,
        clipboard: Clipboard,
        markdown_to_html: ConvertsMarkdownToHtml,
    ) -> None: ...


class NewPlainText:
    def prepare(
        self,
        path: Path | None,
        clipboard: Clipboard,
        html_to_markdown: ConvertsHtmlToMarkdown,
    ) -> None:
        assert path is not None
        path.touch()
        logger.debug("Created empty file.")

    def ex_commands(self) -> list[str]:
        return ["+start"]

    def publish(
        self,
        content: str,
        clipboard: Clipboard,
        markdown_to_html: ConvertsMarkdownToHtml,
    ) -> None:
        logger.info("Copying text to clipboard...")
        clipboard.write(content, mimetype="text/plain")


class EditPlainText:
    def prepare(
        self,
        path: Path | None,
        clipboard: Clipboard,
        html_to_markdown: ConvertsHtmlToMarkdown,
    ) -> None:
        assert path is not None
        logger.debug("Pasting standard clipboard content...")
        path.write_bytes(clipboard.read())

    def ex_commands(self) -> list[str]:
        return []

    def publish(
        self,
        content: str,
        clipboard: Clipboard,
        markdown_to_html: ConvertsMarkdownToHtml,
    ) -> None:
        logger.info("Copying text to clipboard...")
        clipboard.write(content, mimetype="text/plain")


class EditFormattedText:
    def prepare(
        self,
        path: Path | None,
        clipboard: Clipboard,
        html_to_markdown: ConvertsHtmlToMarkdown,
    ) -> None:
        assert path is not None
        logger.debug("Converting HTML clipboard to Markdown...")
        html_data = clipboard.read(mimetype="text/html")
        path.write_text(html_to_markdown.convert(html_data), encoding="utf-8")

    def ex_commands(self) -> list[str]:
        return ["+colorscheme retrobox"]

    def publish(
        self,
        content: str,
        clipboard: Clipboard,
        markdown_to_html: ConvertsMarkdownToHtml,
    ) -> None:
        logger.info("Processing Markdown to Styled HTML...")
        clipboard.write(markdown_to_html.convert(content), mimetype="text/html")


class NewFormattedText:
    def prepare(
        self,
        path: Path | None,
        clipboard: Clipboard,
        html_to_markdown: ConvertsHtmlToMarkdown,
    ) -> None:
        assert path is not None
        path.touch()
        logger.debug("Created empty file.")

    def ex_commands(self) -> list[str]:
        return ["+start", "+colorscheme retrobox"]

    def publish(
        self,
        content: str,
        clipboard: Clipboard,
        markdown_to_html: ConvertsMarkdownToHtml,
    ) -> None:
        logger.info("Processing Markdown to Styled HTML...")
        clipboard.write(markdown_to_html.convert(content), mimetype="text/html")


class NamedSession:
    def prepare(
        self,
        path: Path | None,
        clipboard: Clipboard,
        html_to_markdown: ConvertsHtmlToMarkdown,
    ) -> None:
        return

    def ex_commands(self) -> list[str]:
        return ["+start"]

    def publish(
        self,
        content: str,
        clipboard: Clipboard,
        markdown_to_html: ConvertsMarkdownToHtml,
    ) -> None:
        return


class ResumeSession:
    def prepare(
        self,
        path: Path | None,
        clipboard: Clipboard,
        html_to_markdown: ConvertsHtmlToMarkdown,
    ) -> None:
        return

    def ex_commands(self) -> list[str]:
        return ["+start"]

    def publish(
        self,
        content: str,
        clipboard: Clipboard,
        markdown_to_html: ConvertsMarkdownToHtml,
    ) -> None:
        return


class ClipboardToMarkdown:
    """Read text/html and write Markdown to stdout."""

    def run(
        self,
        clipboard: ReadsRequiredMime,
        html_to_markdown: ConvertsHtmlStrictly,
        stdout: BinaryIO,
    ) -> None:
        markdown = html_to_markdown.convert_strict(clipboard.read_required("text/html"))
        stdout.write(markdown.encode("utf-8"))
        stdout.flush()


class MarkdownToClipboard:
    """Read Markdown and write text/html to the clipboard."""

    def run(
        self,
        markdown: str,
        clipboard: Clipboard,
        markdown_to_html: ConvertsMarkdownStrictly,
    ) -> None:
        clipboard.write(markdown_to_html.convert_strict(markdown), mimetype="text/html")
