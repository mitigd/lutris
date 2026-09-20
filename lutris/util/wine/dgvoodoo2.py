"""dgVoodoo2 helper module.

dgVoodoo2 (https://github.com/dege-diosg/dgVoodoo2) wraps Glide and
DirectX 1-9 (DirectDraw/Direct3D up to 7, plus D3D8/9) for old games,
translating to Direct3D 11/12 - combine with DXVK. Upstream ships
mixed-case DLLs under MS/ (DirectX) and 3Dfx/ (Glide) folders.
"""

import json
import os
import shutil

from lutris.util import system
from lutris.util.log import logger
from lutris.util.wine.dll_manager import DLLManager


class dgvoodoo2Manager(DLLManager):
    name = "dgvoodoo2"
    human_name = "dgvoodoo2"
    managed_dlls = (
        "d3dimm",
        "ddraw",
        "d3d8",
        "d3d9",
        "glide",
        "glide2x",
        "glide3x",
    )
    # Stock config deployed next to the game (never overwritten); the
    # config tab manages it later.
    game_files = {"dgVoodoo.conf": "dgVoodoo.conf"}
    managed_appdata_files = ["dgVoodoo/dgVoodoo.conf"]
    releases_url = "https://api.github.com/repos/dege-diosg/dgVoodoo2/releases"
    # Deployed next to the game like the other DDraw replacements: Proton
    # reinstalls its own DLLs into the prefix on updates, while the game
    # directory is never touched.
    prefer_game_dir = True
    proton_compatible = True
    known_versions = {
        "v2.87.5": "https://github.com/dege-diosg/dgVoodoo2/releases/download/v2.87.5/dgVoodoo2_87_5.zip",
    }

    # Upstream publishes debug (_dbg), 64-bit dev (_dev64), API and WinMM
    # bundles next to the full package; match only the full package.
    full_package_prefix = "dgvoodoo2_"
    full_package_excludes = ("dbg", "dev64")

    # (archive subdir, filename as shipped, Lutris arch dir, Lutris name)
    dll_sources = (
        ("MS/x86", "DDraw.dll", "x32", "ddraw.dll"),
        ("MS/x86", "D3DImm.dll", "x32", "d3dimm.dll"),
        ("MS/x86", "D3D8.dll", "x32", "d3d8.dll"),
        ("MS/x86", "D3D9.dll", "x32", "d3d9.dll"),
        ("MS/x64", "D3D9.dll", "x64", "d3d9.dll"),
        ("3Dfx/x86", "Glide.dll", "x32", "glide.dll"),
        ("3Dfx/x86", "Glide2x.dll", "x32", "glide2x.dll"),
        ("3Dfx/x86", "Glide3x.dll", "x32", "glide3x.dll"),
        ("3Dfx/x64", "Glide.dll", "x64", "glide.dll"),
        ("3Dfx/x64", "Glide2x.dll", "x64", "glide2x.dll"),
        ("3Dfx/x64", "Glide3x.dll", "x64", "glide3x.dll"),
    )

    def get_download_url(self):
        """Fetch the download URL from the JSON version file, preferring
        the full package over debug/dev/API bundles."""
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
                name = (asset.get("name") or "").casefold()
                if (
                    name.startswith(self.full_package_prefix)
                    and name.endswith(".zip")
                    and not any(excluded in name for excluded in self.full_package_excludes)
                ):
                    return asset.get("browser_download_url")
            if assets:
                logger.warning(
                    "Full %s package not found for %s, falling back to %s",
                    self.human_name,
                    self.version,
                    assets[0].get("name"),
                )
                return assets[0].get("browser_download_url")
        return None

    def download(self):
        """Download the component, then reshape the upstream layout into the
        standard x32/x64 layout the base manager expects."""
        if not super().download():
            return False
        self._normalize_layout()
        return True

    def _normalize_layout(self):
        """Copy the mixed-case upstream DLLs into x32/x64 with lowercase
        names; no-op for manually installed Lutris-format packages."""
        found = False
        for subdir, shipped, arch, name in self.dll_sources:
            source = os.path.join(self.path, subdir, shipped)
            if not system.path_exists(source):
                continue
            found = True
            arch_dir = os.path.join(self.path, arch)
            os.makedirs(arch_dir, exist_ok=True)
            shutil.copy(source, os.path.join(arch_dir, name))
        if not found:
            logger.debug("No upstream dgVoodoo2 DLLs found in %s, skipping layout normalization", self.path)
