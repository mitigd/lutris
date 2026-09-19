"""CnC-DDraw helper module.

CnC-DDraw (https://github.com/FunkyFr3sh/cnc-ddraw) is a DirectDraw wrapper
aimed at Command & Conquer and other DDraw-era games, rendering through
OpenGL/GDI+. Upstream releases only provide 32-bit binaries.
"""

import json
import os
import shutil

from lutris.util import system
from lutris.util.log import logger
from lutris.util.wine.dll_manager import DLLManager


class CncDdrawManager(DLLManager):
    name = "cnc-ddraw"
    human_name = "CnC-DDraw"
    managed_dlls = ("ddraw",)
    prefer_game_dir = True
    game_files = {"ddraw.ini": "ddraw.ini", "Shaders": "Shaders"}
    releases_url = "https://api.github.com/repos/FunkyFr3sh/cnc-ddraw/releases"
    # Proton/umu compatible: see DxWrapperManager. Verified: symlinks into
    # the runtime dir resolve inside the umu container.
    proton_compatible = True
    known_versions = {
        "v7.1.0.0": "https://github.com/FunkyFr3sh/cnc-ddraw/releases/download/v7.1.0.0/cnc-ddraw.zip",
    }

    # Upstream also publishes a legacy (Windows ME) bundle and debug symbols;
    # the regular package is cnc-ddraw.zip.
    full_package_asset = "cnc-ddraw.zip"

    def get_download_url(self):
        """Fetch the download URL from the JSON version file, preferring the
        regular package over the legacy bundle and debug symbols."""
        if self.version in self.known_versions:
            return self.known_versions[self.version]
        try:
            with open(self.versions_path, "r", encoding="utf-8") as version_file:
                releases = json.load(version_file)
        except (OSError, json.JSONDecodeError):
            return None
        for release in releases:
            if release.get("tag_name") != self.version:
                continue
            assets = release.get("assets") or []
            for asset in assets:
                if asset.get("name") == self.full_package_asset:
                    return asset.get("browser_download_url")
            if assets:
                logger.warning(
                    "Asset %s not found for %s %s, falling back to %s",
                    self.full_package_asset,
                    self.human_name,
                    self.version,
                    assets[0].get("name"),
                )
                return assets[0].get("browser_download_url")
        return None

    def download(self):
        """Download the component, then reshape the upstream layout into the
        standard x32/x64 layout the base manager expects.

        The upstream zip holds a 32-bit ddraw.dll at its root (plus ddraw.ini,
        shaders and a config tool, which stay at the version root; per-game
        configuration belongs in the game directory).
        """
        if not super().download():
            return False
        self._normalize_layout()
        return True

    def _normalize_layout(self):
        """Copy the 32-bit ddraw.dll into x32/; no-op when absent (e.g. a
        manually installed Lutris-format package)."""
        dll_path = os.path.join(self.path, "ddraw.dll")
        if not system.path_exists(dll_path):
            logger.debug("No ddraw.dll found in %s, skipping layout normalization", self.path)
            return
        arch_dir = os.path.join(self.path, self.archs[32])
        os.makedirs(arch_dir, exist_ok=True)
        shutil.copy(dll_path, os.path.join(arch_dir, "ddraw.dll"))
