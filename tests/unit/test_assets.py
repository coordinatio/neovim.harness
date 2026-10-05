from pathlib import Path

from neovim_harness.assets import AssetPaths


def test_package_data_paths_match_the_shipped_files() -> None:
    assets = AssetPaths.load()
    root = Path("src/neovim_harness/data")
    assert assets.lua_filter.name == "backics.lua"
    assert assets.stylesheet.name == "github-pandoc.css"
    assert assets.lua_filter.read_bytes() == (root / "backics.lua").read_bytes()
    assert assets.stylesheet.read_bytes() == (root / "github-pandoc.css").read_bytes()
