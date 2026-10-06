from __future__ import annotations

import errno
import json
import logging
import os
from datetime import datetime
from pathlib import Path

import pytest

from neovim_harness.sessions import (
    SessionStore,
    _PREVIEW_BYTES,
    _rename_exclusive,
    session_document,
    sessions_root,
    slugify,
)

_WHEN = datetime(2026, 10, 5, 14, 18, 3)
_STAMP = "doc-261005141803"


def _store(root: Path) -> SessionStore:
    return SessionStore(root, clock=lambda: _WHEN)


def test_session_document_rejects_a_symlink(tmp_path: Path) -> None:
    directory = tmp_path / "doc-261005141803"
    directory.mkdir()
    target = tmp_path / "elsewhere.md"
    target.write_text("secret\n", encoding="utf-8")
    link = directory / f"{directory.name}.md"
    link.symlink_to(target)
    assert session_document(directory) is None
    link.unlink()
    link.write_text("body\n", encoding="utf-8")
    assert session_document(directory) == link


def test_session_name_and_mode(tmp_path: Path) -> None:
    previous = os.umask(0)
    try:
        path = _store(tmp_path).create()
    finally:
        os.umask(previous)
    assert path.parent.name == _STAMP
    assert path.name == f"{_STAMP}.md"
    assert path.stat().st_mode & 0o777 == 0o600
    assert path.read_text(encoding="utf-8") == ""


def test_collision_suffix_keeps_the_existing_directory(tmp_path: Path) -> None:
    store = _store(tmp_path)
    first = store.create()
    (first.parent / "keep").write_text("stay", encoding="utf-8")
    second = store.create()
    third = store.create()
    assert second.parent.name == f"{_STAMP}-2"
    assert second.name == f"{_STAMP}-2.md"
    assert third.parent.name == f"{_STAMP}-3"
    assert third.name == f"{_STAMP}-3.md"
    assert (first.parent / "keep").read_text(encoding="utf-8") == "stay"
    assert first.exists()


def test_mkdir_race_uses_the_next_suffix(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    real_mkdir = Path.mkdir
    raised = False

    def flaky_mkdir(
        self: Path,
        mode: int = 0o777,
        parents: bool = False,
        exist_ok: bool = False,
    ) -> None:
        nonlocal raised
        if self.name == _STAMP and not raised:
            raised = True
            raise FileExistsError(self)
        real_mkdir(self, mode, parents, exist_ok)

    monkeypatch.setattr(Path, "mkdir", flaky_mkdir)
    path = _store(tmp_path).create()
    assert raised
    assert not (tmp_path / _STAMP).exists()
    assert path.parent.name == f"{_STAMP}-2"
    assert path.name == f"{_STAMP}-2.md"
    assert path.stat().st_mode & 0o777 == 0o600


def test_collision_fills_the_first_free_suffix(tmp_path: Path) -> None:
    (tmp_path / _STAMP).mkdir()
    (tmp_path / f"{_STAMP}-3").mkdir()
    path = _store(tmp_path).create()
    assert path.parent.name == f"{_STAMP}-2"
    assert path.name == f"{_STAMP}-2.md"


def test_relative_override_is_ignored(tmp_path: Path) -> None:
    home = tmp_path / "home"
    assert sessions_root({"NEOVIM_HARNESS_SESSIONS": "relative/path"}, home) == (
        home / ".neovim.harness" / "sessions"
    )
    assert sessions_root({"NEOVIM_HARNESS_SESSIONS": ""}, home) == (
        home / ".neovim.harness" / "sessions"
    )
    assert sessions_root({}, home) == home / ".neovim.harness" / "sessions"


def test_slug_keeps_letters_and_drops_separators() -> None:
    assert slugify("Починить логин") == "Починить-логин"
    assert slugify("  hello   world ") == "hello-world"
    assert slugify("Hello, world!") == "Hello-world"
    assert slugify("Foo--Bar") == "Foo-Bar"
    assert slugify("a/b") == "ab"
    assert slugify("!!!") is None
    assert slugify("   ") is None
    assert slugify("a" * 100) == "a" * 80
    long = slugify("字" * 80)
    assert long is not None
    assert len(long.encode("utf-8")) <= 200


def test_named_directory_has_no_file_and_collides_on_the_title(tmp_path: Path) -> None:
    store = _store(tmp_path)
    first = store.create_named("Fix-login")
    second = store.create_named("Fix-login")
    assert first.name == f"{_STAMP}--Fix-login"
    assert second.name == f"{_STAMP}--Fix-login-2"
    assert list(first.iterdir()) == []
    assert list(second.iterdir()) == []


def test_rename_keeps_the_date_and_avoids_an_existing_title(tmp_path: Path) -> None:
    store = _store(tmp_path)
    unnamed = store.create().parent
    taken = store.create_named("Later")
    renamed = store.rename(unnamed, "Later")
    collision = store.rename(store.create().parent, "Later")
    assert renamed.name == f"{_STAMP}--Later-2"
    assert taken.name == f"{_STAMP}--Later"
    assert collision.name == f"{_STAMP}--Later-3"
    assert (renamed / f"{renamed.name}.md").is_file()
    assert not (renamed / f"{_STAMP}.md").exists()
    same = store.rename(renamed, "Later")
    assert same == renamed
    assert (same / f"{same.name}.md").is_file()


def test_rename_retries_when_the_target_appears(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = _store(tmp_path)
    directory = store.create().parent
    real_rename = _rename_exclusive
    raised = False

    def flaky_rename(source: Path, target: Path) -> None:
        nonlocal raised
        if not raised and target.name.endswith("--Later"):
            raised = True
            raise FileExistsError(target)
        real_rename(source, target)

    monkeypatch.setattr("neovim_harness.sessions._rename_exclusive", flaky_rename)
    renamed = store.rename(directory, "Later")
    assert raised
    assert renamed.name == f"{_STAMP}--Later-2"
    assert (renamed / f"{renamed.name}.md").is_file()
    assert not (renamed / f"{_STAMP}.md").exists()


def test_rename_leaves_an_existing_empty_directory(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = _store(tmp_path)
    document = store.create()
    occupant = tmp_path / f"{_STAMP}--Later"
    occupant.mkdir()
    real_exists = Path.exists
    hidden = False

    def hide_occupant_once(self: Path) -> bool:
        nonlocal hidden
        if self == occupant and not hidden:
            hidden = True
            return False
        return real_exists(self)

    monkeypatch.setattr(Path, "exists", hide_occupant_once)
    renamed = store.rename(document.parent, "Later")
    assert hidden
    assert occupant.is_dir()
    assert list(occupant.iterdir()) == []
    assert renamed.name == f"{_STAMP}--Later-2"
    assert (renamed / f"{renamed.name}.md").is_file()
    assert not document.exists()


def test_rename_fallback_does_not_replace_an_existing_name(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("neovim_harness.sessions._load_renameat2", lambda: None)
    source = tmp_path / "source"
    source.mkdir()
    (source / "keep.txt").write_text("kept", encoding="utf-8")
    occupied = tmp_path / "occupied"
    occupied.mkdir()
    with pytest.raises(FileExistsError):
        _rename_exclusive(source, occupied)
    assert list(occupied.iterdir()) == []
    assert (source / "keep.txt").read_text(encoding="utf-8") == "kept"

    link = tmp_path / "link"
    link.symlink_to("missing")
    with pytest.raises(FileExistsError):
        _rename_exclusive(source, link)
    assert link.is_symlink()
    assert os.readlink(link) == "missing"
    assert source.is_dir()

    destination = tmp_path / "free"
    _rename_exclusive(source, destination)
    assert not source.exists()
    assert (destination / "keep.txt").read_text(encoding="utf-8") == "kept"

    sessions = tmp_path / "sessions"
    store = _store(sessions)
    document = store.create()
    occupant = sessions / f"{_STAMP}--Later"
    occupant.mkdir()
    real_exists = Path.exists
    hidden = False

    def hide_occupant_once(self: Path) -> bool:
        nonlocal hidden
        if self == occupant and not hidden:
            hidden = True
            return False
        return real_exists(self)

    monkeypatch.setattr(Path, "exists", hide_occupant_once)
    renamed = store.rename(document.parent, "Later")
    assert hidden
    assert occupant.is_dir()
    assert list(occupant.iterdir()) == []
    assert renamed.name == f"{_STAMP}--Later-2"
    assert (renamed / f"{renamed.name}.md").is_file()
    assert not document.exists()


def test_rename_rejects_a_directory_without_a_date(tmp_path: Path) -> None:
    store = _store(tmp_path)
    directory = tmp_path / "notes"
    directory.mkdir()
    with pytest.raises(ValueError):
        store.rename(directory, "Later")


def test_rename_stops_when_the_new_document_name_is_a_directory(tmp_path: Path) -> None:
    store = _store(tmp_path)
    document = store.create()
    directory = document.parent
    blocker = directory / f"{_STAMP}--Later.md"
    blocker.mkdir()
    with pytest.raises(ValueError) as caught:
        store.rename(directory, "Later")
    assert caught.value.args == (blocker,)
    assert directory.is_dir()
    assert document.is_file()
    assert blocker.is_dir()
    assert not (tmp_path / f"{_STAMP}--Later").exists()


def test_rename_stops_when_the_new_document_name_is_a_file(tmp_path: Path) -> None:
    store = _store(tmp_path)
    document = store.create()
    directory = document.parent
    blocker = directory / f"{_STAMP}--Later.md"
    blocker.write_text("keep", encoding="utf-8")
    with pytest.raises(ValueError) as caught:
        store.rename(directory, "Later")
    assert caught.value.args == (blocker,)
    assert directory.is_dir()
    assert document.read_text(encoding="utf-8") == ""
    assert blocker.read_text(encoding="utf-8") == "keep"
    assert not (tmp_path / f"{_STAMP}--Later").exists()


def test_short_non_utf8_files_do_not_take_a_preview_slot(tmp_path: Path) -> None:
    directory = tmp_path / "doc-261005141803"
    directory.mkdir()
    broken = directory / "hello.bin"
    broken.write_bytes(b"hello\xff")
    os.utime(broken, (5_000, 5_000))
    latin = directory / "latin.bin"
    latin.write_bytes(b"\xff\xfe\xfd")
    os.utime(latin, (4_000, 4_000))
    notes = directory / "notes.txt"
    notes.write_text("kept\n", encoding="utf-8")
    os.utime(notes, (1_000, 1_000))
    catalog = SessionStore(tmp_path).catalog()
    assert catalog[0].preview == "notes.txt\nkept"
    assert "hello.bin" not in catalog[0].preview
    assert "hello" not in catalog[0].preview
    assert "latin.bin" not in catalog[0].preview


def test_rename_of_a_collision_uses_the_original_date(tmp_path: Path) -> None:
    store = _store(tmp_path)
    store.create()
    second = store.create().parent
    renamed = store.rename(second, "Notes")
    assert second.name == f"{_STAMP}-2"
    assert renamed.name == f"{_STAMP}--Notes"
    assert (renamed / f"{renamed.name}.md").is_file()
    assert not (renamed / f"{_STAMP}-2.md").exists()


def test_gitfile_is_not_a_preview_or_the_sort_time(tmp_path: Path) -> None:
    directory = tmp_path / "doc-261005141803"
    directory.mkdir()
    gitfile = directory / ".git"
    gitfile.write_text("gitdir: /elsewhere/git\n", encoding="utf-8")
    os.utime(gitfile, (9_000, 9_000))
    notes = directory / "notes.txt"
    notes.write_text("kept\n", encoding="utf-8")
    os.utime(notes, (1_000, 1_000))
    catalog = SessionStore(tmp_path).catalog()
    assert len(catalog) == 1
    assert catalog[0].sort_key == 1_000
    assert catalog[0].preview == "notes.txt\nkept"
    assert "gitdir" not in catalog[0].preview
    assert ".git" not in catalog[0].preview


def test_catalog_orders_by_newest_text_and_previews_ten_lines(tmp_path: Path) -> None:
    older = tmp_path / "doc-261005141801"
    newer = tmp_path / "doc-261005141802--Fix-login"
    skipped = tmp_path / "notes"
    linked = tmp_path / "doc-261005141809"
    older.mkdir()
    newer.mkdir()
    skipped.mkdir()
    linked.symlink_to(older, target_is_directory=True)
    old_file = older / "old.txt"
    old_file.write_text("old\n", encoding="utf-8")
    os.utime(old_file, (1_000, 1_000))
    binary = newer / "blob.bin"
    binary.write_bytes(b"ok\0no")
    os.utime(binary, (5_000, 5_000))
    link = newer / "outside.txt"
    link.symlink_to(old_file)
    git_dir = newer / ".git"
    git_dir.mkdir()
    secret = git_dir / "secret.txt"
    secret.write_text("hidden\n", encoding="utf-8")
    os.utime(secret, (9_000, 9_000))
    lines = "\n".join(f"line {number}" for number in range(1, 13)) + "\n"
    fresh = newer / "notes" / "fresh.txt"
    fresh.parent.mkdir()
    fresh.write_text(lines, encoding="utf-8")
    os.utime(fresh, (4_000, 4_000))
    middle = newer / "middle.txt"
    middle.write_text("middle\n", encoding="utf-8")
    os.utime(middle, (3_000, 3_000))
    third = newer / "third.txt"
    third.write_text("third\n", encoding="utf-8")
    os.utime(third, (2_000, 2_000))
    fourth = newer / "fourth.txt"
    fourth.write_text("fourth\n", encoding="utf-8")
    os.utime(fourth, (1_500, 1_500))
    latin = newer / "latin.bin"
    latin.write_bytes(b"\xff\xfe\xfd")
    os.utime(latin, (100, 100))
    split = newer / "split.txt"
    split.write_bytes(b"a" * 65535 + "я".encode())
    os.utime(split, (3_500, 3_500))
    nested = newer / "linked-dir"
    nested.symlink_to(older, target_is_directory=True)

    catalog = SessionStore(tmp_path).catalog()
    assert [entry.directory for entry in catalog] == [newer, older]
    assert "notes/fresh.txt" in catalog[0].preview
    assert "line 10" in catalog[0].preview
    assert "line 11" not in catalog[0].preview
    assert "middle.txt" in catalog[0].preview
    assert "split.txt" in catalog[0].preview
    assert "third.txt" not in catalog[0].preview
    assert "fourth.txt" not in catalog[0].preview
    assert "hidden" not in catalog[0].preview
    assert "blob.bin" not in catalog[0].preview
    assert "outside.txt" not in catalog[0].preview
    assert "latin.bin" not in catalog[0].preview
    assert "split.txt" in catalog[0].preview
    assert "я" not in catalog[0].preview
    assert catalog[1].preview == "old.txt\nold"
    assert catalog[0].modified == datetime.fromtimestamp(5_000).strftime("%Y-%m-%d %H:%M")


def test_catalog_keeps_a_session_when_its_mtime_cannot_be_formatted(
    tmp_path: Path,
) -> None:
    huge = tmp_path / "doc-261005141803"
    huge.mkdir()
    notes = huge / "notes.txt"
    notes.write_text("kept\n", encoding="utf-8")
    os.utime(notes, (10**18, 10**18))
    mtime = notes.stat().st_mtime
    with pytest.raises((OSError, OverflowError, ValueError)):
        datetime.fromtimestamp(mtime)
    plain = tmp_path / "doc-261005141801"
    plain.mkdir()
    old = plain / "old.txt"
    old.write_text("old\n", encoding="utf-8")
    os.utime(old, (1_000, 1_000))

    catalog = SessionStore(tmp_path).catalog()
    assert [entry.directory for entry in catalog] == [huge, plain]
    assert catalog[0].sort_key == mtime
    assert catalog[0].modified == "unknown"
    assert catalog[0].preview == "notes.txt\nkept"
    assert catalog[1].modified == datetime.fromtimestamp(1_000).strftime("%Y-%m-%d %H:%M")


def test_empty_named_directory_reports_no_text_files(tmp_path: Path) -> None:
    directory = tmp_path / "doc-261005141803--Empty"
    directory.mkdir()
    os.utime(directory, (1_700, 1_700))
    catalog = SessionStore(tmp_path).catalog()
    assert catalog[0].preview == "No text files."
    assert catalog[0].sort_key == directory.stat().st_mtime


def test_rename_accepts_a_resolved_directory_under_a_symlinked_root(tmp_path: Path) -> None:
    real = tmp_path / "real"
    real.mkdir()
    link = tmp_path / "link"
    link.symlink_to(real, target_is_directory=True)
    document = _store(link).create()
    renamed = _store(link).rename(document.parent.resolve(), "Later")
    assert renamed == link / f"{_STAMP}--Later"
    assert (renamed / f"{renamed.name}.md").is_file()
    assert (renamed / f"{renamed.name}.md").stat().st_mode & 0o777 == 0o600
    assert not document.exists()


def test_catalog_skips_fifos_and_stops_after_three_text_files(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import socket

    directory = tmp_path / "doc-261005141803"
    directory.mkdir()
    pipe = directory / "pipe"
    os.mkfifo(pipe)
    os.utime(pipe, (9_000, 9_000))
    sock_path = directory / "sock"
    sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    sock.bind(os.fspath(sock_path))
    binary = directory / "blob.bin"
    binary.write_bytes(b"\0bin")
    os.utime(binary, (5_000, 5_000))
    for name, mtime, text in (
        ("a.txt", 4_000, "alpha\n"),
        ("b.txt", 3_000, "beta\n"),
        ("c.txt", 2_000, "gamma\n"),
    ):
        path = directory / name
        path.write_text(text, encoding="utf-8")
        os.utime(path, (mtime, mtime))
    older = directory / "older.txt"
    older.write_text("old\n", encoding="utf-8")
    os.utime(older, (1_000, 1_000))
    opened: list[str] = []
    real_open = os.open

    def spy(path: str | os.PathLike[str], flags: int, *args: object, **kwargs: object) -> int:
        opened.append(Path(path).name)
        return real_open(path, flags, *args, **kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr(os, "open", spy)
    try:
        catalog = SessionStore(tmp_path).catalog()
    finally:
        sock.close()
    assert len(catalog) == 1
    assert catalog[0].sort_key == 5_000
    assert "a.txt" in catalog[0].preview
    assert "b.txt" in catalog[0].preview
    assert "c.txt" in catalog[0].preview
    assert "older.txt" not in catalog[0].preview
    assert "pipe" not in catalog[0].preview
    assert "pipe" not in opened
    assert "sock" not in opened
    assert "older.txt" not in opened
    assert "blob.bin" in opened
    assert "a.txt" in opened


def test_non_utf8_paths_stay_out_of_the_catalog_json(tmp_path: Path) -> None:
    directory = tmp_path / "doc-261005141803"
    directory.mkdir()
    bad = directory / "a\udcffb.txt"
    descriptor = os.open(bad, os.O_CREAT | os.O_WRONLY, 0o600)
    os.write(descriptor, b"secret\n")
    os.close(descriptor)
    os.utime(bad, (5_000, 5_000))
    notes = directory / "notes.txt"
    notes.write_text("kept\n", encoding="utf-8")
    os.utime(notes, (1_000, 1_000))

    rooted = tmp_path / "root\udcff"
    rooted.mkdir()
    hidden = rooted / "doc-261005141809"
    hidden.mkdir()
    (hidden / "notes.txt").write_text("hidden\n", encoding="utf-8")

    listed = SessionStore(tmp_path).catalog()
    assert [entry.directory for entry in listed] == [directory]
    assert listed[0].sort_key == 5_000
    assert listed[0].preview == "notes.txt\nkept"
    encoded = json.dumps(
        [entry.as_json() for entry in listed],
        ensure_ascii=False,
    ).encode("utf-8")
    assert b"notes.txt" in encoded
    assert b"secret" not in encoded

    omitted = SessionStore(rooted).catalog()
    assert json.dumps(
        [entry.as_json() for entry in omitted],
        ensure_ascii=False,
    ).encode("utf-8") == b"[]"


def test_unreadable_directory_mtime_does_not_abort_the_catalog(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    good = tmp_path / "doc-261005141803"
    empty = tmp_path / "doc-261005141804"
    good.mkdir()
    empty.mkdir()
    (good / "notes.txt").write_text("kept\n", encoding="utf-8")
    real_stat = Path.stat

    def stat(self: Path, *args: object, **kwargs: object) -> os.stat_result:
        if self == empty:
            raise OSError("unreadable directory")
        return real_stat(self, *args, **kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr(Path, "stat", stat)
    catalog = SessionStore(tmp_path).catalog()
    assert {entry.directory for entry in catalog} == {good, empty}
    broken = next(entry for entry in catalog if entry.directory == empty)
    assert broken.sort_key == 0
    assert broken.preview == "No text files."


def test_catalog_of_a_missing_root_is_empty(tmp_path: Path) -> None:
    assert SessionStore(tmp_path / "missing").catalog() == []


def test_unreadable_entries_do_not_abort_the_catalog(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    good = tmp_path / "doc-261005141803"
    blocked = tmp_path / "doc-261005141804"
    good.mkdir()
    blocked.mkdir()
    notes = good / "notes.txt"
    notes.write_text("kept\n", encoding="utf-8")
    visible = good / "visible.txt"
    visible.write_text("skip me\n", encoding="utf-8")
    locked = good / "locked"
    locked.mkdir()
    (locked / "hidden.txt").write_text("hidden\n", encoding="utf-8")
    (blocked / "secret.txt").write_text("nope\n", encoding="utf-8")
    real_is_dir = Path.is_dir
    real_is_symlink = Path.is_symlink
    real_lstat = Path.lstat

    def is_dir(self: Path) -> bool:
        if self == blocked:
            raise OSError("unreadable directory")
        return real_is_dir(self)

    def is_symlink(self: Path) -> bool:
        if self == locked:
            raise OSError("unreadable symlink check")
        return real_is_symlink(self)

    def lstat(self: Path):
        if self == visible:
            raise OSError("unreadable file")
        return real_lstat(self)

    monkeypatch.setattr(Path, "is_dir", is_dir)
    monkeypatch.setattr(Path, "is_symlink", is_symlink)
    monkeypatch.setattr(Path, "lstat", lstat)
    catalog = SessionStore(tmp_path).catalog()
    assert [entry.directory for entry in catalog] == [good]
    assert catalog[0].preview == "notes.txt\nkept"
    assert "hidden" not in catalog[0].preview
    assert "visible" not in catalog[0].preview
    assert "secret" not in catalog[0].preview


def test_preview_probes_nul_before_reading_further_and_stops_at_ten_lines(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    directory = tmp_path / "doc-261005141803"
    directory.mkdir()
    binary = directory / "binary.bin"
    binary.write_bytes(b"\0" + b"z" * 100_000)
    os.utime(binary, (5_000, 5_000))
    short = "".join(f"line {number}\n" for number in range(1, 11))
    long_text = directory / "long.txt"
    long_text.write_text(short + ("y" * 100_000), encoding="utf-8")
    os.utime(long_text, (4_000, 4_000))
    wide = directory / "wide.txt"
    wide.write_bytes(b"ok\n" * 9 + b"a" * 20_000 + b"\n" + b"TAIL" * 30_000)
    os.utime(wide, (3_000, 3_000))

    reads: list[tuple[str, int]] = []
    names: dict[int, str] = {}
    real_open = os.open
    real_read = os.read
    real_close = os.close

    def spy_open(path: str | os.PathLike[str], flags: int, *args: object, **kwargs: object) -> int:
        descriptor = real_open(path, flags, *args, **kwargs)  # type: ignore[arg-type]
        names[descriptor] = Path(path).name
        return descriptor

    def spy_read(descriptor: int, size: int) -> bytes:
        chunk = real_read(descriptor, size)
        reads.append((names.get(descriptor, "?"), len(chunk)))
        return chunk

    def spy_close(descriptor: int) -> None:
        names.pop(descriptor, None)
        real_close(descriptor)

    monkeypatch.setattr(os, "open", spy_open)
    monkeypatch.setattr(os, "read", spy_read)
    monkeypatch.setattr(os, "close", spy_close)
    catalog = SessionStore(tmp_path).catalog()
    by_name = {name: sum(size for label, size in reads if label == name) for name, _size in reads}
    assert by_name["binary.bin"] <= 8192
    assert by_name["long.txt"] <= 8192
    assert 8192 < by_name["wide.txt"] < 65536
    assert "line 10" in catalog[0].preview
    assert "line 11" not in catalog[0].preview
    assert "yyyy" not in catalog[0].preview
    assert "wide.txt" in catalog[0].preview
    assert "TAIL" not in catalog[0].preview
    assert "binary.bin" not in catalog[0].preview


def test_exact_size_invalid_byte_is_not_previewed(tmp_path: Path) -> None:
    directory = tmp_path / "doc-261005141803"
    directory.mkdir()
    broken = directory / "broken.txt"
    broken.write_bytes(b"a" * (_PREVIEW_BYTES - 1) + b"\xff")
    notes = directory / "notes.txt"
    notes.write_text("kept\n", encoding="utf-8")
    os.utime(broken, (5_000, 5_000))
    os.utime(notes, (1_000, 1_000))
    catalog = SessionStore(tmp_path).catalog()
    assert catalog[0].preview == "notes.txt\nkept"
    assert "broken.txt" not in catalog[0].preview


def test_failed_document_rename_restores_the_directory(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = _store(tmp_path)
    document = store.create()
    directory = document.parent
    real_exclusive = _rename_exclusive

    def boom(source: Path, target: Path) -> None:
        if source.suffix == ".md":
            raise OSError("cannot rename document")
        real_exclusive(source, target)

    monkeypatch.setattr("neovim_harness.sessions._rename_exclusive", boom)
    with pytest.raises(OSError, match="cannot rename document"):
        store.rename(directory, "Later")
    assert directory.is_dir()
    assert document.is_file()
    assert document.read_text(encoding="utf-8") == ""
    assert not (tmp_path / f"{_STAMP}--Later").exists()


def test_rename_does_not_replace_an_existing_markdown_file(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The occupancy check can miss a file that appears before the rename."""
    store = _store(tmp_path)
    document = store.create()
    document.write_text("notes", encoding="utf-8")
    directory = document.parent
    occupant = directory / f"{_STAMP}--Later.md"
    occupant.write_text("keep", encoding="utf-8")
    monkeypatch.setattr(
        "neovim_harness.sessions._blocking_document",
        lambda *_args, **_kwargs: None,
    )
    with pytest.raises(OSError) as caught:
        store.rename(directory, "Later")
    assert caught.value.errno == errno.EEXIST
    assert directory.is_dir()
    assert document.read_text(encoding="utf-8") == "notes"
    assert occupant.read_text(encoding="utf-8") == "keep"
    assert not (tmp_path / f"{_STAMP}--Later").exists()


def test_failed_restore_is_logged(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    store = _store(tmp_path)
    document = store.create()
    directory = document.parent
    real_exclusive = _rename_exclusive

    def fail_restore(source: Path, target: Path) -> None:
        if source.suffix == ".md":
            raise OSError("cannot rename document")
        if target == directory and source != directory:
            raise OSError("cannot restore")
        real_exclusive(source, target)

    monkeypatch.setattr("neovim_harness.sessions._rename_exclusive", fail_restore)
    caplog.set_level(logging.ERROR)
    with pytest.raises(OSError, match="cannot rename document") as caught:
        store.rename(directory, "Later")
    assert caught.value.surviving_directory == tmp_path / f"{_STAMP}--Later"  # type: ignore[attr-defined]
    assert "Could not restore the session folder: cannot restore" in caplog.text


def test_rename_repairs_the_document_when_the_folder_already_matches(
    tmp_path: Path,
) -> None:
    store = _store(tmp_path)
    document = store.create()
    directory = document.parent
    target = tmp_path / f"{_STAMP}--Later"
    directory.rename(target)
    assert (target / f"{_STAMP}.md").is_file()
    repaired = store.rename(target, "Later", document_stem=_STAMP)
    assert repaired == target
    assert (target / f"{target.name}.md").read_text(encoding="utf-8") == ""
    assert not (target / f"{_STAMP}.md").exists()


def test_absolute_override_is_the_session_root(tmp_path: Path) -> None:
    custom = tmp_path / "custom"
    home = tmp_path / "home"
    root = sessions_root({"NEOVIM_HARNESS_SESSIONS": str(custom)}, home)
    path = SessionStore(root, clock=lambda: _WHEN).create()
    assert root == custom
    assert path.parent.parent == custom
    assert not home.exists()
