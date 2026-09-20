"""dgVoodoo2 configuration (dgVoodoo.conf) support.

dgVoodoo2 reads dgVoodoo.conf from the game directory. Keys repeat across
sections (Resolution, Antialiasing, ...), so managed identity is the
(section, key) pair while GUI options are named "Section.Key". Anything
unknown (extra sections, comments, the Version header) is preserved
verbatim. Booleans are lowercase true/false. The first managed write backs
the file up to dgVoodoo.conf.lutris-bak.
"""

import os

from lutris.util import system
from lutris.util.log import logger

CONF_FILENAME = "dgVoodoo.conf"
CONF_BACKUP_SUFFIX = ".lutris-bak"
# Full-line marker Lutris writes above the dgVoodoo.conf lines it manages, so
# hand-written lines (even for managed keys) are never touched.
MANAGED_MARKER = "# Managed by Lutris"


def _bool(section, key, default, help_text):
    return {"section": section, "key": key, "type": "bool", "default": default, "help": help_text}


def _choice(section, key, default, choices, help_text):
    return {"section": section, "key": key, "type": "choice", "default": default, "choices": choices, "help": help_text}


def _int(section, key, default, help_text):
    return {"section": section, "key": key, "type": "int", "default": default, "help": help_text}


def _string(section, key, default, help_text):
    return {"section": section, "key": key, "type": "string", "default": default, "help": help_text}


DGVOODOO_CONF_SPEC = [
    # [General]
    _choice(
        "General",
        "OutputAPI",
        "bestavailable",
        ("d3d11warp", "d3d11_fl10_0", "d3d11_fl10_1", "d3d11_fl11_0", "d3d12_fl11_0", "d3d12_fl12_0", "bestavailable"),
        "Output API for rendering.",
    ),
    _string("General", "Adapters", "all", "Adapters to use: all, or an adapter ordinal (1, ...)."),
    _string("General", "FullScreenOutput", "default", "Fullscreen output: default, or an output ordinal (1, ...)."),
    _bool("General", "FullScreenMode", True, "Start fullscreen."),
    _choice(
        "General",
        "ScalingMode",
        "unspecified",
        (
            "unspecified",
            "centered",
            "stretched",
            "centered_ar",
            "stretched_ar",
            "stretched_ar_crt",
            "stretched_4_3",
            "stretched_4_3_crt",
            "stretched_4_3_c64",
        ),
        "How the output image scales to the display.",
    ),
    _bool("General", "ProgressiveScanlineOrder", False, "Progressive scanline order."),
    _bool("General", "EnumerateRefreshRates", False, "Enumerate refresh rates to the application."),
    _int("General", "Brightness", 100, "Brightness (percent)."),
    _int("General", "Color", 100, "Color saturation (percent)."),
    _int("General", "Contrast", 100, "Contrast (percent)."),
    _bool(
        "General",
        "InheritColorProfileInFullScreenMode",
        True,
        "Inherit the color profile in fullscreen. Disable only with explicit D3D11 output for old hardware.",
    ),
    _bool("General", "KeepWindowAspectRatio", True, "Keep the window aspect ratio."),
    _bool("General", "CaptureMouse", True, "Capture the mouse in the game window."),
    _bool("General", "CenterAppWindow", False, "Center the application window."),
    _bool("General", "DisableScreenSaver", False, "Disable screen saver and monitor sleep while rendering."),
    # [GeneralExt]
    _string(
        "GeneralExt",
        "DesktopResolution",
        "",
        "Force a desktop resolution for dgVoodoo's calculations, compact format. Rarely needed.",
    ),
    _string("GeneralExt", "DesktopBitDepth", "", "Screen bit depth reported through dgVoodoo (8, 16, 32)."),
    _int("GeneralExt", "DeframerSize", 1, "Black frame thickness around forced resolutions (max 16, 0 disables)."),
    _string(
        "GeneralExt",
        "ImageScaleFactor",
        "1",
        "Integer output image scale factor (0 = max available). Separate axes like x:3, y:2 are allowed.",
    ),
    _int("GeneralExt", "CursorScaleFactor", 0, "Emulated hardware mouse scale factor (max 16, 0 automatic)."),
    _string(
        "GeneralExt",
        "DisplayROI",
        "",
        "Subrect of the output image to display, e.g. 16_9 with pos:centered. Empty means the whole image.",
    ),
    _choice(
        "GeneralExt",
        "Resampling",
        "bilinear",
        ("pointsampled", "bilinear", "bicubic", "lanczos-2", "lanczos-3"),
        "Filter used when dgVoodoo scales the output image.",
    ),
    _choice(
        "GeneralExt",
        "PresentationModel",
        "auto",
        ("auto", "discard", "seq", "flip_discard", "flip_seq"),
        "Low-level swapchain swap effect. Flip models suit modern OS features; legacy models can present faster.",
    ),
    _choice(
        "GeneralExt",
        "ColorSpace",
        "appdriven",
        ("appdriven", "argb8888_srgb", "argb2101010_sdr", "argb2101010_sdr_wcg", "argb16161616_hdr"),
        "Swap chain color space.",
    ),
    _int("GeneralExt", "WatermarkDisplayDuration", 0, "Watermark display duration in seconds. 0 is infinite."),
    _bool("GeneralExt", "FreeMouse", False, "Let the physical mouse move freely inside the game window."),
    _string(
        "GeneralExt",
        "WindowedAttributes",
        "",
        "Forced windowed attributes, comma separated: borderless, alwaysontop, fullscreenize.",
    ),
    _string("GeneralExt", "FullscreenAttributes", "", "Fullscreen attributes, comma separated: fake."),
    _string("GeneralExt", "FPSLimit", "0", "FPS limit, integer or fraction. 0 is unlimited."),
    _string("GeneralExt", "Environment", "", "Software environment: native, DosBox or QEmu."),
    _string("GeneralExt", "SystemHookFlags", "", "System hooks for x86-DX: gdi, cursor."),
    # [Glide]
    _choice(
        "Glide",
        "VideoCard",
        "voodoo_2",
        ("voodoo_graphics", "voodoo_rush", "voodoo_2", "voodoo_banshee", "other_greater"),
        "Emulated 3Dfx card.",
    ),
    _int("Glide", "OnboardRAM", 8, "Emulated onboard RAM in MB."),
    _int("Glide", "MemorySizeOfTMU", 4096, "TMU memory size in KB."),
    _int("Glide", "NumberOfTMUs", 2, "Number of TMUs."),
    _choice("Glide", "TMUFiltering", "appdriven", ("appdriven", "pointsampled", "bilinear"), "TMU filtering."),
    _bool("Glide", "DisableMipmapping", False, "Disable mipmapping."),
    _string(
        "Glide",
        "Resolution",
        "unforced",
        "Forced resolution: unforced, max variants, desktop, compact like 1024x768@60, h:/v:/refrate: subs.",
    ),
    _choice("Glide", "Antialiasing", "appdriven", ("off", "appdriven", "2x", "4x", "8x", "16x"), "Antialiasing level."),
    _bool("Glide", "EnableGlideGammaRamp", True, "Enable Glide gamma ramp."),
    _bool("Glide", "ForceVerticalSync", True, "Force vertical synchronization."),
    _bool("Glide", "ForceEmulatingTruePCIAccess", False, "Force emulating true PCI access."),
    _bool("Glide", "16BitDepthBuffer", False, "16-bit depth buffer."),
    _bool("Glide", "3DfxWatermark", True, "Show the 3Dfx watermark."),
    _bool("Glide", "3DfxSplashScreen", False, "Show the 3Dfx splash screen."),
    _bool("Glide", "PointcastPalette", False, "Pointcast palette."),
    _bool("Glide", "EnableInactiveAppState", False, "Enable inactive application state."),
    # [GlideExt]
    _choice(
        "GlideExt",
        "DitheringEffect",
        "pure32bit",
        ("pure32bit", "dither2x2", "dither4x4"),
        "Dithering effect.",
    ),
    _choice("GlideExt", "Dithering", "forcealways", ("disabled", "appdriven", "forcealways"), "Dithering mode."),
    _int("GlideExt", "DitherOrderedMatrixSizeScale", 0, "Dither matrix size scale. 0 is automatic."),
    # [DirectX]
    _choice(
        "DirectX",
        "VideoCard",
        "internal3D",
        (
            "svga",
            "internal3D",
            "geforce_ti_4800",
            "ati_radeon_8500",
            "matrox_parhelia-512",
            "geforce_fx_5700_ultra",
            "geforce_9800_gt",
        ),
        "Emulated DirectX card.",
    ),
    _string("DirectX", "VRAM", "256", "Emulated VRAM, in MB or GB (e.g. 2GB)."),
    _string(
        "DirectX",
        "Filtering",
        "appdriven",
        "Filtering: appdriven, pointsampled, bilinear, pointmip, linearmip, trilinear, or an anisotropy level 1-16.",
    ),
    _choice(
        "DirectX",
        "Mipmapping",
        "appdriven",
        ("appdriven", "disabled", "autogen_point", "autogen_bilinear"),
        "Mipmap generation mode.",
    ),
    _bool("DirectX", "KeepFilterIfPointSampled", False, "Only force filtering on non-point-sampled textures."),
    _string("DirectX", "Resolution", "unforced", "Forced resolution, same format as Glide."),
    _choice(
        "DirectX", "Antialiasing", "appdriven", ("off", "appdriven", "2x", "4x", "8x", "16x"), "Antialiasing level."
    ),
    _bool("DirectX", "AppControlledScreenMode", True, "Let the application control the screen mode."),
    _bool("DirectX", "DisableAltEnterToToggleScreenMode", True, "Disable Alt+Enter screen mode toggling."),
    _bool("DirectX", "Bilinear2DOperations", False, "Transfer DirectDraw blits with bilinear scaling."),
    _bool("DirectX", "PhongShadingWhenPossible", False, "Phong shading when possible."),
    _bool("DirectX", "ForceVerticalSync", False, "Force vertical synchronization."),
    _bool("DirectX", "dgVoodooWatermark", True, "Show the dgVoodoo watermark."),
    _bool("DirectX", "FastVideoMemoryAccess", False, "Fast video memory access."),
    _bool("DirectX", "DisableD3DTnLDevice", False, "Don't enumerate the TnL device (no hardware T&L)."),
    # [DirectXExt]
    _string("DirectXExt", "AdapterIDType", "", "Reported ids type: nvidia, amd, intel. SVGA/Internal3D only."),
    _string("DirectXExt", "VendorID", "", "Override vendor id. SVGA/Internal3D only."),
    _string("DirectXExt", "DeviceID", "", "Override device id. SVGA/Internal3D only."),
    _string("DirectXExt", "SubsystemID", "", "Override subsystem id. SVGA/Internal3D only."),
    _string("DirectXExt", "RevisionID", "", "Override revision id. SVGA/Internal3D only."),
    _choice(
        "DirectXExt",
        "DefaultEnumeratedResolutions",
        "all",
        ("all", "classics", "none"),
        "Resolutions enumerated to the application by default.",
    ),
    _string(
        "DirectXExt",
        "ExtraEnumeratedResolutions",
        "",
        "Extra resolutions to enumerate (max 16, comma separated), e.g. max_4_3@60, max_16_9.",
    ),
    _string(
        "DirectXExt",
        "EnumeratedResolutionBitdepths",
        "all",
        "Bitdepths in resolution enumeration: any subset of 8/16/32, or all.",
    ),
    _choice(
        "DirectXExt",
        "DitheringEffect",
        "high_quality",
        ("high_quality", "ordered2x2", "ordered4x4"),
        "Dithering effect.",
    ),
    _choice(
        "DirectXExt",
        "Dithering",
        "forcealways",
        ("disabled", "appdriven", "forceon16bit", "forcealways"),
        "Dithering mode.",
    ),
    _int("DirectXExt", "DitherOrderedMatrixSizeScale", 0, "Dither matrix size scale. 0 is automatic."),
    _choice(
        "DirectXExt",
        "DepthBuffersBitDepth",
        "appdriven",
        ("appdriven", "forcemin24bit", "force32bit"),
        "Internal depth/stencil bit depth. 32 bit is not recommended.",
    ),
    _choice(
        "DirectXExt",
        "Default3DRenderFormat",
        "auto",
        ("auto", "argb8888", "argb2101010", "argb16161616"),
        "Default 3D render format.",
    ),
    _choice("DirectXExt", "MaxVSConstRegisters", 256, (256, 512, 1024), "Vertex shader constant registers (DX8/9)."),
    _bool(
        "DirectXExt",
        "D3D12BoundsChecking",
        True,
        "D3D12 backend bound checking on vs const registers. Needed for spec compliance; off may be faster.",
    ),
    _bool(
        "DirectXExt",
        "AlternativeScaling",
        False,
        "Optimize 3D upscale math for postprocess render passes (better positioning).",
    ),
    _int("DirectXExt", "NPatchTesselationLevel", 0, "Forced N-Patch tesselation level 2-8. 0 app driven, 1 disabled."),
    _string(
        "DirectXExt",
        "DisplayOutputEnableMask",
        "0xffffffff",
        "Bit mask of display outputs visible to device enumeration.",
    ),
    _bool(
        "DirectXExt",
        "MSD3DDeviceNames",
        False,
        "Expose original Microsoft D3D device names. Some applications check for them.",
    ),
    _bool(
        "DirectXExt",
        "RTTexturesForceScaleAndMSAA",
        True,
        "Apply forced scaling and MSAA to rendertarget textures too. Can easily break pixel-precise games.",
    ),
    _bool("DirectXExt", "SmoothedDepthSampling", True, "Extra smoothing when sampling depth textures."),
    _bool(
        "DirectXExt",
        "DeferredScreenModeSwitch",
        False,
        "Defer fullscreen switching until after device init. Helps games crashing on window changes.",
    ),
    _bool(
        "DirectXExt",
        "PrimarySurfaceBatchedUpdate",
        False,
        "Batch primary surface changes for presenting. Off presents every change instantly (debug-like).",
    ),
    _bool(
        "DirectXExt",
        "SuppressAMDBlacklist",
        False,
        "Ignore the AMD solid-color-textures blacklist to test if the driver issue is fixed.",
    ),
    # [Debug] (debug/spec builds only)
    _choice("Debug", "Info", "Enable", ("Disable", "Enable", "EnableBreak"), "Info messages and debugger break."),
    _choice("Debug", "Warning", "Enable", ("Disable", "Enable", "EnableBreak"), "Warning messages and debugger break."),
    _choice("Debug", "Error", "Enable", ("Disable", "Enable", "EnableBreak"), "Error messages and debugger break."),
    _int("Debug", "MaxTraceLevel", 0, "API call tracing level (0 disabled)."),
]

MANAGED_KEYS = frozenset((spec["section"], spec["key"]) for spec in DGVOODOO_CONF_SPEC)


def _option_name(section, key):
    return "%s.%s" % (section, key)


def _normalize(value):
    """Format a GUI value the way dgVoodoo.conf expects it (lowercase bools)."""
    if value is True:
        return "true"
    if value is False:
        return "false"
    return str(value)


def _normalize_choice(value, choices):
    """Match a file value against GUI choices case-insensitively."""
    for choice in choices:
        if str(choice).casefold() == str(value).casefold():
            return str(choice)
    return None


def get_managed_values(runner_config):
    """Return {(section, key): value} for options differing from default."""
    values = {}
    for spec in DGVOODOO_CONF_SPEC:
        option = _option_name(spec["section"], spec["key"])
        if option not in runner_config:
            continue
        value = runner_config[option]
        if value is None:
            continue
        kind = spec["type"]
        if kind == "bool":
            normalized, default = _normalize(value), _normalize(spec["default"])
        elif kind == "choice":
            normalized = _normalize_choice(value, spec["choices"])
            default = _normalize_choice(spec["default"], spec["choices"])
            if normalized is None:
                continue
        else:
            normalized, default = str(value), str(spec["default"])
        if normalized != default:
            values[(spec["section"], spec["key"])] = normalized
    return values


def _parse_section(header):
    return header.strip().strip("[]")


def parse_conf(text):
    """Parse dgVoodoo.conf text into entries preserving order and comments.

    Returns ("raw", line), ("section", name) or ("kv", section, key,
    value, line) tuples. Obsolete management markers left by older Lutris
    versions are silently dropped.
    """
    entries = []
    section = ""
    for line in text.splitlines():
        stripped = line.strip()
        if stripped == MANAGED_MARKER:
            continue
        if stripped.startswith("[") and stripped.endswith("]"):
            section = _parse_section(stripped)
            entries.append(("section", section))
            continue
        if not stripped or stripped.startswith("#") or stripped.startswith(";") or "=" not in stripped:
            entries.append(("raw", line))
            continue
        key, _, value = stripped.partition("=")
        key = key.strip()
        entries.append(("kv", section, key, value.strip(), line))
    return entries


def merge_conf(entries, values):
    """Merge managed values into parsed entries.

    Keys set in the GUI overwrite their line in place; everything else -
    comments, unknown keys and sections, values reset to default - is
    preserved verbatim. Missing managed keys are inserted under their
    section. Nothing is ever deleted.
    """
    lines = []
    seen = set()
    existing = {(entry[1], entry[2]) for entry in entries if entry[0] == "kv"}
    pending = {}
    for section, key in values:
        if (section, key) not in existing:
            pending.setdefault(section, {})[key] = values[(section, key)]

    def flush_pending(section):
        for key in list(pending.get(section, {})):
            lines.append("%s = %s" % (key, pending[section].pop(key)))

    for entry in entries:
        if entry[0] == "raw":
            lines.append(entry[1])
            continue
        if entry[0] == "section":
            lines.append("[%s]" % entry[1])
            flush_pending(entry[1])
            continue
        _kind, section, key, _value, line = entry
        if (section, key) in values and (section, key) not in seen:
            lines.append("%s = %s" % (key, values[(section, key)]))
            seen.add((section, key))
        else:
            lines.append(line)
    for section in list(pending):
        if pending[section]:
            if lines and lines[-1].strip():
                lines.append("")
            lines.append("[%s]" % section)
            flush_pending(section)
    text = "\n".join(lines)
    return text + "\n" if text.strip() else ""


def write_dgvoodoo_conf(game_dir, values):
    """Write the managed values into the game dir's dgVoodoo.conf.

    Returns True when the file was created or updated. Does
    nothing when there is nothing to write. Files are never deleted. The
    file itself is never deleted.
    """
    if not game_dir or not system.path_exists(game_dir):
        logger.warning("Game directory %s does not exist, skipping dgVoodoo.conf.", game_dir)
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
    if not values:
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
        with open(path, "w", encoding="utf-8") as conf_file:
            conf_file.write(merged)
        logger.info("Wrote %s with %d managed option(s).", path, len(values))
    except OSError as ex:
        logger.warning("Failed to write %s: %s", path, ex)
        return False
    return True


def resolve_game_dir(game):
    """Best-effort game directory for dgVoodoo.conf deployment."""
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


def _gui_bool(text):
    """Convert a conf bool to a GUI bool; None when unrecognized."""
    normalized = text.strip().casefold()
    if normalized in ("1", "true", "yes", "on"):
        return True
    if normalized in ("0", "false", "no", "off", ""):
        return False
    return None


def read_managed_values(game):
    """Read managed dgVoodoo.conf values for the GUI to adopt."""
    game_dir = resolve_game_dir(game)
    if not game_dir:
        return {}
    path = os.path.join(game_dir, CONF_FILENAME)
    if not system.path_exists(path):
        return {}
    try:
        with open(path, "r", encoding="utf-8") as conf_file:
            entries = parse_conf(conf_file.read())
    except OSError as ex:
        logger.debug("Could not read %s: %s", path, ex)
        return {}
    by_key = {}
    for spec in DGVOODOO_CONF_SPEC:
        by_key.setdefault((spec["section"], spec["key"]), spec)
    values = {}
    for entry in entries:
        if entry[0] != "kv":
            continue
        _kind, section, key, value, _line = entry
        spec = by_key.get((section, key))
        if spec is None:
            continue
        kind = spec["type"]
        if kind == "bool":
            converted = _gui_bool(value)
        elif kind == "choice":
            converted = _normalize_choice(value, spec["choices"])
        else:
            converted = value
        if converted is not None:
            values[_option_name(section, key)] = converted
    return values


def write_managed_conf(lutris_config, game):
    """Write-through helper for the GUI: writes current managed values now."""
    if not lutris_config or not bool(lutris_config.runner_config.get("dgvoodoo2")):
        return False
    game_dir = resolve_game_dir(game)
    if not game_dir:
        return False
    return write_dgvoodoo_conf(game_dir, get_managed_values(lutris_config.runner_config))


def build_runner_options():
    """Build Wine runner option dicts for every dgVoodoo.conf setting."""
    from gettext import gettext as _

    options = []
    for spec in DGVOODOO_CONF_SPEC:
        option = _option_name(spec["section"], spec["key"])
        kind = spec["type"]
        default = spec["default"]
        if kind == "bool":
            options.append(
                {
                    "option": option,
                    "section": _("dgVoodoo2 Config"),
                    "config_tab": "dgvoodoo2",
                    "label": option,
                    "type": "bool",
                    "default": default,
                    "help": _(spec["help"]),
                }
            )
        elif kind == "choice":
            str_choices = [(str(c), str(c)) for c in spec["choices"]]
            options.append(
                {
                    "option": option,
                    "section": _("dgVoodoo2 Config"),
                    "config_tab": "dgvoodoo2",
                    "label": option,
                    "type": "choice",
                    "choices": str_choices,
                    "default": str(default),
                    "help": _(spec["help"]),
                }
            )
        else:
            options.append(
                {
                    "option": option,
                    "section": _("dgVoodoo2 Config"),
                    "config_tab": "dgvoodoo2",
                    "label": option,
                    "type": "string",
                    "default": str(default),
                    "help": _(spec["help"]),
                }
            )
    return options
