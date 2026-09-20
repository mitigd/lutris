"""DxWrapper helper module.

DxWrapper (https://github.com/elishacloud/dxwrapper) wraps legacy DirectDraw,
Direct3D 8/9, DirectInput, DirectSound and other APIs for old games.
Upstream releases only provide 32-bit binaries.
"""

import json
import os
import re
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
    # API DLLs the exe is sniffed for; the core follows the stubs so the
    # deployed set always matches versions.
    api_dlls = ("ddraw", "d3d8", "d3d9")
    prefer_game_dir = True
    # Stock dxwrapper.ini; all wrappers ship disabled, the user enables what
    # the game needs (e.g. Dd7to9 for DDraw games). Deployed to the game dir.
    game_files = {"dxwrapper.ini": "dxwrapper.ini"}
    releases_url = "https://api.github.com/repos/elishacloud/dxwrapper/releases"
    # Proton/umu compatible: deployed next to the game with a native
    # WINEDLLOVERRIDES entry. Verified: the game dir is visible inside the
    # umu container, unlike prefix files Proton reinstalls on updates.
    proton_compatible = True
    known_versions = {
        "v1.8.8600.25": "https://github.com/elishacloud/dxwrapper/releases/download/v1.8.8600.25/dxwrapper.zip",
    }

    # Upstream publishes per-API bundles (dx7/dx8/dx9.games.zip), debug symbols
    # and a WinXP bundle; the full package we want is dxwrapper.zip.
    full_package_asset = "dxwrapper.zip"

    @staticmethod
    def detect_needed_apis(exe_path):
        """Sniff which API DLLs the target exe references.

        Returns the subset of api_dlls found (byte scan, so static imports
        and dynamic loads both match), an empty set when nothing matches,
        or None when the exe cannot be read at all."""
        if not exe_path:
            return None
        try:
            with open(exe_path, "rb") as exe_file:
                data = exe_file.read()
        except OSError as ex:
            logger.debug("Could not read %s for API detection: %s", exe_path, ex)
            return None
        if not data:
            return None
        return {api for api in DxWrapperManager.api_dlls if re.search(rb"(?i)\b" + api.encode() + rb"\.dll\b", data)}

    def deploy_game_dlls(self, game_dir, exe_path=None, confirmer=None):
        """Deploy only the stubs the target exe uses, plus the matching core.

        Falls back to the ddraw stub when nothing is detected, and to the
        full set when the exe cannot be read. Existing files that differ
        are replaced, asking first when confirmer is given."""
        if not self.is_available():
            logger.warning("%s is not available locally, skipping game DLLs.", self.human_name)
            return False
        if not system.path_exists(game_dir):
            logger.warning("Game directory %s does not exist, skipping game DLLs.", game_dir)
            return False
        needed = self.detect_needed_apis(exe_path) if exe_path else None
        if needed is None:
            apis = list(self.api_dlls)
            logger.debug("Could not determine the APIs used; deploying the full stub set.")
        elif not needed:
            apis = ["ddraw"]
            logger.info("No DDraw/D3D8/D3D9 usage detected; deploying the ddraw stub only.")
        else:
            apis = sorted(needed)
            logger.info("Deploying DxWrapper stubs for detected APIs: %s.", ", ".join(apis))
        arch_dir = os.path.join(self.path, self.archs[32])
        failed = False
        for dll in apis:
            source = os.path.join(arch_dir, "%s.dll" % dll)
            if not system.path_exists(source):
                continue
            dest = os.path.join(game_dir, "%s.dll" % dll)
            if self._copy_with_confirm(source, dest, confirmer, "%s %s.dll" % (self.human_name, dll)) is False:
                failed = True
        # The core must always match the stubs.
        core_source = os.path.join(arch_dir, "dxwrapper.dll")
        if system.path_exists(core_source):
            core_dest = os.path.join(game_dir, "dxwrapper.dll")
            core_label = "%s dxwrapper.dll" % self.human_name
            if self._copy_with_confirm(core_source, core_dest, confirmer, core_label) is False:
                failed = True
        return not failed

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
