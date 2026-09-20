"""Injects sets of DLLs into a prefix"""

import filecmp
import json
import os
import shutil
from gettext import gettext as _

from lutris import settings
from lutris.api import get_runtime_versions
from lutris.exceptions import MissingRuntimeComponentError
from lutris.util import system
from lutris.util.extract import extract_archive
from lutris.util.http import download_file
from lutris.util.log import logger
from lutris.util.strings import parse_version
from lutris.util.wine.prefix import WinePrefixManager


class DLLManager:
    """Utility class to install dlls to a Wine prefix"""

    name = NotImplemented
    human_name = NotImplemented
    managed_dlls = NotImplemented
    managed_appdata_files = []  # most managers have none
    releases_url = NotImplemented
    archs = {32: "x32", 64: "x64"}
    proton_compatible = False  # Proton manages its own DLLs
    known_versions: dict[str, str] = {}
    # Pinned versions mapped to direct download URLs. These are always
    # listed (and downloadable) without needing the versions file that is
    # normally fetched through the runtime updater, so components the Lutris
    # API does not serve yet still work out of the box.
    game_files: dict[str, str] = {}
    # Wrapper support files deployed next to the game (copies, never
    # symlinks, so this also works on Windows filesystems). Maps a path
    # relative to the version directory to the filename in the game
    # directory. Files that already exist are never overwritten, so user
    # tuning is preserved.
    prefer_game_dir = False
    # When True, the wrapper's DLLs are deployed as a version-matched set
    # next to the game instead of into the prefix: Proton reinstalls its own
    # DLLs into the prefix on updates (wiping foreign files), while the game
    # directory is never touched and is also where upstream documents these
    # wrappers to live. DLLs are always refreshed to the enabled version;
    # config files from game_files are still never overwritten.

    def __init__(self, prefix=None, arch="win64", version=None):
        self.prefix = prefix
        self._versions = []
        self._version = None if version is None else str(version)
        self.wine_arch = arch

    @property
    def base_dir(self):
        return os.path.join(settings.RUNTIME_DIR, self.name)

    @property
    def versions_path(self):
        return os.path.join(self.base_dir, f"{self.name}_versions.json")

    @property
    def versions(self):
        """Return available versions"""
        self._versions = self.load_versions()
        if system.path_exists(self.base_dir):
            for local_version in os.listdir(self.base_dir):
                if os.path.isdir(os.path.join(self.base_dir, local_version)) and local_version not in self._versions:
                    self._versions.append(local_version)
        return self._versions

    @property
    def version(self):
        """Return version (latest known version if not provided)"""
        if self._version:
            return self._version
        versions = self.versions
        if versions:

            def get_preference_key(v):
                return not self.is_compatible_version(v), not self.is_recommended_version(v)

            # Put the compatible versions first, and the recommended ones before unrecommended ones.
            sorted_versions = sorted(versions, key=get_preference_key)
            return sorted_versions[0]

    def is_recommended_version(self, version):
        """True if the version given should be usable as the default; false if it
        should not be the default, but may be selected by the user. If only
        non-recommended versions exist, we'll still default to one of them, however."""
        return True

    def is_compatible_version(self, version):
        """True if the version of the component is compatible with this Lutris. We can tell only
        once it is downloaded; if not this is always True.

        This checks the file 'lutris.json', which may contain the lowest version of Lutris
        the component version will work with. If this setting is absent, it is assumed compatible."""
        dir_settings = settings.get_lutris_directory_settings(self.base_dir)

        try:
            if "min_lutris_version" in dir_settings:
                min_lutris_version = parse_version(dir_settings["min_lutris_version"])
                current_lutris_version = parse_version(settings.VERSION)
                if current_lutris_version < min_lutris_version:
                    return False
        except TypeError as ex:
            logger.exception("Invalid lutris.json: %s", ex)
            return False

        return True

    @property
    def path(self):
        """Path to local folder containing DLLs"""
        version = self.version
        if not version:
            raise MissingRuntimeComponentError(
                _(
                    "The '%s' runtime component is not installed; "
                    "visit the Updates tab in the Preferences dialog to install it."
                )
                % self.human_name,
                component_name=self.name,
            )
        return os.path.join(self.base_dir, version)

    @property
    def version_choices(self):
        _choices = [
            (_("Manual"), "manual"),
        ]
        for version in self.versions:
            _choices.append((version, version))
        return _choices

    def load_versions(self) -> list:
        dll_versions = list(self.known_versions)
        if not system.path_exists(self.versions_path):
            return dll_versions

        with open(self.versions_path, "r", encoding="utf-8") as dll_version_file:
            try:
                file_versions = [v["tag_name"] for v in json.load(dll_version_file)]
            except (KeyError, json.decoder.JSONDecodeError):
                logger.warning(
                    "Invalid versions file %s, deleting so it is downloaded on next start.", self.versions_path
                )
                os.remove(self.versions_path)
                return dll_versions
        for file_version in file_versions:
            if file_version not in dll_versions:
                dll_versions.append(file_version)

        # Ensure the versions.json specified version is present and
        # is the default by moving it to the top.
        versions = get_runtime_versions()
        runtimes = versions.get("runtimes")
        if runtimes:
            runtime = runtimes.get(self.name)
            if runtime and runtime.get("versioned"):
                default_version = runtime.get("version")
                if default_version:
                    if default_version in dll_versions:
                        dll_versions.remove(default_version)
                    dll_versions.insert(0, default_version)

        return dll_versions

    @staticmethod
    def is_managed_dll(dll_path):
        """Check if a given DLL path is provided by the component"""
        return False

    def is_available(self):
        """Return whether component is cached locally"""
        return self.version and system.path_exists(self.path)

    def dll_exists(self, dll_name):
        """Check if the dll is provided by the component
        The DLL might not be available for all architectures so
        only check if one exists for the supported ones
        """
        return any(system.path_exists(os.path.join(self.path, arch, dll_name + ".dll")) for arch in self.archs.values())

    def get_download_url(self):
        """Fetch the download URL from the JSON version file"""
        if self.version in self.known_versions:
            return self.known_versions[self.version]
        with open(self.versions_path, "r", encoding="utf-8") as version_file:
            releases = json.load(version_file)
        for release in releases:
            if release["tag_name"] != self.version:
                continue
            return release["assets"][0]["browser_download_url"]

    def download(self):
        """Download component to the local cache; returns True if successful but False
        if the component could not be downloaded."""
        if self.is_available():
            logger.warning("%s already available at %s", self.human_name, self.path)

        if not system.path_exists(self.versions_path):
            self.fetch_versions()

        url = self.get_download_url()
        if not url:
            logger.warning("Could not find a release for %s %s", self.human_name, self.version)
            return False
        archive_path = os.path.join(self.base_dir, os.path.basename(url))
        logger.info("Downloading %s to %s", url, archive_path)
        download_file(url, archive_path, overwrite=True)
        if not system.path_exists(archive_path) or not os.stat(archive_path).st_size:
            logger.error("Failed to download %s %s", self.human_name, self.version)
            return False
        logger.info("Extracting %s to %s", archive_path, self.path)
        extract_archive(archive_path, self.path, merge_single=True)
        os.remove(archive_path)
        return True

    def enable_dll(self, system_dir, arch, dll_path):
        """Copies dlls to the appropriate destination"""
        dll = os.path.basename(dll_path)
        if system.path_exists(dll_path):
            wine_dll_path = os.path.join(system_dir, dll)
            if system.path_exists(wine_dll_path):
                if not self.is_managed_dll(wine_dll_path) and not os.path.islink(wine_dll_path):
                    # Backing up original version (may not be needed)
                    shutil.move(wine_dll_path, wine_dll_path + ".orig")
                else:
                    os.remove(wine_dll_path)
            system.create_symlink(dll_path, wine_dll_path)
        else:
            self.disable_dll(system_dir, arch, dll)

    def disable_dll(self, system_dir, _arch, dll):  # pylint: disable=unused-argument
        """Remove DLL from Wine prefix"""
        wine_dll_path = os.path.join(system_dir, "%s.dll" % dll)
        if system.path_exists(wine_dll_path + ".orig"):
            if system.path_exists(wine_dll_path):
                os.remove(wine_dll_path)
            shutil.move(wine_dll_path + ".orig", wine_dll_path)

    def enable_user_file(self, appdata_dir, file_path, source_path):
        if system.path_exists(source_path):
            wine_file_path = os.path.join(appdata_dir, file_path)
            wine_file_dir = os.path.dirname(wine_file_path)
            if system.path_exists(wine_file_path):
                if not os.path.islink(wine_file_path):
                    # Backing up original version (may not be needed)
                    shutil.move(wine_file_path, wine_file_path + ".orig")
                else:
                    os.remove(wine_file_path)

            if not os.path.isdir(wine_file_dir):
                os.makedirs(wine_file_dir)
            system.create_symlink(source_path, wine_file_path)
        else:
            self.disable_user_file(appdata_dir, file_path)

    def disable_user_file(self, appdata_dir, file_path):
        wine_file_path = os.path.join(appdata_dir, file_path)
        # We only create a symlink; if it is a real file, it mus tbe user data.
        if system.path_exists(wine_file_path) and os.path.islink(wine_file_path):
            os.remove(wine_file_path)
            if system.path_exists(wine_file_path + ".orig"):
                shutil.move(wine_file_path + ".orig", wine_file_path)

    def _iter_dlls(self):
        windows_path = os.path.join(self.prefix, "drive_c/windows")
        if self.wine_arch == "win64":
            system_dirs = {
                self.archs[64]: os.path.join(windows_path, "system32"),
                self.archs[32]: os.path.join(windows_path, "syswow64"),
            }
        elif self.wine_arch == "win32":
            system_dirs = {self.archs[32]: os.path.join(windows_path, "system32")}

        for arch, system_dir in system_dirs.items():
            for dll in self.managed_dlls:
                yield system_dir, arch, dll

    def _iter_appdata_files(self):
        if self.managed_appdata_files:
            prefix_manager = WinePrefixManager(self.prefix)
            appdata_dir = prefix_manager.appdata_dir
            for file in self.managed_appdata_files:
                filename = os.path.basename(file)
                yield appdata_dir, file, filename

    def setup(self, enable):
        """Enable or disable DLLs"""

        # manual version only sets the dlls to native (in get_enabling_dll_overrides())
        manager_version = self.version
        if not manager_version or manager_version.lower() != "manual":
            if enable:
                self.enable()
            else:
                self.disable()

    def get_enabling_dll_overrides(self):
        """Returns aa dll-override dict for the dlls in this manager; these options will
        enable the manager's dll, so call this only for enabled managers."""
        overrides = {}

        for dll in self.managed_dlls:
            # We have to make sure that the dll exists before setting it to native.
            # Native-then-builtin: wrappers require native first with a builtin fallback.
            if self.dll_exists(dll):
                overrides[dll] = "n,b"

        return overrides

    def can_enable(self):
        return True

    def enable(self):
        """Enable Dlls for the current prefix"""
        if not self.is_available():
            if not self.download():
                logger.error(
                    "%s %s could not be enabled because it is not available locally", self.human_name, self.version
                )
                return
        for system_dir, arch, dll in self._iter_dlls():
            dll_path = os.path.join(self.path, arch, "%s.dll" % dll)
            self.enable_dll(system_dir, arch, dll_path)
        for appdata_dir, file, filename in self._iter_appdata_files():
            source_path = os.path.join(self.path, filename)
            self.enable_user_file(appdata_dir, file, source_path)

    def disable(self):
        """Disable DLLs for the current prefix"""
        for system_dir, arch, dll in self._iter_dlls():
            self.disable_dll(system_dir, arch, dll)
        for appdata_dir, file, _filename in self._iter_appdata_files():
            self.disable_user_file(appdata_dir, file)

    def _copy_with_confirm(self, source, dest, confirmer=None, label=None):
        """Copy source to dest, asking first when dest exists with different content.

        Returns True when the file was deployed (or was already correct),
        None when the user kept their file, False on failure. Symlinks are
        always replaced without asking; they can only be Lutris leftovers."""
        try:
            if system.path_exists(dest):
                if os.path.islink(dest):
                    os.remove(dest)
                elif filecmp.cmp(source, dest, shallow=False):
                    return True
                elif confirmer and not confirmer(dest, label or os.path.basename(dest)):
                    logger.info("Keeping existing %s.", dest)
                    return None
            shutil.copy2(source, dest)
            logger.info("Deployed %s to %s.", os.path.basename(source), dest)
            return True
        except OSError as ex:
            logger.warning("Failed to deploy %s to %s: %s", source, dest, ex)
            return False

    def deploy_game_dlls(self, game_dir, exe_path=None, confirmer=None):
        """Deploy the wrapper's DLLs next to the game as a version-matched set.

        Unlike prefix deployment this survives Proton prefix updates, and it
        keeps stub and core DLLs (e.g. dxwrapper) at the same version.
        Returns True when the game-dir route was viable; per-file failures
        are logged (the caller may fall back to prefix deployment)."""
        if not self.is_available():
            logger.warning("%s is not available locally, skipping game DLLs.", self.human_name)
            return False
        if not system.path_exists(game_dir):
            logger.warning("Game directory %s does not exist, skipping game DLLs.", game_dir)
            return False
        arch_dir = os.path.join(self.path, self.archs[32])
        failed = False
        for dll in self.managed_dlls:
            source = os.path.join(arch_dir, "%s.dll" % dll)
            if not system.path_exists(source):
                continue
            dest = os.path.join(game_dir, "%s.dll" % dll)
            if self._copy_with_confirm(source, dest, confirmer, "%s %s.dll" % (self.human_name, dll)) is False:
                failed = True
        return not failed

    def cleanup_game_dlls(self, game_dir, keep=()):
        """Remove this wrapper's game-dir DLLs left from earlier use, e.g.
        after switching to another wrapper.

        Only removes files Lutris deployed itself (byte-identical to the
        local copy), never files owned by an enabled wrapper (keep) and
        never user data."""
        if not self.is_available():
            return
        arch_dir = os.path.join(self.path, self.archs[32])
        for dll in self.managed_dlls:
            filename = "%s.dll" % dll
            if filename in keep:
                continue
            source = os.path.join(arch_dir, filename)
            dest = os.path.join(game_dir, filename)
            if not system.path_exists(source) or not system.path_exists(dest):
                continue
            try:
                if os.path.islink(dest) or not filecmp.cmp(source, dest, shallow=False):
                    continue
                os.remove(dest)
                logger.info("Removed stale %s.", dest)
            except OSError as ex:
                logger.warning("Failed to remove stale %s: %s", dest, ex)

    def deploy_game_files(self, game_dir):
        """Copy wrapper support files (configs, shaders) next to the game.

        Only deploys when the component is available locally, and never
        overwrites files that already exist, so user tuning is preserved.
        Game-dir files are left in place when the wrapper is disabled."""
        if not self.game_files:
            return
        if not self.is_available():
            logger.warning("%s is not available locally, skipping game files.", self.human_name)
            return
        if not system.path_exists(game_dir):
            logger.warning("Game directory %s does not exist, skipping game files.", game_dir)
            return
        for source_rel, dest_name in self.game_files.items():
            source = os.path.join(self.path, source_rel)
            if not system.path_exists(source):
                logger.debug("Optional %s file %s not found, skipping.", self.human_name, source_rel)
                continue
            dest = os.path.join(game_dir, dest_name)
            if system.path_exists(dest):
                logger.debug("Keeping existing %s.", dest)
                continue
            try:
                if os.path.isdir(source):
                    shutil.copytree(source, dest)
                else:
                    shutil.copy2(source, dest)
                logger.info("Deployed %s to %s.", source_rel, dest)
            except OSError as ex:
                logger.warning("Failed to deploy %s to %s: %s", source, dest, ex)

    def fetch_versions(self):
        """Get releases from GitHub"""
        if not os.path.isdir(self.base_dir):
            os.mkdir(self.base_dir)
        download_file(self.releases_url, self.versions_path, overwrite=True)

    def upgrade(self):
        if not self.is_available():
            versions = self.load_versions()

            if not versions:
                logger.warning("Unable to download %s because version information was not available.", self.human_name)

            # We prefer recommended versions, so download those first.
            versions.sort(key=self.is_recommended_version, reverse=True)

            for version in versions:
                logger.info("Downloading %s %s...", self.human_name, version)
                self.download()

                if self.is_compatible_version(version):
                    return  # got a compatible version, that'll do.

                logger.warning(
                    "Version %s of %s is not compatible with this version of Lutris.", version, self.human_name
                )

            # We found nothing compatible, and downloaded everything, we just give up.
