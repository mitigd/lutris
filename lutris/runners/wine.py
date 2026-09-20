"""Wine runner"""

# pylint: disable=too-many-lines
import os
import shlex
import threading
from collections.abc import Iterable
from gettext import gettext as _
from typing import TYPE_CHECKING, Any

from lutris import runtime, settings
from lutris.api import format_runner_version, normalize_version_architecture
from lutris.config import LutrisConfig
from lutris.database.games import get_game_by_field
from lutris.exceptions import (
    EsyncLimitError,
    FsyncUnsupportedError,
    MisconfigurationError,
    MissingExecutableError,
    MissingGameExecutableError,
    SymlinkNotUsableError,
    UnspecifiedVersionError,
)
from lutris.game import Game
from lutris.gui.dialogs import FileDialog
from lutris.runners.commands.wine import (  # noqa: F401 pylint: disable=unused-import
    create_prefix,
    delete_registry_key,
    eject_disc,
    install_cab_component,
    open_wine_terminal,
    set_regedit,
    set_regedit_file,
    winecfg,
    wineexec,
    winekill,
    winetricks,
)
from lutris.runners.runner import RunDataDict, Runner
from lutris.util import system
from lutris.util.display import DISPLAY_MANAGER, get_default_dpi, is_display_x11
from lutris.util.graphics import drivers, vkquery
from lutris.util.jobs import AsyncCall
from lutris.util.linux import LINUX_SYSTEM
from lutris.util.log import logger
from lutris.util.process import Process
from lutris.util.strings import split_arguments
from lutris.util.wine import dxvk_conf, proton
from lutris.util.wine.cnc_ddraw import CncDdrawManager
from lutris.util.wine.cnc_ddraw_conf import (
    build_runner_options as build_cnc_ddraw_conf_options,
)
from lutris.util.wine.cnc_ddraw_conf import (
    get_managed_values as get_managed_cnc_ddraw_conf_values,
)
from lutris.util.wine.cnc_ddraw_conf import (
    write_cnc_ddraw_conf,
)
from lutris.util.wine.d3d_extras import D3DExtrasManager
from lutris.util.wine.d7vk import D7vkManager
from lutris.util.wine.dgvoodoo2 import dgvoodoo2Manager
from lutris.util.wine.dxgl import DxglManager
from lutris.util.wine.dxvk import REQUIRED_VULKAN_API_VERSION, DXVKManager
from lutris.util.wine.dxvk_conf import (
    build_runner_options as build_dxvk_conf_options,
)
from lutris.util.wine.dxvk_conf import (
    get_managed_values as get_managed_dxvk_conf_values,
)
from lutris.util.wine.dxvk_conf import (
    write_dxvk_conf,
)
from lutris.util.wine.dxvk_nvapi import DXVKNVAPIManager
from lutris.util.wine.dxwrapper import DxWrapperManager
from lutris.util.wine.dxwrapper_conf import (
    build_runner_options as build_dxwrapper_conf_options,
)
from lutris.util.wine.dxwrapper_conf import (
    get_managed_values as get_managed_dxwrapper_conf_values,
)
from lutris.util.wine.dxwrapper_conf import (
    write_dxwrapper_conf,
)
from lutris.util.wine.extract_icon import PEFILE_AVAILABLE, IconExtractor
from lutris.util.wine.prefix import DEFAULT_DLL_OVERRIDES, WinePrefixManager, find_prefix
from lutris.util.wine.vkd3d import VKD3DManager
from lutris.util.wine.wine import (
    GE_PROTON_LATEST,
    WINE_DEFAULT_ARCH,
    WINE_PATHS,
    detect_arch,
    get_default_wine_version,
    get_installed_wine_versions,
    get_overrides_env,
    get_real_executable,
    get_runner_files_dir_for_version,
    get_system_wine_version,
    get_wine_path_for_version,
    is_esync_limit_set,
    is_fsync_supported,
    is_gstreamer_build,
    is_winewayland_available,
)

if TYPE_CHECKING:
    from lutris.api import RunnerVersionDict
    from lutris.monitored_command import MonitoredCommand


def is_umu_managed_version(version: str | None) -> bool:
    """True if this Wine 'version' is actually launched through umu: the 'ge-proton'
    sentinel or any Proton build. umu fetches Proton on demand, so there is no Wine
    runner build for Lutris to download or install for these versions."""
    return version == GE_PROTON_LATEST or proton.is_proton_version(version)


def _is_proton_config(config: LutrisConfig) -> bool:
    return is_umu_managed_version(config.runner_config.get("version"))


def _is_pre_proton(_option_key: str, config: LutrisConfig) -> bool:
    return not _is_proton_config(config)


def _is_proton_hdr_available(_option_key: str, config: LutrisConfig) -> bool:
    if _is_proton_config(config):
        version = config.runner_config.get("version")
        return bool(version and is_winewayland_available(version) and config.runner_config.get("Graphics") == "wayland")

    return False


def _get_version_warning(_option_key: str, config: LutrisConfig) -> str | None:
    arch = config.game_config.get("arch")
    if arch == "win32" and _is_proton_config(config):
        return _("Proton is not compatible with 32-bit prefixes.")

    return None


def _get_prefix_warning(_option_key: str, config: LutrisConfig) -> str | None:
    game_config = config.game_config
    if game_config.get("prefix"):
        return None

    exe = game_config.get("exe")
    if exe and find_prefix(exe):
        return None

    return _("<b>Warning</b> Some Wine configuration options cannot be applied, if no prefix can be found.")


def _get_exe_warning(_option_key: str, config: LutrisConfig) -> str | None:
    exe = config.game_config.get("exe") or ""
    stripped_exe = exe.strip()

    if not stripped_exe:
        return _("<b>Warning</b> No executable path specified")
    if exe != stripped_exe:
        return _("<b>Warning</b> Executable path has extra whitespace at the beginning or end")
    if not os.path.isabs(exe):
        # The working dir is a bit dicey- Lutris doe snot use the prefix as a working dir,
        # but it seems like Wine does, so we'll be conservative here. Only works with an explicit
        # prefix- if we derive it from "exe" we obviosly can't use that.
        working_dir = config.game_config.get("working_dir") or config.game_config.get("prefix") or ""
        exe = os.path.join(os.path.expanduser(working_dir), os.path.expanduser(exe))

    exe = system.fix_path_case(exe)

    if not os.path.isfile(exe):
        return _("<b>Warning</b> Executable file does not exist")

    return None


def _get_dxvk_warning() -> str | None:
    if drivers.is_outdated():
        driver_info = drivers.get_nvidia_driver_info()
        return _(
            "<b>Warning</b> Your NVIDIA driver is outdated.\n"
            "You are currently running driver %s which does not "
            "fully support all features for Vulkan and DXVK games."
        ) % (driver_info["version"],)

    return None


def _get_simple_vulkan_support_error(option_key: str, config: LutrisConfig, feature: str) -> str | None:
    if os.environ.get("LUTRIS_NO_VKQUERY"):
        return None
    if config.runner_config.get(option_key) and not LINUX_SYSTEM.is_vulkan_supported():
        return (
            _("<b>Error</b> Vulkan is not installed or is not supported by your system, %s is not available.") % feature
        )
    return None


def _get_dxvk_version_warning(_option_key: str, config: LutrisConfig) -> str | None:
    if os.environ.get("LUTRIS_NO_VKQUERY"):
        return None
    runner_config = config.runner_config
    if runner_config.get("dxvk") and LINUX_SYSTEM.is_vulkan_supported():
        version = runner_config.get("dxvk_version")
        if version is not None:
            version = str(version)
        if version and not version.startswith("v1."):
            library_api_version = vkquery.get_vulkan_api_version()
            if library_api_version and library_api_version < REQUIRED_VULKAN_API_VERSION:
                return _(
                    "<b>Warning</b> Lutris has detected that Vulkan API version %s is installed, "
                    "but to use the latest DXVK version, %s is required."
                ) % (vkquery.format_version(library_api_version), vkquery.format_version(REQUIRED_VULKAN_API_VERSION))

            devices = vkquery.get_device_info()

            if devices and devices[0].api_version < REQUIRED_VULKAN_API_VERSION:
                return _(
                    "<b>Warning</b> Lutris has detected that the best device available ('%s') supports Vulkan API %s, "
                    "but to use the latest DXVK version, %s is required."
                ) % (
                    devices[0].name,
                    vkquery.format_version(devices[0].api_version),
                    vkquery.format_version(REQUIRED_VULKAN_API_VERSION),
                )

    return None


# Every option providing its own ddraw.dll; at most one of these should be
# enabled at a time (dgvoodoo2 has no UI option anymore, but existing
# configurations may still enable it). The wrapper owns ddraw.dll through a
# native override, while DXVK keeps handling Direct3D 8/9/11 - so chains
# like DxWrapper's Dd7to9 (DDraw -> D3D9) feeding into DXVK work, including
# on Wine builds with DXVK-based DDraw such as CachyOS Wine (d7vk).
DDRAW_PROVIDER_OPTIONS = ("dgvoodoo2", "dxwrapper", "dxgl", "cnc_ddraw", "d7vk")

# All DLL managers with their toggle and version options: (manager class,
# enabled option, version option). Game-dir deployment for these is available
# without a prefix; keep this as the single list get_dll_managers uses.
DLL_MANAGER_CLASSES = [
    (DXVKManager, "dxvk", "dxvk_version"),
    (D7vkManager, "d7vk", "d7vk_version"),
    (VKD3DManager, "vkd3d", "vkd3d_version"),
    (DXVKNVAPIManager, "dxvk_nvapi", "dxvk_nvapi_version"),
    (D3DExtrasManager, "d3d_extras", "d3d_extras_version"),
    (dgvoodoo2Manager, "dgvoodoo2", "dgvoodoo2_version"),
    (DxWrapperManager, "dxwrapper", "dxwrapper_version"),
    (DxglManager, "dxgl", "dxgl_version"),
    (CncDdrawManager, "cnc_ddraw", "cnc_ddraw_version"),
]

# Tracks in-flight background downloads so rapid toggling can't start two
# downloads of the same component.
_DLL_DEPLOY_LOCKS: dict[str, threading.Lock] = {}

DDRAW_WRAPPER_LABELS = {
    "dgvoodoo2": "dgvoodoo2",
    "dxwrapper": "DxWrapper",
    "dxgl": "DXGL",
    "cnc_ddraw": "CnC-DDraw",
    "d7vk": "D7VK",
}

# Runner toggles whose switch-off immediately cleans up deployed files
# (the launch-time prelaunch path remains the backstop).
DLL_CLEANUP_TRIGGERS = ("dxvk", "dxwrapper", "dxgl", "cnc_ddraw", "d7vk")


def _get_ddraw_wrapper_warning(option_key: str, config: LutrisConfig) -> str | None:
    runner_config = config.runner_config
    if not runner_config.get(option_key):
        return None
    others = [
        DDRAW_WRAPPER_LABELS[opt] for opt in DDRAW_PROVIDER_OPTIONS if opt != option_key and runner_config.get(opt)
    ]
    if others:
        return _("Another DirectDraw wrapper (%s) is also enabled; only one wrapper can provide ddraw.dll.") % (
            ", ".join(others)
        )
    return None


def is_sarek_available_for_version(version: str | None) -> bool:
    """True if the Wine build ships DXVK-Sarek (a dxvk-sarek directory)."""
    if not version:
        return False
    try:
        files_dir = get_runner_files_dir_for_version(version)
    except Exception as ex:  # noqa: BLE001 - unknown versions simply have no Sarek
        logger.debug("Could not resolve files for Wine version %s: %s", version, ex)
        return False
    if not files_dir:
        return False
    return os.path.isdir(os.path.join(files_dir, "lib", "wine", "dxvk-sarek"))


def _is_sarek_available(_option_key: str, config: LutrisConfig) -> bool:
    version = config.runner_config.get("version") or get_default_wine_version()
    return is_sarek_available_for_version(version)


def _is_sarek_off(_option_key: str, config: LutrisConfig) -> bool:
    return not bool(config.runner_config.get("sarek"))


def _get_sarek_warning(_option_key: str, config: LutrisConfig) -> str | None:
    if config.runner_config.get("sarek"):
        return _(
            "<b>Warning</b> DXVK-Sarek is enabled, so it supersedes the DXVK and D7VK toggles; "
            "those DLLs will not be installed while Sarek is active."
        )
    return None


def _get_d7vk_warning(option_key: str, config: LutrisConfig) -> str | None:
    runner_config = config.runner_config
    if not runner_config.get("d7vk"):
        return None
    messages = []
    if not runner_config.get("dxvk"):
        messages.append(_("D7VK proxies D3D7 and earlier through DXVK's D3D9 backend; enable DXVK as well."))
    multi = _get_ddraw_wrapper_warning(option_key, config)
    if multi:
        messages.append(multi)
    return " ".join(messages) or None


def _get_esync_warning(_option_key: str, config: LutrisConfig) -> str | None:
    if config.runner_config.get("esync"):
        limits_set = is_esync_limit_set()
        if not limits_set:
            return _(
                "<b>Warning</b> Your limits are not set correctly. Please increase them as described here:\n"
                "<a href='https://github.com/lutris/docs/blob/master/HowToEsync.md'>"
                "How-to-Esync (https://github.com/lutris/docs/blob/master/HowToEsync.md)</a>"
            )
    return ""


def _get_fsync_warning(_option_key: str, config: LutrisConfig) -> str | None:
    if config.runner_config.get("fsync"):
        fsync_supported = is_fsync_supported()
        if not fsync_supported:
            return _("<b>Warning</b> Your kernel is not patched for fsync.")
    return None


def _get_virtual_desktop_warning(_option_key: str, config: LutrisConfig) -> str | None:
    message = _("Wine virtual desktop is no longer supported")
    runner_config = config.runner_config
    if runner_config.get("Desktop"):
        version = str(runner_config.get("version")).casefold()
        if "-ge-" in version or "proton" in version:
            message += "\n"
            message += _("Virtual desktops cannot be enabled in Proton or GE Wine versions.")
    return message


def _get_wine_wayland_warning(_option_key: str, config: LutrisConfig) -> str | None:
    runner_config = config.runner_config
    if runner_config.get("Graphics") == "wayland":
        runner_version = runner_config.get("version")

        if not runner_version:
            return None

        if is_display_x11():
            return _("You cannot use winewayland driver when using an X11-based session")

        if not is_winewayland_available(runner_version):
            if _is_proton_config(config):
                return _("Your Proton version does not support winewayland graphics driver")
            else:
                return _("Your Wine version does not support winewayland graphics driver")

    return None


def _get_wine_version_choices():
    version_choices = [(_("Custom (select executable below)"), "custom")]
    system_wine_labels = {
        "winehq-devel": _("WineHQ Devel ({})"),
        "winehq-staging": _("WineHQ Staging ({})"),
        "wine-development": _("Wine Development ({})"),
        "system": _("System ({})"),
    }
    versions = get_installed_wine_versions()
    for version in versions:
        if version == GE_PROTON_LATEST:
            label = _("GE-Proton (Latest)")
        elif version in system_wine_labels:
            version_number = get_system_wine_version(WINE_PATHS[version])
            label = system_wine_labels[version].format(version_number)
        else:
            label = version
        version_choices.append((label, version))
    return version_choices


class wine(Runner):
    description: str = _("Runs Windows games")
    human_name = _("Wine")
    platform_dict = Runner.to_platform_dict([_("Windows")])
    multiple_versions = True
    entry_point_option = "exe"

    game_options = [
        {
            "option": "exe",
            "type": "file",
            "label": _("Executable"),
            "help": _("The game's main EXE file"),
            "warning": _get_exe_warning,
        },
        {
            "option": "args",
            "type": "string",
            "label": _("Arguments"),
            "help": _("Windows command line arguments used when launching the game"),
            "validator": shlex.split,
        },
        {
            "option": "working_dir",
            "type": "directory",
            "label": _("Working directory"),
            "help": _(
                "The location where the game is run from.\nBy default, Lutris uses the directory of the executable."
            ),
        },
        {
            "option": "prefix",
            "type": "directory",
            "label": _("Wine prefix"),
            "warning": _get_prefix_warning,
            "help": _(
                "The prefix used by Wine.\n"
                "It's a directory containing a set of files and "
                "folders making up a confined Windows environment."
            ),
        },
        {
            "option": "arch",
            "type": "choice",
            "label": _("Prefix architecture"),
            "visible": _is_pre_proton,
            "choices": [(_("Auto"), "auto"), (_("32-bit"), "win32"), (_("64-bit"), "win64")],
            "default": "auto",
            "help": _("The architecture of the Windows environment"),
        },
        {
            "option": "desktop_integration",
            "type": "bool",
            "label": _("Integrate system files in the prefix"),
            "default": False,
            "advanced": True,
            "help": _(
                "Place 'Documents', 'Pictures', and similar files in your home folder, instead of "
                "keeping them in the game's prefix. This includes some saved games."
            ),
        },
    ]

    runner_options = [
        {
            "option": "version",
            "label": _("Wine version"),
            "type": "choice",
            "choices": _get_wine_version_choices,
            "default": get_default_wine_version,
            "warning": _get_version_warning,
            "help": _(
                "The version of Wine used to launch the game.\n"
                "Using the last version is generally recommended, "
                "but some games work better on older versions."
            ),
        },
        {
            "option": "custom_wine_path",
            "label": _("Custom Wine executable"),
            "type": "file",
            "advanced": True,
            "help": _('The Wine executable to be used if you have selected "Custom" as the Wine version.'),
        },
        {
            "option": "system_winetricks",
            "label": _("Use system winetricks"),
            "type": "bool",
            "default": False,
            "advanced": True,
            "help": _("Switch on to use /usr/bin/winetricks for winetricks."),
        },
        {
            "option": "dxvk",
            "section": _("Graphics"),
            "label": _("Enable DXVK"),
            "type": "bool",
            "default": True,
            "condition": _is_sarek_off,
            "warning": _get_dxvk_warning,
            "error": lambda k, c: _get_simple_vulkan_support_error(k, c, _("DXVK")),
            "active": True,
            "help": _(
                "Use DXVK to "
                "increase compatibility and performance in Direct3D 11, 10 "
                "and 9 applications by translating their calls to Vulkan."
            ),
        },
        {
            "option": "dxvk_version",
            "section": _("Graphics"),
            "label": _("DXVK version"),
            "advanced": True,
            "type": "choice_with_entry",
            "visible": _is_pre_proton,
            "condition": LINUX_SYSTEM.is_vulkan_supported,
            "conditional_on": "dxvk",
            "choices": lambda: DXVKManager().version_choices,
            "default": lambda: DXVKManager().version,
            "warning": _get_dxvk_version_warning,
        },
        {
            "option": "d7vk",
            "section": _("Graphics"),
            "label": _("Enable D7VK"),
            "type": "bool",
            "default": False,
            "condition": _is_sarek_off,
            "warning": _get_d7vk_warning,
            "help": _(
                "Use D7VK for Direct3D 7 and earlier 3D games: a minimal D3D7/6/5/3 "
                "implementation proxying through DXVK's D3D9 backend, using Wine's "
                "DDraw implementation. Requires DXVK. Only 32-bit applications are supported."
            ),
        },
        {
            "option": "d7vk_version",
            "section": _("Graphics"),
            "label": _("D7VK version"),
            "advanced": True,
            "type": "choice_with_entry",
            "conditional_on": "d7vk",
            "choices": lambda: D7vkManager().version_choices,
            "default": lambda: D7vkManager().version,
        },
        {
            "option": "sarek",
            "section": _("Graphics"),
            "label": _("Enable DXVK-Sarek"),
            "type": "bool",
            "default": False,
            "advanced": True,
            "visible": _is_sarek_available,
            "warning": _get_sarek_warning,
            "error": lambda k, c: _get_simple_vulkan_support_error(k, c, _("DXVK-Sarek")),
            "help": _(
                "Use the DXVK-Sarek fork bundled with this Wine build instead of DXVK. "
                "Sarek targets pre-Vulkan-1.3 GPUs and includes DDraw support, so it "
                "supersedes the DXVK and D7VK toggles while active. Only shown when "
                "the selected Wine version ships Sarek, such as proton-cachyos."
            ),
        },
        {
            "option": "vkd3d",
            "section": _("Graphics"),
            "label": _("Enable VKD3D"),
            "type": "bool",
            "visible": _is_pre_proton,
            "error": lambda k, c: _get_simple_vulkan_support_error(k, c, _("VKD3D")),
            "default": True,
            "active": True,
            "help": _("Use VKD3D to enable support for Direct3D 12 applications by translating their calls to Vulkan."),
        },
        {
            "option": "vkd3d_version",
            "section": _("Graphics"),
            "label": _("VKD3D version"),
            "advanced": True,
            "type": "choice_with_entry",
            "visible": _is_pre_proton,
            "condition": LINUX_SYSTEM.is_vulkan_supported,
            "conditional_on": "vkd3d",
            "choices": lambda: VKD3DManager().version_choices,
            "default": lambda: VKD3DManager().version,
        },
        {
            "option": "d3d_extras",
            "section": _("Graphics"),
            "label": _("Enable D3D Extras"),
            "type": "bool",
            "default": True,
            "advanced": True,
            "help": _(
                "Replace Wine's D3DX and D3DCOMPILER libraries with alternative ones. "
                "Needed for proper functionality of DXVK with some games."
            ),
        },
        {
            "option": "d3d_extras_version",
            "section": _("Graphics"),
            "label": _("D3D Extras version"),
            "advanced": True,
            "conditional_on": "d3d_extras",
            "type": "choice_with_entry",
            "choices": lambda: D3DExtrasManager().version_choices,
            "default": lambda: D3DExtrasManager().version,
        },
        {
            "option": "dxvk_nvapi",
            "section": _("Graphics"),
            "label": _("Enable DXVK-NVAPI / DLSS"),
            "type": "bool",
            "error": lambda k, c: _get_simple_vulkan_support_error(k, c, _("DXVK-NVAPI / DLSS")),
            "default": True,
            "advanced": True,
            "visible": _is_pre_proton,
            "help": _("Enable emulation of Nvidia's NVAPI and add DLSS support, if available."),
        },
        {
            "option": "dxvk_nvapi_version",
            "section": _("Graphics"),
            "label": _("DXVK NVAPI version"),
            "advanced": True,
            "conditional_on": "dxvk_nvapi",
            "visible": _is_pre_proton,
            "type": "choice_with_entry",
            "choices": lambda: DXVKNVAPIManager().version_choices,
            "default": lambda: DXVKNVAPIManager().version,
        },
        {
            "option": "dxwrapper",
            "section": _("Graphics"),
            "label": _("Enable DxWrapper"),
            "type": "bool",
            "default": False,
            "warning": _get_ddraw_wrapper_warning,
            "help": _(
                "Use DxWrapper to translate DirectDraw, Direct3D 8 and Direct3D 9 calls "
                "for legacy games. Only 32-bit applications are supported. "
                "Combines with DXVK, which keeps handling Direct3D 8/9/11 (e.g. Dd7to9 output)."
            ),
        },
        {
            "option": "dxwrapper_version",
            "section": _("Graphics"),
            "label": _("DxWrapper version"),
            "advanced": True,
            "type": "choice_with_entry",
            "conditional_on": "dxwrapper",
            "choices": lambda: DxWrapperManager().version_choices,
            "default": lambda: DxWrapperManager().version,
        },
        {
            "option": "dxgl",
            "section": _("Graphics"),
            "label": _("Enable DXGL"),
            "type": "bool",
            "default": False,
            "warning": _get_ddraw_wrapper_warning,
            "help": _(
                "Use DXGL to translate DirectDraw calls to OpenGL for legacy games. "
                "Only 32-bit applications are supported. "
            ),
        },
        {
            "option": "dxgl_version",
            "section": _("Graphics"),
            "label": _("DXGL version"),
            "advanced": True,
            "type": "choice_with_entry",
            "conditional_on": "dxgl",
            "choices": lambda: DxglManager().version_choices,
            "default": lambda: DxglManager().version,
        },
        {
            "option": "cnc_ddraw",
            "section": _("Graphics"),
            "label": _("Enable CnC-DDraw"),
            "type": "bool",
            "default": False,
            "warning": _get_ddraw_wrapper_warning,
            "help": _(
                "Use CnC-DDraw to translate DirectDraw calls to OpenGL for legacy games. "
                "Only 32-bit applications are supported. "
            ),
        },
        {
            "option": "cnc_ddraw_version",
            "section": _("Graphics"),
            "label": _("CnC-DDraw version"),
            "advanced": True,
            "type": "choice_with_entry",
            "conditional_on": "cnc_ddraw",
            "choices": lambda: CncDdrawManager().version_choices,
            "default": lambda: CncDdrawManager().version,
        },
        {
            "option": "proton_hdr",
            "section": _("Graphics"),
            "label": _("Enable HDR (Experimental)"),
            "type": "bool",
            "default": False,
            "advanced": True,
            "visible": _is_proton_hdr_available,
            "help": _(
                "Enable Proton's support for High Dynamic Range graphics. "
                "Requires Wayland selected as Graphics backend."
            ),
        },
        {
            "option": "esync",
            "label": _("Enable Esync"),
            "type": "bool",
            "warning": _get_esync_warning,
            "active": True,
            "default": True,
            "help": _(
                "Enable eventfd-based synchronization (esync). "
                "This will increase performance in applications "
                "that take advantage of multi-core processors."
            ),
        },
        {
            "option": "fsync",
            "label": _("Enable Fsync"),
            "type": "bool",
            "default": is_fsync_supported,
            "warning": _get_fsync_warning,
            "active": True,
            "help": _(
                "Enable futex-based synchronization (fsync). "
                "This will increase performance in applications "
                "that take advantage of multi-core processors. "
                "Requires kernel 5.16 or above."
            ),
        },
        {
            "option": "fsr",
            "label": _("Enable AMD FidelityFX Super Resolution (FSR)"),
            "type": "bool",
            "default": True,
            "help": _(
                "Use FSR to upscale the game window to native resolution.\n"
                "Requires Lutris Wine FShack >= 6.13 and setting the game to a lower resolution.\n"
                "Does not work with games running in borderless window mode or that perform their own upscaling."
            ),
        },
        {
            "option": "battleye",
            "label": _("Enable BattlEye Anti-Cheat"),
            "type": "bool",
            "default": True,
            "help": _(
                "Enable support for BattlEye Anti-Cheat in supported games\n"
                "Requires Lutris Wine 6.21-2 and newer or any other compatible Wine build.\n"
            ),
        },
        {
            "option": "eac",
            "label": _("Enable Easy Anti-Cheat"),
            "type": "bool",
            "default": True,
            "help": _(
                "Enable support for Easy Anti-Cheat in supported games\n"
                "Requires Lutris Wine 7.2 and newer or any other compatible Wine build.\n"
            ),
        },
        {
            "option": "Desktop",
            "section": _("Virtual Desktop"),
            "label": _("Windowed (virtual desktop)"),
            "type": "bool",
            "advanced": True,
            "visible": _is_pre_proton,
            "warning": _get_virtual_desktop_warning,
            "default": False,
            "help": _(
                "Run the whole Windows desktop in a window.\n"
                "Otherwise, run it fullscreen.\n"
                "This corresponds to Wine's Virtual Desktop option."
            ),
        },
        {
            "option": "WineDesktop",
            "section": _("Virtual Desktop"),
            "label": _("Virtual desktop resolution"),
            "type": "choice_with_entry",
            "visible": _is_pre_proton,
            "conditional_on": "Desktop",
            "advanced": True,
            "choices": DISPLAY_MANAGER.get_resolutions,
            "help": _("The size of the virtual desktop in pixels."),
        },
        {
            "option": "Dpi",
            "section": _("DPI"),
            "label": _("Enable DPI Scaling"),
            "type": "bool",
            "advanced": True,
            "default": False,
            "help": _(
                "Enables the Windows application's DPI scaling.\n"
                "Otherwise, the Screen Resolution option in 'Wine configuration' controls this."
            ),
        },
        {
            "option": "ExplicitDpi",
            "section": _("DPI"),
            "label": _("DPI"),
            "type": "string",
            "conditional_on": "Dpi",
            "advanced": True,
            "default": str(get_default_dpi()),
            "help": _("The DPI to be used if 'Enable DPI Scaling' is turned on."),
        },
        {
            "option": "MouseWarpOverride",
            "label": _("Mouse Warp Override"),
            "type": "choice",
            "choices": [
                (_("Enable"), "enable"),
                (_("Disable"), "disable"),
                (_("Force"), "force"),
            ],
            "default": "enable",
            "advanced": True,
            "help": _(
                "Override the default mouse pointer warping behavior\n"
                "<b>Enable</b>: (Wine default) warp the pointer when the "
                "mouse is exclusively acquired \n"
                "<b>Disable</b>: never warp the mouse pointer \n"
                "<b>Force</b>: always warp the pointer"
            ),
        },
        {
            "option": "Audio",
            "label": _("Audio driver"),
            "type": "choice",
            "advanced": True,
            "choices": [
                (_("Auto"), "auto"),
                ("ALSA", "alsa"),
                ("PulseAudio", "pulse"),
                ("OSS", "oss"),
            ],
            "default": "auto",
            "help": _(
                "Which audio backend to use.\nBy default, Wine automatically picks the right one for your system."
            ),
        },
        {
            "option": "Graphics",
            "label": _("Graphics driver"),
            "type": "choice",
            "advanced": True,
            "choices": [
                (_("Auto"), "auto"),
                ("Wayland", "wayland"),
                ("X11", "x11"),
            ],
            "default": "auto",
            "warning": _get_wine_wayland_warning,
            "help": _(
                "Which graphics backend to use.\nBy default, Wine automatically picks the right one for your system."
            ),
        },
        {
            "option": "overrides",
            "type": "mapping",
            "label": _("DLL overrides"),
            "help": _("Sets WINEDLLOVERRIDES when launching the game."),
        },
        {
            "option": "show_debug",
            "label": _("Output debugging info"),
            "type": "choice",
            "choices": [
                (_("Disabled"), "-all"),
                (_("Enabled"), ""),
                (_("Inherit from environment"), "inherit"),
                (_("Show FPS"), "+fps"),
                (_("Full (CAUTION: Will cause MASSIVE slowdown)"), "+all"),
            ],
            "default": "-all",
            "help": _("Output debugging information in the game log (might affect performance)"),
        },
        {
            "option": "ShowCrashDialog",
            "label": _("Show crash dialogs"),
            "type": "bool",
            "default": False,
            "advanced": True,
        },
        {
            "option": "autoconf_joypad",
            "type": "bool",
            "label": _("Autoconfigure joypads"),
            "advanced": True,
            "default": False,
            "help": _("Automatically disables one of Wine's detected joypad to avoid having 2 controllers detected"),
        },
        *build_dxvk_conf_options(),
        *build_cnc_ddraw_conf_options(),
        *build_dxwrapper_conf_options(),
    ]

    reg_prefix = "HKEY_CURRENT_USER/Software/Wine"
    reg_keys = {
        "Audio": r"%s/Drivers" % reg_prefix,
        "Graphics": r"%s/Drivers" % reg_prefix,
        "MouseWarpOverride": r"%s/DirectInput" % reg_prefix,
        "Desktop": "MANAGED",
        "WineDesktop": "MANAGED",
        "ShowCrashDialog": "MANAGED",
    }

    core_processes = (
        "services.exe",
        "winedevice.exe",
        "plugplay.exe",
        "explorer.exe",
        "rpcss.exe",
        "rundll32.exe",
        "wineboot.exe",
    )

    def __init__(self, config=None, prefix=None, working_dir=None, wine_arch=None):  # noqa: C901
        super().__init__(config)
        self._prefix = prefix
        self._working_dir = working_dir
        self._wine_arch = wine_arch
        self.dll_overrides = DEFAULT_DLL_OVERRIDES.copy()  # we'll modify this, so we better copy it

    @property
    def context_menu_entries(self):
        """Return the contexual menu entries for wine"""
        return [
            ("wineexec", _("Run EXE inside Wine prefix"), self.run_wineexec),
            ("winereg", _("Run REG inside Wine prefix"), self.run_winereg),
            ("wineshell", _("Open Bash terminal"), self.run_wine_terminal),
            ("wineconsole", _("Open Wine console"), self.run_wineconsole),
            (None, "-", None),
            ("winecfg", _("Wine configuration"), self.run_winecfg),
            ("wine-regedit", _("Wine registry"), self.run_regedit),
            ("winecpl", _("Wine Control Panel"), self.run_winecpl),
            ("winetaskmgr", _("Wine Task Manager"), self.run_taskmgr),
            (None, "-", None),
            ("winetricks", _("Winetricks"), self.run_winetricks),
        ]

    @property
    def prefix_path(self):
        """Return the absolute path of the Wine prefix. Falls back to default WINE prefix."""
        _prefix_path = self._prefix or self.game_config.get("prefix") or os.environ.get("WINEPREFIX")
        if not _prefix_path and self.game_config.get("exe"):
            # Find prefix from game if we have one
            _prefix_path = find_prefix(self.game_exe)
        if _prefix_path:
            _prefix_path = os.path.expanduser(_prefix_path)  # just in case!
        return _prefix_path

    @property
    def game_exe(self):
        """Return the game's executable's path, which may not exist. None
        if there is no exe path defined."""
        exe = self.game_config.get("exe")
        if not exe:
            logger.error("The game doesn't have an executable")
            return None
        exe = os.path.expanduser(exe)  # just in case!
        if os.path.isabs(exe):
            return system.fix_path_case(exe)
        if not self.game_path:
            logger.warning("The game has an executable, but not a game path")
            return None
        return system.fix_path_case(os.path.join(self.game_path, exe))

    @property
    def has_working_dir(self) -> bool:
        return bool(self._get_explicit_working_dir() or super().has_working_dir)

    @property
    def working_dir(self):
        """Return the working directory to use when running the game."""
        return self._get_explicit_working_dir() or super().working_dir

    def _get_explicit_working_dir(self):
        _working_dir = self._working_dir or self.game_config.get("working_dir")
        if _working_dir:
            return os.path.expanduser(_working_dir)
        if self.game_exe:
            game_dir = os.path.dirname(self.game_exe)
            if os.path.isdir(game_dir):
                return game_dir
        return None

    @property
    def nvidia_shader_cache_path(self):
        """WINE should give each game its own shader cache if possible."""
        return self.game_path or self.shader_cache_dir

    @property
    def wine_arch(self):
        """Return the wine architecture.

        Get it from the config or detect it from the prefix"""
        arch = self._wine_arch or self.game_config.get("arch") or "auto"
        if arch not in ("win32", "win64"):
            prefix_path = self.prefix_path
            if prefix_path:
                arch = detect_arch(prefix_path, self.get_executable())
            else:
                arch = WINE_DEFAULT_ARCH
        return arch

    def get_runner_version(self, version: str | None = None) -> "RunnerVersionDict | None":
        if version in WINE_PATHS:
            return {"version": version}

        return super().get_runner_version(version)

    def read_version_from_config(self, default: str | None = None) -> str:
        """Return the Wine version to use. use_default can be set to false to
        force the installation of a specific wine version. If no version is configured,
        we return the default supplied, or the global Wine default if none is."""

        # We must use the config levels to avoid getting a default if the setting
        # is not set; we'll fall back to get_default_version()

        for level in [self.config.game_level, self.config.runner_level]:
            if "wine" in level:
                runner_version = level["wine"].get("version")
                # Treat 'ge-proton' as if no version is set
                if runner_version and runner_version != GE_PROTON_LATEST:
                    return runner_version

        if default:
            return default

        return get_default_wine_version()

    def get_path_for_version(self, version: str) -> str:
        """Return the absolute path of a wine executable for a given version"""
        return get_wine_path_for_version(version, config=self.runner_config)

    def resolve_config_path(self, path, relative_to=None):
        # Resolve paths with tolerance for Windows-isms;
        # first try to fix mismatched casing, and then if that
        # finds no file or directory, try again after swapping in
        # slashes for backslashes.

        resolved = super().resolve_config_path(path, relative_to)
        resolved = system.fix_path_case(resolved)

        if not os.path.exists(resolved) and "\\" in path:
            fixed = path.replace("\\", "/")
            fixed_resolved = super().resolve_config_path(fixed, relative_to)
            fixed_resolved = system.fix_path_case(fixed_resolved)
            return fixed_resolved

        return resolved

    def get_launch_config_exe(self, launch_config):
        """Resolve launch config exe relative to game_path, like game_exe does."""
        exe = launch_config.get("exe")
        if not exe:
            return None
        exe = os.path.expanduser(exe)
        if os.path.isabs(exe):
            return system.fix_path_case(exe)
        if self.game_path:
            return system.fix_path_case(os.path.join(self.game_path, exe))
        return exe

    def get_executable(self, version: str = "", fallback: bool = True) -> str:
        """Return the path to the Wine executable.
        A specific version can be specified if needed.
        """
        if not version:
            version = self.read_version_from_config()
        if version == GE_PROTON_LATEST:
            return proton.get_umu_path()

        if proton.is_proton_version(version):
            return proton.get_proton_wine_path(version)
        try:
            wine_path = self.get_path_for_version(version)
            if system.path_exists(wine_path):
                return wine_path
        except MissingExecutableError:
            if not fallback:
                raise

        if not fallback:
            raise MissingExecutableError(_("The Wine executable at '%s' is missing.") % wine_path)

        # Fallback to default version
        default_version = get_default_wine_version()
        wine_path = self.get_path_for_version(default_version)
        if not system.path_exists(wine_path):
            raise MissingExecutableError(_("The Wine executable at '%s' is missing.") % wine_path)

        # Update the version in the config
        if version == self.runner_config.get("version"):
            self.runner_config["version"] = default_version
            # TODO: runner_config is a dict so we have to instanciate a
            # LutrisConfig object to save it.
            # XXX: The version key could be either in the game specific
            # config or the runner specific config. We need to know
            # which one to get the correct LutrisConfig object.
        return wine_path

    def get_command(self) -> list[str]:
        command = super().get_command()
        if command:
            if proton.is_proton_path(command[0]) and not proton.is_umu_path(command[0]):
                command[0] = proton.get_umu_path()

            if proton.is_umu_path(command[0]) and self.wine_arch == "win32":
                raise RuntimeError(_("Proton is not compatible with 32-bit prefixes."))

        return command

    def is_installed(self, flatpak_allowed: bool = True, version: str | None = None, fallback: bool = True) -> bool:
        """Check if Wine is installed.
        If no version is passed, checks if any version of wine is available
        """
        try:
            if version:
                # We don't care where Wine is, but only if it was found at all.
                self.get_executable(version, fallback)
                return True

            return bool(get_installed_wine_versions())
        except MisconfigurationError:
            return False

    def is_installed_for(self, interpreter):
        try:
            version = self.get_installer_runner_version(interpreter.installer, use_api=True)
        except MisconfigurationError:
            return False
        # Proton versions (including the 'ge-proton' sentinel) are managed by umu and
        # fetched on demand at launch; there is no Wine runner build to download, so the
        # installer never needs to install one for them.
        if is_umu_managed_version(version):
            return True
        try:
            return self.is_installed(version=version, fallback=False)
        except MisconfigurationError:
            return False

    def install(self, install_ui_delegate, version=None, callback=None):
        # umu manages Proton on demand; these versions have no downloadable Wine build,
        # so "installing" one is a no-op. Skipping here keeps the installer flow, the
        # "install runner?" dialog, and CLI installs from failing with a spurious
        # "The 'ge-proton' version of the 'wine' runner can't be downloaded" error.
        if is_umu_managed_version(version):
            logger.info("Wine version '%s' is provided by umu; nothing to install.", version)
            if callback:
                callback()
            return
        super().install(install_ui_delegate, version=version, callback=callback)

    def get_installer_runner_version(
        self, installer, use_runner_config: bool = True, use_api: bool = False
    ) -> str | None:
        # If a version is specified in the script choose this one
        version = None
        if installer.script.get(installer.runner):
            version = installer.script[installer.runner].get("version")
            version = normalize_version_architecture(version)
        # If the installer is an extension, use the wine version from the base game
        elif installer.requires:
            db_game = get_game_by_field(installer.requires, field="installer_slug")
            if not db_game:
                db_game = get_game_by_field(installer.requires, field="slug")
            if not db_game:
                raise MisconfigurationError(_("The required game '%s' could not be found.") % installer.requires)
            game = Game(db_game["id"])
            if game.config:
                version = game.config.runner_config["version"]
            else:
                version = None

        if not version and use_runner_config:
            # Try to read the version from the saved runner config for Wine.
            try:
                return wine.get_runner_version_and_config()[0]
            except UnspecifiedVersionError:
                pass  # fall back to the API in this case

        if not version and use_api:
            # Try to obtain the default wine version from the Lutris API.
            default_version_info = self.get_runner_version()
            if default_version_info and "version" in default_version_info:
                logger.debug("Default wine version is %s", default_version_info["version"])
                version = format_runner_version(default_version_info)

        return version

    def adjust_installer_runner_config(self, installer_runner_config: dict[str, Any]) -> None:
        version = installer_runner_config.get("version")
        if version:
            installer_runner_config["version"] = normalize_version_architecture(version)

    @classmethod
    def get_runner_version_and_config(cls) -> tuple[str, LutrisConfig]:
        runner_config = LutrisConfig(runner_slug="wine")
        if "wine" in runner_config.runner_level:
            config_version = runner_config.runner_level["wine"].get("version")
            if config_version:
                return config_version, runner_config

        raise UnspecifiedVersionError(_("The runner configuration does not specify a Wine version."))

    @classmethod
    def msi_exec(
        cls,
        msi_file,
        quiet=False,
        prefix=None,
        wine_path=None,
        working_dir=None,
        blocking=False,
    ):
        msi_args = "/i %s" % msi_file
        if quiet:
            msi_args += " /q"
        return wineexec(
            "msiexec",
            args=msi_args,
            prefix=prefix,
            wine_path=wine_path,
            working_dir=working_dir,
            blocking=blocking,
        )

    def _run_executable(self, executable):
        """Runs a Windows executable using this game's configuration"""
        wineexec(
            executable,
            wine_path=self.get_executable(),
            prefix=self.prefix_path,
            working_dir=self.prefix_path,
            config=self,
            env=self.get_env(os_env=True),
            runner=self,
        )

    def run_wineexec(self, *args):
        """Ask the user for an arbitrary exe file to run in the game's prefix"""
        dlg = FileDialog(_("Select an EXE or MSI file"), default_path=self.game_path)
        filename = dlg.filename
        if not filename:
            return
        self.prelaunch()
        self._run_executable(filename)

    def run_winereg(self, *args):
        """Ask the user for a .reg file to import into the game's prefix"""
        dlg = FileDialog(_("Select a REG file to import"), default_path=self.game_path)
        filename = dlg.filename
        if not filename:
            return
        self.prelaunch()
        wine_path = self.get_executable()
        if self.wine_arch == "win64" and wine_path and system.path_exists(wine_path + "64"):
            # Use wine64 by default if set to a 64bit prefix. Using regular wine
            # will prevent some registry keys from being created. Most likely to be
            # a bug in Wine. see: https://github.com/lutris/lutris/issues/804
            wine_path = wine_path + "64"
        wineexec(
            "regedit",
            args="/S '%s'" % filename,
            wine_path=wine_path,
            prefix=self.prefix_path,
            arch=self.wine_arch,
            config=self,
            env=self.get_env(os_env=True),
            runner=self,
        )

    def run_wineconsole(self, *args):
        """Runs wineconsole inside wine prefix."""
        self.prelaunch()
        self._run_executable("wineconsole")

    def run_winecfg(self, *args):
        """Run winecfg in the current context"""
        self.prelaunch()
        winecfg(
            wine_path=self.get_executable(),
            prefix=self.prefix_path,
            arch=self.wine_arch,
            config=self,
            env=self.get_env(os_env=True),
            runner=self,
        )

    def run_regedit(self, *args) -> None:
        """Run regedit in the current context"""
        self.prelaunch()
        self._run_executable("regedit")

    def run_wine_terminal(self, *args) -> None:
        terminal = self.system_config.get("terminal_app")
        system_winetricks: bool = self.runner_config.get("system_winetricks", False)
        open_wine_terminal(
            terminal=terminal,
            wine_path=self.get_executable(),
            prefix=self.prefix_path,
            env=self.get_env(os_env=True),
            system_winetricks=system_winetricks,
        )

    def run_winetricks(self, *args):
        """Run winetricks in the current context"""
        self.prelaunch()
        disable_runtime = not self.use_runtime()
        system_winetricks = self.runner_config.get("system_winetricks")
        if system_winetricks:
            # Don't run the system winetricks with the runtime; let the
            # system be the system
            disable_runtime = True
        winetricks(
            "",
            prefix=self.prefix_path,
            wine_path=self.get_executable(),
            config=self,
            disable_runtime=disable_runtime,
            system_winetricks=system_winetricks,
            env=self.get_env(os_env=True, disable_runtime=disable_runtime),
            runner=self,
        )

    def run_winecpl(self, *args):
        """Execute Wine control panel."""
        self.prelaunch()
        self._run_executable("control")

    def run_taskmgr(self, *args):
        """Execute Wine task manager"""
        self.prelaunch()
        self._run_executable("taskmgr")

    def run_winekill(self, *args):
        """Runs wineserver -k."""

        winekill(
            self.prefix_path,
            arch=self.wine_arch,
            wine_path=self.get_executable(),
            env=self.get_env(),
            initial_pids=self.get_wine_executable_pids(),
        )
        return True

    def set_regedit_keys(self):
        """Reset regedit keys according to config."""
        prefix_manager = WinePrefixManager(self.prefix_path)
        # Those options are directly changed with the prefix manager and skip
        # any calls to regedit.
        managed_keys = {
            "ShowCrashDialog": prefix_manager.set_crash_dialogs,
            "Desktop": prefix_manager.set_virtual_desktop,
            "WineDesktop": prefix_manager.set_desktop_size,
        }
        for key, path in self.reg_keys.items():
            value = self.runner_config.get(key) or "auto"
            if not value or (value == "auto" and key not in managed_keys):
                prefix_manager.clear_registry_subkeys(path, key)
            elif key in self.runner_config:
                if value and key == "Graphics" and value == "wayland":
                    if not is_winewayland_available(self.read_version_from_config()):
                        logger.warning("Your Wine version does not support winewayland graphics driver")
                        continue

                    graphics_exe = self.get_executable()
                    if proton.is_proton_path(graphics_exe) or proton.is_umu_path(graphics_exe):
                        continue

                if key in managed_keys:
                    # Do not pass fallback 'auto' value to managed keys
                    if value == "auto":
                        value = None
                    wine_exe = self.get_executable()
                    if (
                        value
                        and key in ("Desktop", "WineDesktop")
                        and (
                            proton.is_umu_path(wine_exe)
                            or proton.is_proton_path(wine_exe)
                            or "wine-ge" in wine_exe.casefold()
                        )
                    ):
                        logger.warning("Wine Virtual Desktop can't be used with Wine-GE and Proton")
                        value = None
                    managed_keys[key](value)
                    continue
                # Convert numeric strings to integers so they are saved as dword
                if value.isdigit():
                    value = int(value)

                prefix_manager.set_registry_key(path, key, value)

        # We always configure the DPI, because if the user turns off DPI scaling, but it
        # had been on the only way to implement that is to save 96 DPI into the registry.
        prefix_manager.set_dpi(self.get_dpi())

    def get_dpi(self) -> int:
        """Return the DPI to be used by Wine; returns None to allow Wine's own
        setting to govern."""
        if bool(self.runner_config.get("Dpi")):
            try:
                return int(self.runner_config.get("ExplicitDpi", get_default_dpi()))
            except:
                return get_default_dpi()
        return get_default_dpi()

    def attach_log_handlers(self, monitored_command: "MonitoredCommand", game: Game) -> None:
        """Install a umu launch-status parser when the wine executable is
        actually umu — umu's runtime/Proton setup can take a long time on the
        first launch and there's no other indication of progress."""
        try:
            wine_exe = self.get_executable()
        except MissingExecutableError:
            return
        if proton.is_umu_path(wine_exe):
            monitored_command.log_handlers.append(proton.UmuLaunchStatusParser(game))

    def prelaunch(self):
        prefix_path = self.prefix_path
        managers = self.get_dll_managers()
        if prefix_path:
            if os.path.islink(prefix_path) and not os.path.exists(prefix_path):
                raise SymlinkNotUsableError(
                    message=f"Link {prefix_path} couldn't be used, please check permissions or broken link.",
                    link=prefix_path,
                )
            if not system.path_exists(os.path.join(prefix_path, "user.reg")):
                logger.warning("No valid prefix detected in %s, creating one...", prefix_path)
                create_prefix(prefix_path, wine_path=self.get_executable(), arch=self.wine_arch, runner=self)

            prefix_manager = WinePrefixManager(prefix_path)
            prefix_manager.cleanup_broken_symlinks()
            if self.runner_config.get("autoconf_joypad", False):
                prefix_manager.configure_joypads()
            prefix_manager.create_user_symlinks()
            self.configure_desktop_integration(prefix_manager)
            self.set_regedit_keys()

            # Disable first, enable after: several managers provide the same
            # DLLs (e.g. every DirectDraw wrapper provides ddraw.dll), so a
            # disabled manager must not remove the DLLs of an enabled one.
            for manager, enabled in managers.items():
                if manager.prefer_game_dir:
                    continue  # handled via the game directory below
                if not enabled:
                    manager.setup(enabled)
            for manager, enabled in managers.items():
                if manager.prefer_game_dir:
                    continue  # handled via the game directory below
                if enabled:
                    manager.setup(enabled)

        # Wrappers such as DxWrapper live next to the game: deploy their
        # DLLs as a version-matched set plus stock configs (configs never
        # overwrite user files). This needs no prefix, so it also works for
        # games running in umu's default prefix. Game-dir deployment
        # survives Proton prefix updates, which reinstall Proton's own DLLs;
        # clear any prefix remnants so the two cannot mix versions.
        game_dir = self._get_game_dll_dir()
        enabled_game_dlls = set()
        for manager, enabled in managers.items():
            if enabled and manager.prefer_game_dir:
                enabled_game_dlls.update("%s.dll" % dll for dll in manager.managed_dlls)
        for manager, enabled in managers.items():
            if not manager.prefer_game_dir:
                continue
            if not enabled:
                # Game-dir configs stay (inert without overrides); remove
                # stale Lutris-deployed DLLs unless an enabled wrapper
                # owns the filename, and clear any prefix remnants.
                if game_dir:
                    manager.cleanup_game_dlls(game_dir, keep=enabled_game_dlls)
                if prefix_path:
                    manager.setup(False)
                continue
            self._deploy_manager(manager, game_dir, prefix_path, self.game_exe)

        # DXVK and D7VK read dxvk.conf from the game directory; write the
        # managed options there. Needs no prefix either.
        if game_dir and any(self.runner_config.get(opt) for opt in dxvk_conf.CONF_TOGGLES):
            write_dxvk_conf(game_dir, get_managed_dxvk_conf_values(self.runner_config))
        # CnC-DDraw reads ddraw.ini from the game directory; same deal.
        if game_dir and self.runner_config.get("cnc_ddraw"):
            write_cnc_ddraw_conf(game_dir, get_managed_cnc_ddraw_conf_values(self.runner_config))
        # DxWrapper reads dxwrapper.ini from the game directory; same deal.
        if game_dir and self.runner_config.get("dxwrapper"):
            write_dxwrapper_conf(game_dir, get_managed_dxwrapper_conf_values(self.runner_config))

        client_exe = self.game_config.get("client_exe")
        if client_exe:
            self._ensure_client_running(client_exe)

    def _ensure_client_running(self, client_exe, wait_time=15):
        """Launch a client application (e.g. Battle.net) and wait for it to be ready.
        Many game clients need to be fully initialized before they can accept
        commands like --exec to launch a specific game."""
        import time

        if not os.path.isabs(client_exe):
            client_exe = os.path.join(self.prefix_path, client_exe)

        if not os.path.exists(client_exe):
            logger.warning("Client executable not found: %s", client_exe)
            return

        exe_name = os.path.basename(client_exe)

        # Search for the full path so we match the umu-run/pressure-vessel
        # wrapper processes, which use Unix paths.  This also implicitly
        # scopes the check to the current prefix.
        if system.is_process_running(client_exe):
            logger.info("Client %s is already running", exe_name)
            return

        logger.info("Launching client %s", exe_name)
        wineexec(
            client_exe,
            prefix=self.prefix_path,
            wine_path=self.get_executable(),
            arch=self.wine_arch,
        )
        logger.info("Waiting %d seconds for client to be ready", wait_time)
        time.sleep(wait_time)

    def _get_game_dll_dir(self) -> str | None:
        """Directory the game-dir wrappers deploy into (exe dir, else working dir)."""
        game_dir = None
        if self.game_exe:
            game_dir = os.path.dirname(self.game_exe)
        if not game_dir or not os.path.isdir(game_dir):
            game_dir = self.working_dir
        if not game_dir or not os.path.isdir(game_dir):
            return None
        return game_dir

    def cleanup_disabled_dlls(self) -> None:
        """Immediately remove files deployed for currently-disabled DLL managers.

        Used when a toggle is switched off in the GUI so disabled components
        don't linger until the next launch. Only removes Lutris-deployed
        files (game-dir cleanup is byte-compared, prefix cleanup restores
        backed-up originals); user data is never touched. All failures are
        logged, never raised."""
        try:
            managers = self.get_dll_managers()
        except Exception as ex:
            logger.debug("Skipping DLL cleanup: %s", ex)
            return
        try:
            game_dir = self._get_game_dll_dir()
        except Exception as ex:
            logger.debug("Skipping game-dir DLL cleanup: %s", ex)
            game_dir = None
        try:
            prefix_path = self.prefix_path
        except Exception as ex:
            logger.debug("Skipping prefix DLL cleanup: %s", ex)
            prefix_path = None
        enabled_game_dlls = set()
        for manager, enabled in managers.items():
            if enabled and manager.prefer_game_dir:
                enabled_game_dlls.update("%s.dll" % dll for dll in manager.managed_dlls)
        for manager, enabled in managers.items():
            if enabled:
                continue
            try:
                if manager.prefer_game_dir:
                    if game_dir:
                        manager.cleanup_game_dlls(game_dir, keep=enabled_game_dlls)
                elif prefix_path:
                    manager.setup(False)
            except Exception as ex:
                logger.warning("Failed to clean up %s: %s", manager.human_name, ex)

    def _deploy_manager(
        self, manager, game_dir: str | None, prefix_path: str | None, exe_path=None, confirmer=None
    ) -> bool:
        """Deploy one enabled manager (game dir preferred, prefix fallback).

        confirmer(dest, label) is called on the main thread before replacing
        an existing differing file; it must return True to replace. None
        means replace without asking (game launch path)."""
        if manager.prefer_game_dir:
            if game_dir and manager.deploy_game_dlls(game_dir, exe_path, confirmer):
                manager.deploy_game_files(game_dir)
                if prefix_path:
                    manager.setup(False)
                return True
            if prefix_path:
                manager.setup(True)
                return True
            logger.warning("Cannot deploy %s: no game directory and no prefix.", manager.human_name)
            return False
        if prefix_path:
            manager.setup(True)
            return True
        return False

    def deploy_enabled_dlls(self, confirmer=None) -> None:
        """Deploy files for currently-enabled DLL managers right away.

        Used when a toggle is switched on in the GUI so enabling takes
        effect without waiting for the next launch. Components already
        cached deploy synchronously; missing ones download in a worker
        thread and deploy on completion (without asking again). All
        failures are logged (and notified on download failure), never raised."""
        try:
            managers = self.get_dll_managers(enabled_only=True)
        except Exception as ex:
            logger.debug("Skipping DLL deploy: %s", ex)
            return
        try:
            game_dir = self._get_game_dll_dir()
        except Exception as ex:
            logger.debug("Skipping game-dir DLL deploy: %s", ex)
            game_dir = None
        try:
            prefix_path = self.prefix_path
        except Exception as ex:
            logger.debug("Skipping prefix DLL deploy: %s", ex)
            prefix_path = None
        try:
            exe_path = self.game_exe
        except Exception as ex:
            logger.debug("Skipping exe detection: %s", ex)
            exe_path = None
        for manager, _enabled in managers.items():
            try:
                if manager.is_available():
                    self._deploy_manager(manager, game_dir, prefix_path, exe_path, confirmer)
                else:
                    self._fetch_manager_in_background(manager)
            except Exception as ex:
                logger.warning("Failed to deploy %s: %s", manager.human_name, ex)

    def _fetch_manager_in_background(self, manager) -> None:
        """Download a missing component in a worker thread, then deploy it."""
        lock = _DLL_DEPLOY_LOCKS.setdefault(manager.name, threading.Lock())
        if not lock.acquire(blocking=False):
            logger.debug("Download of %s already in progress.", manager.human_name)
            return
        logger.info("Downloading %s in the background...", manager.human_name)

        def done(result, error, _manager=manager, _lock=lock):
            try:
                if error or not result:
                    logger.warning("Failed to download %s: %s", _manager.human_name, error or "unknown")
                    try:
                        from lutris.gui.widgets.notifications import send_notification

                        send_notification(
                            _("Download failed"),
                            _("Could not download %s.") % _manager.human_name,
                        )
                    except Exception as notify_ex:
                        logger.debug("Notification failed: %s", notify_ex)
                    return
                logger.info("Downloaded %s, deploying...", _manager.human_name)
                self.deploy_enabled_dlls()
            finally:
                _lock.release()

        AsyncCall(manager.download, done)

    def is_sarek_active(self) -> bool:
        """True if DXVK-Sarek is enabled and the Wine build ships it."""
        if not self.runner_config.get("sarek"):
            return False
        version = self.runner_config.get("version") or get_default_wine_version()
        return is_sarek_available_for_version(version)

    def get_dll_managers(self, enabled_only=False):
        """Returns the DLL managers in a dict; the keys are the managers themselves,
        and the values are the enabled flags for them. If 'enabled_only' is true,
        only enabled managers are returned, so disabled managers are not created."""
        managers = {}
        wine_exe = self.get_executable()
        is_proton = proton.is_proton_path(wine_exe) or proton.is_umu_path(wine_exe)
        sarek_active = self.is_sarek_active()

        enabled_wrappers = [DDRAW_WRAPPER_LABELS[opt] for opt in DDRAW_PROVIDER_OPTIONS if self.runner_config.get(opt)]
        if len(enabled_wrappers) > 1:
            logger.warning(
                "Multiple DirectDraw wrappers enabled (%s); only one can provide ddraw.dll.",
                ", ".join(enabled_wrappers),
            )

        for manager_class, enabled_option, version_option in DLL_MANAGER_CLASSES:
            enabled = bool(self.runner_config.get(enabled_option))
            version = self.runner_config.get(version_option)
            if enabled or not enabled_only:
                manager = manager_class(self.prefix_path, arch=self.wine_arch, version=version)

                if not manager.can_enable():
                    enabled = False

                if not manager.proton_compatible and is_proton:
                    enabled = False

                if enabled and sarek_active and isinstance(manager, (DXVKManager, D7vkManager)):
                    # Sarek ships its own DXVK fork including DDraw support,
                    # so the DXVK and D7VK toggles stay off while it is active.
                    logger.warning("Disabling %s while DXVK-Sarek is enabled.", manager.human_name)
                    enabled = False

                if enabled or not enabled_only:
                    managers[manager] = enabled

        return managers

    def get_dll_overrides(self):
        """Return the DLLs overriden at runtime"""
        try:
            overrides = self.runner_config["overrides"]
        except KeyError:
            overrides = {}
        if not isinstance(overrides, dict):
            logger.warning("DLL overrides is not a mapping: %s", overrides)
            overrides = {}
        return overrides

    def get_env(self, os_env=False, disable_runtime=False):
        """Return environment variables used by the game"""
        # Always false to runner.get_env, the default value
        # of os_env is inverted in the wine class,
        # the OS env is read later.
        env = super().get_env(os_env, disable_runtime=disable_runtime)
        show_debug = self.runner_config.get("show_debug", "-all")
        if show_debug != "inherit":
            env["WINEDEBUG"] = show_debug
            env["DXVK_LOG_LEVEL"] = "error"
            env["UMU_LOG"] = "1"
            if show_debug == "":
                env["DXVK_LOG_LEVEL"] = "info"
                env["UMU_LOG"] = "warning"
            elif show_debug == "+all":
                env["DXVK_LOG_LEVEL"] = "debug"
                env["UMU_LOG"] = "debug"
        env["WINEARCH"] = self.wine_arch
        wine_exe = self.get_executable()
        is_proton = proton.is_proton_path(wine_exe) or proton.is_umu_path(wine_exe)

        wine_config_version = self.read_version_from_config()
        if wine_config_version == GE_PROTON_LATEST:
            env["PROTONPATH"] = "GE-Proton"
            is_proton_version = True
        else:
            is_proton_version = proton.is_proton_version(wine_config_version)
        env["WINE"] = wine_exe

        files_dir = get_runner_files_dir_for_version(wine_config_version)
        if files_dir:
            env["WINE_MONO_CACHE_DIR"] = os.path.join(files_dir, "mono")
            env["WINE_GECKO_CACHE_DIR"] = os.path.join(files_dir, "gecko")

        # We don't want to override gstreamer for proton, it has it's own version
        if files_dir and not is_proton and is_gstreamer_build(wine_exe):
            path_64 = os.path.join(files_dir, "lib64/gstreamer-1.0/")
            path_32 = os.path.join(files_dir, "lib/gstreamer-1.0/")
            if os.path.exists(path_64) or os.path.exists(path_32):
                env["GST_PLUGIN_SYSTEM_PATH_1_0"] = path_64 + ":" + path_32

        if self.prefix_path:
            env["WINEPREFIX"] = self.prefix_path

        if "WINEESYNC" not in env:
            env["WINEESYNC"] = "1" if self.runner_config.get("esync") else "0"

        # Proton uses an env-var with the opposite sense!
        if "PROTON_NO_ESYNC" not in env and not self.runner_config.get("esync"):
            env["PROTON_NO_ESYNC"] = "1"

        if "WINEFSYNC" not in env:
            env["WINEFSYNC"] = "1" if self.runner_config.get("fsync") else "0"

        # Proton uses an env-var with the opposite sense!
        if "PROTON_NO_FSYNC" not in env and not self.runner_config.get("fsync"):
            env["PROTON_NO_FSYNC"] = "1"

        if self.runner_config.get("fsr"):
            env["WINE_FULLSCREEN_FSR"] = "1"

        if self.runner_config.get("dxvk_nvapi"):
            env["DXVK_NVAPIHACK"] = "0"
            env["DXVK_ENABLE_NVAPI"] = "1"

        if self.runner_config.get("battleye"):
            env["PROTON_BATTLEYE_RUNTIME"] = os.path.join(settings.RUNTIME_DIR, "battleye_runtime")

        if self.runner_config.get("eac"):
            env["PROTON_EAC_RUNTIME"] = os.path.join(settings.RUNTIME_DIR, "eac_runtime")

        sarek_active = self.is_sarek_active()
        using_dxvk = (self.runner_config.get("dxvk") or sarek_active) and LINUX_SYSTEM.is_vulkan_supported()
        if not using_dxvk:
            env["PROTON_USE_WINED3D"] = "1"

        if "PROTON_DXVK_D3D8" not in env:
            env["PROTON_DXVK_D3D8"] = "1" if using_dxvk else "0"

        if sarek_active and "PROTON_DXVK_SAREK" not in env:
            env["PROTON_DXVK_SAREK"] = "1"

        if (
            using_dxvk
            and is_proton_version
            and "PROTON_DXVK_SAREK" not in env
            and not os.environ.get("LUTRIS_NO_VKQUERY")
        ):
            lib_api_version = vkquery.get_vulkan_api_version()
            devices = vkquery.get_device_info()
            if (lib_api_version and lib_api_version < REQUIRED_VULKAN_API_VERSION) or (
                devices and devices[0].api_version < REQUIRED_VULKAN_API_VERSION
            ):
                env["PROTON_DXVK_SAREK"] = "1"

        if (
            self.runner_config.get("Graphics") == "wayland"
            and is_winewayland_available(wine_config_version)
            and is_proton_version
        ):
            env["PROTON_ENABLE_WAYLAND"] = "1"

            if self.runner_config.get("proton_hdr"):
                env["PROTON_ENABLE_HDR"] = "1"

        for dll_manager in self.get_dll_managers(enabled_only=True):
            if not dll_manager.is_available():
                logger.warning(
                    "%s is enabled but its files are not downloaded; its DLL overrides will be skipped.",
                    dll_manager.human_name,
                )
                continue
            self.dll_overrides.update(dll_manager.get_enabling_dll_overrides())

        overrides = self.get_dll_overrides()
        if overrides:
            self.dll_overrides.update(overrides)

        env["WINEDLLOVERRIDES"] = get_overrides_env(self.dll_overrides)

        return env

    def finish_env(self, env: dict[str, str], game: Game | None = None) -> None:
        super().finish_env(env, game)

        wine_exe = self.get_executable()

        if proton.is_proton_path(wine_exe) or proton.is_umu_path(wine_exe):
            game_id = proton.get_game_id(game, env)
            proton.update_proton_env(wine_exe, env, game_id=game_id)

    def get_run_data(self) -> RunDataDict:
        # The standalone run() path does not call finish_env() the way launching a
        # game does, so finalize the environment here too. Without a game context,
        # Proton/umu falls back to a default GAMEID.
        data = super().get_run_data()
        self.finish_env(data["env"])
        return data

    def get_runtime_env(self):
        """Return runtime environment variables with path to wine for Lutris builds"""
        try:
            wine_path = os.path.dirname(os.path.dirname(self.get_executable()))
        except MisconfigurationError:
            wine_path = None

        return runtime.get_env(
            version="Ubuntu-18.04",
            prefer_system_libs=self.system_config.get("prefer_system_libs", True),
            wine_path=wine_path,
        )

    def get_wine_executable_pids(self):
        """Return a list of pids of processes using the current wine exe."""
        try:
            exe = self.get_executable()
            if proton.is_proton_path(exe) or proton.is_umu_path(exe):
                logger.debug("Tracking PIDs of Proton games is not possible at the moment")
                return set()
            if not exe.startswith("/"):
                exe = system.find_required_executable(exe)
            pids = system.get_pids_using_file(exe)
            if self.wine_arch == "win64" and os.path.basename(exe) == "wine":
                pids = pids | system.get_pids_using_file(exe + "64")
        except MisconfigurationError:
            return set()

        # Add wineserver PIDs to the mix (at least one occurence of fuser not
        # picking the games's PID from wine/wine64 but from wineserver for some
        # unknown reason.
        pids = pids | system.get_pids_using_file(os.path.join(os.path.dirname(exe), "wineserver"))
        return pids

    def configure_desktop_integration(self, wine_prefix):
        try:
            if self.game_config.get("desktop_integration", False):
                wine_prefix.install_desktop_integration()
            else:
                wine_prefix.remove_desktop_integration()
        except Exception as ex:
            logger.exception("Failed to setup desktop integration, the prefix may not be valid: %s", ex)

    def play(self) -> dict[str, Any]:  # pylint: disable=too-many-return-statements
        game_exe = self.game_exe
        arguments: str = self.game_config.get("args", "")
        launch_info: dict = {"env": self.get_env(os_env=False)}
        using_dxvk = (self.runner_config.get("dxvk") or self.is_sarek_active()) and LINUX_SYSTEM.is_vulkan_supported()

        if using_dxvk:
            # Set this to 1 to enable access to more RAM for 32-bit applications
            launch_info["env"]["WINE_LARGE_ADDRESS_AWARE"] = "1"

        if not game_exe or not system.path_exists(game_exe):
            raise MissingGameExecutableError(filename=game_exe)

        if launch_info["env"].get("WINEESYNC") == "1":
            limit_set = is_esync_limit_set()

            if not limit_set:
                raise EsyncLimitError()

        if launch_info["env"].get("WINEFSYNC") == "1":
            fsync_supported = is_fsync_supported()

            if not fsync_supported:
                raise FsyncUnsupportedError()

        command = self.get_command()

        game_exe, args, _working_dir = get_real_executable(game_exe, self.working_dir)
        command.append(game_exe)
        if args:
            command = command + args

        if arguments:
            for arg in split_arguments(arguments):
                command.append(arg)
        launch_info["command"] = command
        return launch_info

    def filter_game_pids(self, candidate_pids: Iterable[int], game_uuid: str, game_folder: str) -> set[int]:
        """Checks the pids given and returns a set containing only those that are part of the running game,
        identified by its UUID and directory."""

        wine_exe = self.get_executable()
        if proton.is_proton_path(wine_exe) or proton.is_umu_path(wine_exe):
            folder_pids = set()
            gamescope_pids = set()
            has_gamescope = self.system_config.get("gamescope")

            for pid in candidate_pids:
                proc = Process(pid)
                cmdline = proc.cmdline or ""
                # pressure-vessel: This could potentially pick up PIDs not started by lutris?
                if game_folder in cmdline or "pressure-vessel" in cmdline:
                    folder_pids.add(pid)
                # Include gamescope-related processes when gamescope is enabled
                if has_gamescope and (proc.name or "").startswith("gamescope"):
                    gamescope_pids.add(pid)

            uuid_pids = set(pid for pid in candidate_pids if Process(pid).environ.get("LUTRIS_GAME_UUID") == game_uuid)

            return (folder_pids & uuid_pids) | gamescope_pids
        else:
            return super().filter_game_pids(candidate_pids, game_uuid, game_folder)

    def force_stop_game(self, game_pids: Iterable[int]) -> None:
        """Kill WINE with kindness, or at least with -k. This seems to leave a process
        alive for some reason, but the caller will detect this and SIGKILL it."""

        winekill(
            self.prefix_path,
            arch=self.wine_arch,
            wine_path=self.get_executable(),
            env=self.get_env(),
            initial_pids=game_pids,
        )

        # Kill non-Wine processes (like gamescope) that winekill doesn't handle
        super().force_stop_game(game_pids)

    def extract_icon(self, game_slug):
        """Extracts the 128*128 icon from EXE and saves it, if not resizes the biggest icon found.
        returns true if an icon is saved, false if not"""

        try:
            wantedsize = (128, 128)
            pathtoicon = settings.ICON_PATH + "/lutris_" + game_slug + ".png"
            exe = self.game_exe
            if not exe or os.path.exists(pathtoicon) or not PEFILE_AVAILABLE:
                return False

            extractor = IconExtractor(exe)

            icon = extractor.get_best_icon()

            if not icon.size == wantedsize:
                icon = icon.resize(wantedsize)
            icon.save(pathtoicon)
            return True
        except Exception as ex:
            logger.exception("Unable to extract icon from %s: %s", exe, ex)
            return False
