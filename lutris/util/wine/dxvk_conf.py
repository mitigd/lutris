"""DXVK configuration (dxvk.conf) support.

DXVK reads a dxvk.conf file from the game's working directory. This module
describes every known option (key, type, default and help) so the Wine runner
can expose them in the GUI, and merges the values Lutris manages into the
game's dxvk.conf while preserving hand-written keys. The first managed write
backs the original file up to dxvk.conf.lutris-bak.
"""

import os

from lutris.util import system
from lutris.util.log import logger

CONF_FILENAME = "dxvk.conf"
CONF_BACKUP_SUFFIX = ".lutris-bak"
# Runner toggles that make this tab and file relevant. D7VK shares
# dxvk.conf with DXVK and proxies D3D7 and earlier through DXVK's D3D9 backend.
CONF_TOGGLES = ("dxvk", "d7vk")
# Full-line marker Lutris writes above the dxvk.conf lines it manages, so
# hand-written lines (even for managed keys) are never touched.
MANAGED_MARKER = "# Managed by Lutris"

AUTO_TRUE_FALSE = ("Auto", "True", "False")


def get_device_filter_choices():
    """GPU choices for dxvk.deviceFilter: label and value are the Vulkan
    device name DXVK matches against."""
    from gettext import gettext as _

    from lutris.util.graphics.gpu import get_gpus

    choices = [(_("Off"), "")]
    try:
        gpus = get_gpus()
    except Exception as ex:  # noqa: BLE001 - GPU probing must not break the dialog
        logger.warning("Could not list GPUs for dxvk.deviceFilter: %s", ex)
        return choices
    for _card, gpu in gpus.items():
        try:
            name = gpu.name
        except Exception as ex:  # noqa: BLE001
            logger.warning("Could not read GPU name: %s", ex)
            continue
        if name and (name, name) not in choices:
            choices.append((name, name))
    return choices


def _bool(key, default, help_text):
    return {"key": key, "type": "bool", "default": default, "help": help_text}


def _tri(key, default, help_text, choices=AUTO_TRUE_FALSE):
    return {"key": key, "type": "tri", "default": default, "choices": choices, "help": help_text}


def _choice(key, default, choices, help_text):
    return {"key": key, "type": "choice", "default": default, "choices": choices, "help": help_text}


def _int(key, default, help_text):
    return {"key": key, "type": "int", "default": default, "help": help_text}


def _float(key, default, help_text):
    return {"key": key, "type": "float", "default": default, "help": help_text}


def _string(key, default, help_text):
    return {"key": key, "type": "string", "default": default, "help": help_text}


DXVK_CONF_SPEC = [
    {
        "key": "dxvk.deviceFilter",
        "type": "gpu",
        "default": "",
        "help": "Only expose Vulkan devices matching this name. Useful to force a game onto a specific GPU.",
    },
    _bool(
        "dxgi.enableHDR",
        True,
        "Expose the HDR10 color space so games offer HDR output. Many games only enable HDR when they see it.",
    ),
    _bool(
        "dxgi.enableDummyCompositionSwapchain",
        False,
        "Expose dummy DirectComposition swap chains. Helps games that require the functionality to be present.",
    ),
    _bool(
        "dxvk.allowFse",
        False,
        "Let the Vulkan driver use exclusive fullscreen (needed for VRR/HDR). Breaks alt+tab and some GDI games.",
    ),
    _bool(
        "dxgi.enableUe4Workarounds",
        False,
        "Unreal Engine 4 HDR workarounds for games not following the standard -Win64-Shipping.exe naming scheme.",
    ),
    _bool(
        "dxgi.deferSurfaceCreation",
        False,
        "Create the Vulkan surface on first Present instead of swap chain creation. Fixes black windows in some games.",
    ),
    _bool(
        "d3d9.deferSurfaceCreation",
        False,
        "Create the Vulkan surface on first Present instead of swap chain creation. Fixes black windows in some games.",
    ),
    _int(
        "dxgi.maxFrameLatency",
        0,
        "Cap the maximum frame latency (0-16), overriding the app. 0 disables.",
    ),
    _int(
        "d3d9.maxFrameLatency",
        0,
        "Cap the maximum frame latency (0-16), overriding the app. 0 disables.",
    ),
    _int(
        "dxgi.maxFrameRate",
        0,
        "Frame rate limiter. 0 uses display refresh with Vsync; n caps FPS; -n caps only when faster; -1 disables.",
    ),
    _int(
        "d3d9.maxFrameRate",
        0,
        "Frame rate limiter. 0 uses display refresh with Vsync; n caps FPS; -n caps only when faster; -1 disables.",
    ),
    _int(
        "dxvk.maxFrameRate",
        0,
        "Frame rate limiter. 0 uses display refresh with Vsync; n caps FPS; -n caps only when faster; -1 disables.",
    ),
    _tri(
        "dxvk.latencySleep",
        "Auto",
        "Latency sleep / Reflex. Auto uses the driver when available; True forces the built-in heuristic.",
    ),
    _int(
        "dxvk.latencyTolerance",
        1000,
        "Latency sleep tolerance in microseconds. Higher values add latency but may smooth frame pacing.",
    ),
    _tri(
        "dxvk.disableNvLowLatency2",
        "Auto",
        "Disable VK_NV_low_latency2 (off in 32-bit apps by default). Also removes Reflex support.",
    ),
    _string(
        "dxgi.customDeviceId",
        "0000",
        "Override the PCI device ID reported to the application. Any four-digit hex number.",
    ),
    _string(
        "dxgi.customVendorId",
        "0000",
        "Override the PCI vendor ID reported to the application. Any four-digit hex number.",
    ),
    _string(
        "d3d9.customDeviceId",
        "0000",
        "Override the PCI device ID reported to the application. Any four-digit hex number.",
    ),
    _string(
        "d3d9.customVendorId",
        "0000",
        "Override the PCI vendor ID reported to the application. Any four-digit hex number.",
    ),
    _string(
        "dxgi.customDeviceDesc",
        "",
        "Override the device description string reported to the application.",
    ),
    _string(
        "d3d9.customDeviceDesc",
        "",
        "Override the device description string reported to the application.",
    ),
    _tri(
        "dxgi.hideNvidiaGpu",
        "Auto",
        "Report Nvidia GPUs as AMD. Works around crashes and slow Nvidia code paths, especially Unreal Engine.",
    ),
    _tri(
        "d3d9.hideNvidiaGpu",
        "Auto",
        "Report Nvidia GPUs as AMD. Only applied to games known to misbehave on Nvidia.",
    ),
    _tri(
        "dxgi.hideNvkGpu",
        "Auto",
        "Report Nvidia GPUs running on the NVK driver as AMD GPUs.",
    ),
    _tri(
        "d3d9.hideNvkGpu",
        "Auto",
        "Report Nvidia GPUs running on the NVK driver as AMD GPUs.",
    ),
    _tri(
        "dxgi.hideAmdGpu",
        "Auto",
        "Report AMD GPUs as Nvidia. Only for games with broken AMD-specific code paths such as AMDAGS.",
    ),
    _tri(
        "d3d9.hideAmdGpu",
        "Auto",
        "Report AMD GPUs as Nvidia. Only for games with broken AMD-specific code paths such as AMDAGS.",
    ),
    _tri(
        "dxgi.hideIntelGpu",
        "Auto",
        "Report Intel GPUs as AMD. For games with issues with Intel-specific libraries such as XeSS.",
    ),
    _bool(
        "d3d9.hideIntelGpu",
        True,
        "Report Intel GPUs as AMD. Defaults to on to work around iGPU restrictions affecting early Intel hardware.",
    ),
    _int(
        "dxgi.maxDeviceMemory",
        0,
        "Override reported device memory in MB. May fix streaming in games that dislike large VRAM. 0 disables.",
    ),
    _int(
        "dxgi.maxSharedMemory",
        0,
        "Override reported shared memory in MB. May fix streaming in games that dislike large amounts. 0 disables.",
    ),
    _int(
        "dxgi.syncInterval",
        -1,
        "Override Vsync: 0 disables it, positive n repeats each image n times. Negative values have no effect.",
    ),
    _int(
        "d3d9.presentInterval",
        -1,
        "Override Vsync: 0 disables it, positive n repeats each image n times. Negative values have no effect.",
    ),
    _tri(
        "dxvk.tearFree",
        "Auto",
        "Tearing behaviour: True uses mailbox mode with in-game Vsync off; False uses relaxed FIFO with Vsync on.",
    ),
    _tri(
        "dxvk.tilerMode",
        "Auto",
        "Tiler GPU optimizations. Only intended for performance testing and debugging.",
    ),
    _choice(
        "d3d11.maxFeatureLevel",
        "12_1",
        ("9_1", "9_2", "9_3", "10_0", "10_1", "11_0", "11_1", "12_0", "12_1"),
        "Highest D3D11 feature level an application may create. Raising it can let some games create their device.",
    ),
    _int(
        "d3d11.maxTessFactor",
        0,
        "Cap the tessellation factor (8-64) for titles that overuse tessellation. 0 disables.",
    ),
    _bool(
        "d3d11.relaxedBarriers",
        False,
        "Relax UAV pipeline barriers. Faster in some games, can glitch rendering. Do not report bugs with it on.",
    ),
    _bool(
        "d3d11.relaxedGraphicsBarriers",
        False,
        "Relax UAV barriers in graphics shaders only (compute UAVs unaffected). Do not report bugs with it on.",
    ),
    _int(
        "d3d11.samplerAnisotropy",
        -1,
        "Force anisotropic filtering for all samplers (0-16). 0 disables AF; negatives do nothing. Can break games.",
    ),
    _int(
        "d3d9.samplerAnisotropy",
        -1,
        "Force anisotropic filtering for all samplers (0-16). 0 disables AF; negatives do nothing. Can break games.",
    ),
    _float(
        "d3d11.samplerLodBias",
        0.0,
        "Add this mipmap LOD bias to every sampler (-2.0 to 1.0). Negative values sharpen at the cost of shimmer.",
    ),
    _float(
        "d3d9.samplerLodBias",
        0.0,
        "Add this mipmap LOD bias to every sampler (-2.0 to 1.0). Negative values sharpen at the cost of shimmer.",
    ),
    _bool(
        "d3d11.clampNegativeLodBias",
        False,
        "Clamp negative LOD bias to 0 after samplerLodBias. Helps games with a high negative bias by default.",
    ),
    _bool(
        "d3d9.clampNegativeLodBias",
        False,
        "Clamp negative LOD bias to 0 after samplerLodBias. Helps games with a high negative bias by default.",
    ),
    _bool(
        "d3d11.forceSampleRateShading",
        False,
        "Force per-sample shading with MSAA. Clearer image at a large performance cost; may break some games.",
    ),
    _bool(
        "d3d9.forceSampleRateShading",
        False,
        "Force per-sample shading with MSAA. Clearer image at a large performance cost; may break some games.",
    ),
    _bool(
        "d3d11.disableMsaa",
        False,
        "Force the sample count of all textures to 1, fixing up resolves and shaders.",
    ),
    _bool(
        "d3d11.forceComputeLdsBarriers",
        False,
        "Barrier after group-shared writes in compute shaders. For unsynchronized games; may cost performance.",
    ),
    _bool(
        "d3d11.forceComputeUavBarriers",
        False,
        "Barrier after coherent UAV access in compute shaders. For unsynchronized games; may cost performance.",
    ),
    _bool(
        "dxvk.zeroMappedMemory",
        False,
        "Zero mapped memory when freed. Huge CPU overhead; last resort for games that don't initialize mapped buffers.",
    ),
    _string(
        "d3d11.cachedDynamicResources",
        "",
        "Allocate dynamic resources in cached memory for fast CPU readback. Buggy apps only; may hurt GPU performance.",
    ),
    _bool(
        "d3d11.disableDirectImageMapping",
        False,
        "Disable direct image mapping for games that expect tightly packed rows for mapped dynamic images.",
    ),
    _bool(
        "d3d11.enableContextLock",
        False,
        "Force the D3D11 context lock via ID3D10Multithread. Useful to debug race conditions.",
    ),
    _bool(
        "d3d11.exposeDriverCommandLists",
        True,
        "Expose driver command list support. Some games use it to decide on deferred contexts.",
    ),
    _bool(
        "d3d11.reproducibleCommandStream",
        False,
        "Identical Vulkan commands between runs. For benchmarking; hurts performance and can break games.",
    ),
    _bool(
        "d3d9.reproducibleCommandStream",
        False,
        "Identical Vulkan commands between runs. For benchmarking; hurts performance and can break games.",
    ),
    _int(
        "dxvk.numCompilerThreads",
        0,
        "Pipeline compiler threads when the graphics pipeline library is enabled. 0 uses all CPU cores.",
    ),
    _tri(
        "dxvk.useRawSsbo",
        "Auto",
        "Implement raw/structured buffer views with storage buffers. Can be faster, but unsafe on some hardware.",
    ),
    _tri(
        "dxvk.enableGraphicsPipelineLibrary",
        "Auto",
        "Use VK_EXT_graphics_pipeline_library. Disabling likely increases stutter. Debug purposes only.",
    ),
    _tri(
        "dxvk.enableDescriptorHeap",
        "Auto",
        "Use VK_EXT_descriptor_heap. Takes precedence over descriptor buffers when both apply.",
    ),
    _tri(
        "dxvk.enableDescriptorBuffer",
        "Auto",
        "Use VK_EXT_descriptor_buffer. The descriptor heap feature takes precedence when enabled.",
    ),
    _bool(
        "dxvk.enableUnifiedImageLayouts",
        True,
        "Use VK_KHR_unified_image_layouts and opportunistic layout paths. Debugging aid; leave enabled.",
    ),
    _bool(
        "dxvk.enableImplicitResolves",
        True,
        "Resolve multisampled images sampled as textures (fixes Nvidia striping). Disable only if unneeded.",
    ),
    _bool(
        "dxvk.enableNvRawAccessChains",
        True,
        "Use VK_NV_raw_access_chains on Nvidia. Disabling costs performance; debugging only.",
    ),
    _bool(
        "dxvk.enableNvCudaInterop",
        True,
        "Enable the VK_NVX_* extensions required for DLSS on 64-bit games on Nvidia.",
    ),
    _bool(
        "dxvk.enablePresentTiming",
        True,
        "Present timing for frame pacing and the frame rate limiter. Disable for debugging only.",
    ),
    _tri(
        "dxvk.trackPipelineLifetime",
        "Auto",
        "Aggressively free pipeline libraries to save memory. Auto enables it for 32-bit applications only.",
    ),
    _tri(
        "dxvk.enableMemoryDefrag",
        "Auto",
        "Defragment video memory when much is wasted or the budget is exceeded. Debug purposes only.",
    ),
    _string(
        "dxvk.hud",
        "",
        "DXVK HUD elements, same syntax as the DXVK_HUD environment variable. Ignored when the variable is set.",
    ),
    _choice(
        "d3d9.shaderModel",
        3,
        (0, 1, 2, 3),
        "Shader model reported to the application (0 is fixed-function only). Limited to 1 for D3D8 applications.",
    ),
    _bool(
        "d3d9.dpiAware",
        True,
        "Call SetProcessDPIAware on device creation to avoid upscaling blur on Hi-DPI screens.",
    ),
    _bool(
        "d3d9.lenientClear",
        False,
        "Fast-path clears that are close to, but not exactly, a full render target.",
    ),
    _int(
        "d3d9.maxAvailableMemory",
        4096,
        "Initial value for memory tracking and GetAvailableTextureMem, in MB.",
    ),
    _bool(
        "d3d9.memoryTrackTest",
        False,
        "Memory tracking test mode. Pairs with maxAvailableMemory.",
    ),
    _choice(
        "d3d9.floatEmulation",
        "Auto",
        ("Auto", "True", "False", "Strict"),
        "Float quirk emulation: True is fast but less accurate, Strict is slow but correct, Auto picks per game.",
    ),
    _tri(
        "dxvk.lowerSinCos",
        "Auto",
        "Custom sin/cos approximation. Accurate on some hardware; costs performance. Auto enables it where needed.",
        choices=("True", "Auto", "False"),
    ),
    _tri(
        "d3d9.deviceLocalConstantBuffers",
        "Auto",
        "Stream shader constants to VRAM. May help GPU-bound scenes. Auto enables it on discrete GPUs only.",
        choices=("True", "Auto", "False"),
    ),
    _bool(
        "d3d9.supportCubeDepthFormats",
        False,
        "Depth formats on cube textures like old drivers. Needed by some games, breaks others such as Gothic 3.",
    ),
    _bool(
        "d3d9.supportDFFormats",
        True,
        "Support vendor DF floating point depth formats on AMD and Intel. Ignored on Nvidia.",
    ),
    _bool(
        "d3d9.useD32forD24",
        False,
        "Use D32F for D24. Useful to reproduce AMD issues on other hardware.",
    ),
    _bool(
        "d3d9.supportX4R4G4B4",
        True,
        "Support the X4R4G4B4 format. The Sims 2 is a very broken game.",
    ),
    _bool(
        "d3d9.disableA8RT",
        False,
        "Disable A8 format render targets. The Sims 2 is a very broken game.",
    ),
    _bool(
        "d3d9.forceSamplerTypeSpecConstants",
        False,
        "Force sampler type spec constants. Fixes rendering in old broken games like Halo: CE or SpellForce.",
    ),
    _string(
        "d3d9.forceAspectRatio",
        "",
        'Only expose display modes with this aspect ratio (e.g. "16:9", "4:3"). For titles that break on ultra-wide.',
    ),
    _int(
        "dxgi.forceRefreshRate",
        0,
        "Only expose modes with this refresh rate in Hz. 0 disables. High rates can break games; use with caution.",
    ),
    _int(
        "d3d9.forceRefreshRate",
        0,
        "Only expose modes with this refresh rate in Hz. 0 disables. High rates can break games; use with caution.",
    ),
    _bool(
        "d3d9.modeCountCompatibility",
        False,
        "Only list the desktop resolution plus minimal fallbacks. For titles choking on too many modes, e.g. AquaNox.",
    ),
    _bool(
        "d3d9.enumerateByDisplays",
        True,
        "Enumerate D3D9 adapters by display (Windows behaviour) instead of by physical adapter. May help PRIME setups.",
    ),
    _bool(
        "d3d9.cachedWriteOnlyBuffers",
        False,
        "Allocate write-only D3DPOOL_DEFAULT resources in cached memory for fast CPU readback. Buggy apps only.",
    ),
    _bool(
        "d3d9.seamlessCubes",
        False,
        "Avoid non-seamless cube maps when supported. Non-seamless is correct D3D9 but can look worse.",
    ),
    _bool(
        "dxvk.enableDebugUtils",
        False,
        "Enable debug utils (user annotations like BeginEvent/EndEvent). Alternatively set DXVK_DEBUG=markers.",
    ),
    _int(
        "d3d9.textureMemory",
        100,
        "Virtual memory for D3D9 textures, in MB. 0 disables the limit. Not quality-related; do not change lightly.",
    ),
    _bool(
        "dxvk.hideIntegratedGraphics",
        False,
        "Hide integrated graphics when dedicated GPUs exist. Prefer DXVK_FILTER_DEVICE_NAME unless a game needs this.",
    ),
    _bool(
        "d3d9.deviceLossOnFocusLoss",
        False,
        "Report DEVICELOST when a fullscreen game loses focus. Some games need it, others mishandle it.",
    ),
    _bool(
        "d3d9.countLosableResources",
        True,
        "Reject Device::Reset while losable resources are alive, as real D3D9 does. Leaky games may hang with it on.",
    ),
    _bool(
        "d3d9.extraFrontbuffer",
        False,
        "Second buffer so GetFrontBufferData works on single-buffered swap chains. Only one modded game needs it.",
    ),
    _tri(
        "d3d9.useFP16",
        "False",
        "FP16 for partial-precision shader instructions. Faster on weak GPUs, may glitch rendering on desktops.",
        choices=("True", "Auto", "False"),
    ),
    _bool(
        "d3d9.ignoreDefaultBufferLockRange",
        False,
        "Ignore the locking range for D3DPOOL_DEFAULT buffers and mark the whole buffer dirty. May cost performance.",
    ),
    _int(
        "d3d8.scaleDref",
        0,
        "Scale the depth texcoord back to [0..1] for early D3D8 games expecting [0..2^bitDepth - 1]. Typically 24.",
    ),
    _bool(
        "d3d8.shadowPerspectiveDivide",
        False,
        "Force projected texture coordinates for depth textures in slot 0, emulating GeForce 3/4 era Nvidia hardware.",
    ),
    _string(
        "d3d8.forceVsDecl",
        "",
        'Force a vertex shader declaration, e.g. "0:2,3:2,7:1". Fixes games using undeclared shader inputs.',
    ),
    _bool(
        "d3d8.batching",
        False,
        "Batch many similar draw calls. Helps specific games drawing triangle-by-triangle; can hurt or glitch others.",
    ),
    _bool(
        "d3d8.placeP8InScratch",
        False,
        "Put P8 textures in D3DPOOL_SCRATCH so creation succeeds unsupported. For old titles mishandling P8.",
    ),
    _bool(
        "d3d8.forceLegacyBuffers",
        False,
        "Ignore D3DLOCK_DISCARD except for dynamic write-only buffers and map directly. Costs performance.",
    ),
    _int(
        "dxvk.maxMemoryBudget",
        0,
        "Limit VRAM DXVK uses, in MB. Debug only; expect severe performance degradation. 0 disables.",
    ),
    _bool(
        "ddraw.forceLegacyBuffers",
        False,
        "D7VK: ignore D3DLOCK_DISCARD except for dynamic write-only buffers. Costs performance.",
    ),
    _bool(
        "ddraw.forceMultiThreaded",
        False,
        "D7VK: multithreaded device protection for apps needing thread safety without the cooperative level.",
    ),
    _bool(
        "ddraw.supportD16",
        True,
        "D7VK: advertise D16 depth surfaces. Disabling may fix Z-fighting but can crash games needing D16.",
    ),
    _choice(
        "ddraw.alternatePixelCenter",
        "False",
        ("False", "True", "Legacy"),
        "D7VK: half-texel offset correction for games like Resident Evil 1/2. Legacy applies it to SWVP transforms.",
    ),
    _bool(
        "ddraw.backBufferResize",
        True,
        "D7VK: resize an oversized back buffer to the display mode. Helps fullscreen on Wayland.",
    ),
    _bool(
        "ddraw.forceLegacyPresent",
        False,
        "D7VK: shadow-surface presentation for early D3D games blitting onto the front buffer. Fixes flickering.",
    ),
    _bool(
        "ddraw.forceDCForwarding",
        False,
        "D7VK: forward GetDC/ReleaseDC to D3D9 surfaces. Faster for some apps, slower or neutral for others.",
    ),
    _bool(
        "ddraw.emulateFrontBuffer",
        False,
        "D7VK: re-upload the front buffer for legacy games reading it. An extra copy; use only when needed.",
    ),
    _bool(
        "ddraw.ignoreGammaRamp",
        False,
        "D7VK: ignore application gamma ramps. Testing/debugging or personal preference.",
    ),
    _bool(
        "ddraw.autoGenMipMaps",
        False,
        "D7VK: generate mipmaps on the GPU. Faster, but can break some apps or fix others like UE1 titles.",
    ),
    _choice(
        "ddraw.emulateFSAA",
        "False",
        ("False", "True", "Forced"),
        "D7VK: emulate full-scene AA up to 4x. True advertises it, Forced also enables it. Costs performance.",
    ),
    _bool(
        "ddraw.legacyDeviceNames",
        False,
        "D7VK: report native D3D device names for games matching on them. Otherwise cosmetic.",
    ),
]

MANAGED_KEYS = frozenset(spec["key"] for spec in DXVK_CONF_SPEC)


def _normalize(value):
    """Format a GUI value the way dxvk.conf expects it."""
    if value is True:
        return "True"
    if value is False:
        return "False"
    return str(value)


def get_managed_values(runner_config):
    """Return {conf key: value} for options differing from their default."""
    values = {}
    for spec in DXVK_CONF_SPEC:
        key = spec["key"]
        if key not in runner_config:
            continue
        value = runner_config[key]
        if value is None:
            continue
        if _normalize(value) != _normalize(spec["default"]):
            values[key] = _normalize(value)
    return values


def parse_conf(text):
    """Parse dxvk.conf text into entries preserving order and comments.

    Returns a list of ("raw", line) for comments/blanks/unknown lines and
    ("kv", key, value, managed, line) for assignments, where managed is
    True when the line carries Lutris' management marker.
    """
    entries = []
    marked = False
    for line in text.splitlines():
        stripped = line.strip()
        if stripped == MANAGED_MARKER:
            marked = True
            continue
        if not stripped or stripped.startswith("#") or stripped.startswith(";") or "=" not in stripped:
            entries.append(("raw", line))
            marked = False
            continue
        key, _, value = stripped.partition("=")
        entries.append(("kv", key.strip(), value.strip(), marked, line))
        marked = False
    return entries


def merge_conf(entries, values):
    """Merge managed values into parsed entries.

    Lutris-managed lines are updated or, when reset to default, removed.
    Hand-written lines (even for managed keys) and unknown keys are
    preserved verbatim; new managed keys are appended with a marker.
    """
    lines = []
    seen = set()
    for entry in entries:
        if entry[0] == "raw":
            lines.append(entry[1])
            continue
        _kind, key, _value, managed, line = entry
        if key not in MANAGED_KEYS or not managed:
            if key in values and key not in seen:
                # GUI takes ownership of a hand-written line for this key.
                lines.append(MANAGED_MARKER)
                lines.append("%s = %s" % (key, values[key]))
                seen.add(key)
            else:
                lines.append(line)
            continue
        seen.add(key)
        if key in values:
            lines.append(MANAGED_MARKER)
            lines.append("%s = %s" % (key, values[key]))
        # Managed keys reset to default are dropped.
    for key, value in values.items():
        if key not in seen:
            lines.append(MANAGED_MARKER)
            lines.append("%s = %s" % (key, value))
    text = "\n".join(lines)
    return text + "\n" if text.strip() else ""


def write_dxvk_conf(game_dir, values):
    """Write the managed values into the game dir's dxvk.conf.

    Returns True when the file was created, updated or removed. Does
    nothing when there is nothing to write and nothing to clean up.
    """
    if not game_dir or not system.path_exists(game_dir):
        logger.warning("Game directory %s does not exist, skipping dxvk.conf.", game_dir)
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
    has_managed = any(entry[0] == "kv" and entry[1] in MANAGED_KEYS for entry in entries)
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
    """Best-effort game directory for dxvk.conf deployment."""
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
    """Write-through helper for the GUI: writes current managed values now.

    Returns True when the file was created, updated or removed."""
    if not lutris_config or not any(bool(lutris_config.runner_config.get(opt)) for opt in CONF_TOGGLES):
        return False
    game_dir = resolve_game_dir(game)
    if not game_dir:
        return False
    return write_dxvk_conf(game_dir, get_managed_values(lutris_config.runner_config))


def build_runner_options():
    """Build Wine runner option dicts for every dxvk.conf setting.

    The section only applies while DXVK is enabled (conditional_on).
    """
    from gettext import gettext as _

    options = []
    for spec in DXVK_CONF_SPEC:
        key = spec["key"]
        kind = spec["type"]
        default = spec["default"]
        if kind == "bool":
            options.append(
                {
                    "option": key,
                    "section": _("DXVK Config"),
                    "config_tab": "dxvk",
                    "label": key,
                    "type": "bool",
                    "default": default,
                    "help": _(spec["help"]),
                }
            )
        elif kind == "gpu":
            options.append(
                {
                    "option": key,
                    "section": _("DXVK Config"),
                    "config_tab": "dxvk",
                    "label": key,
                    "type": "choice",
                    "choices": get_device_filter_choices,
                    "default": default,
                    "help": _(spec["help"]),
                }
            )
        elif kind in ("tri", "choice"):
            # Choice ids must be strings for the combobox; labels stay
            # untranslated since they are literal dxvk.conf syntax.
            str_choices = [(str(c), str(c)) for c in spec["choices"]]
            options.append(
                {
                    "option": key,
                    "section": _("DXVK Config"),
                    "config_tab": "dxvk",
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
                    "section": _("DXVK Config"),
                    "config_tab": "dxvk",
                    "label": key,
                    "type": "string",
                    "default": str(default),
                    "help": _(spec["help"]),
                }
            )
    return options
