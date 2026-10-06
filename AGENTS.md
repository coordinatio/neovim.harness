# Agents

Neovim Harness is a Wayland clipboard editor and a launcher for longer Neovide sessions. Clipboard modes write a session file, open that file in Neovide, and copy the result back to the clipboard. Named sessions start from an empty directory with a git repository and do not touch the clipboard.

## Modes

| Command | Input | Ex commands after `--` | Clipboard MIME |
|---|---|---|---|
| `neovim.harness` | empty file | `+start` | `text/plain` |
| `neovim.harness -p` | `wl-paste --no-newline` | none | `text/plain` |
| `neovim.harness -m` | `wl-paste --no-newline -t text/html`, then Pandoc to GFM | `+colorscheme retrobox` | `text/html` |
| `neovim.harness -n` | empty file | `+start` then `+colorscheme retrobox` | `text/html` |
| `neovim.harness -s` / `--session` | `kdialog` title, then an empty directory and `git init -b main` | `+start` | none |
| `neovim.harness -r` / `--resume` | a session chosen in the picker | `+start` | none |

`-p`, `-m`, `-n`, `-s`, and `-r` are mutually exclusive. The default is new plain text. `-v` / `--verbose` enables debug logging. `--check-environment` only prints the requirement report.

## Invariants

- Clipboard sessions go to `~/.neovim.harness/sessions/doc-YYMMDDHHMMSS/doc-YYMMDDHHMMSS.md`. Nothing in the program deletes or expires them, so a later open of that folder can continue a `yapt.nvim` session.
- Named sessions go to `~/.neovim.harness/sessions/doc-YYMMDDHHMMSS--<title>/`. The title is asked with `kdialog --title "Neovim Harness" --inputbox <text>` before the directory exists. Cancel exits 0 and creates nothing. An unusable title asks again. No document file is created. `git init -b main` runs in that directory before Neovide, with no commit and no gitignore. If that git init fails, the new directory may be removed when it is empty or contains only `.git`.
- A title becomes a path segment: letters and digits stay, spaces become `-`, `--` collapses to `-`, and the segment is at most 80 characters and 200 UTF-8 bytes. The date prefix stays `doc-` plus 12 digits. A second directory with the same date and title gets `-2`, `-3`, …
- Resume lists directories matching that grammar, newest regular-file activity first. The picker is `neovide --no-fork -- --noplugin -i NONE -u NONE -c lua dofile(<resume.lua>)`, without the user config. Each row is one line: the recognizable name, the 12-digit date, then the modified time. The filter matches the full directory name. A space in the query matches a hyphen in that name, and repeated hyphens collapse to one. A query that is only hyphens after that normalization shows every session. Enter writes the directory and quits. If that write fails, the picker stays open, the user is notified, and a partial choice file is removed. Esc quits with no further launch. No sessions prints `No sessions to resume.` and exits 0. A path outside the session root, or a name that is not a session directory, opens an error dialog saying `Selected session is not in the session root.` A session name whose directory is gone says `Selected session no longer exists.` If the picker exits non-zero and writes no choice, the dialog says `Could not open the session list.` and the process exits 1. A chosen clipboard session opens `doc-….md` when that regular file exists. A symlink with that name is not the document. Resume does not run `git init` and does not use the clipboard.
- The picker preview is the first 10 lines of up to three newest text files. `.git`, `node_modules`, `__pycache__`, `.venv`, and `venv` are skipped. A NUL in the first 8 KiB, or text that is not UTF-8, is not previewed. Symlinks are not followed.
- `NEOVIM_HARNESS_SESSIONS` replaces that root only when the value is an absolute path. A relative value is ignored.
- If the timestamp directory exists, append `-2`, `-3`, … For a clipboard session the file stem matches the directory name, including the suffix. The session file mode is `0600`.
- Neovide's working directory is the session directory, not that directory's parent and not `$HOME`.
- A clipboard launch is `neovide --no-fork <file> --` plus the Ex commands, then `-c lua dofile(<rename.lua>)`. A named launch omits `<file>`. stdin, stdout, and stderr are `DEVNULL`. `NEOVIM_HARNESS_RENAME_FILE` is a path outside the session.
- `:HarnessRename` saves named buffers, writes the request, then quits, and removes the request if quit fails. If any loaded modified buffer has no file name, the editor stays open and reports `Save unnamed buffers in this session, then run :HarnessRename again.` The request is not written. If the write fails, the editor stays open, the user is notified, and the request file is removed. After Neovide exits, a usable title renames the directory, keeps the date prefix, renames `doc-….md` when that file is present so its stem matches, initializes git when `.git` is absent, and opens Neovide again. A successful rename does not write the clipboard on that exit or from the editor that opens afterward. An unusable title leaves the directory in place, logs the reason, and opens Neovide again. If the directory was renamed and cannot be moved back, the dialog says the folder is already at the new path and the previous name could not be restored, and the editor opens in the directory that still exists. A missing request file ends the loop.
- A missing `neovide` executable, or any other launch failure, exits 1. If the editor fails before it returns, the rename-request temporary directory is removed. A normal return still lets that request be read.
- If the session file is gone after the editor exits, do not write the clipboard.
- Plain modes write only `text/plain`. Formatted modes write only `text/html`. Named and resumed sessions do not read or write the clipboard.
- Clipboard read is `wl-paste --no-newline`, plus `-t <mime>` when a MIME type is requested. Clipboard write is `wl-copy`. Plain writes pass `-t text/plain` and formatted writes pass `-t text/html`. An empty MIME type omits `-t`.
- HTML to Markdown: `pandoc -f html -t gfm-raw_html --wrap=none --lua-filter=<backics.lua>`. Empty HTML becomes an empty Markdown file and does not call Pandoc. Pandoc failure returns an empty string.
- Markdown to HTML: `pandoc -f markdown+hard_line_breaks+lists_without_preceding_blankline -c <github-pandoc.css> --embed-resources --standalone`, then `premailer` with `remove_classes=True`, then lxml keeps only the `body` element's children. Premailer failure returns the Pandoc HTML. lxml failure, or a missing `body`, returns the inlined HTML. Pandoc failure returns an empty string.
- Suppress `cssutils` logging to `CRITICAL` during conversion. `cssutils` is imported directly.
- `backics.lua`, `github-pandoc.css`, `rename.lua`, and `resume.lua` are package data. Resolve them with `importlib.resources.as_file`. Pass the Pandoc paths to Pandoc and the editor scripts to Neovide.
- `:start` and `retrobox` are literal Ex commands from the user's Neovim config. This package does not install them and does not probe for them.
- Before the editor opens, run the same environment check as `--check-environment`. On failure, print the report and exit 1 without creating a session and without launching Neovide.

## Module boundaries

`cli.py` is the only composition root. It parses arguments and wires Wayland, Pandoc, Neovide, kdialog, and git. `app.py` is one sequence: open a workspace, prepare, run the editor, relocate while a rename was requested, then publish when the workspace still wants the clipboard. It has no mode branches and no subprocess calls.

| Change | Owner |
|---|---|
| Mode policy (input, Ex commands, output MIME) | `modes.py` — one class per workflow |
| Clipboard argv | `clipboard.py` |
| Pandoc argv and HTML fallbacks | `convert.py` |
| Package-data paths | `assets.py` |
| Session paths, slug, catalog, preview, rename | `sessions.py` |
| Which workspace opens, and rename after exit | `workspace.py` |
| kdialog argv | `prompt.py` |
| `git init` argv | `repository.py` |
| Neovide argv, working directory, detached streams | `editor.py` |
| Requirement report text | `environment.py` |

A new workflow is a new mode class plus a CLI flag. Keep the `app.py` sequence as it is.

## Desktop files

Source files live in `share/applications/`. `Exec` is the PATH command `neovim.harness`, not an absolute path. `NoDisplay` is omitted. Each file sets `X-KDE-GlobalAccel-CommandShortcut=true`, `StartupNotify=false`, `Terminal=false`, `Icon=neovide`, `Categories=Utility;TextEditor;`, and `GenericName=Neovim clipboard editor`.

| File | Exec |
|---|---|
| `neovim.harness.new-plain.desktop` | `neovim.harness` |
| `neovim.harness.edit-plain.desktop` | `neovim.harness -p` |
| `neovim.harness.new-formatted.desktop` | `neovim.harness -n` |
| `neovim.harness.edit-formatted.desktop` | `neovim.harness -m` |
| `neovim.harness.new-session.desktop` | `neovim.harness -s` |
| `neovim.harness.resume-session.desktop` | `neovim.harness -r` |

## Tests

- `tests/unit/` uses fakes and `monkeypatch`. It must not read or write the real clipboard, launch Neovide, or create directories under the user's home. Session tests use `tmp_path`.
- `tests/environment/` calls the real machine: real `PATH`, real imports, and the real `WAYLAND_DISPLAY`. It does not launch Neovide. Each failed assertion message is only that check's user-facing paragraph. `tests/environment/conftest.py` reprints the failures as one report.

```sh
pytest tests/unit --cov=neovim_harness --cov-report=term-missing --cov-fail-under=90
pytest tests/environment --tb=no -q
```

To change a requirement message, edit `environment.py`, then the unit test that locks the wording, then the matching live test if the pass condition changed.

## Build and run

Install from the repo:

```sh
cd packaging/arch && makepkg -si
```

`check()` runs the environment suite, then the unit suite. `packaging/arch/neovim.harness.install` runs `neovim.harness --check-environment` from `post_install` and `post_upgrade` and does not swallow a failing exit code.

From a checkout, `pip install -e .` installs the console script. `PYTHONPATH=src python -m neovim_harness` runs the same entry point without installing it.
