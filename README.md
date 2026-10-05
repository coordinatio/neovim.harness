# Neovim Harness

Neovim Harness takes text from the Wayland clipboard, opens it in Neovide, and copies the result back when the editor closes. Plain-text sessions copy `text/plain`. Formatted sessions are edited as Markdown and copy styled HTML.

`-p`, `-m`, and `-n` are mutually exclusive. With no flag, the tool starts a new plain-text document. `-v` / `--verbose` turns on debug logging.

## Commands

| Command | What you edit | Clipboard after exit |
|---|---|---|
| `neovim.harness` | A new empty document | plain text |
| `neovim.harness -p` | Plain text already on the clipboard | plain text |
| `neovim.harness -m` | Formatted HTML from the clipboard, converted to Markdown | formatted HTML |
| `neovim.harness -n` | A new empty Markdown document | formatted HTML |

## Launchers

These desktop entries are installed for KRunner and other application launchers. Bind any of them under System Settings → Shortcuts.

| Name | Command |
|---|---|
| Neovim Harness: New Plain Text | `neovim.harness` |
| Neovim Harness: Edit Plain Text | `neovim.harness -p` |
| Neovim Harness: New Formatted Text | `neovim.harness -n` |
| Neovim Harness: Edit Formatted Text | `neovim.harness -m` |

## Requirements

- Python
- `python-lxml`
- `python-premailer` (not in the official repositories)
- `python-cssutils` (not in the official repositories)
- `pandoc-cli`
- `wl-clipboard`
- `neovide`

Run the install from a Wayland session so `WAYLAND_DISPLAY` is set.

`:start` comes from your Neovim configuration. `yapt.nvim` is a separate plugin. Neovide's working directory is the session folder, so that plugin can keep its state beside the document.

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

New documents are stored under `~/.neovim.harness/sessions/`:

```text
~/.neovim.harness/sessions/doc-YYMMDDHHMMSS/doc-YYMMDDHHMMSS.md
```

If that directory already exists, the name gains a `-2`, `-3`, … suffix. The file name matches the directory name. The file mode is `0600`.

Set `NEOVIM_HARNESS_SESSIONS` to an absolute path to store sessions somewhere else. A relative value is ignored.

Sessions are never deleted. Open the folder again later and continue a `yapt.nvim` session stored there.
