"""Main window GUI for the WireProxy SurfShark GUI application."""

from __future__ import annotations

import tkinter as tk
from tkinter import ttk, messagebox, scrolledtext, filedialog  # noqa: F401  (kept intentionally)
import threading  # noqa: F401  (kept intentionally)
import webbrowser  # noqa: F401  (kept intentionally)
from datetime import datetime, timedelta
from typing import Optional, List

from models import LogLevel, ProxyStatus
from gui.queue import GUIMessageQueue  # noqa: F401  (kept intentionally)
from gui.preferences import PreferencesWindow
from gui.theme import get_theme_manager, configure_widget  # noqa: F401  (kept intentionally)
import constants

import sys
if sys.platform == "win32":
    try:
        import ctypes
        ctypes.windll.shcore.SetProcessDpiAwareness(1)  # SYSTEM_AWARE
    except Exception:
        pass


class MainWindow:
    """Main application window with improved layout and resize handling."""

    # ---- Class-level constants / shared mappings ---------------------------------

    _LOG_LEVEL_NAMES = {
        LogLevel.DEBUG: "DEBUG",
        LogLevel.INFO: "INFO",
        LogLevel.WARNING: "WARNING",
        LogLevel.ERROR: "ERROR",
    }

    _LOG_LEVEL_NAMES_ABBREV = {
        LogLevel.DEBUG: "DEBUG",
        LogLevel.INFO: "INFO",
        LogLevel.WARNING: "WARN",
        LogLevel.ERROR: "ERROR",
    }

    _STATUS_ICONS = {
        ProxyStatus.RUNNING: "[RUNNING]",
        ProxyStatus.STARTING: "[STARTING]",
        ProxyStatus.ERROR: "[ERROR]",
        ProxyStatus.STOPPED: "[STOPPED]",
    }

    _TITLE_FONT = ("Bahnschrift", 16, "bold")
    _LOG_LEVEL_FONT = ("Bahnschrift", 8)
    _DEFAULT_GEOMETRY = "900x750"
    _MIN_WIDTH = 700
    _MIN_HEIGHT = 600

    def __init__(self, app_manager):
        self.app_manager = app_manager

        # Tk / widget references (initialized at create_gui)
        self.root: Optional[tk.Tk] = None
        self.country_var: Optional[tk.StringVar] = None
        self.port_var: Optional[tk.IntVar] = None
        self.proxy_listbox: Optional[tk.Listbox] = None
        self.log_text: Optional[scrolledtext.ScrolledText] = None
        self.status_label: Optional[ttk.Label] = None
        self.private_key_entry: Optional[ttk.Entry] = None
        self.public_key_entry: Optional[ttk.Entry] = None
        self.country_combo: Optional[ttk.Combobox] = None
        self.log_level_label: Optional[ttk.Label] = None

        # Flag to prevent UI updates during resize operations
        self._updating_ui = False

    # ---- GUI creation -------------------------------------------------------------

    def create_gui(self) -> Optional[tk.Tk]:
        """Create the main GUI with improved wireproxy executable handling."""
        try:
            self.root = tk.Tk()
            self.root.minsize(self._MIN_WIDTH, self._MIN_HEIGHT)
            self.root.title(constants.TITLE)
            self.root.geometry(self._DEFAULT_GEOMETRY)
            self.root.protocol("WM_DELETE_WINDOW", self.app_manager.on_closing)

            # Bind resize events for better handling
            self.root.bind("<Configure>", self._on_window_configure)

            # Check wireproxy availability and offer download if needed.
            self._check_wireproxy_availability()

            if getattr(self.app_manager.settings, "start_minimized", False):
                self.root.withdraw()

            main_frame = self._create_main_frame()
            self._create_title_section(main_frame)
            self._create_keys_frame(main_frame)
            self._create_config_frame(main_frame)
            self._create_management_frame(main_frame)
            self._create_status_bar(main_frame)

            # Ensure minimize-to-tray behavior (if enabled).
            self.root.bind("<Unmap>", self._on_minimize)

            # Apply theme after widgets are fully created.
            self.apply_theme_to_widgets()

            return self.root
        except tk.TclError as e:
            self.app_manager.log_message(f"Failed to create GUI: {e}", LogLevel.ERROR)
            self.app_manager.log_message("Running in headless mode.", LogLevel.INFO)
            # Fallback: create a withdrawn root so dependent code can still call into tk safely.
            try:
                self.root = tk.Tk()
                self.root.withdraw()
            except Exception:
                self.root = None
            return self.root

    def apply_theme_to_widgets(self) -> None:
        """Apply theme to all widgets after creation."""
        if not self.root:
            return

        # Local imports to avoid circulars and allow headless operation if needed.
        from gui.theme import (
            get_theme_manager,
            apply_theme_to_children,
            update_scrolledtext_theme,
            create_dark_title_bar,
        )

        theme_manager = get_theme_manager()

        # Apply theme to all widgets recursively.
        apply_theme_to_children(self.root)

        # Special handling for ScrolledText widget.
        if self.log_text:
            update_scrolledtext_theme(self.log_text)

        # Special handling for Listbox with scrollbar.
        if self.proxy_listbox:
            theme_manager.configure_widget(self.proxy_listbox)

        # Apply dark title bar if in dark mode.
        if theme_manager.is_dark_mode():
            create_dark_title_bar(self.root)

    # ---- Wireproxy availability checks -------------------------------------------

    def _check_wireproxy_availability(self) -> None:
        """Check wireproxy availability and offer download if needed."""
        from processes.manager import ProcessManager

        wireproxy_path = ProcessManager.find_wireproxy_executable()

        if not wireproxy_path:
            self.app_manager.log_message("wireproxy executable not found during startup", LogLevel.WARNING)
            # Show a non-blocking warning with download option after UI settles.
            if self.root:
                self.root.after(1000, self._show_wireproxy_missing_dialog)
        else:
            self.app_manager.log_message(f"wireproxy executable found at: {wireproxy_path}", LogLevel.INFO)

    def _show_wireproxy_missing_dialog(self) -> None:
        """Show dialog about missing wireproxy with download option."""
        try:
            from gui.download_dialog import WireproxyDownloadManager

            result = messagebox.askyesno(
                "wireproxy Not Found",
                "wireproxy executable was not found on your system.\n\n"
                "wireproxy is required to create SOCKS5 proxies through WireGuard.\n\n"
                "Would you like to download it now?\n\n"
                "• Yes: Download automatically from GitHub\n"
                "• No: Continue without wireproxy (you can download later)",
                icon=messagebox.WARNING,
                parent=self.root,
            )

            if result:
                self.app_manager.log_message("User chose to download wireproxy at startup", LogLevel.INFO)

                def on_download_complete(success: bool, message: str) -> None:
                    if success:
                        self.app_manager.log_message("wireproxy downloaded successfully at startup", LogLevel.INFO)
                        messagebox.showinfo(
                            "Download Complete",
                            "wireproxy has been downloaded successfully!\n\nYou can now create proxies.",
                            parent=self.root,
                        )
                    else:
                        self.app_manager.log_message(
                            f"wireproxy download failed at startup: {message}", LogLevel.ERROR
                        )

                WireproxyDownloadManager.download_wireproxy_with_ui(self.root, on_complete=on_download_complete)
            else:
                self.app_manager.log_message("User chose to continue without wireproxy at startup", LogLevel.INFO)
                messagebox.showinfo(
                    "wireproxy Missing",
                    "You can download wireproxy later through:\n\n"
                    "• Preferences → wireproxy Binary → Download Latest Version\n"
                    "• Or manually from: https://github.com/whyvl/wireproxy/releases\n\n"
                    "Proxy creation will fail until wireproxy is installed.",
                    parent=self.root,
                )

        except ImportError as e:
            self.app_manager.log_message(f"Failed to import download dialog at startup: {e}", LogLevel.ERROR)
            # Fallback to simple error message
            messagebox.showerror(
                constants.MISSING_DEPENDENCY_TITLE,
                constants.MISSING_DEPENDENCY_MESSAGE,
                parent=self.root,
            )

    # ---- Layout: top-level containers --------------------------------------------

    def _create_main_frame(self) -> ttk.Frame:
        """Create and return the main container frame with proper grid configuration."""
        assert self.root is not None

        # Configure root window grid
        self.root.columnconfigure(0, weight=1)
        self.root.rowconfigure(0, weight=1)

        main_frame = ttk.Frame(self.root, padding="15")
        main_frame.grid(row=0, column=0, sticky=(tk.W, tk.E, tk.N, tk.S))

        # Configure main frame grid weights for responsive behavior
        main_frame.columnconfigure(0, weight=1)  # Single column that expands
        main_frame.rowconfigure(0, weight=0)     # Title - fixed height
        main_frame.rowconfigure(1, weight=0)     # Keys frame - fixed height
        main_frame.rowconfigure(2, weight=0)     # Config frame - fixed height
        main_frame.rowconfigure(3, weight=1)     # Management frame - expandable
        main_frame.rowconfigure(4, weight=0)     # Status bar - fixed height

        return main_frame

    def _create_title_section(self, parent: ttk.Frame) -> None:
        """Create the title section with improved spacing."""
        title_frame = ttk.Frame(parent)
        title_frame.grid(row=0, column=0, sticky=(tk.W, tk.E), pady=(0, 20))
        title_frame.columnconfigure(0, weight=1)

        title_label = ttk.Label(title_frame, text=constants.TITLE, font=self._TITLE_FONT)
        title_label.grid(row=0, column=0, pady=10)

    def _create_keys_frame(self, parent: ttk.Frame) -> None:
        """Create the keys input frame with flexible layout."""
        keys_frame = ttk.LabelFrame(parent, text=constants.KEYS_FRAME_TITLE, padding="15")
        keys_frame.grid(row=1, column=0, sticky=(tk.W, tk.E), pady=(0, 15))

        # Configure grid weights
        keys_frame.columnconfigure(0, weight=0)  # Labels - fixed width
        keys_frame.columnconfigure(1, weight=1)  # Entry fields - expandable
        keys_frame.columnconfigure(2, weight=0)  # Button - fixed width

        # Private key row - REMOVED width=50
        ttk.Label(keys_frame, text=constants.PRIVATE_KEY_LABEL).grid(
            row=0, column=0, sticky=tk.W, padx=(0, 10), pady=(5, 8)
        )
        self.private_key_entry = ttk.Entry(keys_frame, show="*")
        self.private_key_entry.grid(row=0, column=1, sticky=(tk.W, tk.E), padx=(0, 10), pady=(5, 8))

        # Public key row - REMOVED width=50
        ttk.Label(keys_frame, text=constants.PUBLIC_KEY_LABEL).grid(
            row=1, column=0, sticky=tk.W, padx=(0, 10), pady=(0, 5)
        )
        self.public_key_entry = ttk.Entry(keys_frame)
        self.public_key_entry.grid(row=1, column=1, sticky=(tk.W, tk.E), padx=(0, 10), pady=(0, 5))

        # Update button spanning both rows
        update_btn = ttk.Button(keys_frame, text=constants.UPDATE_KEYS_BUTTON, command=self.app_manager.update_keys)
        update_btn.grid(row=0, column=2, rowspan=2, padx=(10, 0), pady=5, sticky=(tk.N, tk.S))

    def _create_config_frame(self, parent: ttk.Frame) -> None:
        """Create the proxy configuration frame with flexible layout."""
        config_frame = ttk.LabelFrame(parent, text=constants.ADD_PROXY_FRAME_TITLE, padding="15")
        config_frame.grid(row=2, column=0, sticky=(tk.W, tk.E), pady=(0, 15))

        # Configure grid weights
        config_frame.columnconfigure(0, weight=1)  # Left section - expandable
        config_frame.columnconfigure(1, weight=0)  # Right section - fixed

        # Left section - input controls
        left_section = ttk.Frame(config_frame)
        left_section.grid(row=0, column=0, sticky=(tk.W, tk.E), padx=(0, 20))
        left_section.columnconfigure(1, weight=1)

        # Country selection - REMOVED width=35
        ttk.Label(left_section, text=constants.COUNTRY_LABEL).grid(
            row=0, column=0, sticky=tk.W, padx=(0, 10), pady=(0, 8)
        )
        self.country_var = tk.StringVar()
        self.country_combo = ttk.Combobox(left_section, textvariable=self.country_var, state="readonly")
        self.country_combo.grid(row=0, column=1, sticky=(tk.W, tk.E), pady=(0, 8))

        # Port selection - REDUCED width from 15 to 8
        ttk.Label(left_section, text=constants.SOCKS5_PORT_LABEL).grid(
            row=1, column=0, sticky=tk.W, padx=(0, 10)
        )
        self.port_var = tk.IntVar(value=1080)
        port_spinbox = ttk.Spinbox(left_section, from_=1024, to=65535, textvariable=self.port_var, width=8)
        port_spinbox.grid(row=1, column=1, sticky=tk.W)

        # Right section - action buttons
        right_section = ttk.Frame(config_frame)
        right_section.grid(row=0, column=1, sticky=(tk.E, tk.N))

        button_configs = [
            (constants.ADD_PROXY_BUTTON, self.app_manager.add_proxy),
            (constants.RELOAD_SERVERS_BUTTON, self.app_manager.load_servers),
            (constants.PREFERENCES_BUTTON, self.show_preferences),
        ]

        # REMOVED width=18 from all buttons
        for i, (text, command) in enumerate(button_configs):
            btn = ttk.Button(right_section, text=text, command=command)
            btn.grid(row=i, column=0, pady=(0, 5) if i < len(button_configs) - 1 else 0, sticky=(tk.W, tk.E))

    def _create_management_frame(self, parent: ttk.Frame) -> None:
        """Create the management frame with flexible layout."""
        mgmt_frame = ttk.Frame(parent)
        mgmt_frame.grid(row=3, column=0, sticky=(tk.W, tk.E, tk.N, tk.S), pady=(0, 15))

        # Use weight ratios without minsize to prevent crashes
        mgmt_frame.columnconfigure(0, weight=2)  # Proxy list - larger portion
        mgmt_frame.columnconfigure(1, weight=1)  # Log area - smaller portion
        mgmt_frame.rowconfigure(0, weight=1)     # Both expand vertically

        self._create_proxy_list_frame(mgmt_frame)
        self._create_log_frame(mgmt_frame)

    def _create_proxy_list_frame(self, parent: ttk.Frame) -> None:
        """Create the active proxy list frame with flexible layout."""
        left_frame = ttk.LabelFrame(parent, text=constants.ACTIVE_PROXIES_FRAME_TITLE, padding="10")
        left_frame.grid(row=0, column=0, sticky=(tk.W, tk.E, tk.N, tk.S), padx=(0, 10))

        # Configure grid weights
        left_frame.columnconfigure(0, weight=1)
        left_frame.rowconfigure(0, weight=1)  # Listbox area - expandable
        left_frame.rowconfigure(1, weight=0)  # Button area - fixed

        # Listbox container
        listbox_container = ttk.Frame(left_frame)
        listbox_container.grid(row=0, column=0, sticky=(tk.W, tk.E, tk.N, tk.S), pady=(0, 10))
        listbox_container.columnconfigure(0, weight=1)
        listbox_container.columnconfigure(1, weight=0)  # Scrollbar column
        listbox_container.rowconfigure(0, weight=1)

        # Listbox - REMOVED width=35
        self.proxy_listbox = tk.Listbox(listbox_container, exportselection=False)
        self.proxy_listbox.grid(row=0, column=0, sticky=(tk.W, tk.E, tk.N, tk.S))

        scrollbar = ttk.Scrollbar(listbox_container, orient="vertical", command=self.proxy_listbox.yview)
        scrollbar.grid(row=0, column=1, sticky=(tk.N, tk.S))
        self.proxy_listbox.configure(yscrollcommand=scrollbar.set)

        self._create_proxy_buttons_frame(left_frame)

    def _create_proxy_buttons_frame(self, parent: ttk.Frame) -> None:
        """Create organized action buttons with flexible layout."""
        btn_container = ttk.Frame(parent)
        btn_container.grid(row=1, column=0, sticky=(tk.W, tk.E))

        # Configure grid for even distribution
        for i in range(4):  # 4 columns of buttons
            btn_container.columnconfigure(i, weight=1)

        # Button configurations organized by function
        primary_buttons = [
            (constants.START_BUTTON, self.app_manager.start_proxy),
            (constants.STOP_BUTTON, self.app_manager.stop_proxy),
            (constants.REMOVE_BUTTON, self.app_manager.remove_proxy),
            (constants.EXPORT_CONFIG_BUTTON, self.app_manager.export_config),
        ]

        secondary_buttons = [
            (constants.STOP_ALL_BUTTON, self.app_manager.stop_all_proxies),
            (constants.SHOW_CONFIG_BUTTON, self.app_manager.show_config),
            ("Copy Address", self.app_manager.copy_proxy_address),
            ("", None),  # Empty slot for alignment
        ]

        # Create primary buttons (first row) - REMOVED width=12
        for i, (text, command) in enumerate(primary_buttons):
            btn = ttk.Button(btn_container, text=text, command=command)
            btn.grid(row=0, column=i, padx=2, pady=(0, 5), sticky=(tk.W, tk.E))

        # Create secondary buttons (second row) - REMOVED width=12
        for i, (text, command) in enumerate(secondary_buttons):
            if text and command:  # Skip empty slots
                btn = ttk.Button(btn_container, text=text, command=command)
                btn.grid(row=1, column=i, padx=2, pady=0, sticky=(tk.W, tk.E))

    def _create_log_frame(self, parent: ttk.Frame) -> None:
        """Create the log display frame with flexible layout."""
        right_frame = ttk.LabelFrame(parent, text=constants.LOG_FRAME_TITLE, padding="10")
        right_frame.grid(row=0, column=1, sticky=(tk.W, tk.E, tk.N, tk.S))

        # Configure grid weights
        right_frame.columnconfigure(0, weight=1)
        right_frame.rowconfigure(0, weight=1)  # Log text - expandable
        right_frame.rowconfigure(1, weight=0)  # Buttons - fixed

        # Log text area - REMOVED width=30, kept height=15
        self.log_text = scrolledtext.ScrolledText(right_frame, wrap=tk.WORD, height=15)
        self.log_text.grid(row=0, column=0, sticky=(tk.W, tk.E, tk.N, tk.S), pady=(0, 10))

        self._create_log_buttons_frame(right_frame)

    def _create_log_buttons_frame(self, parent: ttk.Frame) -> None:
        """Create organized buttons below the log area with flexible layout."""
        log_btn_container = ttk.Frame(parent)
        log_btn_container.grid(row=1, column=0, sticky=(tk.W, tk.E))

        # Configure grid for flexible layout
        log_btn_container.columnconfigure(0, weight=1)
        log_btn_container.columnconfigure(1, weight=1)
        log_btn_container.columnconfigure(2, weight=1)
        log_btn_container.columnconfigure(3, weight=0)  # Log level label

        button_configs = [
            (constants.CLEAR_LOG_BUTTON, self.app_manager.clear_log),
            (constants.SAVE_LOG_BUTTON, self.app_manager.save_log),
            (constants.LOG_LEVEL_BUTTON, self.app_manager.change_log_level),
        ]

        # REMOVED width=10 from all buttons
        for i, (text, command) in enumerate(button_configs):
            btn = ttk.Button(log_btn_container, text=text, command=command)
            btn.grid(row=0, column=i, padx=(0, 5) if i < len(button_configs) - 1 else (0, 10), sticky=(tk.W, tk.E))

        current_level_name = self._LOG_LEVEL_NAMES.get(self.app_manager.settings.log_level, "UNKNOWN")
        self.log_level_label = ttk.Label(log_btn_container, text=current_level_name, font=self._LOG_LEVEL_FONT)
        self.log_level_label.grid(row=0, column=3, sticky=tk.E)

    def _create_status_bar(self, parent: ttk.Frame) -> None:
        """Create the status bar at the bottom."""
        status_container = ttk.Frame(parent)
        status_container.grid(row=4, column=0, sticky=(tk.W, tk.E))
        status_container.columnconfigure(0, weight=1)

        self.status_label = ttk.Label(status_container, text=constants.STATUS_LABEL_DEFAULT, relief="sunken")
        theme_manager = get_theme_manager()
        theme_manager.configure_widget(self.status_label)
        self.status_label.grid(row=0, column=0, sticky=(tk.W, tk.E), pady=(10, 0))

    # ---- Window behavior ----------------------------------------------------------

    def _on_window_configure(self, event: Optional[tk.Event] = None) -> None:
        """Handle window resize events to prevent crashes."""
        if event and event.widget == self.root:
            # Ensure minimum size constraints
            if self.root.winfo_width() < self._MIN_WIDTH or self.root.winfo_height() < self._MIN_HEIGHT:
                self.root.minsize(self._MIN_WIDTH, self._MIN_HEIGHT)

            # Throttle UI updates during resize
            if hasattr(self, '_resize_after_id'):
                self.root.after_cancel(self._resize_after_id)
            self._resize_after_id = self.root.after(100, self._handle_resize_complete)

    def _handle_resize_complete(self) -> None:
        """Handle operations after resize is complete."""
        try:
            # Force a redraw if needed
            if self.root:
                self.root.update_idletasks()
        except Exception as e:
            self.app_manager.log_message(f"Error handling resize: {e}", LogLevel.DEBUG)

    def _on_minimize(self, event: Optional[tk.Event] = None) -> None:
        """Handle minimize-to-tray behavior if enabled in settings."""
        if self.root and getattr(self.app_manager.settings, "minimize_to_tray", False):
            self.root.after(100, self.app_manager.hide_to_tray)

    def show_preferences(self) -> None:
        """Show preferences window."""
        assert self.root is not None
        preferences = PreferencesWindow(self.root, self.app_manager)
        preferences.show()

    # ---- UI updates from controller ----------------------------------------------

    def update_log_display(self, message: str, level: LogLevel) -> None:
        """Update log display (called from main thread only)."""
        if not self.log_text or level.value < self.app_manager.settings.log_level.value:
            return

        # Prevent updates during UI operations that might cause crashes
        if self._updating_ui:
            return

        try:
            self._updating_ui = True

            timestamp = self._timestamp_now()
            level_name = self._LOG_LEVEL_NAMES_ABBREV.get(level, "INFO")

            # Get color from theme manager
            theme_manager = get_theme_manager()
            color = theme_manager.get_log_level_color(level_name)

            tag_name = f"level_{level.value}"
            # Configure the tag once per level (safe to reconfigure).
            self.log_text.tag_configure(tag_name, foreground=color)

            log_entry = f"[{timestamp}] [{level_name:5}] {message}\n"
            self.log_text.insert(tk.END, log_entry, tag_name)
            self.log_text.see(tk.END)

        except Exception as e:
            # Fail silently to prevent crash loops
            pass
        finally:
            self._updating_ui = False

    def update_status_display(self, message: str) -> None:
        """Update status display (called from main thread only)."""
        if self.status_label and not self._updating_ui:
            try:
                self.status_label.config(text=f"Status: {message}")
            except Exception:
                pass

    def update_proxy_list_display(self) -> None:
        """Update proxy list with robust error handling."""
        if not self.proxy_listbox or self._updating_ui:
            return

        try:
            self._updating_ui = True

            # Save current selection
            current_selection = self.proxy_listbox.curselection()
            current_size = self.proxy_listbox.size()

            proxy_instances = self.app_manager.state.get_proxy_instances()
            running_processes = self.app_manager.state.get_running_processes()

            # Only update if size changed or forced
            if current_size != len(proxy_instances):
                self.proxy_listbox.delete(0, tk.END)
                need_full_update = True
            else:
                need_full_update = False

            theme_manager = get_theme_manager()

            for i, instance in enumerate(proxy_instances):
                # Check actual process status with better error handling
                actual_status = instance.status
                process_info = running_processes.get(i)

                if instance.status == ProxyStatus.RUNNING and process_info:
                    try:
                        if process_info.process.poll() is not None:
                            actual_status = ProxyStatus.STOPPED
                            self.app_manager.state.update_proxy_status(i, ProxyStatus.STOPPED)
                            self.app_manager.state.remove_running_process(i)
                    except Exception as e:
                        self.app_manager.log_message(f"Error checking process status: {e}", LogLevel.ERROR)
                        actual_status = ProxyStatus.ERROR

                # Create display text
                status_icon = self._STATUS_ICONS.get(actual_status, "[UNKNOWN]")
                load = instance.server.get("load", "unknown")

                # Calculate runtime string
                runtime = self._format_runtime(instance.start_time) if actual_status == ProxyStatus.RUNNING else ""

                text = (
                    f"{status_icon} Port {instance.port} - {instance.country} "
                    f"({instance.location}) - Load: {load}%{runtime}"
                )

                if need_full_update:
                    self.proxy_listbox.insert(tk.END, text)
                else:
                    # Update existing item if text changed
                    try:
                        current_text = self.proxy_listbox.get(i)
                        if current_text != text:
                            self.proxy_listbox.delete(i)
                            self.proxy_listbox.insert(i, text)
                    except tk.TclError:
                        # Item doesn't exist, insert it
                        self.proxy_listbox.insert(tk.END, text)

                # Add color coding using theme colors
                try:
                    status_color = theme_manager.get_status_color(actual_status.value)
                    self.proxy_listbox.itemconfig(i, {"fg": status_color})
                except Exception:
                    # Color setting is non-critical
                    pass

            # Restore selection
            if current_selection:
                for index in current_selection:
                    if index < self.proxy_listbox.size():
                        try:
                            self.proxy_listbox.selection_set(index)
                        except Exception:
                            pass

        except Exception as e:
            self.app_manager.log_message(f"Error updating proxy list display: {e}", LogLevel.ERROR)
        finally:
            self._updating_ui = False

    def update_server_dropdown(self, country_options: List[str]) -> None:
        """Update server dropdown (called from main thread only)."""
        if self.country_combo and self.country_var is not None and not self._updating_ui:
            try:
                self.country_var.set("")
                self.country_combo["values"] = country_options
            except Exception:
                pass

    def update_gui_with_loaded_keys(self) -> None:
        """Update GUI with loaded keys."""
        if self._updating_ui:
            return

        try:
            private_key, public_key = self.app_manager.state.get_keys()
            if self.private_key_entry and private_key:
                self.private_key_entry.delete(0, tk.END)
                self.private_key_entry.insert(0, private_key)
            if self.public_key_entry and public_key:
                self.public_key_entry.delete(0, tk.END)
                self.public_key_entry.insert(0, public_key)
        except Exception:
            pass

    # ---- Helpers -----------------------------------------------------------------

    @staticmethod
    def _timestamp_now() -> str:
        """Return current timestamp with millisecond precision."""
        return datetime.now().strftime("%H:%M:%S.%f")[:-3]

    @staticmethod
    def _format_runtime(start_time: Optional[datetime]) -> str:
        """Return a human-readable runtime like ' [mm:ss]' or ' [hh:mm:ss]'."""
        if not start_time:
            return ""
        try:
            delta: timedelta = datetime.now() - start_time
            total_seconds = max(0, int(delta.total_seconds()))
            hours, remainder = divmod(total_seconds, 3600)
            minutes, seconds = divmod(remainder, 60)
            if hours > 0:
                return f" [{hours:02d}:{minutes:02d}:{seconds:02d}]"
            return f" [{minutes:02d}:{seconds:02d}]"
        except Exception:
            return " [??:??]"