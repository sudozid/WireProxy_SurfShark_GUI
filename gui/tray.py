"""System tray icon management for the WireProxy SurfShark GUI application."""

import threading
import logging
from PIL import Image, ImageDraw

logger = logging.getLogger(__name__)


class TrayIconManager:
    """Manages system tray icon"""

    def __init__(self, app_manager):
        self.app_manager = app_manager
        self.tray_icon = None

    def create_tray_icon(self):
        """Create system tray icon"""
        try:
            import pystray

            def create_icon_image():
                width = 64
                height = 64
                image = Image.new('RGB', (width, height), color='blue')
                draw = ImageDraw.Draw(image)
                draw.ellipse([16, 16, 48, 48], fill='white')
                return image

            menu = pystray.Menu(
                pystray.MenuItem("Show", self.show_from_tray),
                pystray.MenuItem("Preferences", self.app_manager.show_preferences),
                pystray.MenuItem("Quit", self.quit_from_tray)
            )

            self.tray_icon = pystray.Icon("wireproxy", create_icon_image(), "Wireproxy Manager", menu)
        except Exception as e:
            logger.error(f"Failed to create tray icon: {e}")
            self.tray_icon = None

    def show_from_tray(self, icon=None, item=None):
        """Show window from tray"""
        if self.app_manager.main_window and self.app_manager.main_window.root:
            self.app_manager.main_window.root.after(0, lambda: [
                self.app_manager.main_window.root.deiconify(),
                self.app_manager.main_window.root.lift(),
                self.app_manager.main_window.root.focus_force()
            ])

    def hide_to_tray(self):
        """Hide window to tray"""
        if (self.app_manager.settings.minimize_to_tray and 
            self.app_manager.main_window and 
            self.app_manager.main_window.root):
            self.app_manager.main_window.root.withdraw()
            if self.tray_icon and not self.tray_icon.visible:
                threading.Thread(target=self.tray_icon.run, daemon=True).start()

    def quit_from_tray(self, icon=None, item=None):
        """Quit from tray"""
        if self.tray_icon:
            self.tray_icon.stop()
        if self.app_manager.main_window and self.app_manager.main_window.root:
            self.app_manager.main_window.root.after(0, self.app_manager.on_closing)

    def start_tray_if_minimized(self):
        """Start tray icon if application is set to start minimized"""
        if self.app_manager.settings.start_minimized and self.tray_icon:
            threading.Thread(target=self.tray_icon.run, daemon=True).start()