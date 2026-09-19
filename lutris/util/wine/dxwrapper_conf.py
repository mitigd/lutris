"""DxWrapper configuration (dxwrapper.ini) support.

DxWrapper reads dxwrapper.ini from the game directory. All stock sections
hold global settings; anything unknown (e.g. extra user sections) is
preserved verbatim. Boolean options use 1/0. The first managed write backs
the file up to dxwrapper.ini.lutris-bak.
"""

import os

from lutris.util import system
from lutris.util.log import logger

CONF_FILENAME = "dxwrapper.ini"
CONF_BACKUP_SUFFIX = ".lutris-bak"
# Full-line marker Lutris writes above the dxwrapper.ini lines it manages, so
# hand-written lines (even for managed keys) are never touched.
MANAGED_MARKER = "# Managed by Lutris"


def _flag(section, key, help_text):
    return {"section": section, "key": key, "type": "flag", "default": False, "help": help_text}


def _str(section, key, default, help_text):
    return {"section": section, "key": key, "type": "str", "default": default, "help": help_text}


DXWRAPPER_CONF_SPEC = [
    # [General]
    _str("General", "RealDllPath", "AUTO", "Where the real system DLLs live. AUTO detects it."),
    _str("General", "WrapperMode", "AUTO", "How the wrapper loads. AUTO detects the best mode."),
    _str("General", "LoadCustomDllPath", "", "Extra folder to load custom DLLs from."),
    _str("General", "ExcludeProcess", "", "Process names that must never use the wrapper."),
    _str("General", "IncludeProcess", "", "If set, only these process names use the wrapper."),
    _str("General", "RunProcess", "", "Program to run automatically with the wrapper."),
    _flag("General", "WaitForProcess", "Wait for the run process before continuing."),
    _flag("General", "DisableLogging", "Disable the dxwrapper log file."),
    # [Plugins]
    _flag("Plugins", "LoadPlugins", "Load plugin DLLs from the plugins folder."),
    _flag("Plugins", "LoadFromScriptsOnly", "Only load plugins requested by scripts."),
    # [Compatibility]
    _flag("Compatibility", "Dd7to9", "Translate DirectDraw 7 calls to Direct3D 9. Fixes most DDraw games."),
    _flag("Compatibility", "D3d8to9", "Translate Direct3D 8 calls to Direct3D 9."),
    _flag("Compatibility", "D3d9to9Ex", "Use Direct3D 9Ex instead of Direct3D 9."),
    _flag("Compatibility", "D3d9on12", "Run Direct3D 9 on top of Direct3D 12 (D3D9On12)."),
    _flag("Compatibility", "DDrawCompat", "Enable the DDrawCompat compatibility layer."),
    _flag("Compatibility", "Dinputto8", "Translate DirectInput 1-7 calls to DirectInput 8."),
    _flag("Compatibility", "DisableGameUX", "Disable fullscreen game UX features."),
    _flag("Compatibility", "EnableDdrawWrapper", "Enable the WineD3D-based DDraw wrapper."),
    _flag("Compatibility", "EnableD3d9Wrapper", "Enable the WineD3D-based D3D9 wrapper."),
    _flag("Compatibility", "EnableDinput8Wrapper", "Enable the DirectInput 8 wrapper."),
    _flag("Compatibility", "EnableDsoundWrapper", "Enable the DirectSound wrapper."),
    _flag("Compatibility", "DisableGDIGammaRamp", "Disable GDI gamma ramp handling."),
    _flag("Compatibility", "EnableOpenDialogHook", "Hook open/save dialogs."),
    _str("Compatibility", "WinVersionLie", "off", "Lie about the Windows version. off disables."),
    _str("Compatibility", "WinVersionLieSP", "0", "Service pack number to report with the version lie. 0 disables."),
    _str("Compatibility", "ForceKeyboardLayout", "0", "Force a keyboard layout id. 0 disables."),
    _flag("Compatibility", "FixPerfCounterUptime", "Fix performance counter uptime quirks."),
    _flag("Compatibility", "HandleExceptions", "Let the wrapper handle application exceptions."),
    _flag("Compatibility", "SingleProcAffinity", "Lock the game to a single CPU."),
    _str("Compatibility", "ProcAffinityMask", "0", "CPU affinity mask. 0 disables."),
    # [DDrawCompat]
    _flag("DDrawCompat", "DDrawCompat20", "DDrawCompat 2.0 compatibility mode."),
    _flag("DDrawCompat", "DDrawCompat21", "DDrawCompat 2.1 compatibility mode."),
    _flag("DDrawCompat", "DDrawCompat32", "DDrawCompat 3.2 compatibility mode."),
    _flag("DDrawCompat", "DDrawCompatDisableGDIHook", "Disable the DDrawCompat GDI hook."),
    _flag("DDrawCompat", "DDrawCompatNoProcAffinity", "Don't let DDrawCompat manage CPU affinity."),
    # [ddraw]
    _str("ddraw", "DdrawOverrideBitMode", "0", "Force a display bit mode. 0 disables."),
    _flag("ddraw", "DdrawUseDirect3D9Caps", "Report Direct3D 9 caps for DirectDraw."),
    # [Dd7to9]
    _flag("Dd7to9", "DdrawAutoFrameSkip", "Skip frames automatically to keep speed up."),
    _flag("Dd7to9", "DdrawEmulateSurface", "Emulate surfaces in system memory."),
    _flag("Dd7to9", "DdrawEmulateLock", "Emulate surface locking."),
    _flag("Dd7to9", "DdrawUseShadowSurface", "Render via a shadow surface."),
    _flag("Dd7to9", "DdrawKeepAllInterfaceCache", "Keep every interface in the cache."),
    _flag("Dd7to9", "DdrawAllowMultiSampling", "Allow multisampling in DDraw games."),
    _flag("Dd7to9", "DdrawForceMipMapAutoGen", "Force mipmap auto generation."),
    _flag("Dd7to9", "DdrawClampVertexZDepth", "Clamp vertex Z depth."),
    _flag("Dd7to9", "DdrawEnableByteAlignment", "Enable byte alignment handling."),
    _flag("Dd7to9", "DdrawFixByteAlignment", "Fix byte alignment issues."),
    _flag("Dd7to9", "DdrawIntroVideoFix", "Fix intro videos that otherwise stay black."),
    _flag("Dd7to9", "DdrawFilterActivateApp", "Filter activate-app messages."),
    _flag("Dd7to9", "DdrawRemoveScanlines", "Remove scanlines effect."),
    _flag("Dd7to9", "DdrawRemoveInterlacing", "Remove interlacing artifacts."),
    _flag("Dd7to9", "DdrawReadFromGDI", "Read the frame via GDI."),
    _flag("Dd7to9", "DdrawWriteToGDI", "Write the frame via GDI."),
    _flag("Dd7to9", "DdrawLimitTextureFormats", "Limit texture formats for old games."),
    _flag("Dd7to9", "DdrawLimitDisplayModeCount", "Limit reported display modes."),
    _str("Dd7to9", "DdrawCustomWidth", "0", "Custom rendering width. 0 disables."),
    _str("Dd7to9", "DdrawCustomHeight", "0", "Custom rendering height. 0 disables."),
    _flag("Dd7to9", "DdrawLinearTextureFilter", "Use linear texture filtering."),
    _flag("Dd7to9", "DdrawUseNativeResolution", "Render at the native display resolution."),
    _str("Dd7to9", "DdrawOverrideWidth", "0", "Force the rendering width. 0 disables."),
    _str("Dd7to9", "DdrawOverrideHeight", "0", "Force the rendering height. 0 disables."),
    _str("Dd7to9", "DdrawOverrideStencilFormat", "0", "Force a stencil format. 0 disables."),
    _flag("Dd7to9", "DdrawIntegerScalingClamp", "Clamp integer scaling."),
    _flag("Dd7to9", "DdrawMaintainAspectRatio", "Maintain aspect ratio when scaling."),
    # [d3d9]
    _str("d3d9", "AnisotropicFiltering", "0", "Force anisotropic filtering level. 0 disables."),
    _str("d3d9", "AntiAliasing", "0", "Force antialiasing level. 0 disables."),
    _flag("d3d9", "EnableMultisamplingATOC", "Enable multisampling alpha-to-coverage."),
    _flag("d3d9", "EnvironmentCubeMapFix", "Fix environment cube maps."),
    _flag("d3d9", "ForceMipMapUsage", "Force mipmap usage."),
    _str("d3d9", "DepthBiasFactor", "0", "Depth bias factor adjustment."),
    _str("d3d9", "DepthBiasDropOffValue", "0", "Depth bias drop-off value."),
    _flag("d3d9", "EnableVSync", "Enable vertical synchronization."),
    _str("d3d9", "ForceVsyncMode", "0", "Force a vsync mode. 0 disables."),
    _flag("d3d9", "ShowFPSCounter", "Show an FPS counter overlay."),
    _str("d3d9", "OverrideRefreshRate", "0", "Force a refresh rate in Hz. 0 disables."),
    _str("d3d9", "LimitRefreshRates", "0", "Limit reported refresh rates. 0 disables."),
    _str("d3d9", "LimitDisplayModeCount", "0", "Limit reported display modes. 0 disables."),
    _str("d3d9", "CustomDisplayWidth", "0", "Custom display width. 0 disables."),
    _str("d3d9", "CustomDisplayHeight", "0", "Custom display height. 0 disables."),
    _str("d3d9", "LimitPerFrameFPS", "0", "Per-frame FPS limit. 0 disables."),
    _flag("d3d9", "EnableWindowMode", "Run the game in windowed mode."),
    _flag("d3d9", "WindowModeBorder", "Show borders in forced window mode."),
    _flag("d3d9", "WindowModeGammaShader", "Apply gamma shader in window mode."),
    _str("d3d9", "DisplayBrightness", "0", "Display brightness adjustment. 0 disables."),
    _str("d3d9", "DisplayContrast", "0", "Display contrast adjustment. 0 disables."),
    _flag("d3d9", "SetInitialWindowPosition", "Set the initial window position."),
    _str("d3d9", "InitialWindowPositionLeft", "0", "Initial window left position."),
    _str("d3d9", "InitialWindowPositionTop", "0", "Initial window top position."),
    _flag("d3d9", "FullscreenWindowMode", "Use a fullscreen window instead of exclusive mode."),
    _flag("d3d9", "HideWindowFocusChanges", "Hide window focus change messages."),
    _flag("d3d9", "EnableCursorClip", "Clip the cursor to the game window."),
    _flag("d3d9", "ForceExclusiveFullscreen", "Force exclusive fullscreen mode."),
    _flag("d3d9", "ForceMixedVertexProcessing", "Force mixed vertex processing."),
    _flag("d3d9", "ForceSystemMemVertexCache", "Force system-memory vertex cache."),
    _flag("d3d9", "UseShadowBackbuffer", "Render via a shadow backbuffer."),
    _str("d3d9", "OverrideStencilFormat", "0", "Force a stencil format. 0 disables."),
    _flag("d3d9", "FlipEx", "Use flipEx presentation."),
    _flag("d3d9", "SetSwapEffectShim", "Shim the swap effect."),
    _flag("d3d9", "DisableMaxWindowedMode", "Disable maximized windowed mode."),
    _flag("d3d9", "GraphicsHybridAdapter", "Hybrid graphics adapter handling."),
    # [FullScreen]
    _flag("FullScreen", "FullScreen", "Run fullscreen."),
    _flag("FullScreen", "ForceWindowResize", "Force window resizing."),
    _flag("FullScreen", "WaitForWindowChanges", "Wait for window changes."),
    # [dinput8]
    _str("dinput8", "DeviceLookupCacheTime", "0", "Input device lookup cache time in ms. 0 disables."),
    _flag("dinput8", "FilterNonActiveInput", "Filter input when the window is not active."),
    _flag("dinput8", "InvertForceDirection", "Invert force-feedback direction."),
    _flag("dinput8", "FixHighFrequencyMouse", "Fix high-frequency gaming mice."),
    _str("dinput8", "MouseMovementFactor", "0", "Mouse movement multiplier. 0 disables."),
    _str("dinput8", "MouseMovementFactorX", "0", "Horizontal mouse movement multiplier. 0 disables."),
    _str("dinput8", "MouseMovementFactorY", "0", "Vertical mouse movement multiplier. 0 disables."),
    _str("dinput8", "MouseMovementPadding", "0", "Mouse movement padding. 0 disables."),
    _str("dinput8", "MouseMovementPaddingX", "0", "Horizontal mouse padding. 0 disables."),
    _str("dinput8", "MouseMovementPaddingY", "0", "Vertical mouse padding. 0 disables."),
    # [dsound]
    _str("dsound", "Num2DBuffers", "0", "Number of 2D sound buffers. 0 disables."),
    _str("dsound", "Num3DBuffers", "0", "Number of 3D sound buffers. 0 disables."),
    _flag("dsound", "ForceCertification", "Force driver certification."),
    _flag("dsound", "ForceExclusiveMode", "Force exclusive audio mode."),
    _flag("dsound", "ForceSoftwareMixing", "Force software audio mixing."),
    _flag("dsound", "ForceHardwareMixing", "Force hardware audio mixing."),
    _flag("dsound", "ForceHQ3DSoftMixing", "Force high-quality 3D software mixing."),
    _flag("dsound", "ForceNonStaticBuffers", "Force non-static buffers."),
    _flag("dsound", "ForceVoiceManagement", "Force voice management."),
    _flag("dsound", "ForcePrimaryBufferFormat", "Force the primary buffer format below."),
    _str("dsound", "PrimaryBufferBits", "16", "Primary buffer bits."),
    _str("dsound", "PrimaryBufferSamples", "44100", "Primary buffer sample rate."),
    _str("dsound", "PrimaryBufferChannels", "2", "Primary buffer channels."),
    _flag("dsound", "AudioClipDetection", "Detect audio clipping."),
]

MANAGED_KEYS = frozenset((spec["section"], spec["key"]) for spec in DXWRAPPER_CONF_SPEC)


def _normalize(value):
    """Format a GUI value the way dxwrapper.ini expects it (1/0 flags)."""
    if value is True:
        return "1"
    if value is False:
        return "0"
    return str(value)


def get_managed_values(runner_config):
    """Return {(section, key): value} for options differing from default."""
    values = {}
    for spec in DXWRAPPER_CONF_SPEC:
        key = spec["key"]
        if key not in runner_config:
            continue
        value = runner_config[key]
        if value is None:
            continue
        if _normalize(value) != _normalize(spec["default"]):
            values[(spec["section"], key)] = _normalize(value)
    return values


def _parse_section(header):
    return header.strip().strip("[]")


def parse_conf(text):
    """Parse dxwrapper.ini text into entries preserving order and comments.

    Returns ("raw", line), ("section", name) or ("kv", section, key, value,
    managed, line) tuples.
    """
    entries = []
    section = ""
    marked = False
    for line in text.splitlines():
        stripped = line.strip()
        if stripped == MANAGED_MARKER:
            marked = True
            continue
        if stripped.startswith("[") and stripped.endswith("]"):
            section = _parse_section(stripped)
            entries.append(("section", section))
            marked = False
            continue
        if not stripped or stripped.startswith("#") or stripped.startswith(";") or "=" not in stripped:
            entries.append(("raw", line))
            marked = False
            continue
        key, _, value = stripped.partition("=")
        key = key.strip()
        managed = marked and (section, key) in MANAGED_KEYS
        entries.append(("kv", section, key, value.strip(), managed, line))
        marked = False
    return entries


def merge_conf(entries, values):
    """Merge managed values into parsed entries.

    Lutris-managed lines are updated or, when reset to default, removed.
    Hand-written lines, comments and unknown sections are preserved
    verbatim; missing managed keys are inserted under their section.
    """
    lines = []
    seen = set()
    existing = {(entry[1], entry[2]) for entry in entries if entry[0] == "kv"}
    # Keys missing from the file are inserted right under their section
    # header; keys already present are handled inline.
    pending = {}
    for section, key in values:
        if (section, key) not in existing:
            pending.setdefault(section, {})[key] = values[(section, key)]

    def flush_pending(section):
        for key in list(pending.get(section, {})):
            lines.append(MANAGED_MARKER)
            lines.append("%s = %s" % (key, pending[section].pop(key)))

    for entry in entries:
        if entry[0] == "raw":
            lines.append(entry[1])
            continue
        if entry[0] == "section":
            lines.append("[%s]" % entry[1])
            flush_pending(entry[1])
            continue
        _kind, section, key, _value, managed, line = entry
        if (section, key) not in MANAGED_KEYS or not managed:
            if (section, key) in values and (section, key) not in seen:
                # GUI takes ownership of a hand-written line for this key.
                lines.append(MANAGED_MARKER)
                lines.append("%s = %s" % (key, values[(section, key)]))
                seen.add((section, key))
            else:
                lines.append(line)
            continue
        seen.add((section, key))
        if (section, key) in values:
            lines.append(MANAGED_MARKER)
            lines.append("%s = %s" % (key, values[(section, key)]))
        # Managed keys reset to default are dropped.
    for section in list(pending):
        if pending[section]:
            if lines and lines[-1].strip():
                lines.append("")
            lines.append("[%s]" % section)
            flush_pending(section)
    text = "\n".join(lines)
    return text + "\n" if text.strip() else ""


def write_dxwrapper_conf(game_dir, values):
    """Write the managed values into the game dir's dxwrapper.ini.

    Returns True when the file was created, updated or removed. Does
    nothing when there is nothing to write and nothing to clean up.
    """
    if not game_dir or not system.path_exists(game_dir):
        logger.warning("Game directory %s does not exist, skipping dxwrapper.ini.", game_dir)
        return False
    path = os.path.join(game_dir, CONF_FILENAME)
    existing = ""
    if system.path_exists(path):
        try:
            with open(path, "r", encoding="utf-8") as conf_file:
                existing = conf_file.read()
        except OSError as ex:
            logger.warning("Failed to read %s: %s", path, ex)
            return False
    entries = parse_conf(existing)
    has_managed = any(entry[0] == "kv" and entry[4] for entry in entries)
    if not values and not has_managed:
        return False
    if existing and not system.path_exists(path + CONF_BACKUP_SUFFIX):
        try:
            with open(path + CONF_BACKUP_SUFFIX, "w", encoding="utf-8") as backup_file:
                backup_file.write(existing)
            logger.info("Backed up %s.", path)
        except OSError as ex:
            logger.warning("Failed to back up %s: %s", path, ex)
    merged = merge_conf(entries, values)
    try:
        if not merged:
            if system.path_exists(path):
                os.remove(path)
                logger.info("Removed empty %s.", path)
            return True
        with open(path, "w", encoding="utf-8") as conf_file:
            conf_file.write(merged)
        logger.info("Wrote %s with %d managed option(s).", path, len(values))
    except OSError as ex:
        logger.warning("Failed to write %s: %s", path, ex)
        return False
    return True


def resolve_game_dir(game):
    """Best-effort game directory for dxwrapper.ini deployment."""
    if game is None:
        return None
    try:
        game_config = game.config.game_config
    except Exception as ex:  # noqa: BLE001 - config access must not break the dialog
        logger.debug("Could not read game config: %s", ex)
        return None
    exe = game_config.get("exe")
    if exe:
        directory = os.path.dirname(os.path.expanduser(exe))
        if system.path_exists(directory):
            return directory
    for candidate in (game_config.get("working_dir"), getattr(game, "directory", None)):
        if candidate and system.path_exists(os.path.expanduser(candidate)):
            return os.path.expanduser(candidate)
    return None


def write_managed_conf(lutris_config, game):
    """Write-through helper for the GUI: writes current managed values now."""
    if not lutris_config or not bool(lutris_config.runner_config.get("dxwrapper")):
        return False
    game_dir = resolve_game_dir(game)
    if not game_dir:
        return False
    return write_dxwrapper_conf(game_dir, get_managed_values(lutris_config.runner_config))


def build_runner_options():
    """Build Wine runner option dicts for every dxwrapper.ini setting."""
    from gettext import gettext as _

    options = []
    for spec in DXWRAPPER_CONF_SPEC:
        key = spec["key"]
        kind = spec["type"]
        default = spec["default"]
        if kind == "flag":
            options.append(
                {
                    "option": key,
                    "section": _("DxWrapper Config"),
                    "config_tab": "dxwrapper",
                    "label": key,
                    "type": "bool",
                    "default": default,
                    "help": _(spec["help"]),
                }
            )
        else:
            options.append(
                {
                    "option": key,
                    "section": _("DxWrapper Config"),
                    "config_tab": "dxwrapper",
                    "label": key,
                    "type": "string",
                    "default": str(default),
                    "help": _(spec["help"]),
                }
            )
    return options
