"""DXGL helper module.

DXGL (https://dxgl.org) wraps DirectDraw for old games, rendering through
OpenGL. Upstream publishes a 32-bit NSIS installer (no GitHub releases),
so this manager pins known versions to their download URLs and extracts the
installer with 7zip.
"""

import json
import os
import shutil

from lutris.util import system
from lutris.util.log import logger
from lutris.util.wine.dll_manager import DLLManager


class DxglManager(DLLManager):
    name = "dxgl"
    human_name = "DXGL"
    managed_dlls = ("ddraw",)
    prefer_game_dir = True
    # Upstream documents this as: place next to the game renamed to dxgl.ini;
    # unset options fall back to the registry profile.
    game_files = {"dxgl-example.ini": "dxgl.ini"}
    # No GitHub API here; fetch_versions() synthesizes the versions file from
    # the table below. The base class only uses releases_url there, so it is
    # intentionally left at its default.
    # Proton/umu compatible: see DxWrapperManager. Verified: symlinks into
    # the runtime dir resolve inside the umu container.
    proton_compatible = True

    known_versions = {
        "0.5.27": "https://dxgl.org/download/DXGL-0.5.27-win32.exe",
    }

    def fetch_versions(self):
        """Write the versions file from the known-versions table, in the same
        shape as the GitHub API responses the base manager consumes."""
        if not os.path.isdir(self.base_dir):
            os.makedirs(self.base_dir, exist_ok=True)
        releases = [
            {"tag_name": tag, "assets": [{"browser_download_url": url}]} for tag, url in self.known_versions.items()
        ]
        with open(self.versions_path, "w", encoding="utf-8") as version_file:
            json.dump(releases, version_file)

    def download(self):
        """Download the NSIS installer, extract it, then reshape the layout
        into the standard x32/x64 layout the base manager expects.

        The installer holds a 32-bit ddraw.dll at its root (plus a config
        tool and docs, which stay at the version root).
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
