"""Resolve package-data paths that Pandoc can open."""

from __future__ import annotations

from importlib.resources import as_file, files
from pathlib import Path


class AssetPaths:
    def __init__(
        self,
        lua_filter: Path,
        stylesheet: Path,
        _open_resources: list[object],
    ) -> None:
        self.lua_filter = lua_filter
        self.stylesheet = stylesheet
        self._open_resources = _open_resources

    @classmethod
    def load(cls) -> AssetPaths:
        open_resources: list[object] = []
        return cls(
            _as_path("backics.lua", open_resources),
            _as_path("github-pandoc.css", open_resources),
            open_resources,
        )


def _as_path(name: str, open_resources: list[object]) -> Path:
    resource = files("neovim_harness").joinpath("data").joinpath(name)
    context = as_file(resource)
    path = Path(context.__enter__())
    open_resources.append(context)
    return path
