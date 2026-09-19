"""D7VK helper module.

D7VK (https://github.com/WinterSnowfall/d7vk) is a Vulkan-based translation
layer for Direct3D 7 and earlier (shipped in ddraw.dll). It acts as a proxy
between DXVK's D3D9 backend and Wine's (or Windows native) DDraw
implementation. Upstream releases only provide 32-bit binaries in an
already standard x32/ layout, so no reshaping is needed.
"""

from lutris.util.wine.dll_manager import DLLManager


class D7vkManager(DLLManager):
    name = "d7vk"
    human_name = "D7VK"
    managed_dlls = ("ddraw",)
    releases_url = "https://api.github.com/repos/WinterSnowfall/d7vk/releases"
    # Deployed next to the game like the other DDraw replacements: Proton
    # reinstalls its own ddraw.dll into the prefix on updates, while the
    # game directory is never touched. Verified working under umu.
    prefer_game_dir = True
    proton_compatible = True
    known_versions = {
        "v2.2": "https://github.com/WinterSnowfall/d7vk/releases/download/v2.2/d7vk-v2.2.zip",
    }
