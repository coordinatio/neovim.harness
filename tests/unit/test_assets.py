from pathlib import Path

from neovim_harness.assets import AssetPaths, ConversionAssets


def test_package_data_paths_match_the_shipped_files() -> None:
    assets = AssetPaths.load()
    root = Path("src/neovim_harness/data")
    assert assets.lua_filter.name == "backics.lua"
    assert assets.stylesheet.name == "github-pandoc.css"
    assert assets.rename_lua.name == "rename.lua"
    assert assets.resume_lua.name == "resume.lua"
    assert assets.lua_filter.read_bytes() == (root / "backics.lua").read_bytes()
    assert assets.stylesheet.read_bytes() == (root / "github-pandoc.css").read_bytes()
    assert assets.rename_lua.read_bytes() == (root / "rename.lua").read_bytes()
    assert assets.resume_lua.read_bytes() == (root / "resume.lua").read_bytes()


def test_conversion_assets_are_the_pandoc_files() -> None:
    assets = ConversionAssets.load()
    root = Path("src/neovim_harness/data")
    assert assets.lua_filter.read_bytes() == (root / "backics.lua").read_bytes()
    assert assets.stylesheet.read_bytes() == (root / "github-pandoc.css").read_bytes()
