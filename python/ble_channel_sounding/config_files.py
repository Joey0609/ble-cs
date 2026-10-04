"""Locate the example configurations in a checkout or installed package."""

from pathlib import Path


def configs_directory() -> Path:
    package = Path(__file__).resolve().parent
    bundled = package / "configs"
    return bundled if bundled.is_dir() else package.parent / "configs"
