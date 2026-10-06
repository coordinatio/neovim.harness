# Neovim Harness

Neovim Harness takes text from the Wayland clipboard, opens it in Neovide, and copies the result back when the editor closes. Plain-text sessions copy `text/plain`. Formatted sessions are edited as Markdown and copy styled HTML.

A named session is for work you expect to reopen. It asks for a title, creates an empty directory, initializes a git repository, and does not use the clipboard. Resume lists previous sessions, newest regular-file activity first, with a preview of the latest text files.

`-p`, `-m`, `-n`, `-s`, and `-r` are mutually exclusive. With no flag, the tool starts a new plain-text document. `-v` / `--verbose` turns on debug logging.

## Commands

| Command | What you edit | Clipboard after exit |
|---|---|---|
| `neovim.harness` | A new empty document | plain text |
| `neovim.harness -p` | Plain text already on the clipboard | plain text |
| `neovim.harness -m` | Formatted HTML from the clipboard, converted to Markdown | formatted HTML |
| `neovim.harness -n` | A new empty Markdown document | formatted HTML |
| `neovim.harness -s` | A new named directory with a git repository | nothing |
| `neovim.harness -r` | A previous session, chosen from a list | nothing |

## Launchers

These desktop entries are installed for KRunner and other application launchers. Bind any of them under System Settings → Shortcuts.

| Name | Command |
|---|---|
| Neovim Harness: New Plain Text | `neovim.harness` |
| Neovim Harness: Edit Plain Text | `neovim.harness -p` |
| Neovim Harness: New Formatted Text | `neovim.harness -n` |
| Neovim Harness: Edit Formatted Text | `neovim.harness -m` |
| Neovim Harness: New Session | `neovim.harness -s` |
| Neovim Harness: Resume Session | `neovim.harness -r` |

## Requirements

- Python
- `python-lxml`
- `python-premailer` (not in the official repositories)
- `python-cssutils` (not in the official repositories)
- `pandoc-cli`
- `wl-clipboard`
- `neovide`
- `git`
- `kdialog`

Run the install from a Wayland session so `WAYLAND_DISPLAY` is set.

`:start` comes from your Neovim configuration. `yapt.nvim` is a separate plugin. Neovide's working directory is the session folder, so that plugin can keep its state beside the document.

Inside the editor, `:HarnessRename` asks for a title, saves named buffers, writes the request, and quits. If a modified buffer has no file name, Neovim stays open and asks you to save it in this session before running `:HarnessRename` again. If the write fails, Neovim stays open and no request file is left. If quitting fails, the request is removed. The folder is renamed only after that exit, then Neovide opens again in the new folder. A clipboard file named after the old folder is renamed so its name matches the new folder. A successful rename does not copy anything to the clipboard on that exit or from the editor that opens afterward. The date in the folder name stays; the title after `--` changes. A folder without `.git` gets a repository before the editor returns.

## Install

From a Wayland terminal:

```sh
cd packaging/arch && makepkg -si
```

Installation runs the environment checks. If something required is missing, the check prints what to change and the build stops.

Check again any time:

```sh
neovim.harness --check-environment
```

When every requirement is met, that command prints `Neovim Harness environment check passed.`

## Sessions

Clipboard documents are stored under `~/.neovim.harness/sessions/`:

```text
~/.neovim.harness/sessions/doc-YYMMDDHHMMSS/doc-YYMMDDHHMMSS.md
```

A named session has no document file. The title is part of the directory name, after the date:

```text
~/.neovim.harness/sessions/doc-YYMMDDHHMMSS--Fix-login/
```

Letters and digits are kept, including Cyrillic. Spaces become `-`. The title is at most 80 characters and 200 UTF-8 bytes. If that directory already exists, the name gains a `-2`, `-3`, … suffix. A clipboard file is mode `0600` and its name matches its directory. Resume sorts by the newest file inside each session and shows the first 10 lines of up to three newest text files. In the resume filter, a space matches a hyphen and repeated hyphens count as one. A query that is only spaces or hyphens shows every session.

Set `NEOVIM_HARNESS_SESSIONS` to an absolute path to store sessions somewhere else. A relative value is ignored.

Clipboard sessions are never deleted. A new named session may be removed when git init fails and that directory is empty or contains only `.git`. Open the folder again later and continue a `yapt.nvim` session stored there. Canceling the name dialog or the resume list leaves the disk unchanged.
