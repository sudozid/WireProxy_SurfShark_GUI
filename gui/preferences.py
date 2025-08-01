"""Preferences window for the WireProxy SurfShark GUI application."""

import tkinter as tk
from tkinter import ttk, messagebox
import requests
import subprocess
import os
import webbrowser
from datetime import datetime

from models import LogLevel
from processes.manager import ProcessManager
from gui.theme import get_theme_manager, set_dark_mode
import constants

# Pre-import the download dialog to avoid runtime import issues
try:
    from gui.download_dialog import WireproxyDownloadManager
    DOWNLOAD_DIALOG_AVAILABLE = True
except ImportError as e:
    print(f"Warning: Download dialog not available: {e}")
    DOWNLOAD_DIALOG_AVAILABLE = False


class PreferencesWindow:
    """Preferences window for application settings"""

    def __init__(self, parent, app_manager):
        self.parent = parent
        self.app_manager = app_manager
        self.preferences_window = None
        self.prefs_log_level_label = None

    def show(self):
        """Show preferences window with improved structure"""
        # Reuse existing window if available
        if hasattr(self, 'preferences_window') and self.preferences_window and self.preferences_window.winfo_exists():
            self.preferences_window.lift()
            self.preferences_window.focus_set()
            return

        # Helper functions
        def close_window():
            """Properly cleanup window"""
            try:
                if hasattr(self, 'preferences_window') and self.preferences_window:
                    self.preferences_window.grab_release()
                    self.preferences_window.destroy()
            except tk.TclError:
                pass  # Window already destroyed

        def save_and_close():
            self._save_preferences(
                start_min_var.get(),
                min_to_tray_var.get(),
                auto_start_var.get(),
                api_endpoint_var.get(),
                dark_mode_var.get()
            )
            close_window()

        def on_mousewheel(event):
            """Cross-platform mousewheel scroll handler with safety checks"""
            try:
                # Check if canvas still exists and is valid
                if canvas and canvas.winfo_exists():
                    if event.num == 4 or event.delta > 0:
                        canvas.yview_scroll(-1, "units")
                    elif event.num == 5 or event.delta < 0:
                        canvas.yview_scroll(1, "units")
            except tk.TclError:
                # Canvas destroyed, ignore the event
                pass
            except Exception:
                # Any other error, ignore silently
                pass

        # Window setup
        self.preferences_window = tk.Toplevel(self.parent)
        self.preferences_window.title("Preferences")
        self.preferences_window.resizable(True, True)
        self.preferences_window.transient(self.parent)
        self.preferences_window.protocol("WM_DELETE_WINDOW", close_window)
        self.preferences_window.minsize(width=450, height=400)

        # Scrollable area setup
        main_container = ttk.Frame(self.preferences_window)
        main_container.pack(fill="both", expand=True)

        canvas = tk.Canvas(main_container, highlightthickness=0)
        scrollbar = ttk.Scrollbar(main_container, orient="vertical", command=canvas.yview)
        scrollable_frame = ttk.Frame(canvas)

        canvas_window_id = canvas.create_window((0, 0), window=scrollable_frame, anchor="nw")
        canvas.configure(yscrollcommand=scrollbar.set)

        # Bindings
        canvas.bind("<Configure>", lambda e: canvas.itemconfig(canvas_window_id, width=e.width))
        scrollable_frame.bind("<Configure>", lambda e: canvas.configure(scrollregion=canvas.bbox("all")))

        # Improved mousewheel binding - use widget-specific binding instead of global
        # This prevents issues when window is destroyed
        canvas.bind("<MouseWheel>", on_mousewheel)  # Windows/macOS
        canvas.bind("<Button-4>", on_mousewheel)   # Linux scroll up
        canvas.bind("<Button-5>", on_mousewheel)   # Linux scroll down
        scrollable_frame.bind("<MouseWheel>", on_mousewheel)  # Windows/macOS
        scrollable_frame.bind("<Button-4>", on_mousewheel)    # Linux scroll up
        scrollable_frame.bind("<Button-5>", on_mousewheel)    # Linux scroll down

        canvas.pack(side="left", fill="both", expand=True, padx=(10, 0), pady=10)
        scrollbar.pack(side="right", fill="y", padx=(0, 10), pady=10)

        # Content setup
        content_frame = ttk.Frame(scrollable_frame, padding=20)
        content_frame.pack(fill="x", expand=True)

        start_min_var = tk.BooleanVar(value=self.app_manager.settings.start_minimized)
        min_to_tray_var = tk.BooleanVar(value=self.app_manager.settings.minimize_to_tray)
        auto_start_var = tk.BooleanVar(value=self.app_manager.settings.auto_start_proxies)
        api_endpoint_var = tk.StringVar(value=self.app_manager.settings.api_endpoint)
        dark_mode_var = tk.BooleanVar(value=self.app_manager.settings.dark_mode)

        sections = [
            self._create_title_section(content_frame),
            self._create_startup_section(content_frame, start_min_var, auto_start_var),
            self._create_api_section(content_frame, api_endpoint_var),
            self._create_tray_section(content_frame, min_to_tray_var),
            self._create_appearance_section(content_frame, dark_mode_var),
            self._create_logging_section(content_frame),
            self._create_wireproxy_status_section(content_frame),
            self._create_about_section(content_frame)
        ]
        for section in sections:
            section.pack(fill="x", pady=(0, 15), anchor="w")

        # Bottom buttons
        button_frame = ttk.Frame(self.preferences_window, padding=(10, 5))
        button_frame.pack(fill="x", side="bottom")

        ttk.Button(button_frame, text="Cancel", command=close_window).pack(side="right", padx=5)
        ttk.Button(button_frame, text="Save", command=save_and_close).pack(side="right")

        # Center window
        self._center_window(self.preferences_window, 450, 600)
        self.preferences_window.grab_set()
        
        # Apply theme to the preferences window
        self._apply_theme_to_preferences()

    def _center_window(self, window, width, height):
        """Center a window on screen"""
        window.update_idletasks()
        screen_width = window.winfo_screenwidth()
        screen_height = window.winfo_screenheight()
        x = (screen_width // 2) - (width // 2)
        y = (screen_height // 2) - (height // 2)
        window.geometry(f"{width}x{height}+{x}+{y}")
    
    def _apply_theme_to_preferences(self):
        """Apply theme to all widgets in the preferences window"""
        if not self.preferences_window:
            return
            
        from gui.theme import apply_theme_to_children, create_dark_title_bar, get_theme_manager
        
        theme_manager = get_theme_manager()
        
        # Apply theme to all widgets recursively
        apply_theme_to_children(self.preferences_window)
        
        # Apply dark title bar if in dark mode
        if theme_manager.is_dark_mode():
            create_dark_title_bar(self.preferences_window)

    def _create_title_section(self, parent):
        """Create title section"""
        frame = ttk.Frame(parent)
        ttk.Label(frame, text="Preferences", font=("Arial", 16, "bold")).pack(pady=(0, 10))
        return frame

    def _create_startup_section(self, parent, start_min_var, auto_start_var):
        """Create startup options section"""
        frame = ttk.LabelFrame(parent, text="Startup Options", padding=15)

        ttk.Checkbutton(frame, text="Start minimized to system tray",
                        variable=start_min_var).pack(anchor="w", pady=5)

        ttk.Checkbutton(frame, text="Auto-start previously running proxies",
                        variable=auto_start_var).pack(anchor="w", pady=5)

        return frame

    def _create_api_section(self, parent, api_endpoint_var):
        """Create API configuration section"""
        frame = ttk.LabelFrame(parent, text="API Configuration", padding=15)

        ttk.Label(frame, text="SurfShark API Endpoint:").pack(anchor="w", pady=(0, 5))

        entry = ttk.Entry(frame, textvariable=api_endpoint_var, width=60)
        entry.pack(fill="x", pady=(0, 5))

        ttk.Label(frame,
                  text="• Change this if the default endpoint stops working\n• Restart required after changing",
                  foreground=get_theme_manager().get_color("secondary_fg")).pack(anchor="w", pady=(5, 0))

        ttk.Button(frame, text="Reset to Default",
                   command=lambda: api_endpoint_var.set("https://api.surfshark.com/v4/server/clusters/generic")
                   ).pack(anchor="w", pady=(10, 0))

        return frame

    def _create_tray_section(self, parent, min_to_tray_var):
        """Create system tray section"""
        frame = ttk.LabelFrame(parent, text="System Tray", padding=15)

        ttk.Checkbutton(frame, text="Minimize to system tray instead of taskbar",
                        variable=min_to_tray_var).pack(anchor="w", pady=5)

        ttk.Label(frame,
                  text="• Right-click tray icon for menu\n• Double-click to show/hide window",
                  foreground=get_theme_manager().get_color("secondary_fg")).pack(anchor="w", pady=(5, 0))

        return frame

    def _create_appearance_section(self, parent, dark_mode_var):
        """Create appearance section"""
        frame = ttk.LabelFrame(parent, text=constants.APPEARANCE_FRAME_TITLE, padding=15)

        ttk.Checkbutton(frame, text=constants.DARK_MODE_CHECKBOX,
                        variable=dark_mode_var).pack(anchor="w", pady=5)

        ttk.Label(frame,
                  text=constants.DARK_MODE_INFO,
                  foreground=get_theme_manager().get_color("secondary_fg")).pack(anchor="w", pady=(5, 0))

        return frame

    def _create_logging_section(self, parent):
        """Create logging section with updateable log level display"""
        frame = ttk.LabelFrame(parent, text="Logging", padding=15)

        level_frame = ttk.Frame(frame)
        level_frame.pack(fill="x", pady=5)

        ttk.Label(level_frame, text="Current log level:").pack(side="left")

        level_names = {
            LogLevel.DEBUG: "DEBUG",
            LogLevel.INFO: "INFO",
            LogLevel.WARNING: "WARNING",
            LogLevel.ERROR: "ERROR"
        }
        current_level = level_names.get(self.app_manager.settings.log_level, "UNKNOWN")

        # Store reference to the label so it can be updated later
        self.prefs_log_level_label = ttk.Label(level_frame, text=current_level,
                                               font=("Arial", 10, "bold"))
        self.prefs_log_level_label.pack(side="left", padx=(10, 0))

        def change_log_level_for_prefs():
            """Change log level from preferences window"""
            self.app_manager.show_log_level_dialog(self.preferences_window)

        ttk.Button(frame, text="Change Log Level",
                   command=change_log_level_for_prefs).pack(anchor="w", pady=(10, 0))

        return frame

    def _create_about_section(self, parent):
        """Create about section with app information"""
        frame = ttk.LabelFrame(parent, text=constants.ABOUT_FRAME_TITLE, padding=15)
        self._create_about_info_section(frame)
        return frame

    def _create_about_info_section(self, parent):
        about_text = (
            f"{constants.APP_NAME}\n"
            f"Version {constants.APP_VERSION}\n"
            "Manage multiple SOCKS5 proxies via WireGuard"
        )
        ttk.Label(parent, text=about_text, foreground=get_theme_manager().get_color("secondary_fg")).pack(anchor="w")
        ttk.Button(parent, text="Check for Updates", command=self.app_manager.check_for_updates).pack(anchor="w", pady=(10, 0))
        ttk.Button(parent, text="View on GitHub", command=lambda: webbrowser.open(constants.APP_REPOSITORY_URL)).pack(anchor="w", pady=(10, 0))

    def _create_wireproxy_status_section(self, parent):
        wireproxy_section = ttk.LabelFrame(parent, text=constants.WIREDPROXY_BINARY_FRAME_TITLE, padding=10)
        current_wireproxy = ProcessManager.find_wireproxy_executable()
        self._create_wireproxy_status_display(wireproxy_section, current_wireproxy)
        ttk.Separator(wireproxy_section, orient='horizontal').pack(fill='x', pady=(10, 10))
        self._create_wireproxy_download_section(wireproxy_section)
        return wireproxy_section

    def _create_wireproxy_status_display(self, parent, current_wireproxy):
        status_frame = ttk.Frame(parent)
        status_frame.pack(fill="x", pady=(0, 10))
        if current_wireproxy:
            self._display_wireproxy_found(status_frame, current_wireproxy)
        else:
            self._display_wireproxy_not_found(status_frame)

    def _display_wireproxy_found(self, parent, current_wireproxy):
        ttk.Label(parent, text=constants.WIREDPROXY_STATUS_LABEL, font=("Arial", 9, "bold")).pack(side="left")
        ttk.Label(parent, text=constants.WIREDPROXY_FOUND_STATUS, foreground=get_theme_manager().get_color("success_fg"), font=("Arial", 9, "bold")).pack(side="left")
        self._display_wireproxy_details(parent, current_wireproxy)

    def _display_wireproxy_not_found(self, parent):
        ttk.Label(parent, text=constants.WIREDPROXY_STATUS_LABEL, font=("Arial", 9, "bold")).pack(side="left")
        ttk.Label(parent, text=constants.WIREDPROXY_NOT_FOUND_STATUS, foreground=get_theme_manager().get_color("error_fg"), font=("Arial", 9, "bold")).pack(side="left")
        ttk.Label(parent, text="wireproxy binary not found in PATH or common locations.", font=("Arial", 8), foreground=get_theme_manager().get_color("error_fg")).pack(anchor="w", pady=(5, 0))

    def _display_wireproxy_details(self, parent, current_wireproxy):
        self._display_wireproxy_detail(parent, constants.WIREDPROXY_LOCATION_LABEL, current_wireproxy)
        try:
            stat_info = os.stat(current_wireproxy)
            file_size = stat_info.st_size
            mod_time = datetime.fromtimestamp(stat_info.st_mtime)
            size_text = f"{file_size / 1024:.1f} KB" if file_size >= 1024 else f"{file_size} bytes"
            self._display_wireproxy_detail(parent, constants.WIREDPROXY_SIZE_LABEL, size_text)
            self._display_wireproxy_detail(parent, constants.WIREDPROXY_MODIFIED_LABEL, mod_time.strftime("%Y-%m-%d %H:%M:%S"))
        except Exception:
            pass
        try:
            result = subprocess.run([current_wireproxy, '--version'], capture_output=True, text=True, timeout=5)
            if result.returncode == 0 and result.stdout.strip():
                version_text = result.stdout.strip().replace('\n', ' ')[:50]
                self._display_wireproxy_detail(parent, constants.WIREDPROXY_VERSION_LABEL, version_text)
        except Exception:
            pass

    def _display_wireproxy_detail(self, parent, label, value):
        frame = ttk.Frame(parent)
        frame.pack(fill="x", pady=(2, 0))
        ttk.Label(frame, text=label, font=("Arial", 9, "bold")).pack(side="left")
        ttk.Label(frame, text=value, font=("Arial", 8), foreground=get_theme_manager().get_color("secondary_fg")).pack(side="left")

    def _create_wireproxy_download_section(self, parent):
        download_frame = ttk.Frame(parent)
        download_frame.pack(fill="x")
        button_frame = ttk.Frame(download_frame)
        button_frame.pack(anchor="w")
        download_btn = ttk.Button(button_frame, text=constants.DOWNLOAD_LATEST_BUTTON, command=self._download_latest_wireproxy)
        download_btn.pack(side="left", padx=(0, 10))
        ttk.Button(button_frame, text=constants.CHECK_LATEST_BUTTON, command=self._check_latest_version).pack(side="left", padx=(0, 10))
        info_text = (
            "• Downloads from: https://github.com/whyvl/wireproxy/releases\n"
            "• Automatically detects your platform and architecture\n"
            "• Replaces existing binary if found"
        )
        ttk.Label(parent, text=info_text, font=("Arial", 8), foreground=get_theme_manager().get_color("secondary_fg")).pack(anchor="w", pady=(10, 0))

    def _download_latest_wireproxy(self):
        """Download latest wireproxy version with improved progress feedback"""
        self.app_manager.log_message("Starting wireproxy download from preferences...", LogLevel.INFO)
        
        if not DOWNLOAD_DIALOG_AVAILABLE:
            self.app_manager.log_message("Download dialog not available, using fallback method", LogLevel.WARNING)
            self._download_wireproxy_fallback()
            return
            
        try:
            def on_download_complete(success: bool, message: str):
                if success:
                    self.app_manager.log_message("Latest wireproxy downloaded successfully from preferences", LogLevel.INFO)
                    # Refresh the preferences window to show updated status
                    try:
                        if hasattr(self, 'preferences_window') and self.preferences_window and self.preferences_window.winfo_exists():
                            self.preferences_window.destroy()
                            # Delay showing the updated window slightly
                            self.parent.after(100, self.show)
                    except Exception as refresh_error:
                        self.app_manager.log_message(f"Error refreshing preferences window: {refresh_error}", LogLevel.WARNING)
                else:
                    self.app_manager.log_message(f"Failed to download wireproxy from preferences: {message}", LogLevel.ERROR)
                    
            # Use the new download dialog
            self.app_manager.log_message("Using modern download dialog for wireproxy download", LogLevel.DEBUG)
            WireproxyDownloadManager.download_wireproxy_with_ui(
                self.preferences_window,
                on_complete=on_download_complete
            )
            
        except Exception as e:
            self.app_manager.log_message(f"Error with modern download dialog: {str(e)}", LogLevel.ERROR)
            self._download_wireproxy_fallback()
    
    def _download_wireproxy_fallback(self):
        """Fallback download method for wireproxy"""
        try:
            self.app_manager.log_message("Using fallback download method", LogLevel.INFO)
            if ProcessManager._download_wireproxy_with_ui(self.preferences_window):
                self.app_manager.log_message("Latest wireproxy downloaded successfully (fallback)", LogLevel.INFO)
                messagebox.showinfo(constants.DOWNLOAD_SUCCESS_TITLE, constants.DOWNLOAD_SUCCESS_MESSAGE)
                # Refresh preferences window
                try:
                    if hasattr(self, 'preferences_window') and self.preferences_window and self.preferences_window.winfo_exists():
                        self.preferences_window.destroy()
                        self.parent.after(100, self.show)
                except Exception as refresh_error:
                    self.app_manager.log_message(f"Error refreshing preferences window: {refresh_error}", LogLevel.WARNING)
            else:
                self.app_manager.log_message("Failed to download wireproxy (fallback)", LogLevel.ERROR)
                messagebox.showerror(constants.DOWNLOAD_ERROR_TITLE, constants.DOWNLOAD_ERROR_MESSAGE)
        except Exception as fallback_error:
            self.app_manager.log_message(f"Fallback download also failed: {fallback_error}", LogLevel.ERROR)
            messagebox.showerror(constants.DOWNLOAD_ERROR_TITLE, f"Download failed: {fallback_error}\n\nPlease download manually from:\n{constants.GITHUB_RELEASES_URL}")
            messagebox.showerror(constants.DOWNLOAD_ERROR_TITLE, f"Download error: {str(e)}")

    def _check_latest_version(self):
        """Check what the latest version is without downloading"""
        try:
            self.app_manager.log_message("Checking latest wireproxy version...", LogLevel.INFO)
            
            # Use the download manager to get release info
            from gui.download_dialog import WireproxyDownloadManager
            release_data = WireproxyDownloadManager.get_latest_release_info()
            
            latest_version = release_data.get('tag_name', 'unknown')
            published_date = release_data.get('published_at', '')
            
            if published_date:
                try:
                    # Handle GitHub's ISO format
                    pub_date = datetime.fromisoformat(published_date.replace('Z', '+00:00'))
                    date_str = pub_date.strftime("%Y-%m-%d")
                except ValueError:
                    date_str = published_date
            else:
                date_str = "unknown date"
                
            self.app_manager.log_message(f"Latest wireproxy version: {latest_version}", LogLevel.INFO)
            
            messagebox.showinfo(
                constants.LATEST_VERSION_TITLE,
                constants.LATEST_VERSION_MESSAGE.format(version=latest_version, date=date_str)
            )
            
        except ImportError as e:
            self.app_manager.log_message(f"Failed to import download manager: {e}", LogLevel.ERROR)
            messagebox.showerror(constants.LATEST_VERSION_ERROR_TITLE, f"Failed to check version: {e}")
            
        except Exception as e:
            self.app_manager.log_message(f"Error checking latest version: {str(e)}", LogLevel.ERROR)
            messagebox.showerror(
                constants.LATEST_VERSION_ERROR_TITLE,
                constants.LATEST_VERSION_ERROR_MESSAGE.format(error=str(e))
            )

    def _save_preferences(self, start_minimized, minimize_to_tray, auto_start_proxies, api_endpoint, dark_mode):
        """Save preferences and validate input"""
        # Validate API endpoint
        api_endpoint = api_endpoint.strip()
        if not api_endpoint:
            messagebox.showerror("Error", "API endpoint cannot be empty")
            return

        if not api_endpoint.startswith(('http://', 'https://')):
            messagebox.showerror("Error", "API endpoint must start with http:// or https://")
            return

        # Check for changes
        api_changed = self.app_manager.settings.api_endpoint != api_endpoint
        theme_changed = self.app_manager.settings.dark_mode != dark_mode

        # Update settings
        self.app_manager.settings.start_minimized = start_minimized
        self.app_manager.settings.minimize_to_tray = minimize_to_tray
        self.app_manager.settings.auto_start_proxies = auto_start_proxies
        self.app_manager.settings.api_endpoint = api_endpoint
        self.app_manager.settings.dark_mode = dark_mode

        # Apply theme change immediately
        if theme_changed:
            set_dark_mode(dark_mode)
            self.app_manager.log_message(f"Theme changed to {'dark' if dark_mode else 'light'} mode", LogLevel.INFO)
            
            # Apply theme to main window
            if self.app_manager.main_window:
                self.app_manager.main_window.apply_theme_to_widgets()
            
            # Apply theme to preferences window
            self._apply_theme_to_preferences()

        # Persist changes
        from state import StateManager
        StateManager.save_settings(self.app_manager.settings)
        self.app_manager.log_message("Preferences saved", LogLevel.INFO)

        # Debug log to verify what was saved
        self.app_manager.log_message(
            f"Saved: start_minimized={start_minimized}, minimize_to_tray={minimize_to_tray}, "
            f"auto_start_proxies={auto_start_proxies}, api_endpoint={api_endpoint}",
            LogLevel.DEBUG)

        # Handle API endpoint change
        if api_changed:
            self.app_manager.log_message(f"API endpoint changed to: {api_endpoint}", LogLevel.INFO)
            messagebox.showinfo(
                "API Endpoint Changed",
                "API endpoint has been updated. You may want to reload servers to test the new endpoint."
            )