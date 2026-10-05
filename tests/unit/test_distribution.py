from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]

_DESKTOPS = {
    "neovim.harness.new-plain.desktop": {
        "Name": "Neovim Harness: New Plain Text",
        "Exec": "neovim.harness",
        "Keywords": "neovim;clipboard;plain;text;",
        "Comment": "Copies plain text to the clipboard after exit.",
    },
    "neovim.harness.edit-plain.desktop": {
        "Name": "Neovim Harness: Edit Plain Text",
        "Exec": "neovim.harness -p",
        "Keywords": "neovim;clipboard;plain;text;paste;",
        "Comment": "Copies plain text to the clipboard after exit.",
    },
    "neovim.harness.new-formatted.desktop": {
        "Name": "Neovim Harness: New Formatted Text",
        "Exec": "neovim.harness -n",
        "Keywords": "neovim;clipboard;markdown;html;formatted;",
        "Comment": "Copies formatted HTML to the clipboard after exit.",
    },
    "neovim.harness.edit-formatted.desktop": {
        "Name": "Neovim Harness: Edit Formatted Text",
        "Exec": "neovim.harness -m",
        "Keywords": "neovim;clipboard;markdown;html;formatted;paste;",
        "Comment": "Copies formatted HTML to the clipboard after exit.",
    },
}


def _desktop(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line or line.startswith("#") or line.startswith("["):
            continue
        key, value = line.split("=", 1)
        values[key] = value
    return values


def _bash_array(text: str, name: str) -> list[str]:
    match = re.search(rf"^{name}=\((.*?)\)$", text, re.M | re.S)
    assert match is not None
    return re.findall(r"[A-Za-z0-9][A-Za-z0-9_.+-]*", match.group(1))


def test_desktop_files_have_the_launcher_keys() -> None:
    for name, expected in _DESKTOPS.items():
        path = ROOT / "share" / "applications" / name
        values = _desktop(path)
        assert "NoDisplay" not in values
        assert values["Type"] == "Application"
        assert values["Name"] == expected["Name"]
        assert values["GenericName"] == "Neovim clipboard editor"
        assert values["Comment"] == expected["Comment"]
        assert values["Exec"] == expected["Exec"]
        assert not values["Exec"].startswith("/")
        assert values["Icon"] == "neovide"
        assert values["Terminal"] == "false"
        assert values["StartupNotify"] == "false"
        assert values["Categories"] == "Utility;TextEditor;"
        assert values["Keywords"] == expected["Keywords"]
        assert values["X-KDE-GlobalAccel-CommandShortcut"] == "true"


def test_pkgbuild_matches_the_package_contract() -> None:
    text = (ROOT / "packaging" / "arch" / "PKGBUILD").read_text(encoding="utf-8")
    assert "pkgname=neovim.harness" in text
    assert "pkgver=0.1.0" in text
    assert "pkgrel=1" in text
    assert "arch=('any')" in text
    assert "license=('MIT')" in text
    assert "install=neovim.harness.install" in text
    assert _bash_array(text, "depends") == [
        "python",
        "python-lxml",
        "python-premailer",
        "python-cssutils",
        "pandoc-cli",
        "wl-clipboard",
        "neovide",
    ]
    assert _bash_array(text, "makedepends") == [
        "python-build",
        "python-installer",
        "python-setuptools",
        "python-wheel",
        "python-pytest",
        "python-pytest-cov",
    ]
    assert text.count('cd "$startdir/../.."') >= 3
    assert "python -m build --wheel" in text
    assert 'python -m installer --destdir="$pkgdir"' in text
    check = re.search(r"check\(\) \{(.*?\n)\}", text, re.S)
    assert check is not None
    body = check.group(1)
    environment = body.index("pytest tests/environment --tb=no -q")
    unit = body.index(
        "pytest tests/unit --cov=neovim_harness --cov-report=term-missing --cov-fail-under=90"
    )
    assert environment < unit
    for name in _DESKTOPS:
        assert f"install -Dm644 share/applications/{name}" in text


def test_install_script_runs_the_environment_check() -> None:
    script = (ROOT / "packaging" / "arch" / "neovim.harness.install").read_text(
        encoding="utf-8"
    )
    assert "post_install()" in script
    assert "post_upgrade()" in script
    assert script.count("neovim.harness --check-environment") >= 2
    assert "|| true" not in script
    assert "||true" not in script
    assert "set +e" not in script


def test_gitignore_covers_build_artifacts() -> None:
    root = (ROOT / ".gitignore").read_text(encoding="utf-8")
    for entry in ("dist/", "build/", "*.egg-info", ".coverage", "__pycache__"):
        assert entry in root
    packaging = (ROOT / "packaging" / "arch" / ".gitignore").read_text(encoding="utf-8")
    for entry in ("src/", "pkg/", "*.pkg.tar.zst"):
        assert entry in packaging
