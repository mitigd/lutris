"""DxWrapper helper module.

DxWrapper (https://github.com/elishacloud/dxwrapper) wraps legacy DirectDraw,
Direct3D 8/9, DirectInput, DirectSound and other APIs for old games.
Upstream releases only provide 32-bit binaries.
"""

import json
import os
import shutil

from lutris.util import system
from lutris.util.log import logger
from lutris.util.wine.dll_manager import DLLManager


class DxWrapperManager(DLLManager):
    name = "dxwrapper"
    human_name = "DxWrapper"
    # 'dxwrapper' is the wrapper itself (loaded by the stub DLLs, so it must be
    # deployed next to them); the stubs are the APIs it wraps for DDraw-era games.
    managed_dlls = ("ddraw", "d3d8", "d3d9", "dxwrapper")
    prefer_game_dir = True
    # Stock dxwrapper.ini; all wrappers ship disabled, the user enables what
    # the game needs (e.g. Dd7to9 for DDraw games). Deployed to the game dir.
    game_files = {"dxwrapper.ini": "dxwrapper.ini"}
    releases_url = "https://api.github.com/repos/elishacloud/dxwrapper/releases"
    # Proton/umu compatible: the wrapper is deployed into the prefix with a
    # native WINEDLLOVERRIDES entry, and Lutris sets PROTON_USE_WINED3D so
    # Proton does not substitute its own DDraw/D3D. Verified: symlinks into
    # the runtime dir resolve inside the umu container.
    proton_compatible = True
    known_versions = {
        "v1.8.8600.25": "https://github.com/elishacloud/dxwrapper/releases/download/v1.8.8600.25/dxwrapper.zip",
    }

    # Upstream publishes per-API bundles (dx7/dx8/dx9.games.zip), debug symbols
    # and a WinXP bundle; the full package we want is dxwrapper.zip.
    full_package_asset = "dxwrapper.zip"

    def get_download_url(self):
        """Fetch the download URL from the JSON version file.

        Upstream releases carry several assets, so pick the full package
        instead of blindly taking the first asset.
        """
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

        The upstream zip holds dxwrapper.dll at its root and the wrappable API
        DLLs (ddraw, d3d8, ...) as stubs under Stub/.
        """
        if not super().download():
            return False
        self._normalize_layout()
        return True

    def _normalize_layout(self):
        """Copy the 32-bit wrapper and stubs into x32/; no-op when the sources
        are absent (e.g. a manually installed Lutris-format package)."""
        arch_dir = os.path.join(self.path, self.archs[32])
        wrapper_dll = os.path.join(self.path, "dxwrapper.dll")
        if system.path_exists(wrapper_dll):
            os.makedirs(arch_dir, exist_ok=True)
            shutil.copy(wrapper_dll, os.path.join(arch_dir, "dxwrapper.dll"))
        else:
            logger.debug("No dxwrapper.dll found in %s, skipping layout normalization", self.path)
            return
        for dll in self.managed_dlls:
            if dll == "dxwrapper":
                continue
            stub_dll = os.path.join(self.path, "Stub", "%s.dll" % dll)
            if system.path_exists(stub_dll):
                shutil.copy(stub_dll, os.path.join(arch_dir, "%s.dll" % dll))
            else:
                logger.debug("No Stub/%s.dll found in %s", dll, self.path)
