# Neovim Harness

Neovim Harness takes text from the Wayland clipboard, opens it in Neovide, and copies the result back when the editor closes. Plain-text sessions copy `text/plain`. Formatted sessions are edited as Markdown and copy styled HTML. An optional Neovim module can also copy a Markdown selection to the clipboard as HTML, or paste clipboard HTML back as Markdown, without opening another editor.

A named session is for work you expect to reopen. It asks for a title, creates an empty directory, initializes a git repository, and does not use the clipboard. Resume lists previous sessions, newest regular-file activity first, with a preview of the latest text files.

`-p`, `-m`, `-n`, `-s`, `-r`, `--clipboard-to-markdown`, and `--markdown-to-clipboard` are mutually exclusive. With no flag, the tool starts a new plain-text document. `-v` / `--verbose` turns on debug logging.

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

## Neovim

The Arch package installs an optional module on Neovim's runtime path. It does not change `p`. Enable it from your configuration:

```lua
require("neovim_harness").setup()
```

Neovim 0.10 or newer is required. On an older version, `setup()` shows an error and does not create commands.

```lua
require("neovim_harness").setup({
  command = "neovim.harness",
  mappings = {
    copy_html = "<leader>mh",
    paste_markdown = "<leader>mp",
  },
})
```

Set a mapping to `false` to leave it unset. The commands are created either way. Calling `setup()` again replaces the previous commands and mappings.

| Action | Command | Mapping |
|---|---|---|
| Copy the visual selection to the clipboard as HTML | `:HarnessCopyHtml` | `<leader>mh` in visual mode |
| Paste clipboard HTML as Markdown | `:HarnessPasteMarkdown` | `<leader>mp` in normal and visual mode |

Characterwise and linewise selections are supported in Visual and Select mode, including combining characters, emoji, exclusive `'selection'`, and `'virtualedit'` columns. A selection that reaches the end of a line replaces the line break the highlight covers. A blockwise selection shows an error and does not start a conversion. Copy reads the selection before the converter runs and does not change the buffer. Copying an empty selection shows an error and leaves the clipboard alone. `:2HarnessCopyHtml` copies that whole line. A range on different lines does not reuse the last visual selection. Paste in normal mode inserts the Markdown after the cursor and leaves the cursor where `p` does: on the last character of a single inserted line, and on the first inserted character when the result spans lines. Paste in visual mode replaces the selection. An empty Markdown result leaves a visual selection unchanged. That insertion is one undo step.

The converter runs in the background. A newer copy or paste cancels the one still running, and the cancelled result is ignored. If the buffer changes before the result comes back, the result is discarded. A missing `text/html` clipboard value, a Pandoc failure, any other non-zero exit, or a missing `neovim.harness` command shows an error and leaves the buffer unchanged.

These are the commands the module runs. They do not open Neovide. Errors go to standard error, and a successful copy leaves standard output empty.

| Command | Effect |
|---|---|
| `neovim.harness --clipboard-to-markdown` | Read `text/html` and write Markdown to standard output |
| `neovim.harness --markdown-to-clipboard` | Read UTF-8 Markdown from standard input and copy `text/html` |

From a git checkout, add the plugin directory before `setup()`:

```lua
vim.opt.runtimepath:append("/path/to/neovim.harness/share/nvim/site/pack/neovim-harness/start/neovim-harness")
```

The installed package already places that directory under `/usr/share/nvim/site`.

## Requirements

- Python
- `python-lxml`
- `python-premailer` (not in the official repositories)
- `python-cssutils` (not in the official repositories)
- `pandoc-cli`
- `wl-clipboard`
- `neovide`
- `neovim` 0.10 or newer, for the optional module
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
