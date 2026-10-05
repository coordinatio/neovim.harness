# Agents

Neovim Harness is a Wayland clipboard editor. It writes a session file, opens that file in Neovide, and copies the result back to the clipboard.

## Modes

| Command | Input | Ex commands after `--` | Clipboard MIME |
|---|---|---|---|
| `neovim.harness` | empty file | `+start` | `text/plain` |
| `neovim.harness -p` | `wl-paste --no-newline` | none | `text/plain` |
| `neovim.harness -m` | `wl-paste --no-newline -t text/html`, then Pandoc to GFM | `+colorscheme retrobox` | `text/html` |
| `neovim.harness -n` | empty file | `+start` then `+colorscheme retrobox` | `text/html` |

`-p`, `-m`, and `-n` are mutually exclusive. The default is new plain text. `-v` / `--verbose` enables debug logging. `--check-environment` only prints the requirement report.

## Invariants

- New sessions go to `~/.neovim.harness/sessions/doc-YYMMDDHHMMSS/doc-YYMMDDHHMMSS.md`. Nothing in the program deletes or expires them, so a later open of that folder can continue a `yapt.nvim` session.
- `NEOVIM_HARNESS_SESSIONS` replaces that root only when the value is an absolute path. A relative value is ignored.
- If the timestamp directory exists, append `-2`, `-3`, … The file stem matches the directory name, including the suffix.
- The session file mode is `0600`.
- Neovide's working directory is the session directory (the file's parent), not that directory's parent and not `$HOME`.
- The Neovide command is `neovide --no-fork <file> --` plus the Ex commands. stdin, stdout, and stderr are `DEVNULL`.
- A missing `neovide` executable, or any other launch failure, exits 1.
- If the session file is gone after the editor exits, do not write the clipboard.
- Plain modes write only `text/plain`. Formatted modes write only `text/html`.
- Clipboard read is `wl-paste --no-newline`, plus `-t <mime>` when a MIME type is requested. Clipboard write is `wl-copy`. Plain writes pass `-t text/plain` and formatted writes pass `-t text/html`. An empty MIME type omits `-t`.
- HTML to Markdown: `pandoc -f html -t gfm-raw_html --wrap=none --lua-filter=<backics.lua>`. Empty HTML becomes an empty Markdown file and does not call Pandoc. Pandoc failure returns an empty string.
- Markdown to HTML: `pandoc -f markdown+hard_line_breaks+lists_without_preceding_blankline -c <github-pandoc.css> --embed-resources --standalone`, then `premailer` with `remove_classes=True`, then lxml keeps only the `body` element's children. Premailer failure returns the Pandoc HTML. lxml failure, or a missing `body`, returns the inlined HTML. Pandoc failure returns an empty string.
- Suppress `cssutils` logging to `CRITICAL` during conversion. `cssutils` is imported directly.
- `backics.lua` and `github-pandoc.css` are package data. Resolve them with `importlib.resources.as_file` and pass those filesystem paths to Pandoc.
- `:start` and `retrobox` are literal Ex commands from the user's Neovim config. This package does not install them and does not probe for them.
- Before the editor opens, run the same environment check as `--check-environment`. On failure, print the report and exit 1 without creating a session and without launching Neovide.

## Module boundaries

`cli.py` is the only composition root. It parses arguments and wires Wayland, Pandoc, and Neovide. `app.py` is one sequence: create session, prepare, open editor, publish. It has no mode branches and no subprocess calls.

| Change | Owner |
|---|---|
| Mode policy (input, Ex commands, output MIME) | `modes.py` — one class per workflow |
| Clipboard argv | `clipboard.py` |
| Pandoc argv and HTML fallbacks | `convert.py` |
| Package-data paths | `assets.py` |
| Session paths, collision suffix, mode `0600` | `sessions.py` |
| Neovide argv, working directory, detached streams | `editor.py` |
| Requirement report text | `environment.py` |

A new workflow is a new mode class plus a CLI flag. Leave `app.py` as it is.

## Desktop files

Source files live in `share/applications/`. `Exec` is the PATH command `neovim.harness`, not an absolute path. `NoDisplay` is omitted. Each file sets `X-KDE-GlobalAccel-CommandShortcut=true`, `StartupNotify=false`, `Terminal=false`, `Icon=neovide`, `Categories=Utility;TextEditor;`, and `GenericName=Neovim clipboard editor`.

| File | Exec |
|---|---|
| `neovim.harness.new-plain.desktop` | `neovim.harness` |
| `neovim.harness.edit-plain.desktop` | `neovim.harness -p` |
| `neovim.harness.new-formatted.desktop` | `neovim.harness -n` |
| `neovim.harness.edit-formatted.desktop` | `neovim.harness -m` |

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
