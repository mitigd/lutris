"""CnC-DDraw configuration (ddraw.ini) support.

CnC-DDraw reads ddraw.ini from the game directory. Only the global [ddraw]
section is managed here; the per-game [exename] sections are upstream's
compatibility database and are never touched. Values use lowercase
true/false. The first managed write backs the file up to
ddraw.ini.lutris-bak.
"""

import os

from lutris.util import system
from lutris.util.log import logger

CONF_FILENAME = "ddraw.ini"
CONF_BACKUP_SUFFIX = ".lutris-bak"
MANAGED_SECTION = "ddraw"
# Full-line marker Lutris writes above the ddraw.ini lines it manages, so
# hand-written lines (even for managed keys) are never touched.
MANAGED_MARKER = "# Managed by Lutris"


def _bool(key, default, help_text):
    return {"key": key, "type": "bool", "default": default, "help": help_text}


def _choice(key, default, choices, help_text):
    return {"key": key, "type": "choice", "default": default, "choices": choices, "help": help_text}


def _int(key, default, help_text):
    return {"key": key, "type": "int", "default": default, "help": help_text}


def _string(key, default, help_text):
    return {"key": key, "type": "string", "default": default, "help": help_text}


CNC_DDRAW_CONF_SPEC = [
    _int("width", 0, "Stretch to custom width. 0 defaults to the size the game requests."),
    _int("height", 0, "Stretch to custom height. 0 defaults to the size the game requests."),
    _bool("fullscreen", False, "Always stretch to fullscreen. Combines with windowed for borderless mode."),
    _bool("windowed", False, "Run in windowed mode rather than going fullscreen."),
    _bool("maintas", False, "Maintain aspect ratio when stretching."),
    _string("aspect_ratio", "", 'Custom aspect ratio, e.g. "4:3", "16:10", "16:9", "21:9".'),
    _bool("boxing", False, "Windowboxing / integer scaling."),
    _int(
        "maxfps",
        -1,
        "Rendering rate cap: -1 follows the screen rate, 0 is unlimited, n caps. Does not affect game speed.",
    ),
    _bool(
        "vsync",
        False,
        "Vertical synchronization. Fixes tearing but adds input lag. Needs an auto/opengl/direct3d9 renderer.",
    ),
    _bool(
        "adjmouse",
        True,
        "Scale mouse sensitivity with stretching. Only works while stretching is enabled.",
    ),
    _string(
        "shader",
        "Shaders\\interpolation\\catmull-rom-bilinear.glsl",
        "Libretro GLSL shader, full path or a preset such as Nearest neighbor, Bilinear, Bicubic, Lanczos, xBR-lv2.",
    ),
    _int("posX", -32000, "Window position X. -32000 centers to screen."),
    _int("posY", -32000, "Window position Y. -32000 centers to screen."),
    _choice(
        "renderer",
        "auto",
        ("auto", "opengl", "openglcore", "gdi", "direct3d9", "direct3d9on12"),
        "Renderer. Auto tries direct3d9/opengl and falls back to gdi.",
    ),
    _bool("devmode", False, "Developer mode (don't lock the cursor)."),
    _bool("border", True, "Show window borders in windowed mode."),
    _int(
        "savesettings",
        1,
        "Save window position/size/state on exit and restore it: 0 disabled, 1 global section, 2 game section.",
    ),
    _bool("resizable", True, "Allow the user to resize the window in windowed mode."),
    _int(
        "d3d9_filter",
        2,
        "Upscaling filter for the direct3d9 renderers: 0 nearest-neighbor, 1 bilinear, 2 bicubic, 3 lanczos.",
    ),
    _int("anti_aliased_fonts_min_size", 13, "Disable font smoothing for fonts smaller than this size."),
    _int("min_font_size", 0, "Raise the size of small fonts to this size."),
    _int("center_window", 1, "Center the window on resolution changes: 0 never, 1 automatic, 2 always."),
    _string(
        "inject_resolution",
        "",
        'Inject a custom display resolution into the in-game list, e.g. "960x540". Also allows downsampling.',
    ),
    _bool("vhack", False, "Upscale hack for high resolution patches (C&C1, Red Alert 1, Worms 2, KKND Xtreme)."),
    _string("screenshotdir", ".\\Screenshots\\", "Where screenshots are saved."),
    _bool("toggle_borderless", False, "Alt+Enter switches windowed/borderless instead of windowed/fullscreen."),
    _bool("toggle_upscaled", False, "Alt+Enter switches windowed/fullscreen upscaled modes."),
    _bool("noactivateapp", False, "Hide activate messages to fix alt+tab problems."),
    _int(
        "maxgameticks",
        0,
        "Max game ticks per second: -1 disabled, -2 refresh rate, 0 emulate 60hz vblank, 1-1000 custom speed.",
    ),
    _int(
        "limiter_type",
        0,
        "Tick limiter method: 0 automatic, 1 TestCooperativeLevel, 2 BltFast, 3 Unlock, 4 PeekMessage.",
    ),
    _int(
        "minfps",
        0,
        "Force minimum FPS: 0 disabled, -1 use maxfps, -2 same but force full redraw. Low values can fix hidden menus.",
    ),
    _bool(
        "nonexclusive",
        True,
        "Disable fullscreen-exclusive mode. Use when GUI elements like buttons or videos are invisible.",
    ),
    _bool("singlecpu", True, "Force CPU0 affinity. Avoids crashes/freezing; may affect smoothness or sound."),
    _int(
        "resolutions",
        0,
        "Advertised display resolutions: 0 small list, 1 very small list (fixes startup crashes), 2 full list.",
    ),
    _int(
        "fixchilds",
        2,
        "Child window handling: 0 disabled, 1 top left, 2 top left + repaint, 3 hide, 4 top left + hide.",
    ),
    _bool("hook_peekmessage", False, "Enable if the cursor won't lock or misbehaves with upscaling."),
    _bool("fix_alt_key_stuck", False, "Undocumented: fix a stuck alt key."),
    _bool("game_handles_close", False, "Undocumented: let the game handle window close."),
    _bool("fix_not_responding", False, "Undocumented: fix not-responding hangs."),
    _bool("no_compat_warning", False, "Undocumented: hide the compatibility warning."),
    _int("guard_lines", 200, "Undocumented: guard lines for rendering hacks."),
    _int("max_resolutions", 0, "Undocumented: cap the number of reported resolutions."),
    _bool("lock_surfaces", False, "Undocumented: lock surfaces."),
    _bool("flipclear", False, "Undocumented: clear on flip."),
    _bool("rgb555", False, "Undocumented: RGB555 handling."),
    _bool("no_dinput_hook", False, "Undocumented: don't hook DirectInput."),
    _bool("center_cursor_fix", False, "Undocumented: center cursor fix."),
    _bool("lock_mouse_top_left", False, "Undocumented: lock the mouse to the top left."),
    _int("hook", 4, "Undocumented: hook method."),
    _bool("limit_gdi_handles", False, "Undocumented: limit GDI handles."),
    _bool("remove_menu", False, "Undocumented: remove the window menu."),
    _int("refresh_rate", 0, "Undocumented: forced refresh rate, 0 disables."),
    _string("fake_mode", "", "Undocumented: fake display mode, e.g. 640x480x32."),
    _string("win_version", "", "Undocumented: lie about the Windows version, e.g. 95."),
    _string("checkfile", "", "Undocumented: only apply game-section matching when this file exists."),
    _string("keytogglefullscreen", "0x0D", "Hotkey: switch windowed/fullscreen with Alt. 0x00 disables."),
    _string("keytogglefullscreen2", "0x00", "Hotkey: switch windowed/fullscreen, single key. 0x00 disables."),
    _string("keytogglemaximize", "0x22", "Hotkey: maximize window with Alt. 0x00 disables."),
    _string("keytogglemaximize2", "0x00", "Hotkey: maximize window, single key. 0x00 disables."),
    _string("keyunlockcursor1", "0x09", "Hotkey: unlock cursor 1 with Ctrl. 0x00 disables."),
    _string("keyunlockcursor2", "0xA3", "Hotkey: unlock cursor 2 with Right Alt. 0x00 disables."),
    _string("keyscreenshot", "0x2C", "Hotkey: screenshot. 0x00 disables."),
    _choice(
        "configlang",
        "auto",
        ("auto", "english", "chinese", "german", "spanish", "russian", "hungarian", "french", "italian", "vietnamese"),
        "Config program language.",
    ),
    _choice("configtheme", "Windows10", ("Windows10", "Cobalt XEMedia"), "Config program theme."),
    _bool("hide_compat_tab", False, "Hide the Compatibility Settings tab in cnc-ddraw config."),
    _bool("allow_reset", True, "Allow restoring default settings via cnc-ddraw config."),
]

MANAGED_KEYS = frozenset(spec["key"] for spec in CNC_DDRAW_CONF_SPEC)


def _normalize(value):
    """Format a GUI value the way ddraw.ini expects it (lowercase bools)."""
    if value is True:
        return "true"
    if value is False:
        return "false"
    return str(value)


def get_managed_values(runner_config):
    """Return {ini key: value} for options differing from their default."""
    values = {}
    for spec in CNC_DDRAW_CONF_SPEC:
        key = spec["key"]
        if key not in runner_config:
            continue
        value = runner_config[key]
        if value is None:
            continue
        if _normalize(value) != _normalize(spec["default"]):
            values[key] = _normalize(value)
    return values


def _is_managed_section(header):
    return header.strip().casefold() == "[%s]" % MANAGED_SECTION


def parse_conf(text):
    """Parse ddraw.ini text into entries preserving order, sections and comments.

    Returns ("raw", line), ("section", name) or ("kv", section, key, value,
    managed, line) tuples. Only keys inside the global [ddraw] section can
    ever be managed; per-game sections are upstream's database.
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
            section = stripped
            entries.append(("section", section))
            marked = False
            continue
        if (
            not stripped
            or stripped.startswith("#")
            or stripped.startswith(";")
            or "=" not in stripped
            or not _is_managed_section(section)
        ):
            entries.append(("raw", line))
            marked = False
            continue
        key, _, value = stripped.partition("=")
        entries.append(("kv", section, key.strip(), value.strip(), marked, line))
        marked = False
    return entries


def merge_conf(entries, values):
    """Merge managed values into parsed entries.

    Lutris-managed lines under [ddraw] are updated or, when reset to
    default, removed. Hand-written lines, comments and every other section
    are preserved verbatim; new managed keys are appended to [ddraw].
    """
    lines = []
    seen = set()
    managed_section_seen = False
    for entry in entries:
        if entry[0] == "raw":
            lines.append(entry[1])
            continue
        if entry[0] == "section":
            lines.append(entry[1])
            if _is_managed_section(entry[1]):
                managed_section_seen = True
            continue
        _kind, _section, key, _value, managed, line = entry
        if key not in MANAGED_KEYS or not managed:
            if key in values and key not in seen:
                # GUI takes ownership of a hand-written line for this key.
                lines.append(MANAGED_MARKER)
                lines.append("%s=%s" % (key, values[key]))
                seen.add(key)
            else:
                lines.append(line)
            continue
        seen.add(key)
        if key in values:
            lines.append(MANAGED_MARKER)
            lines.append("%s=%s" % (key, values[key]))
        # Managed keys reset to default are dropped.
    if values:
        if not managed_section_seen:
            if lines and lines[-1].strip():
                lines.append("")
            lines.append("[%s]" % MANAGED_SECTION)
        for key, value in values.items():
            if key not in seen:
                lines.append(MANAGED_MARKER)
                lines.append("%s=%s" % (key, value))
    text = "\n".join(lines)
    return text + "\n" if text.strip() else ""


def write_cnc_ddraw_conf(game_dir, values):
    """Write the managed values into the game dir's ddraw.ini.

    Returns True when the file was created, updated or removed. Does
    nothing when there is nothing to write and nothing to clean up.
    """
    if not game_dir or not system.path_exists(game_dir):
        logger.warning("Game directory %s does not exist, skipping ddraw.ini.", game_dir)
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
    """Best-effort game directory for ddraw.ini deployment."""
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
    if not lutris_config or not bool(lutris_config.runner_config.get("cnc_ddraw")):
        return False
    game_dir = resolve_game_dir(game)
    if not game_dir:
        return False
    return write_cnc_ddraw_conf(game_dir, get_managed_values(lutris_config.runner_config))


def build_runner_options():
    """Build Wine runner option dicts for every ddraw.ini setting."""
    from gettext import gettext as _

    options = []
    for spec in CNC_DDRAW_CONF_SPEC:
        key = spec["key"]
        kind = spec["type"]
        default = spec["default"]
        if kind == "bool":
            options.append(
                {
                    "option": key,
                    "section": _("CnC-DDraw Config"),
                    "config_tab": "cnc_ddraw",
                    "label": key,
                    "type": "bool",
                    "default": default,
                    "help": _(spec["help"]),
                }
            )
        elif kind == "choice":
            str_choices = [(str(c), str(c)) for c in spec["choices"]]
            options.append(
                {
                    "option": key,
                    "section": _("CnC-DDraw Config"),
                    "config_tab": "cnc_ddraw",
                    "label": key,
                    "type": "choice",
                    "choices": str_choices,
                    "default": str(default),
                    "help": _(spec["help"]),
                }
            )
        else:
            options.append(
                {
                    "option": key,
                    "section": _("CnC-DDraw Config"),
                    "config_tab": "cnc_ddraw",
                    "label": key,
                    "type": "string",
                    "default": str(default),
                    "help": _(spec["help"]),
                }
            )
    return options
