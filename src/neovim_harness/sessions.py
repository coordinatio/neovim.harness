"""Allocate session directories. Nothing in this module deletes them."""

from __future__ import annotations

import ctypes
import errno
import logging
import os
import re
import stat
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

logger = logging.getLogger(__name__)

_SKIP_DIRECTORIES = frozenset({".git", "node_modules", "__pycache__", ".venv", "venv"})
_UNFORMATTED_MTIME = "unknown"
_SESSION_NAME = re.compile(r"^doc-\d{12}(?:$|-\d+$|--[^-].*)$")
_STAMP = re.compile(r"^(doc-\d{12})")
_SLUG_CHARS = 80
_SLUG_BYTES = 200
_PREVIEW_FILES = 3
_PREVIEW_LINES = 10
_PREVIEW_BYTES = 65536
_BINARY_PROBE = 8192
_RENAME_NOREPLACE = 1
_renameat2 = None
_renameat2_ready = False


def sessions_root(environ: Mapping[str, str], home: Path) -> Path:
    """Return the session root. A relative override is ignored."""
    raw = environ.get("NEOVIM_HARNESS_SESSIONS")
    if raw:
        candidate = Path(raw)
        if candidate.is_absolute():
            return candidate
    return home / ".neovim.harness" / "sessions"


def slugify(raw: str) -> str | None:
    """Turn a session title into a single path segment."""
    cleaned: list[str] = []
    for character in raw.strip():
        if character.isspace():
            cleaned.append("-")
        elif character.isalnum() or character == "-":
            cleaned.append(character)
    slug = re.sub(r"-{2,}", "-", "".join(cleaned)).strip("-")
    if not slug:
        return None
    slug = slug[:_SLUG_CHARS].rstrip("-")
    while slug and len(slug.encode("utf-8")) > _SLUG_BYTES:
        slug = slug[:-1]
    slug = slug.rstrip("-")
    return slug or None


def is_session_directory(name: str) -> bool:
    return _SESSION_NAME.fullmatch(name) is not None


def session_document(directory: Path) -> Path | None:
    """Return the clipboard markdown file when it is a regular file."""
    candidate = directory / f"{directory.name}.md"
    try:
        info = candidate.lstat()
    except OSError:
        return None
    if not stat.S_ISREG(info.st_mode):
        return None
    return candidate


@dataclass(frozen=True)
class SessionEntry:
    directory: Path
    label: str
    modified: str
    sort_key: float
    preview: str

    def as_json(self) -> dict[str, str]:
        return {
            "directory": str(self.directory),
            "label": self.label,
            "modified": self.modified,
            "preview": self.preview,
        }


class SessionStore:
    """Create ``doc-YYMMDDHHMMSS`` directories and a mode-0600 Markdown file."""

    def __init__(self, root: Path, clock: Callable[[], datetime] | None = None) -> None:
        self._root = root
        self._clock = clock or datetime.now

    @property
    def root(self) -> Path:
        return self._root

    def create(self) -> Path:
        self._root.mkdir(parents=True, exist_ok=True)
        directory = self._claim(self._clock().strftime("%y%m%d%H%M%S"))
        path = directory / f"{directory.name}.md"
        path.touch()
        path.chmod(0o600)
        return path

    def create_named(self, slug: str) -> Path:
        """Create an empty named directory. The caller owns ``git init``."""
        self._root.mkdir(parents=True, exist_ok=True)
        prefix = f"doc-{self._clock().strftime('%y%m%d%H%M%S')}"
        return self._claim_named(prefix, slug)

    def rename(
        self,
        directory: Path,
        slug: str,
        *,
        document_stem: str | None = None,
    ) -> Path:
        """Keep the date prefix and replace the title. The directory must exist."""
        if directory.resolve().parent != self._root.resolve():
            raise ValueError(directory.name)
        previous_name = document_stem or directory.name
        prefix = _stamp_prefix(directory.name)
        number = 1
        while True:
            target = self._root / _named(prefix, slug, number)
            if _same_directory(target, directory):
                _move_clipboard_file(directory, previous_name)
                return directory
            if target.exists():
                number = 2 if number == 1 else number + 1
                continue
            blocker = _blocking_document(directory, previous_name, target.name)
            if blocker is not None:
                raise ValueError(blocker)
            try:
                _rename_exclusive(directory, target)
            except OSError as exc:
                if _name_taken(exc):
                    number = 2 if number == 1 else number + 1
                    continue
                raise
            try:
                _move_clipboard_file(target, previous_name)
            except (OSError, ValueError) as exc:
                if not _restore_directory(target, directory):
                    exc.surviving_directory = target  # type: ignore[attr-defined]
                raise
            return target

    def catalog(self) -> list[SessionEntry]:
        """Newest regular-file activity first."""
        if not self._root.is_dir():
            return []
        entries: list[SessionEntry] = []
        for child in self._root.iterdir():
            if _is_symlink(child) is not False or _is_dir(child) is not True:
                continue
            if not is_session_directory(child.name):
                continue
            if not _encodes_as_utf8(str(child)):
                continue
            newest, preview = _activity(child)
            entries.append(
                SessionEntry(
                    directory=child,
                    label=child.name,
                    modified=_format_mtime(newest),
                    sort_key=newest,
                    preview=preview,
                )
            )
        entries.sort(key=lambda entry: (entry.sort_key, entry.label), reverse=True)
        return entries

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

    def _claim_named(self, prefix: str, slug: str) -> Path:
        number = 1
        while True:
            directory = self._root / _named(prefix, slug, number)
            try:
                directory.mkdir(parents=False, exist_ok=False)
            except FileExistsError:
                number = 2 if number == 1 else number + 1
                continue
            return directory


def _named(prefix: str, slug: str, number: int) -> str:
    stem = f"{prefix}--{slug}"
    if number == 1:
        return stem
    return f"{stem}-{number}"


def _stamp_prefix(name: str) -> str:
    match = _STAMP.match(name)
    if match is None:
        raise ValueError(name)
    return match.group(1)


def _format_mtime(timestamp: float) -> str:
    """Local time, or a fallback when the timestamp cannot be formatted."""
    try:
        return datetime.fromtimestamp(timestamp).strftime("%Y-%m-%d %H:%M")
    except (OSError, OverflowError, ValueError):
        return _UNFORMATTED_MTIME


def _same_directory(left: Path, right: Path) -> bool:
    if left == right:
        return True
    try:
        return left.resolve() == right.resolve()
    except OSError:
        return False


def _blocking_document(directory: Path, previous_name: str, new_name: str) -> Path | None:
    """The path that already occupies ``<new_name>.md``, when the note cannot move."""
    source = directory / f"{previous_name}.md"
    destination = directory / f"{new_name}.md"
    if source == destination:
        return None
    try:
        info = source.lstat()
    except OSError:
        return None
    if not stat.S_ISREG(info.st_mode):
        return None
    try:
        destination.lstat()
    except OSError:
        return None
    return destination


def _restore_directory(target: Path, original: Path) -> bool:
    """Move ``target`` back. False means ``target`` is the folder that still exists."""
    try:
        _rename_exclusive(target, original)
    except OSError as exc:
        logger.error("Could not restore the session folder: %s", exc)
        return False
    return True


def _name_taken(exc: OSError) -> bool:
    return exc.errno in (errno.EEXIST, errno.ENOTEMPTY) or isinstance(exc, FileExistsError)


def _rename_exclusive(source: Path, target: Path) -> None:
    """Rename a file or directory. An existing target raises ``EEXIST`` or ``ENOTEMPTY``."""
    renamer = _load_renameat2()
    if renamer is None:
        if _name_exists(target):
            raise FileExistsError(
                errno.EEXIST,
                os.strerror(errno.EEXIST),
                str(target),
            )
        source.rename(target)
        return
    source_dir = os.open(source.parent, os.O_RDONLY | os.O_DIRECTORY)
    try:
        target_dir = os.open(target.parent, os.O_RDONLY | os.O_DIRECTORY)
        try:
            result = renamer(
                source_dir,
                os.fsencode(source.name),
                target_dir,
                os.fsencode(target.name),
                _RENAME_NOREPLACE,
            )
        finally:
            os.close(target_dir)
    finally:
        os.close(source_dir)
    if result == 0:
        return
    error_number = ctypes.get_errno()
    raise OSError(error_number, os.strerror(error_number), str(source), None, str(target))


def _name_exists(target: Path) -> bool:
    """True when ``target`` is already a file, directory, or symlink."""
    try:
        target.lstat()
    except OSError:
        return False
    return True


def _load_renameat2() -> Callable[..., int] | None:
    global _renameat2, _renameat2_ready
    if _renameat2_ready:
        return _renameat2
    _renameat2_ready = True
    libc = ctypes.CDLL(None, use_errno=True)
    function = getattr(libc, "renameat2", None)
    if function is None:
        return None
    function.argtypes = [
        ctypes.c_int,
        ctypes.c_char_p,
        ctypes.c_int,
        ctypes.c_char_p,
        ctypes.c_uint,
    ]
    function.restype = ctypes.c_int
    _renameat2 = function
    return function


def _move_clipboard_file(directory: Path, previous_name: str) -> None:
    """Rename ``<old directory name>.md`` so the stem matches ``directory``."""
    blocker = _blocking_document(directory, previous_name, directory.name)
    if blocker is not None:
        raise ValueError(blocker)
    source = directory / f"{previous_name}.md"
    destination = directory / f"{directory.name}.md"
    if source == destination:
        return
    try:
        info = source.lstat()
    except OSError:
        return
    if not stat.S_ISREG(info.st_mode):
        return
    _rename_exclusive(source, destination)


def _activity(directory: Path) -> tuple[float, str]:
    files: list[tuple[float, str, Path]] = []
    for current, dir_names, file_names in os.walk(directory):
        kept: list[str] = []
        for name in dir_names:
            if name in _SKIP_DIRECTORIES:
                continue
            path = Path(current) / name
            if _is_symlink(path) is not False or _is_dir(path) is not True:
                continue
            kept.append(name)
        dir_names[:] = kept
        for name in file_names:
            if name == ".git":
                continue
            path = Path(current) / name
            try:
                info = path.lstat()
            except OSError:
                continue
            if not stat.S_ISREG(info.st_mode):
                continue
            files.append((info.st_mtime, path.relative_to(directory).as_posix(), path))
    if files:
        newest = max(item[0] for item in files)
    else:
        try:
            newest = directory.stat().st_mtime
        except OSError:
            newest = 0.0
    files.sort(key=lambda item: (-item[0], item[1]))
    chosen: list[tuple[str, list[str]]] = []
    for _mtime, relative, path in files:
        if len(chosen) == _PREVIEW_FILES:
            break
        if not _encodes_as_utf8(relative):
            continue
        lines = _text_preview(path)
        if lines is None:
            continue
        chosen.append((relative, lines))
    if not chosen:
        return newest, "No text files."
    blocks = [
        relative if not lines else f"{relative}\n" + "\n".join(lines)
        for relative, lines in chosen
    ]
    return newest, "\n\n".join(blocks)


def _encodes_as_utf8(text: str) -> bool:
    try:
        text.encode("utf-8")
    except UnicodeEncodeError:
        return False
    return True


def _is_dir(path: Path) -> bool | None:
    try:
        return path.is_dir()
    except OSError:
        return None


def _is_symlink(path: Path) -> bool | None:
    try:
        return path.is_symlink()
    except OSError:
        return None


def _text_preview(path: Path) -> list[str] | None:
    blob = _read_preview(path)
    if blob is None:
        return None
    text = _decode_text(blob)
    if text is None:
        return None
    return text.splitlines()[:_PREVIEW_LINES]


def _read_preview(path: Path) -> bytes | None:
    """Read a text prefix. A NUL in the first 8 KiB stops the read."""
    flags = os.O_RDONLY | os.O_NONBLOCK
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    try:
        descriptor = os.open(path, flags)
    except OSError:
        return None
    try:
        probe = _read_amount(descriptor, _BINARY_PROBE)
        if probe is None or b"\0" in probe:
            return None
        blob = probe
        while len(blob) < _PREVIEW_BYTES and blob.count(b"\n") < _PREVIEW_LINES:
            piece = _read_amount(
                descriptor, min(_BINARY_PROBE, _PREVIEW_BYTES - len(blob))
            )
            if piece is None:
                return None
            if not piece:
                break
            blob += piece
        return _through_line(blob, _PREVIEW_LINES)
    finally:
        os.close(descriptor)


def _read_amount(descriptor: int, amount: int) -> bytes | None:
    chunks: list[bytes] = []
    remaining = amount
    while remaining > 0:
        try:
            piece = os.read(descriptor, remaining)
        except OSError:
            return None
        if not piece:
            break
        chunks.append(piece)
        remaining -= len(piece)
    return b"".join(chunks)


def _through_line(blob: bytes, count: int) -> bytes:
    index = -1
    for _ in range(count):
        index = blob.find(b"\n", index + 1)
        if index < 0:
            return blob
    return blob[: index + 1]


def _decode_text(blob: bytes) -> str | None:
    try:
        return blob.decode("utf-8")
    except UnicodeDecodeError as error:
        truncated = (
            len(blob) == _PREVIEW_BYTES
            and error.end == len(blob)
            and error.reason == "unexpected end of data"
        )
        if not truncated:
            return None
        try:
            return blob[: error.start].decode("utf-8")
        except UnicodeDecodeError:
            return None
