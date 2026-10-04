"""Bundle shared examples, including in self-contained source distributions."""

from pathlib import Path
from shutil import copy2

from setuptools import setup
from setuptools.command.sdist import sdist


CONFIGS = "configs" if Path("configs").is_dir() else "../configs"


class SdistWithConfigs(sdist):
    def make_release_tree(self, base_dir, files):
        # Shared checkout data must stay inside the source archive's root.
        super().make_release_tree(
            base_dir, [name for name in files if not name.startswith("../configs/")])
        target = Path(base_dir) / "configs"
        target.mkdir(exist_ok=True)
        for source in [Path(CONFIGS) / "README.md", *Path(CONFIGS).glob("*.json"),
                       *Path(CONFIGS).glob("*.c")]:
            copy2(source, target / source.name)


if __name__ == "__main__":
    setup(
        package_dir={"ble_channel_sounding_planner": ".",
                     "ble_channel_sounding_planner.configs": CONFIGS},
        cmdclass={"sdist": SdistWithConfigs},
    )
