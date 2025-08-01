"""Theme management for the WireProxy SurfShark GUI application."""

import tkinter as tk
from tkinter import ttk
from typing import Dict, Any, Optional
import constants


class ThemeManager:
    """Manages application themes and provides centralized color access"""
    
    def __init__(self):
        self._current_theme = constants.THEME_LIGHT
        self._theme_colors = {
            constants.THEME_LIGHT: constants.LIGHT_THEME,
            constants.THEME_DARK: constants.DARK_THEME
        }
        self._style: Optional[ttk.Style] = None
        self._root: Optional[tk.Tk] = None
    
    def initialize(self, root: tk.Tk):
        """Initialize the theme manager with the root window"""
        self._root = root
        self._style = ttk.Style()
        # Use clam theme as base for better dark mode support
        self._style.theme_use("clam")
        self.apply_theme()
    
    def set_theme(self, theme: str) -> bool:
        """Set the current theme"""
        if theme not in self._theme_colors:
            return False
        
        self._current_theme = theme
        if self._root:
            self.apply_theme()
        return True
    
    def get_current_theme(self) -> str:
        """Get the current theme name"""
        return self._current_theme
    
    def is_dark_mode(self) -> bool:
        """Check if current theme is dark mode"""
        return self._current_theme == constants.THEME_DARK
    
    def get_color(self, color_key: str) -> str:
        """Get a color value for the current theme"""
        # Use a theme-appropriate fallback instead of hardcoded black
        fallback = "#000000" if self._current_theme == constants.THEME_LIGHT else "#FFFFFF"
        return self._theme_colors[self._current_theme].get(color_key, fallback)
    
    def get_colors(self) -> Dict[str, str]:
        """Get all colors for the current theme"""
        return self._theme_colors[self._current_theme].copy()
    
    def apply_theme(self):
        """Apply the current theme to all widgets"""
        if not self._root or not self._style:
            return
        
        colors = self.get_colors()
        
        # Configure root window
        self._root.configure(bg=colors["bg"])
        
        # Configure ttk styles
        self._configure_ttk_styles(colors)
        
        # Configure default tkinter widget options
        self._configure_tk_defaults(colors)
    
    def _configure_ttk_styles(self, colors: Dict[str, str]):
        """Configure TTK widget styles with enhanced dark mode support"""
        
        # Frame style
        self._style.configure("TFrame", 
                             background=colors["frame_bg"],
                             foreground=colors["frame_fg"])
        
        # Label style
        self._style.configure("TLabel",
                             background=colors["frame_bg"],
                             foreground=colors["frame_fg"])
        
        # Button style - enhanced with borders
        self._style.configure("TButton",
                             background=colors["button_bg"],
                             foreground=colors["button_fg"],
                             borderwidth=1,
                             relief="solid",
                             focuscolor=colors["focus_border"])
        self._style.map("TButton",
                       background=[("active", colors["button_active_bg"]),
                                 ("pressed", colors["button_active_bg"]),
                                 ("focus", colors["button_bg"])],
                       foreground=[("active", colors["button_active_fg"]),
                                 ("pressed", colors["button_active_fg"]),
                                 ("focus", colors["button_fg"])],
                       bordercolor=[("focus", colors["focus_border"])])
        
        # Entry style - enhanced with borders and focus
        self._style.configure("TEntry",
                             fieldbackground=colors["entry_bg"],
                             foreground=colors["entry_fg"],
                             borderwidth=1,
                             relief="solid",
                             insertcolor=colors["entry_fg"])
        self._style.map("TEntry",
                       fieldbackground=[("disabled", colors["entry_disabled_bg"]),
                                      ("focus", colors["entry_bg"])],
                       foreground=[("disabled", colors["entry_disabled_fg"]),
                                 ("focus", colors["entry_fg"])],
                       bordercolor=[("focus", colors["focus_border"]),
                                  ("!focus", colors["border"])])
        
        # Combobox style - enhanced
        self._style.configure("TCombobox",
                             fieldbackground=colors["entry_bg"],
                             foreground=colors["entry_fg"],
                             background=colors["button_bg"],
                             borderwidth=1,
                             relief="solid",
                             arrowcolor=colors["entry_fg"])
        self._style.map("TCombobox",
                       fieldbackground=[("disabled", colors["entry_disabled_bg"]),
                                      ("focus", colors["entry_bg"])],
                       foreground=[("disabled", colors["entry_disabled_fg"])],
                       bordercolor=[("focus", colors["focus_border"]),
                                  ("!focus", colors["border"])])
        
        # Spinbox style (for numeric controls)
        self._style.configure("TSpinbox",
                             fieldbackground=colors["entry_bg"],
                             foreground=colors["entry_fg"],
                             borderwidth=1,
                             relief="solid",
                             insertcolor=colors["entry_fg"],
                             arrowcolor=colors["entry_fg"])
        self._style.map("TSpinbox",
                       fieldbackground=[("disabled", colors["entry_disabled_bg"]),
                                      ("focus", colors["entry_bg"])],
                       foreground=[("disabled", colors["entry_disabled_fg"])],
                       bordercolor=[("focus", colors["focus_border"]),
                                  ("!focus", colors["border"])])
        
        # Notebook style
        self._style.configure("TNotebook",
                             background=colors["frame_bg"],
                             borderwidth=0)
        self._style.configure("TNotebook.Tab",
                             background=colors["button_bg"],
                             foreground=colors["button_fg"],
                             padding=[10, 5],
                             borderwidth=1)
        self._style.map("TNotebook.Tab",
                       background=[("selected", colors["frame_bg"]),
                                 ("active", colors["button_active_bg"])],
                       foreground=[("selected", colors["frame_fg"]),
                                 ("active", colors["button_active_fg"])])
        
        # Progressbar style
        self._style.configure("TProgressbar",
                             background=colors["select_bg"],
                             troughcolor=colors["entry_bg"],
                             borderwidth=0)
        
        # Enhanced Scrollbar style
        scrollbar_bg = colors["scrollbar_bg"]
        scrollbar_fg = colors["scrollbar_fg"]
        scrollbar_active = colors["scrollbar_active"]
        
        self._style.configure("TScrollbar",
                             background=scrollbar_bg,
                             troughcolor=colors["entry_bg"],
                             borderwidth=1,
                             relief="solid",
                             arrowcolor=scrollbar_fg)
        self._style.map("TScrollbar",
                       background=[("active", scrollbar_active),
                                 ("pressed", scrollbar_active)])
        
        # Vertical scrollbar
        self._style.configure("Vertical.TScrollbar",
                             background=scrollbar_bg,
                             troughcolor=colors["entry_bg"],
                             borderwidth=1,
                             arrowcolor=scrollbar_fg)
        
        # Horizontal scrollbar  
        self._style.configure("Horizontal.TScrollbar",
                             background=scrollbar_bg,
                             troughcolor=colors["entry_bg"], 
                             borderwidth=1,
                             arrowcolor=scrollbar_fg)
        
        # Enhanced LabelFrame style - fixes dark mode caption gap issue
        # The key fix: ensure background matches window/parent exactly to avoid visual "break"
        self._style.configure("TLabelframe",
                             background=colors["labelframe_bg"],  # Use dedicated labelframe background
                             foreground=colors["labelframe_fg"],
                             borderwidth=1,
                             relief="solid",
                             bordercolor=colors["labelframe_border"])
        
        # LabelFrame.Label style - CRITICAL: must match the window background exactly
        # This fills the gap in the border where the caption sits
        self._style.configure("TLabelframe.Label",
                             background=colors["labelframe_bg"],  # Must match window background exactly
                             foreground=colors["labelframe_fg"])
        
        # Create enhanced dark-specific style for better dark mode support
        if self.is_dark_mode():
            self._style.configure("Dark.TLabelframe",
                                 background=colors["labelframe_bg"],
                                 foreground=colors["labelframe_fg"],
                                 bordercolor=colors["labelframe_border"],
                                 relief="solid")
            self._style.configure("Dark.TLabelframe.Label",
                                 background=colors["labelframe_bg"],
                                 foreground=colors["labelframe_fg"])
        
        # Ensure both capitalization variants work for compatibility
        # Some tkinter versions use different capitalization
        for style_name in ["TLabelFrame", "TLabelframe"]:
            self._style.configure(style_name,
                                 background=colors["labelframe_bg"],
                                 foreground=colors["labelframe_fg"],
                                 borderwidth=1,
                                 relief="solid",
                                 bordercolor=colors["labelframe_border"])
            
            # Also configure the label variants
            for label_suffix in [".Label"]:
                self._style.configure(f"{style_name}{label_suffix}",
                                     background=colors["labelframe_bg"],
                                     foreground=colors["labelframe_fg"])
        
        # Checkbutton style
        self._style.configure("TCheckbutton",
                             background=colors["frame_bg"],
                             foreground=colors["frame_fg"],
                             focuscolor=colors["focus_border"])
        self._style.map("TCheckbutton",
                       background=[("active", colors["frame_bg"])],
                       foreground=[("active", colors["frame_fg"])])
        
        # Radiobutton style
        self._style.configure("TRadiobutton",
                             background=colors["frame_bg"],
                             foreground=colors["frame_fg"],
                             focuscolor=colors["focus_border"])
        self._style.map("TRadiobutton",
                       background=[("active", colors["frame_bg"])],
                       foreground=[("active", colors["frame_fg"])])
    
    def _configure_tk_defaults(self, colors: Dict[str, str]):
        """Configure default Tkinter widget options with comprehensive coverage"""
        # Set default options for Tkinter widgets
        self._root.option_add("*background", colors["bg"])
        self._root.option_add("*foreground", colors["fg"])
        self._root.option_add("*selectBackground", colors["select_bg"])
        self._root.option_add("*selectForeground", colors["select_fg"])
        self._root.option_add("*insertBackground", colors["fg"])
        self._root.option_add("*highlightColor", colors["focus_border"])
        self._root.option_add("*highlightBackground", colors["bg"])
        
        # Entry widget defaults
        self._root.option_add("*Entry.background", colors["entry_bg"])
        self._root.option_add("*Entry.foreground", colors["entry_fg"])
        self._root.option_add("*Entry.selectBackground", colors["select_bg"])
        self._root.option_add("*Entry.selectForeground", colors["select_fg"])
        self._root.option_add("*Entry.insertBackground", colors["entry_fg"])
        self._root.option_add("*Entry.highlightColor", colors["focus_border"])
        self._root.option_add("*Entry.highlightBackground", colors["border"])
        self._root.option_add("*Entry.relief", "solid")
        self._root.option_add("*Entry.borderWidth", "1")
        
        # Spinbox widget defaults (numeric up/down controls)
        self._root.option_add("*Spinbox.background", colors["entry_bg"])
        self._root.option_add("*Spinbox.foreground", colors["entry_fg"])
        self._root.option_add("*Spinbox.selectBackground", colors["select_bg"])
        self._root.option_add("*Spinbox.selectForeground", colors["select_fg"])
        self._root.option_add("*Spinbox.insertBackground", colors["entry_fg"])
        self._root.option_add("*Spinbox.buttonBackground", colors["button_bg"])
        self._root.option_add("*Spinbox.highlightColor", colors["focus_border"])
        self._root.option_add("*Spinbox.highlightBackground", colors["border"])
        self._root.option_add("*Spinbox.relief", "solid")
        self._root.option_add("*Spinbox.borderWidth", "1")
        
        # Text widget defaults (log area)
        self._root.option_add("*Text.background", colors["text_bg"])
        self._root.option_add("*Text.foreground", colors["text_fg"])
        self._root.option_add("*Text.selectBackground", colors["select_bg"])
        self._root.option_add("*Text.selectForeground", colors["select_fg"])
        self._root.option_add("*Text.insertBackground", colors["text_fg"])
        self._root.option_add("*Text.highlightColor", colors["focus_border"])
        self._root.option_add("*Text.highlightBackground", colors["border"])
        self._root.option_add("*Text.relief", "solid")
        self._root.option_add("*Text.borderWidth", "1")
        
        # Listbox defaults (Active Proxies list)
        self._root.option_add("*Listbox.background", colors["listbox_bg"])
        self._root.option_add("*Listbox.foreground", colors["listbox_fg"])
        self._root.option_add("*Listbox.selectBackground", colors["listbox_select_bg"])
        self._root.option_add("*Listbox.selectForeground", colors["listbox_select_fg"])
        self._root.option_add("*Listbox.highlightColor", colors["focus_border"])
        self._root.option_add("*Listbox.highlightBackground", colors["border"])
        self._root.option_add("*Listbox.relief", "solid")
        self._root.option_add("*Listbox.borderWidth", "1")
        
        # Button defaults
        self._root.option_add("*Button.background", colors["button_bg"])
        self._root.option_add("*Button.foreground", colors["button_fg"])
        self._root.option_add("*Button.activeBackground", colors["button_active_bg"])
        self._root.option_add("*Button.activeForeground", colors["button_active_fg"])
        self._root.option_add("*Button.highlightColor", colors["focus_border"])
        self._root.option_add("*Button.highlightBackground", colors["border"])
        self._root.option_add("*Button.relief", "solid")
        self._root.option_add("*Button.borderWidth", "1")
        
        # Label defaults
        self._root.option_add("*Label.background", colors["frame_bg"])
        self._root.option_add("*Label.foreground", colors["frame_fg"])
        
        # Frame defaults
        self._root.option_add("*Frame.background", colors["frame_bg"])
        
        # Toplevel (dialog) defaults
        self._root.option_add("*Toplevel.background", colors["bg"])
        
        # Scale defaults
        self._root.option_add("*Scale.background", colors["frame_bg"])
        self._root.option_add("*Scale.foreground", colors["frame_fg"])
        self._root.option_add("*Scale.troughColor", colors["entry_bg"])
        self._root.option_add("*Scale.activeBackground", colors["select_bg"])
        self._root.option_add("*Scale.highlightColor", colors["focus_border"])
        
        # Scrollbar defaults
        scrollbar_bg = colors["scrollbar_bg"]
        self._root.option_add("*Scrollbar.background", scrollbar_bg)
        self._root.option_add("*Scrollbar.troughColor", colors["entry_bg"])
        self._root.option_add("*Scrollbar.activeBackground", colors["scrollbar_active"])
        self._root.option_add("*Scrollbar.relief", "solid")
        self._root.option_add("*Scrollbar.borderWidth", "1")
        
        # Checkbutton and Radiobutton defaults
        self._root.option_add("*Checkbutton.background", colors["frame_bg"])
        self._root.option_add("*Checkbutton.foreground", colors["frame_fg"])
        self._root.option_add("*Checkbutton.activeBackground", colors["frame_bg"])
        self._root.option_add("*Checkbutton.activeForeground", colors["frame_fg"])
        self._root.option_add("*Checkbutton.selectColor", colors["entry_bg"])
        
        self._root.option_add("*Radiobutton.background", colors["frame_bg"])
        self._root.option_add("*Radiobutton.foreground", colors["frame_fg"])
        self._root.option_add("*Radiobutton.activeBackground", colors["frame_bg"])
        self._root.option_add("*Radiobutton.activeForeground", colors["frame_fg"])
        self._root.option_add("*Radiobutton.selectColor", colors["entry_bg"])
        
        # Menu defaults (for context menus)
        self._root.option_add("*Menu.background", colors["frame_bg"])
        self._root.option_add("*Menu.foreground", colors["frame_fg"])
        self._root.option_add("*Menu.activeBackground", colors["select_bg"])
        self._root.option_add("*Menu.activeForeground", colors["select_fg"])
        self._root.option_add("*Menu.selectColor", colors["select_bg"])
        
        # Menubutton defaults
        self._root.option_add("*Menubutton.background", colors["button_bg"])
        self._root.option_add("*Menubutton.foreground", colors["button_fg"])
        self._root.option_add("*Menubutton.activeBackground", colors["button_active_bg"])
        self._root.option_add("*Menubutton.activeForeground", colors["button_active_fg"])
    
    def configure_widget(self, widget: tk.Widget, **kwargs):
        """Configure a specific widget with theme colors"""
        colors = self.get_colors()
        
        # Get widget type
        widget_type = widget.winfo_class()
        
        # Apply appropriate colors based on widget type
        if widget_type in ["Frame", "Toplevel"]:
            widget.configure(bg=colors["frame_bg"], **kwargs)
        elif widget_type == "Label":
            widget.configure(bg=colors["frame_bg"], fg=colors["frame_fg"], **kwargs)
        elif widget_type == "Button":
            widget.configure(
                bg=colors["button_bg"], 
                fg=colors["button_fg"],
                activebackground=colors["button_active_bg"],
                activeforeground=colors["button_active_fg"],
                highlightcolor=colors["focus_border"],
                highlightbackground=colors["border"],
                relief="solid",
                borderwidth=1,
                **kwargs
            )
        elif widget_type == "Entry":
            widget.configure(
                bg=colors["entry_bg"], 
                fg=colors["entry_fg"],
                insertbackground=colors["entry_fg"],
                selectbackground=colors["select_bg"],
                selectforeground=colors["select_fg"],
                highlightcolor=colors["focus_border"],
                highlightbackground=colors["border"],
                relief="solid",
                borderwidth=1,
                **kwargs
            )
        elif widget_type == "Spinbox":
            widget.configure(
                bg=colors["entry_bg"],
                fg=colors["entry_fg"],
                insertbackground=colors["entry_fg"],
                selectbackground=colors["select_bg"],
                selectforeground=colors["select_fg"],
                buttonbackground=colors["button_bg"],
                highlightcolor=colors["focus_border"],
                highlightbackground=colors["border"],
                relief="solid",
                borderwidth=1,
                **kwargs
            )
        elif widget_type == "Text":
            widget.configure(
                bg=colors["text_bg"], 
                fg=colors["text_fg"],
                insertbackground=colors["text_fg"],
                selectbackground=colors["select_bg"],
                selectforeground=colors["select_fg"],
                highlightcolor=colors["focus_border"],
                highlightbackground=colors["border"],
                relief="solid",
                borderwidth=1,
                **kwargs
            )
        elif widget_type == "Listbox":
            widget.configure(
                bg=colors["listbox_bg"], 
                fg=colors["listbox_fg"],
                selectbackground=colors["listbox_select_bg"],
                selectforeground=colors["listbox_select_fg"],
                highlightcolor=colors["focus_border"],
                highlightbackground=colors["border"],
                relief="solid",
                borderwidth=1,
                **kwargs
            )
        elif widget_type == "Scrollbar":
            scrollbar_bg = colors["scrollbar_bg"]
            widget.configure(
                bg=scrollbar_bg,
                troughcolor=colors["entry_bg"],
                activebackground=colors["scrollbar_active"],
                relief="solid",
                borderwidth=1,
                **kwargs
            )
        elif widget_type in ["Checkbutton", "Radiobutton"]:
            widget.configure(
                bg=colors["frame_bg"],
                fg=colors["frame_fg"],
                activebackground=colors["frame_bg"],
                activeforeground=colors["frame_fg"],
                selectcolor=colors["entry_bg"],
                **kwargs
            )
        elif widget_type == "Scale":
            widget.configure(
                bg=colors["frame_bg"],
                fg=colors["frame_fg"],
                troughcolor=colors["entry_bg"],
                activebackground=colors["select_bg"],
                highlightcolor=colors["focus_border"],
                **kwargs
            )
        elif widget_type == "Canvas":
            widget.configure(bg=colors["bg"], **kwargs)
        elif widget_type == "Menu":
            widget.configure(
                bg=colors["frame_bg"],
                fg=colors["frame_fg"],
                activebackground=colors["select_bg"],
                activeforeground=colors["select_fg"],
                **kwargs
            )
        elif widget_type == "Menubutton":
            widget.configure(
                bg=colors["button_bg"],
                fg=colors["button_fg"],
                activebackground=colors["button_active_bg"],
                activeforeground=colors["button_active_fg"],
                **kwargs
            )
        else:
            # Default configuration - safely apply supported options
            config_options = {}
            
            # Try to apply background color if supported
            try:
                widget.configure(bg=colors["bg"])
                config_options["bg"] = colors["bg"]
            except tk.TclError:
                pass
            
            # Try to apply foreground color if supported
            try:
                widget.configure(fg=colors["fg"])
                config_options["fg"] = colors["fg"]
            except tk.TclError:
                pass
            
            # Apply any additional kwargs that are supported
            for key, value in kwargs.items():
                try:
                    test_config = {key: value}
                    widget.configure(**test_config)
                    config_options[key] = value
                except tk.TclError:
                    pass
            
            # Apply all supported options at once
            if config_options:
                try:
                    widget.configure(**config_options)
                except tk.TclError:
                    # If batch configuration fails, skip this widget
                    pass
    
    def get_log_level_color(self, level_name: str) -> str:
        """Get color for log level"""
        level_map = {
            "DEBUG": "log_debug",
            "INFO": "log_info", 
            "WARNING": "log_warning",
            "ERROR": "log_error"
        }
        color_key = level_map.get(level_name.upper(), "log_info")
        return self.get_color(color_key)
    
    def get_status_color(self, status: str) -> str:
        """Get color for proxy status"""
        status_map = {
            "Running": "status_running",
            "Stopped": "status_stopped",
            "Starting": "status_starting",
            "Error": "status_error"
        }
        color_key = status_map.get(status, "fg")
        return self.get_color(color_key)
    
    def apply_theme_to_children(self, parent_widget: tk.Widget):
        """Recursively apply theme to all child widgets"""
        # Apply theme to the parent widget
        self.configure_widget(parent_widget)
        
        # Recursively apply to all children
        try:
            for child in parent_widget.winfo_children():
                self.apply_theme_to_children(child)
        except tk.TclError:
            # Widget might have been destroyed
            pass
    
    def update_scrolledtext_theme(self, scrolled_text_widget):
        """Special handling for ScrolledText widgets"""
        colors = self.get_colors()
        try:
            # Configure the text widget
            text_widget = scrolled_text_widget.text if hasattr(scrolled_text_widget, 'text') else scrolled_text_widget
            self.configure_widget(text_widget)
            
            # Find and configure the scrollbar
            for child in scrolled_text_widget.winfo_children():
                if child.winfo_class() == "Scrollbar":
                    self.configure_widget(child)
        except (AttributeError, tk.TclError):
            # Fallback for different ScrolledText implementations
            try:
                scrolled_text_widget.configure(
                    bg=colors["text_bg"],
                    fg=colors["text_fg"],
                    insertbackground=colors["text_fg"],
                    selectbackground=colors["select_bg"],
                    selectforeground=colors["select_fg"]
                )
            except tk.TclError:
                pass
    
    def create_dark_title_bar(self, window: tk.Tk):
        """Enable dark title bar on Windows 10 1809+ and other platforms"""
        try:
            import platform
            if platform.system() == "Windows":
                # Try to set dark title bar on Windows
                try:
                    import ctypes
                    from ctypes import wintypes
                    
                    # Get window handle
                    hwnd = ctypes.windll.user32.GetParent(window.winfo_id())
                    if not hwnd:
                        hwnd = window.winfo_id()
                    
                    # DWMWA_USE_IMMERSIVE_DARK_MODE attribute
                    DWMWA_USE_IMMERSIVE_DARK_MODE = 20
                    value = ctypes.c_int(1 if self.is_dark_mode() else 0)
                    
                    # Try to call DwmSetWindowAttribute
                    result = ctypes.windll.dwmapi.DwmSetWindowAttribute(
                        ctypes.wintypes.HWND(hwnd),
                        ctypes.wintypes.DWORD(DWMWA_USE_IMMERSIVE_DARK_MODE),
                        ctypes.byref(value),
                        ctypes.sizeof(value)
                    )
                    
                    if result == 0:  # S_OK
                        return True
                except Exception:
                    # If modern API fails, try legacy approach
                    try:
                        DWMWA_USE_IMMERSIVE_DARK_MODE_LEGACY = 19
                        result = ctypes.windll.dwmapi.DwmSetWindowAttribute(
                            ctypes.wintypes.HWND(hwnd),
                            ctypes.wintypes.DWORD(DWMWA_USE_IMMERSIVE_DARK_MODE_LEGACY),
                            ctypes.byref(value),
                            ctypes.sizeof(value)
                        )
                        return result == 0
                    except Exception:
                        pass
            
            # For other platforms, we can't easily change the title bar
            # but we can ensure the window background is correct
            colors = self.get_colors()
            window.configure(bg=colors["bg"])
            return False
            
        except Exception:
            return False


# Global theme manager instance
_theme_manager = None


def get_theme_manager() -> ThemeManager:
    """Get the global theme manager instance"""
    global _theme_manager
    if _theme_manager is None:
        _theme_manager = ThemeManager()
    return _theme_manager


def initialize_theme(root: tk.Tk, dark_mode: bool = False):
    """Initialize the theme system with enhanced dark mode support"""
    theme_manager = get_theme_manager()
    theme_manager.initialize(root)
    if dark_mode:
        theme_manager.set_theme(constants.THEME_DARK)
        # Apply dark title bar if possible
        theme_manager.create_dark_title_bar(root)
    else:
        theme_manager.set_theme(constants.THEME_LIGHT)
    return theme_manager


def set_dark_mode(enabled: bool):
    """Set dark mode on or off"""
    theme_manager = get_theme_manager()
    theme = constants.THEME_DARK if enabled else constants.THEME_LIGHT
    return theme_manager.set_theme(theme)


def is_dark_mode() -> bool:
    """Check if dark mode is enabled"""
    return get_theme_manager().is_dark_mode()


def get_color(color_key: str) -> str:
    """Get a theme color"""
    return get_theme_manager().get_color(color_key)


def configure_widget(widget: tk.Widget, **kwargs):
    """Configure a widget with theme colors"""
    get_theme_manager().configure_widget(widget, **kwargs)


def apply_theme_to_children(parent_widget: tk.Widget):
    """Apply theme recursively to all child widgets"""
    get_theme_manager().apply_theme_to_children(parent_widget)


def update_scrolledtext_theme(scrolled_text_widget):
    """Apply theme to ScrolledText widgets"""
    get_theme_manager().update_scrolledtext_theme(scrolled_text_widget)


def create_dark_title_bar(window: tk.Tk):
    """Enable dark title bar where supported"""
    return get_theme_manager().create_dark_title_bar(window)