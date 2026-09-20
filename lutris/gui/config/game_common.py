"""Shared config dialog stuff"""

# pylint: disable=not-an-iterable
import os
from collections.abc import Callable
from gettext import gettext as _
from typing import TYPE_CHECKING

from gi.repository import GLib, Gtk

from lutris import settings
from lutris.config import LutrisConfig, make_game_config_id, rename_config
from lutris.game import Game
from lutris.gui.config import DIALOG_HEIGHT, DIALOG_WIDTH
from lutris.gui.config.boxes import GameBox, RunnerBox, SystemConfigBox, WrapperConfBox
from lutris.gui.config.game_info_box import GameInfoBox
from lutris.gui.config.widget_generator import WidgetWarningMessageBox
from lutris.gui.dialogs import DirectoryDialog, ErrorDialog, QuestionDialog, SavableModelessDialog, display_error
from lutris.gui.dialogs.delegates import DialogInstallUIDelegate
from lutris.gui.dialogs.move_game import MoveDialog
from lutris.gui.widgets import EMPTY_NOTIFICATION_REGISTRATION
from lutris.gui.widgets.notifications import send_notification
from lutris.runners import import_runner
from lutris.services.lutris import download_lutris_media
from lutris.util.jobs import AsyncCall
from lutris.util.log import logger
from lutris.util.strings import parse_playtime, slugify
from lutris.util.wine import cnc_ddraw_conf, dgvoodoo2_conf, dxvk_conf, dxwrapper_conf

if TYPE_CHECKING:
    from lutris.gui.config.boxes import ConfigBox


class _WrapperConfigTab:
    """Manages one dynamically shown wrapper config tab (DXVK Config, ...).

    The tab only exists while its toggle option (DXVK, CnC-DDraw, ...) is
    enabled; toggling the option shows or hides it."""

    def __init__(self, dialog, runner_index, order, flags, label, tab_id, info, managed_keys, writer, reader=None):
        self.dialog = dialog
        self.runner_index = runner_index
        self.order = order
        self.flag_options = tuple(flags)
        self.reader = reader
        self.label_text = label
        self.tab_id = tab_id
        self.info_text = info
        self.managed_keys = managed_keys
        self.writer = writer
        self.box = None
        self.page = None
        self.label_widget = None
        self.visible = False
        self.saved_trackers = {}
        self.saved_sets = set()
        self.registration = EMPTY_NOTIFICATION_REGISTRATION

    def adopt_existing_values(self) -> None:
        """Adopt game-dir config values the user never set in Lutris.

        When a config file is already there (hand-written before Lutris
        managed it), its values show up in the tab instead of defaults.
        Keys already present in the runner config are never overridden."""
        dialog = self.dialog
        if not self.reader or not dialog.game or not dialog.lutris_config:
            return
        try:
            values = self.reader(dialog.game)
        except Exception as ex:
            logger.debug("Could not read existing config values: %s", ex)
            return
        if not values:
            return
        raw = dialog.lutris_config.raw_runner_config
        adopted = 0
        for key, value in values.items():
            if key not in raw:
                raw[key] = value
                adopted += 1
        if adopted:
            dialog.lutris_config.update_cascaded_config()
            logger.info("Adopted %d existing option(s) into the %s tab.", adopted, self.label_text)

    def build(self):
        dialog = self.dialog
        self.registration.unregister()
        if not dialog.lutris_config or dialog.lutris_config.runner_slug != "wine" or not dialog.runner_box:
            return
        self.adopt_existing_values()
        self.box = dialog._build_options_tab(
            self.label_text,
            lambda: WrapperConfBox(
                dialog.config_level,
                dialog.lutris_config,
                dialog.game,
                tab_id=self.tab_id,
                info_text=self.info_text,
                managed_keys=self.managed_keys,
                writer=self.writer,
            ),
        )
        self.page = dialog.notebook.get_nth_page(dialog.notebook.get_n_pages() - 1)
        self.label_widget = dialog.notebook.get_tab_label(self.page)
        self.visible = True
        self.sync()
        # The runner page generates lazily; hook the toggle once its
        # widgets (and their change notifications) exist. If it already
        # generated (page 0), connect right away.
        generator_entry = dialog.notebook_page_generators.get(self.runner_index)
        if generator_entry is None:
            self.connect()
        else:

            def generate_runner_then_connect():
                generator_entry()
                self.connect()

            dialog.notebook_page_generators[self.runner_index] = generate_runner_then_connect

    def connect(self) -> None:
        """Listen for toggle changes to show or hide this tab."""
        self.registration.unregister()
        if self.dialog.runner_box is None:
            return
        generator = self.dialog.runner_box.get_widget_generator()
        self.registration = generator.changed.register(self.on_flag_changed)

    def is_wanted(self) -> bool:
        if not self.dialog.lutris_config:
            return False
        return any(bool(self.dialog.lutris_config.runner_config.get(flag)) for flag in self.flag_options)

    def on_flag_changed(self, option_key: str, new_value) -> None:
        if option_key in self.flag_options:
            # Use the toggled value directly: the config cascade is only
            # updated after change handlers run.
            self.sync(wanted=bool(new_value))
            if new_value and self.writer:
                self.writer(self.dialog.lutris_config, self.dialog.game)

    def show_position(self) -> int:
        """Notebook position for this tab: after the runner tab, ordered
        among the other visible dynamic tabs."""
        dialog = self.dialog
        predecessors = sum(
            1 for tab in dialog.wrapper_config_tabs if tab is not self and tab.visible and tab.order < self.order
        )
        return min(self.runner_index + 1 + predecessors, dialog.notebook.get_n_pages())

    def sync(self, wanted: bool | None = None) -> None:
        """Show or hide this tab to match its toggle option."""
        if self.page is None:
            return
        if wanted is None:
            wanted = self.is_wanted()
        if wanted == self.visible:
            return
        dialog = self.dialog
        if wanted:
            index = self.show_position()
            dialog._shift_notebook_indices(index, +1)
            dialog.notebook.insert_page(self.page, self.label_widget, index)
            self._restore_trackers(index)
        else:
            index = dialog.notebook.page_num(self.page)
            if index < 0:
                return
            self._save_trackers(index)
            dialog.notebook.remove_page(index)
            dialog._shift_notebook_indices(index + 1, -1)
        self.visible = wanted
        self.box.show_all()

    def _save_trackers(self, index: int) -> None:
        """Stash this tab's widget bookkeeping before removing its page."""
        dialog = self.dialog
        self.saved_trackers = {}
        for tracker in (dialog.notebook_page_generators, dialog.notebook_page_updater):
            if index in tracker:
                self.saved_trackers[id(tracker)] = tracker.pop(index)
        self.saved_sets = set()
        for index_set in (dialog.option_page_indices, dialog.searchable_page_indices):
            if index in index_set:
                index_set.discard(index)
                self.saved_sets.add(id(index_set))

    def _restore_trackers(self, index: int) -> None:
        """Restore this tab's widget bookkeeping after re-inserting its page."""
        dialog = self.dialog
        for tracker in (dialog.notebook_page_generators, dialog.notebook_page_updater):
            saved = self.saved_trackers.pop(id(tracker), None)
            if saved is not None:
                tracker[index] = saved
        for index_set in (dialog.option_page_indices, dialog.searchable_page_indices):
            if id(index_set) in self.saved_sets:
                index_set.add(index)
        self.saved_sets.clear()


# pylint: disable=too-many-instance-attributes, no-member
class GameDialogCommon(SavableModelessDialog, DialogInstallUIDelegate):
    """Base class for config dialogs"""

    no_runner_label = _("Select a runner in the Game Info tab")

    def __init__(self, title: str, config_level: str, parent: Gtk.Widget | None = None):
        super().__init__(title, parent=parent, border_width=0)
        self.config_level = config_level
        self.set_default_size(DIALOG_WIDTH, DIALOG_HEIGHT)
        self.vbox.set_border_width(0)

        self.notebook: Gtk.Notebook = None

        self.info_box: GameInfoBox = None
        self.runner_box = None

        self.timer_id = None
        self.game: Game = None
        self.saved = None
        self.option_page_indices = set()
        self.searchable_page_indices = set()
        self.advanced_switch_widgets = []
        self.header_bar_widgets = []
        self.game_box = None
        self.system_box: SystemConfigBox = None
        self.wrapper_config_tabs: list = []
        self.runner_name = None
        self.lutris_config: LutrisConfig = None
        self.notebook_page_generators = {}
        self.notebook_page_updater = {}

        self.build_header_bar()

    @staticmethod
    def build_scrolled_window(widget: Gtk.Widget) -> Gtk.ScrolledWindow:
        """Return a scrolled window containing config widgets"""
        scrolled_window = Gtk.ScrolledWindow(visible=True)
        scrolled_window.set_policy(Gtk.PolicyType.AUTOMATIC, Gtk.PolicyType.AUTOMATIC)
        scrolled_window.add(widget)
        return scrolled_window

    def build_notebook(self) -> None:
        self.notebook = Gtk.Notebook(visible=True)
        self.notebook.set_show_border(False)
        self.notebook.connect("switch-page", self.on_notebook_switch_page)
        self.vbox.pack_start(self.notebook, True, True, 0)

    def on_notebook_switch_page(self, notebook: Gtk.Notebook, page: Gtk.Widget, index: int) -> None:
        generator = self.notebook_page_generators.get(index)
        if generator:
            generator()
            del self.notebook_page_generators[index]
        else:
            updater = self.notebook_page_updater.get(index)
            if updater:
                updater()

        self.update_advanced_switch_visibility(index)
        self.update_search_entry_visibility(index)

    def build_tabs(self) -> None:
        """Build tabs (for game and runner levels)"""
        self.timer_id = None
        if self.config_level == "game":
            self._build_info_tab()
            self._build_game_tab()
        self._build_runner_tab()
        self._build_wrapper_config_tabs()
        self._build_system_tab()

        current_page_index = self.notebook.get_current_page()
        self.update_advanced_switch_visibility(current_page_index)
        self.update_search_entry_visibility(current_page_index)

    def set_header_bar_widgets_visibility(self, value: bool) -> None:
        for widget in self.header_bar_widgets:
            widget.set_visible(value)

    def update_advanced_switch_visibility(self, current_page_index: int) -> None:
        if self.notebook:
            show_switch = current_page_index in self.option_page_indices
            for widget in self.advanced_switch_widgets:
                widget.set_visible(show_switch)

    def update_search_entry_visibility(self, current_page_index: int) -> None:
        """Shows or hides the search entry according to what page is currently displayed."""
        if self.notebook:
            show_search = current_page_index in self.searchable_page_indices
            self.set_search_entry_visibility(show_search)

    def set_search_entry_visibility(
        self, show_search: bool, placeholder_text: str | None = None, tooltip_markup: str | None = None
    ) -> None:
        """Explicitly shows or hides the search entry; can also update the placeholder text."""
        header_bar = self.get_header_bar()
        if show_search and self.search_entry:
            header_bar.set_custom_title(self.search_entry)
            self.search_entry.set_placeholder_text(placeholder_text or self.get_search_entry_placeholder())
            self.search_entry.set_tooltip_markup(tooltip_markup)
        else:
            header_bar.set_custom_title(None)

    def get_search_entry_placeholder(self) -> str:
        if self.game and self.game.name:
            return _("Search %s options") % self.game.name

        return _("Search options")

    def _build_info_tab(self) -> None:
        self.info_box = GameInfoBox(parent_widget=self, game=self.game)

        info_sw = self.build_scrolled_window(self.info_box)
        page_index = self._add_notebook_tab(info_sw, _("Game info"))
        self.option_page_indices.add(page_index)

    def on_move_clicked(self, _button: Gtk.Button) -> None:
        game_directory = self.game.directory if self.game else ""
        new_location = DirectoryDialog("Select new location for the game", default_path=game_directory, parent=self)
        if not new_location.folder or new_location.folder == game_directory:
            return
        move_dialog = MoveDialog(self.game, new_location.folder, parent=self)
        move_dialog.connect("game-moved", self.on_game_moved)
        move_dialog.move()

    def on_game_moved(self, dialog: MoveDialog) -> None:
        """Show a notification when the game is moved"""
        new_directory = dialog.new_directory
        if new_directory:
            self.game = Game(self.game.id if self.game else None)
            self.lutris_config = self.game.config
            self._rebuild_tabs()
            if self.info_box.directory_entry:
                self.info_box.directory_entry.set_text(new_directory)
            send_notification("Finished moving game", "%s moved to %s" % (dialog.game, new_directory))
        else:
            send_notification("Failed to move game", "Lutris could not move %s" % dialog.game)

    def _build_game_tab(self) -> None:
        def is_searchable(game: Game) -> bool:
            return game.has_runner and len(game.runner.game_options) > 8

        def has_advanced(game: Game) -> bool:
            if game.has_runner:
                for opt in game.runner.game_options:
                    if opt.get("advanced"):
                        return True
            return False

        if self.game and self.runner_name:
            self.game.runner_name = self.runner_name
            self.game_box = self._build_options_tab(
                _("Game options"),
                lambda: GameBox(self.config_level, self.lutris_config, self.game),
                advanced=has_advanced(self.game),
                searchable=is_searchable(self.game),
            )
        elif self.runner_name:
            game = Game(None)
            game.runner_name = self.runner_name
            self.game_box = self._build_options_tab(
                _("Game options"),
                lambda: GameBox(self.config_level, self.lutris_config, game),
                advanced=has_advanced(game),
                searchable=is_searchable(game),
            )
        else:
            self._build_missing_options_tab(self.no_runner_label, _("Game options"))

    def _build_runner_tab(self) -> None:
        if self.runner_name:
            self.runner_box = self._build_options_tab(
                _("Runner options"), lambda: RunnerBox(self.config_level, self.lutris_config)
            )
            self._connect_runner_dll_cleanup()
        else:
            self._build_missing_options_tab(self.no_runner_label, _("Runner options"))

    def _connect_runner_dll_cleanup(self) -> None:
        """Remove deployed DLLs as soon as a toggle is switched off, instead
        of waiting for the next launch."""
        if not self.lutris_config or self.lutris_config.runner_slug != "wine" or not self.runner_box:
            return
        runner_index = self.notebook.get_n_pages() - 1
        generator_entry = self.notebook_page_generators.get(runner_index)
        if generator_entry is None:
            self._hook_runner_dll_cleanup()
        else:

            def generate_runner_then_hook():
                generator_entry()
                self._hook_runner_dll_cleanup()

            self.notebook_page_generators[runner_index] = generate_runner_then_hook

    def _hook_runner_dll_cleanup(self) -> None:
        if self.runner_box is None:
            return
        try:
            generator = self.runner_box.get_widget_generator()
        except RuntimeError:
            return
        generator.changed.register(self._on_runner_dll_toggle, priority=2000)

    def _on_runner_dll_toggle(self, option_key: str, new_value) -> None:
        from lutris.runners.wine import DLL_CLEANUP_TRIGGERS

        if option_key not in DLL_CLEANUP_TRIGGERS:
            return
        try:
            runner = import_runner("wine")(self.lutris_config)
        except Exception as ex:
            logger.warning("DLL sync after toggle failed: %s", ex)
            return
        if new_value:
            runner.deploy_enabled_dlls(confirmer=self._confirm_dll_replace)
        else:
            runner.cleanup_disabled_dlls()

    def _confirm_dll_replace(self, dest_path: str, label: str) -> bool:
        """Ask whether a differing game-dir file may be replaced. Runs on
        the main thread; any failure keeps the existing file."""
        try:
            dialog = Gtk.MessageDialog(
                transient_for=self,
                modal=True,
                message_type=Gtk.MessageType.QUESTION,
                buttons=Gtk.ButtonsType.NONE,
                text=_("Replace existing file?"),
            )
            dialog.format_secondary_markup(
                _("<b>%s</b> already exists in the game folder.\n\nReplace it with the %s version?")
                % (GLib.markup_escape_text(os.path.basename(dest_path)), label)
            )
            dialog.add_button(_("_Keep mine"), Gtk.ResponseType.NO)
            dialog.add_button(_("_Replace"), Gtk.ResponseType.YES)
            dialog.set_default_response(Gtk.ResponseType.YES)
            response = dialog.run()
            dialog.destroy()
            return response == Gtk.ResponseType.YES
        except Exception as ex:
            logger.warning("Replace prompt failed, keeping %s: %s", dest_path, ex)
            return False

    def _wrapper_config_tab_defs(self):
        """Tab definitions for the wrapper config tabs (DXVK Config, ...)."""
        return [
            {
                "flags": ("dxvk", "d7vk"),
                "label": _("DXVK Config"),
                "tab_id": "dxvk",
                "info": _("These options are written to the game's dxvk.conf when DXVK is enabled."),
                "managed_keys": dxvk_conf.MANAGED_KEYS,
                "writer": dxvk_conf.write_managed_conf,
                "reader": dxvk_conf.read_managed_values,
            },
            {
                "flags": ("cnc_ddraw",),
                "label": _("CnC-DDraw Config"),
                "tab_id": "cnc_ddraw",
                "info": _("These options are written to the game's ddraw.ini when CnC-DDraw is enabled."),
                "managed_keys": cnc_ddraw_conf.MANAGED_KEYS,
                "writer": cnc_ddraw_conf.write_managed_conf,
                "reader": cnc_ddraw_conf.read_managed_values,
            },
            {
                "flags": ("dxwrapper",),
                "label": _("DxWrapper Config"),
                "tab_id": "dxwrapper",
                "info": _("These options are written to the game's dxwrapper.ini when DxWrapper is enabled."),
                "managed_keys": dxwrapper_conf.MANAGED_KEYS,
                "writer": dxwrapper_conf.write_managed_conf,
                "reader": dxwrapper_conf.read_managed_values,
            },
            {
                "flags": ("dgvoodoo2",),
                "label": _("dgVoodoo2 Config"),
                "tab_id": "dgvoodoo2",
                "info": _("These options are written to the game's dgVoodoo.conf when dgvoodoo2 is enabled."),
                "managed_keys": dgvoodoo2_conf.MANAGED_KEYS,
                "writer": dgvoodoo2_conf.write_managed_conf,
                "reader": dgvoodoo2_conf.read_managed_values,
            },
        ]

    def _build_wrapper_config_tabs(self) -> None:
        """Builds the wrapper config tabs for the Wine runner.

        Each tab only exists while its toggle (DXVK, CnC-DDraw, ...) is
        enabled; toggling the option shows or hides it."""
        self.wrapper_config_tabs = []
        if not self.lutris_config or self.lutris_config.runner_slug != "wine" or not self.runner_box:
            return
        runner_index = self.notebook.get_n_pages() - 1
        for order, tab_def in enumerate(self._wrapper_config_tab_defs()):
            tab = _WrapperConfigTab(self, runner_index, order, **tab_def)
            tab.build()
            self.wrapper_config_tabs.append(tab)

    def _shift_notebook_indices(self, start: int, delta: int) -> None:
        """Shift tracked notebook page indices after inserting (+1) or
        removing (-1) a wrapper config tab at the given index."""
        # NB: shifting up must iterate downward (and vice versa), or
        # pop-and-reinsert overwrites entries that have not moved yet.
        for tracker in (self.notebook_page_generators, self.notebook_page_updater):
            for index in sorted(tracker.keys(), reverse=delta > 0):
                if index >= start:
                    tracker[index + delta] = tracker.pop(index)
        for index_set in (self.option_page_indices, self.searchable_page_indices):
            for index in sorted(index_set, reverse=delta > 0):
                if index >= start:
                    index_set.discard(index)
                    index_set.add(index + delta)

    def _build_system_tab(self) -> None:
        self.system_box = self._build_options_tab(
            _("System options"), lambda: SystemConfigBox(self.config_level, self.lutris_config)
        )

    def _build_options_tab(
        self,
        notebook_label: str,
        box_factory: Callable[[], "ConfigBox"],
        advanced: bool = True,
        searchable: bool = True,
    ) -> "ConfigBox":
        if not self.lutris_config:
            raise RuntimeError("Lutris config not loaded yet")
        config_box = box_factory()
        page_index = self._add_notebook_tab(self.build_scrolled_window(config_box), notebook_label)

        self.notebook_page_updater[page_index] = config_box.update_widgets

        if page_index == 0:
            config_box.generate_widgets()
        else:
            self.notebook_page_generators[page_index] = config_box.generate_widgets

        if advanced:
            self.option_page_indices.add(page_index)
        if searchable:
            self.searchable_page_indices.add(page_index)
        return config_box

    def _build_missing_options_tab(self, missing_label: str, notebook_label: str) -> None:
        label = Gtk.Label(label=self.no_runner_label)
        page_index = self._add_notebook_tab(label, notebook_label)
        self.option_page_indices.add(page_index)

    def _add_notebook_tab(self, widget: Gtk.Widget, label: str) -> int:
        return self.notebook.append_page(widget, Gtk.Label(label=label))

    def build_header_bar(self) -> None:
        self.search_entry = Gtk.SearchEntry(width_chars=30, placeholder_text=_("Search options"))
        self.search_entry.connect("search-changed", self.on_search_entry_changed)
        self.search_entry.show_all()

        # Advanced settings toggle
        switch_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=5, no_show_all=True, visible=True)
        switch_box.set_tooltip_text(_("Show advanced options"))

        switch_label = Gtk.Label(label=_("Advanced"), no_show_all=True, visible=True)
        switch = Gtk.Switch(no_show_all=True, visible=True, valign=Gtk.Align.CENTER)
        switch.set_state(settings.read_setting("show_advanced_options") == "True")
        switch.connect("state-set", lambda _w, s: self.on_show_advanced_options_toggled(bool(s)))

        switch_box.pack_start(switch_label, False, False, 0)
        switch_box.pack_end(switch, False, False, 0)

        header_bar = self.get_header_bar()

        header_bar.pack_end(switch_box)

        # These lists need to be distinct, so they can be separately
        # hidden or shown without interfering with each other.
        self.advanced_switch_widgets = [switch_label, switch]
        self.header_bar_widgets = [self.cancel_button, self.save_button, switch_box]

        if self.notebook:
            self.update_advanced_switch_visibility(self.notebook.get_current_page())

    def on_search_entry_changed(self, entry: Gtk.Entry) -> None:
        """Callback for the search input keypresses"""
        text = entry.get_text().lower().strip()
        self._set_filter(text)

    def on_show_advanced_options_toggled(self, is_active: bool) -> None:
        settings.write_setting("show_advanced_options", is_active)

        self._set_advanced_options_visible(is_active)

    def _set_advanced_options_visible(self, value: bool) -> None:
        """Change visibility of advanced options across all config tabs."""
        if self.info_box:
            self.info_box.advanced_visibility = value
        self.system_box.advanced_visibility = value
        if self.runner_box:
            self.runner_box.advanced_visibility = value
        if self.game_box:
            self.game_box.advanced_visibility = value

    def _set_filter(self, value: str) -> None:
        if self.system_box:
            self.system_box.filter = value
        if self.runner_box:
            self.runner_box.filter = value
        if self.game_box:
            self.game_box.filter = value

    def on_runner_changed(self, widget: Gtk.ComboBox) -> None:
        """Action called when runner drop down is changed."""
        new_runner_index = widget.get_active()
        game_info_box = self.info_box
        if game_info_box.runner_index and new_runner_index != game_info_box.runner_index:
            dlg = QuestionDialog(
                {
                    "parent": self,
                    "question": _(
                        "Are you sure you want to change the runner for this game ? "
                        "This will reset the full configuration for this game and "
                        "is not reversible."
                    ),
                    "title": _("Confirm runner change"),
                }
            )

            if dlg.result == Gtk.ResponseType.YES:
                self._switch_runner(widget, new_runner_index)
            else:
                # Revert the dropdown menu to the previously selected runner
                widget.set_active(game_info_box.runner_index)
        else:
            self._switch_runner(widget, new_runner_index)

    def _switch_runner(self, widget: Gtk.ComboBox, new_runner_index: int) -> None:
        """Rebuilds the UI on runner change"""
        current_page = self.notebook.get_current_page()
        game_info_box = self.info_box
        game_info_box.runner_index = new_runner_index
        if new_runner_index == 0:
            logger.info("No runner selected, resetting configuration")
            self.runner_name = None
            self.lutris_config = None
        else:
            runner_name = widget.get_model()[new_runner_index][1]
            if runner_name == self.runner_name:
                logger.debug("Runner unchanged, not creating a new config")
                return
            logger.info("Creating new configuration with runner %s", runner_name)
            self.runner_name = runner_name
            self.lutris_config = LutrisConfig(runner_slug=self.runner_name, level="game")
        self._rebuild_tabs()
        self.notebook.set_current_page(current_page)

    def _rebuild_tabs(self) -> None:
        """Rebuild notebook pages"""
        for i in range(self.notebook.get_n_pages(), 1, -1):
            self.notebook.remove_page(i - 1)
        self.option_page_indices.clear()
        self.searchable_page_indices.clear()
        self._build_game_tab()
        self._build_runner_tab()
        self._build_wrapper_config_tabs()
        self._build_system_tab()
        self.show_all()

    def on_response(self, _widget: Gtk.Dialog, response: Gtk.ResponseType) -> None:
        if response in (Gtk.ResponseType.CANCEL, Gtk.ResponseType.DELETE_EVENT):
            # Reload the config to clean out any changes we may have made
            if self.game:
                self.game.reload_config()
        super().on_response(_widget, response)

    def is_valid(self) -> bool:
        game_info_box = self.info_box
        if not self.runner_name:
            ErrorDialog(_("Runner not provided"), parent=self)
            return False
        if not game_info_box.name_entry.get_text():
            ErrorDialog(_("Please fill in the name"), parent=self)
            return False
        if self.runner_name == "steam" and not self.lutris_config.game_config.get("appid"):
            ErrorDialog(_("Steam AppID not provided"), parent=self)
            return False
        playtime_text = game_info_box.playtime_entry.get_text()
        if playtime_text and (not self.game or playtime_text != self.game.formatted_playtime):
            try:
                parse_playtime(playtime_text)
            except ValueError as ex:
                display_error(ex, parent=self)
                return False

        invalid_fields = []
        runner_class = import_runner(self.runner_name)
        runner_instance = runner_class()
        for config in ["game", "runner"]:
            for k, v in getattr(self.lutris_config, config + "_config").items():
                option = runner_instance.find_option(config + "_options", k)
                if option is None:
                    continue
                validator = option.get("validator")
                if validator is not None:
                    try:
                        res = validator(v)
                        logger.debug("%s validated successfully: %s", k, res)
                    except Exception:
                        invalid_fields.append(option.get("label"))
        if invalid_fields:
            ErrorDialog(_("The following fields have invalid values: ") + ", ".join(invalid_fields), parent=self)
            return False
        return True

    def on_save(self, _button: Gtk.Button) -> bool | None:
        """Save game info and destroy widget."""
        if not self.is_valid():
            logger.warning(_("Current configuration is not valid, ignoring save request"))
            return None
        game_info_box = self.info_box
        name = game_info_box.name_entry.get_text()
        sortname = game_info_box.sortname_entry.get_text()

        if not game_info_box.slug:
            game_info_box.slug = slugify(name)
        if game_info_box.slug != game_info_box.initial_slug:
            AsyncCall(download_lutris_media, None, game_info_box.slug)
        if not self.game:
            self.game = Game()

        year = None
        if game_info_box.year_entry.get_text():
            year = int(game_info_box.year_entry.get_text())

        playtime = None
        playtime_text = game_info_box.playtime_entry.get_text()
        if playtime_text and playtime_text != self.game.formatted_playtime:
            playtime = parse_playtime(playtime_text)

        if not self.lutris_config.game_config_id:
            self.lutris_config.game_config_id = make_game_config_id(game_info_box.slug)

        self.game.name = name
        self.game.sortname = sortname
        self.game.slug = game_info_box.slug
        self.game.year = year
        if playtime:
            self.game.playtime = playtime
        self.game.is_installed = True
        self.game.config = self.lutris_config

        # Rename config file if game slug changed
        if new_config_id := rename_config(self.lutris_config.game_config_id, self.game.slug):
            self.game.game_config_id = new_config_id

        self.game.runner_name = self.runner_name

        if "icon" not in self.game.custom_images:
            self.game.runner.extract_icon(game_info_box.slug)

        self.game.save()
        self.destroy()
        self.saved = True
        return True  # stop signal propagation


class RunnerMessageBox(WidgetWarningMessageBox):
    def __init__(self) -> None:
        super().__init__(margin_left=12, margin_right=12, icon_name="dialog-warning")
