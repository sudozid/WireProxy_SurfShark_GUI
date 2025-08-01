"""Main application manager for the WireProxy SurfShark GUI application."""

import tkinter as tk
from tkinter import ttk, messagebox, filedialog, scrolledtext
import threading
import time
import logging
import sys
import os
import atexit
import concurrent.futures
import socket
from datetime import datetime
from typing import List

from models import LogLevel, ProxyStatus, ProxyInstance
from state import ThreadSafeState, StateManager
from network.manager import NetworkManager, ServerManager
from config.manager import ConfigurationManager
from processes.manager import ProcessManager
from gui.main_window import MainWindow
from gui.tray import TrayIconManager
from gui.queue import GUIMessageQueue
from gui.theme import initialize_theme
import constants

logger = logging.getLogger(__name__)


class WireproxyManager:
    """Main application class that coordinates all components"""

    def __init__(self):
        self.state = ThreadSafeState()
        self.gui_queue = GUIMessageQueue()
        self.settings = StateManager.load_settings()

        # GUI and tray managers
        self.main_window = None
        self.tray_manager = None

        # Monitoring
        self.monitor_thread = None
        self.shutdown_event = threading.Event()
        self._last_force_update = time.time()
        self.thread_pool = concurrent.futures.ThreadPoolExecutor(max_workers=4)

        # Register cleanup on exit
        atexit.register(lambda: StateManager.cleanup_temp_files(self.state))

    def log_message(self, message: str, level: LogLevel = LogLevel.INFO):
        """Thread-safe logging"""
        self.gui_queue.put_log_message(message, level)

        # Also log to Python logger
        if level == LogLevel.DEBUG:
            logger.debug(message)
        elif level == LogLevel.INFO:
            logger.info(message)
        elif level == LogLevel.WARNING:
            logger.warning(message)
        elif level == LogLevel.ERROR:
            logger.error(message)

    def update_status(self, message: str):
        """Thread-safe status updates"""
        self.gui_queue.put_status_update(message)

    def force_gui_update(self):
        """Force immediate GUI update - use when queue might be failing"""
        try:
            if self.main_window:
                self.main_window.update_proxy_list_display()
                if self.main_window.root:
                    self.main_window.root.update_idletasks()
        except Exception as e:
            logger.error(f"Force GUI update failed: {e}")

    def process_gui_messages(self):
        """Process messages with better error handling"""
        try:
            messages = self.gui_queue.get_messages()

            for message in messages:
                try:
                    if message[0] == 'log':
                        self.main_window.update_log_display(message[1], message[2])
                    elif message[0] == 'status':
                        self.main_window.update_status_display(message[1])
                    elif message[0] == 'proxy_list_update':
                        self.main_window.update_proxy_list_display()
                    elif message[0] == 'server_update':
                        self.main_window.update_server_dropdown(message[1])
                except Exception as e:
                    logger.error(f"Error processing message {message[0]}: {e}")

            # Controlled force update every 10 seconds (reduced frequency)
            current_time = time.time()
            if current_time - self._last_force_update > 10:
                proxy_instances = self.state.get_proxy_instances()
                if len(proxy_instances) <= 50:  # Only for reasonable number of proxies
                    self.main_window.update_proxy_list_display()
                self._last_force_update = current_time

            # Schedule next update
            if self.main_window and self.main_window.root:
                self.main_window.root.after(100, self.process_gui_messages)

        except Exception as e:
            logger.error(f"Error processing GUI messages: {e}")
            # Ensure we keep trying even if queue fails
            if self.main_window and self.main_window.root:
                self.main_window.root.after(500, self.process_gui_messages)

    def start_monitoring(self):
        """Start the process monitoring thread"""
        if self.monitor_thread and self.monitor_thread.is_alive():
            return

        self.shutdown_event.clear()
        self.monitor_thread = threading.Thread(target=self._monitor_processes, daemon=True)
        self.monitor_thread.start()
        self.log_message("Process monitor started", LogLevel.DEBUG)

    def _monitor_processes(self):
        """Monitor running processes (runs in background thread)"""
        while not self.shutdown_event.is_set():
            try:
                self._check_running_proxies()
                self.shutdown_event.wait(5)
            except Exception as e:
                self.log_message(f"Error in process monitor: {str(e)}", LogLevel.ERROR)
                self.shutdown_event.wait(10)

    def _check_running_proxies(self):
        proxy_instances = self.state.get_proxy_instances()
        running_processes = self.state.get_running_processes()
        for i, instance in enumerate(proxy_instances):
            if instance.status == ProxyStatus.RUNNING and i in running_processes:
                process_info = running_processes[i]
                if process_info.process.poll() is not None:
                    self._handle_unexpected_process_termination(i, instance)
                else:
                    self._monitor_resource_usage(i, instance, process_info)

    def _handle_unexpected_process_termination(self, index, instance):
        self.log_message(f"Process for port {instance.port} has died unexpectedly", LogLevel.ERROR)
        self.state.update_proxy_status(index, ProxyStatus.STOPPED)
        removed_process = self.state.remove_running_process(index)
        if removed_process:
            try:
                os.unlink(removed_process.config_file)
            except OSError:
                pass
        self.gui_queue.put_proxy_list_update()

    def _monitor_resource_usage(self, index, instance, process_info):
        try:
            import psutil
            ps_process = psutil.Process(process_info.process.pid)
            cpu_percent = ps_process.cpu_percent()
            memory_mb = ps_process.memory_info().rss / 1024 / 1024
            self._check_cpu_usage(index, instance, process_info, cpu_percent)
            if cpu_percent > 1.0 or memory_mb > 50:
                self.log_message(f"Port {instance.port}: CPU: {cpu_percent:.1f}%, Memory: {memory_mb:.1f}MB", LogLevel.DEBUG)
        except (psutil.NoSuchProcess, psutil.AccessDenied, AttributeError):
            pass

    def _check_cpu_usage(self, index, instance, process_info, cpu_percent):
        if cpu_percent > 90:
            if process_info.high_cpu_start is None:
                process_info.high_cpu_start = time.time()
            elif time.time() - process_info.high_cpu_start > 30:
                self.log_message(f"Killing process on port {instance.port} due to high CPU usage", LogLevel.WARNING)
                ProcessManager.stop_process_gracefully(process_info, timeout=2)
                self.state.update_proxy_status(index, ProxyStatus.ERROR)
                self.state.remove_running_process(index)
                self.gui_queue.put_proxy_list_update()
        else:
            process_info.high_cpu_start = None

    def load_servers(self):
        """Load servers from API with caching fallback"""

        def fetch_servers():
            try:
                self.update_status(constants.STATUS_LOADING_SERVERS)
                self.log_message("Starting server fetch from SurfShark API...", LogLevel.INFO)

                # Try to fetch fresh servers
                servers = NetworkManager.fetch_servers_with_retry(self.settings.api_endpoint)

                if servers:
                    # Save to cache
                    StateManager.save_servers_cache(servers)
                else:
                    # Try to load from cache as fallback
                    self.log_message("Failed to fetch servers, trying cache...", LogLevel.WARNING)
                    servers = StateManager.load_servers_cache()

                    if servers:
                        self.log_message("Loaded servers from cache", LogLevel.INFO)
                    else:
                        self.update_status(constants.STATUS_ERROR_LOADING_SERVERS)
                        self.log_message("Failed to load servers from API and cache", LogLevel.ERROR)
                        return

                self.state.set_servers(servers)

                # Process servers for dropdown
                country_options = ServerManager.process_servers(servers)

                total_countries = len(set(server['country'] for server in servers))
                total_locations = len(set(f"{server['country']}-{server['location']}" for server in servers))

                self.log_message(
                    f"Loaded {len(servers)} servers from {total_countries} countries, "
                    f"{total_locations} locations",
                    LogLevel.INFO
                )

                self.update_status(constants.STATUS_READY.format(countries=total_countries, locations=total_locations))
                self.gui_queue.put_server_update(country_options)

            except Exception as e:
                self.log_message(f"Error loading servers: {str(e)}", LogLevel.ERROR)
                self.update_status(constants.STATUS_ERROR_LOADING_SERVERS)

        # Use thread pool for better management
        self.thread_pool.submit(fetch_servers)

    def add_proxy(self):
        """Add a new SOCKS5 proxy with comprehensive validation"""
        try:
            if not self.main_window or not self.main_window.country_var or not self.main_window.port_var:
                self.log_message("GUI not properly initialized", LogLevel.ERROR)
                return

            country = self.main_window.country_var.get()
            port = self.main_window.port_var.get()

            self.log_message(f"Attempting to add proxy: Country={country}, Port={port}", LogLevel.DEBUG)

            # Validation
            if not country:
                self.log_message("No country selected", LogLevel.WARNING)
                messagebox.showerror(constants.NO_COUNTRY_SELECTED_TITLE, constants.NO_COUNTRY_SELECTED_MESSAGE)
                return

            if not port or port < 1024 or port > 65535:
                self.log_message(f"Invalid port number: {port}", LogLevel.WARNING)
                messagebox.showerror(constants.INVALID_PORT_TITLE, constants.INVALID_PORT_MESSAGE)
                return

            # Check for port conflicts
            proxy_instances = self.state.get_proxy_instances()
            for instance in proxy_instances:
                if instance.port == port:
                    self.log_message(f"Port {port} already in use", LogLevel.WARNING)
                    messagebox.showerror(constants.PORT_IN_USE_TITLE, constants.PORT_IN_USE_MESSAGE.format(port=port))
                    return

            # Check if port is available on system
            try:
                with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                    s.bind(('127.0.0.1', port))
                self.log_message(f"Port {port} is available", LogLevel.DEBUG)
            except OSError:
                self.log_message(f"Port {port} is in use by another application", LogLevel.WARNING)
                messagebox.showerror(constants.PORT_IN_USE_BY_OTHER_APP_TITLE, constants.PORT_IN_USE_BY_OTHER_APP_MESSAGE.format(port=port))
                return

            # Get servers for selection
            servers = self.state.get_servers()
            if not servers:
                self.log_message("No servers loaded", LogLevel.ERROR)
                messagebox.showerror(constants.SERVERS_NOT_LOADED_TITLE, constants.SERVERS_NOT_LOADED_MESSAGE)
                return

            country_servers = ServerManager.get_servers_by_selection(servers, country)
            if not country_servers:
                self.log_message(f"No servers found for {country}", LogLevel.ERROR)
                messagebox.showerror(constants.NO_SERVERS_FOUND_TITLE, constants.NO_SERVERS_FOUND_MESSAGE.format(country=country))
                return

            chosen_server = ServerManager.select_best_server(country_servers)
            if not chosen_server:
                self.log_message(f"Could not select server for {country}", LogLevel.ERROR)
                messagebox.showerror(constants.COULD_NOT_SELECT_SERVER_TITLE, constants.COULD_NOT_SELECT_SERVER_MESSAGE.format(country=country))
                return

            self.log_message(
                f"Selected server {chosen_server['location']} with "
                f"{chosen_server.get('load', 'unknown')}% load",
                LogLevel.INFO
            )

            # Create proxy instance
            instance = ProxyInstance(
                id=len(proxy_instances),
                country=country,
                location=chosen_server['location'],
                port=port,
                server=chosen_server,
                status=ProxyStatus.STOPPED
            )

            self.state.add_proxy_instance(instance)
            self.gui_queue.put_proxy_list_update()

            self.log_message(
                f"Added proxy: {country} - {chosen_server['location']} on port {port}",
                LogLevel.INFO
            )

            # Auto-increment port
            self.main_window.port_var.set(port + 1)

            # Save state
            StateManager.save_state(self.state, self.settings)

        except Exception as e:
            self.log_message(f"Error adding proxy: {str(e)}", LogLevel.ERROR)
            messagebox.showerror(constants.ADD_PROXY_ERROR_TITLE, constants.ADD_PROXY_ERROR_MESSAGE.format(error=str(e)))

    def remove_proxy(self):
        """Remove selected proxy with proper cleanup"""
        try:
            if not self.main_window or not self.main_window.proxy_listbox:
                return

            selection = self.main_window.proxy_listbox.curselection()
            if not selection:
                self.log_message("No proxy selected for removal", LogLevel.WARNING)
                messagebox.showwarning(constants.REMOVE_PROXY_WARNING_TITLE, constants.REMOVE_PROXY_WARNING_MESSAGE)
                return

            index = selection[0]
            instance = self.state.get_proxy_instance(index)

            if not instance:
                self.log_message(f"Invalid proxy index: {index}", LogLevel.ERROR)
                return

            self.log_message(f"Removing proxy on port {instance.port} ({instance.country})", LogLevel.INFO)

            # Stop if running
            if instance.status == ProxyStatus.RUNNING:
                self.log_message("Stopping running proxy before removal", LogLevel.DEBUG)
                self._stop_proxy_by_index(index)

            # Remove from state
            removed_instance = self.state.remove_proxy_instance(index)
            if removed_instance:
                self.gui_queue.put_proxy_list_update()
                self.log_message(f"Successfully removed proxy on port {removed_instance.port}", LogLevel.INFO)

                # Save state
                StateManager.save_state(self.state, self.settings)

        except Exception as e:
            self.log_message(f"Error removing proxy: {str(e)}", LogLevel.ERROR)
            messagebox.showerror(constants.REMOVE_PROXY_ERROR_TITLE, constants.REMOVE_PROXY_ERROR_MESSAGE.format(error=str(e)))

    def start_proxy(self):
        """Start selected proxy with comprehensive error handling"""
        try:
            if not self.main_window or not self.main_window.proxy_listbox:
                return

            selection = self.main_window.proxy_listbox.curselection()
            if not selection:
                self.log_message("No proxy selected for start operation", LogLevel.WARNING)
                messagebox.showwarning(constants.START_PROXY_WARNING_TITLE, constants.START_PROXY_WARNING_MESSAGE)
                return

            index = selection[0]
            self._start_proxy_by_index(index)

        except Exception as e:
            self.log_message(f"Error starting proxy: {str(e)}", LogLevel.ERROR)
            messagebox.showerror(constants.START_PROXY_ERROR_TITLE, constants.START_PROXY_ERROR_MESSAGE.format(error=str(e)))

    def _start_proxy_by_index(self, index: int):
        """Start proxy by index"""
        instance = self.state.get_proxy_instance(index)
        if not instance:
            self.log_message(f"Invalid proxy index: {index}", LogLevel.ERROR)
            return

        if instance.status == ProxyStatus.RUNNING:
            self.log_message(f"Proxy on port {instance.port} is already running", LogLevel.WARNING)
            return

        # Check keys
        private_key, public_key = self.state.get_keys()
        if not private_key or not public_key:
            self.log_message("WireGuard keys not configured", LogLevel.ERROR)
            messagebox.showerror(constants.WIREGUARD_KEYS_NOT_CONFIGURED_TITLE, constants.WIREGUARD_KEYS_NOT_CONFIGURED_MESSAGE)
            return

        # Update status immediately
        self.state.update_proxy_status(index, ProxyStatus.STARTING)
        instance.connection_attempts += 1

        # Force immediate GUI update
        if self.main_window:
            self.main_window.update_proxy_list_display()

        try:
            # Generate configurations
            wg_config = ConfigurationManager.generate_wireguard_config(instance.server, private_key)
            wireproxy_config = ConfigurationManager.generate_wireproxy_config(wg_config, instance.port)

            # Start process
            process_info = ProcessManager.start_wireproxy_process(
                wireproxy_config, 
                self.state, 
                parent_window=self.main_window.root if self.main_window else None
            )

            if not process_info:
                self.state.update_proxy_status(index, ProxyStatus.ERROR)
                if self.main_window:
                    self.main_window.update_proxy_list_display()
                return

            # Store process info and update status
            self.state.add_running_process(index, process_info)
            self.state.update_proxy_status(index, ProxyStatus.RUNNING)
            instance.start_time = datetime.now()

            # Force GUI update
            if self.main_window:
                self.main_window.update_proxy_list_display()

            # Save state
            StateManager.save_state(self.state, self.settings)

            self.log_message(f"Successfully started proxy on port {instance.port}", LogLevel.INFO)

            # Test connection in background
            self.thread_pool.submit(self._test_proxy_connection, instance.port)

        except Exception as e:
            self.state.update_proxy_status(index, ProxyStatus.ERROR)
            if self.main_window:
                self.main_window.update_proxy_list_display()
            self.log_message(f"Error starting proxy: {str(e)}", LogLevel.ERROR)

    def _test_proxy_connection(self, port: int):
        """Test proxy connection (runs in background)"""
        time.sleep(2)  # Wait for proxy to be ready
        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.settimeout(5)
            result = sock.connect_ex(('127.0.0.1', port))
            sock.close()

            if result == 0:
                self.log_message(f"Proxy on port {port} is accepting connections", LogLevel.INFO)
            else:
                self.log_message(f"Proxy on port {port} is not accepting connections", LogLevel.WARNING)

        except Exception as e:
            self.log_message(f"Could not test proxy connection: {str(e)}", LogLevel.WARNING)

    def stop_proxy(self):
        """Stop selected proxy"""
        try:
            if not self.main_window or not self.main_window.proxy_listbox:
                return

            selection = self.main_window.proxy_listbox.curselection()
            if not selection:
                self.log_message("No proxy selected for stop operation", LogLevel.WARNING)
                messagebox.showwarning(constants.STOP_PROXY_WARNING_TITLE, constants.STOP_PROXY_WARNING_MESSAGE)
                return

            index = selection[0]
            self._stop_proxy_by_index(index)

            # Save state
            StateManager.save_state(self.state, self.settings)

        except Exception as e:
            self.log_message(f"Error stopping proxy: {str(e)}", LogLevel.ERROR)
            messagebox.showerror(constants.STOP_PROXY_ERROR_TITLE, constants.STOP_PROXY_ERROR_MESSAGE.format(error=str(e)))

    def _stop_proxy_by_index(self, index: int):
        """Stop proxy by index (internal method)"""
        instance = self.state.get_proxy_instance(index)
        if not instance:
            self.log_message(f"Invalid proxy index: {index}", LogLevel.ERROR)
            return

        self.log_message(f"Stopping proxy on port {instance.port}", LogLevel.INFO)

        if instance.status != ProxyStatus.RUNNING:
            self.log_message(f"Proxy on port {instance.port} is not running", LogLevel.DEBUG)
            return

        # Get and remove process info
        process_info = self.state.remove_running_process(index)

        if process_info:
            # Stop process in background thread
            def stop_process():
                ProcessManager.stop_process_gracefully(process_info)

            self.thread_pool.submit(stop_process)

        # Update status
        self.state.update_proxy_status(index, ProxyStatus.STOPPED)
        instance.start_time = None
        self.gui_queue.put_proxy_list_update()

        self.log_message(f"Successfully stopped proxy on port {instance.port}", LogLevel.INFO)

    def stop_all_proxies(self):
        """Stop all running proxies with proper thread management"""
        proxy_instances = self.state.get_proxy_instances()
        running_count = sum(1 for instance in proxy_instances if instance.status == ProxyStatus.RUNNING)

        self.log_message("Stopping all running proxies...", LogLevel.INFO)
        self.log_message(f"Found {running_count} running proxies to stop", LogLevel.DEBUG)

        # Submit stop tasks to thread pool
        stop_futures = []
        for i, instance in enumerate(proxy_instances):
            if instance.status == ProxyStatus.RUNNING:
                future = self.thread_pool.submit(self._stop_proxy_by_index, i)
                stop_futures.append(future)

        # Wait for all stops to complete with timeout
        if stop_futures:
            try:
                concurrent.futures.wait(stop_futures, timeout=10)
                self.log_message("All proxy stop operations completed", LogLevel.INFO)
            except concurrent.futures.TimeoutError:
                self.log_message("Some proxy stop operations timed out", LogLevel.WARNING)

    def update_keys(self):
        """Update WireGuard keys from entries"""
        if not self.main_window or not self.main_window.private_key_entry or not self.main_window.public_key_entry:
            return

        new_private_key = self.main_window.private_key_entry.get().strip()
        new_public_key = self.main_window.public_key_entry.get().strip()

        if new_private_key and new_public_key:
            self.state.set_keys(new_private_key, new_public_key)
            self.log_message("WireGuard keys updated", LogLevel.INFO)
            StateManager.save_state(self.state, self.settings)
        else:
            self.log_message("Both private and public keys must be provided", LogLevel.WARNING)
            messagebox.showwarning("Warning", "Please enter both public and private keys")

    def export_config(self):
        """Export selected proxy config"""
        try:
            if not self.main_window or not self.main_window.proxy_listbox:
                return

            selection = self.main_window.proxy_listbox.curselection()
            if not selection:
                self.log_message("No proxy selected for config export", LogLevel.WARNING)
                messagebox.showwarning(constants.EXPORT_CONFIG_WARNING_TITLE, constants.EXPORT_CONFIG_WARNING_MESSAGE)
                return

            index = selection[0]
            instance = self.state.get_proxy_instance(index)

            if not instance:
                return

            private_key, _ = self.state.get_keys()
            if not private_key:
                messagebox.showerror(constants.WIREGUARD_KEYS_NOT_CONFIGURED_TITLE, constants.WIREGUARD_KEYS_NOT_CONFIGURED_MESSAGE)
                return

            wg_config = ConfigurationManager.generate_wireguard_config(instance.server, private_key)
            wireproxy_config = ConfigurationManager.generate_wireproxy_config(wg_config, instance.port)

            filename = filedialog.asksaveasfilename(
                defaultextension=".conf",
                filetypes=[("Config files", "*.conf"), ("All files", "*.*")],
                initialfile=f"wireproxy_{instance.country}_{instance.port}.conf"
            )

            if filename:
                with open(filename, 'w') as f:
                    f.write(wireproxy_config)

                self.log_message(f"Config exported to {filename}", LogLevel.INFO)
                messagebox.showinfo(constants.EXPORT_CONFIG_SUCCESS_TITLE, constants.EXPORT_CONFIG_SUCCESS_MESSAGE.format(filename=filename))

        except Exception as e:
            self.log_message(f"Error exporting config: {str(e)}", LogLevel.ERROR)
            messagebox.showerror(constants.EXPORT_CONFIG_ERROR_TITLE, constants.EXPORT_CONFIG_ERROR_MESSAGE.format(error=str(e)))

    def show_config(self):
        """Show generated config in a popup"""
        try:
            if not self.main_window or not self.main_window.proxy_listbox:
                self.log_message("GUI not initialized properly for show_config", LogLevel.ERROR)
                return

            selection = self.main_window.proxy_listbox.curselection()
            if not selection:
                messagebox.showwarning(constants.SHOW_CONFIG_WARNING_TITLE, constants.SHOW_CONFIG_WARNING_MESSAGE)
                return

            index = selection[0]
            instance = self.state.get_proxy_instance(index)

            if not instance:
                self.log_message(f"No proxy instance found at index {index}", LogLevel.ERROR)
                return

            private_key, _ = self.state.get_keys()
            if not private_key:
                messagebox.showerror(constants.WIREGUARD_KEYS_NOT_CONFIGURED_TITLE, constants.WIREGUARD_KEYS_NOT_CONFIGURED_MESSAGE)
                return

            self.log_message(f"Generating config for proxy: {instance.server.name} on port {instance.port}", LogLevel.DEBUG)
            
            wg_config = ConfigurationManager.generate_wireguard_config(instance.server, private_key)
            wireproxy_config = ConfigurationManager.generate_wireproxy_config(wg_config, instance.port)

            # Create config display window with improved error handling
            try:
                config_window = tk.Toplevel(self.main_window.root)
                config_window.title(f"Config - {instance.server.name} ({instance.port})")
                config_window.geometry("700x500")
                config_window.transient(self.main_window.root)
                config_window.grab_set()

                # Center the window
                config_window.update_idletasks()
                x = (config_window.winfo_screenwidth() // 2) - (700 // 2)
                y = (config_window.winfo_screenheight() // 2) - (500 // 2)
                config_window.geometry(f"700x500+{x}+{y}")

                # Create frame for better layout
                main_frame = ttk.Frame(config_window, padding="10")
                main_frame.pack(fill="both", expand=True)

                # Title label
                title_label = ttk.Label(main_frame, text=f"Configuration for {instance.server.name}", 
                                      font=("Arial", 12, "bold"))
                title_label.pack(pady=(0, 10))

                # Text widget with scrollbar
                text_widget = scrolledtext.ScrolledText(main_frame, wrap=tk.WORD, 
                                                      font=("Consolas", 9))
                text_widget.pack(fill="both", expand=True, pady=(0, 10))
                text_widget.insert("1.0", wireproxy_config)
                text_widget.config(state="disabled")  # Make read-only

                # Button frame
                button_frame = ttk.Frame(main_frame)
                button_frame.pack(fill="x")

                # Copy to clipboard button
                def copy_to_clipboard():
                    try:
                        config_window.clipboard_clear()
                        config_window.clipboard_append(wireproxy_config)
                        self.log_message("Config copied to clipboard", LogLevel.INFO)
                    except Exception as copy_error:
                        self.log_message(f"Failed to copy to clipboard: {copy_error}", LogLevel.ERROR)

                ttk.Button(button_frame, text="Copy to Clipboard", 
                          command=copy_to_clipboard).pack(side="left", padx=(0, 10))
                ttk.Button(button_frame, text="Close", 
                          command=config_window.destroy).pack(side="left")

                self.log_message(f"Config window opened for {instance.server.name}", LogLevel.INFO)

            except Exception as window_error:
                self.log_message(f"Error creating config window: {window_error}", LogLevel.ERROR)
                # Fallback: show config in a simple message box
                messagebox.showinfo("Configuration", wireproxy_config[:1000] + ("..." if len(wireproxy_config) > 1000 else ""))

        except Exception as e:
            self.log_message(f"Error showing config: {str(e)}", LogLevel.ERROR)
            messagebox.showerror("Error", f"Failed to show configuration: {str(e)}")

    def clear_log(self):
        """Clear the log window"""
        if self.main_window and self.main_window.log_text:
            self.main_window.log_text.delete(1.0, tk.END)
            self.log_message("Log cleared", LogLevel.INFO)

    def save_log(self):
        """Save log to file"""
        try:
            if not self.main_window or not self.main_window.log_text:
                return

            filename = filedialog.asksaveasfilename(
                defaultextension=".log",
                filetypes=[("Log files", "*.log"), ("Text files", "*.txt"), ("All files", "*.*")],
                initialfile=f"wireproxy_log_{datetime.now().strftime('%Y%m%d_%H%M%S')}.log"
            )

            if filename:
                with open(filename, 'w') as f:
                    f.write(self.main_window.log_text.get(1.0, tk.END))

                file_size = os.path.getsize(filename)
                self.log_message(f"Log saved to {filename} ({file_size} bytes)", LogLevel.INFO)
                messagebox.showinfo(constants.SAVE_LOG_SUCCESS_TITLE, constants.SAVE_LOG_SUCCESS_MESSAGE.format(filename=filename))

        except Exception as e:
            self.log_message(f"Error saving log: {str(e)}", LogLevel.ERROR)
            messagebox.showerror(constants.SAVE_LOG_ERROR_TITLE, constants.SAVE_LOG_ERROR_MESSAGE.format(error=str(e)))

    def change_log_level(self):
        """Unified log level change method"""
        self.show_log_level_dialog(self.main_window.root if self.main_window else None)

    def show_log_level_dialog(self, parent):
        """Show log level selection dialog"""
        if not parent:
            return

        level_window = tk.Toplevel(parent)
        level_window.title("Log Level")
        level_window.geometry("300x250")
        level_window.transient(parent)
        level_window.grab_set()

        # Center the window
        level_window.update_idletasks()
        x = (level_window.winfo_screenwidth() // 2) - (300 // 2)
        y = (level_window.winfo_screenheight() // 2) - (250 // 2)
        level_window.geometry(f"300x250+{x}+{y}")

        ttk.Label(level_window, text="Select Log Level:", font=("Arial", 12)).pack(pady=10)

        level_var = tk.IntVar(value=self.settings.log_level.value)

        levels = [
            (LogLevel.DEBUG, "DEBUG - Show everything"),
            (LogLevel.INFO, "INFO - Normal operation"),
            (LogLevel.WARNING, "WARNING - Important messages only"),
            (LogLevel.ERROR, "ERROR - Errors only")
        ]

        for level, description in levels:
            ttk.Radiobutton(
                level_window,
                text=description,
                variable=level_var,
                value=level.value
            ).pack(anchor=tk.W, padx=20, pady=2)

        def apply_level():
            old_level = self.settings.log_level
            self.settings.log_level = LogLevel(level_var.get())

            level_names = {
                LogLevel.DEBUG: "DEBUG",
                LogLevel.INFO: "INFO",
                LogLevel.WARNING: "WARNING",
                LogLevel.ERROR: "ERROR"
            }

            new_level_name = level_names.get(self.settings.log_level, "UNKNOWN")

            # Update all UI labels
            if self.main_window and hasattr(self.main_window, 'log_level_label') and self.main_window.log_level_label:
                self.main_window.log_level_label.config(text=new_level_name)

            self.log_message(
                f"Log level changed from {level_names.get(old_level, 'UNKNOWN')} "
                f"to {new_level_name}",
                LogLevel.INFO
            )

            StateManager.save_settings(self.settings)
            level_window.destroy()

        # Buttons
        button_frame = ttk.Frame(level_window)
        button_frame.pack(pady=20)

        ttk.Button(button_frame, text="Cancel", command=level_window.destroy).pack(side=tk.LEFT, padx=5)
        ttk.Button(button_frame, text="Apply", command=apply_level).pack(side=tk.LEFT, padx=5)

    def show_preferences(self):
        """Show preferences window"""
        if self.main_window:
            self.main_window.show_preferences()

    def hide_to_tray(self):
        """Hide window to tray"""
        if self.tray_manager:
            self.tray_manager.hide_to_tray()

    def copy_proxy_address(self):
        """Copy the selected proxy address to the clipboard."""
        try:
            if not self.main_window or not self.main_window.proxy_listbox:
                return

            selection = self.main_window.proxy_listbox.curselection()
            if not selection:
                messagebox.showwarning("Warning", "Please select a proxy to copy its address.")
                return

            index = selection[0]
            instance = self.state.get_proxy_instance(index)

            if not instance:
                return

            proxy_address = f"127.0.0.1:{instance.port}"
            self.main_window.root.clipboard_clear()
            self.main_window.root.clipboard_append(proxy_address)
            self.log_message(f"Copied to clipboard: {proxy_address}", LogLevel.INFO)
            messagebox.showinfo("Copied", f"Proxy address {proxy_address} copied to clipboard.")

        except Exception as e:
            self.log_message(f"Error copying proxy address: {str(e)}", LogLevel.ERROR)
            messagebox.showerror("Error", f"Failed to copy proxy address: {str(e)}")

    def check_for_updates(self):
        """Check for new versions of the application on GitHub."""
        try:
            import requests
            api_url = f"https://api.github.com/repos/your-repo/releases/latest"
            response = requests.get(api_url, timeout=10)
            response.raise_for_status()
            latest_version = response.json()['tag_name']

            if latest_version > constants.APP_VERSION:
                messagebox.showinfo("Update Available", f"A new version ({latest_version}) is available!")
            else:
                messagebox.showinfo("No Updates", "You are using the latest version.")
        except Exception as e:
            messagebox.showerror("Error", f"Failed to check for updates: {str(e)}")

    def auto_restart_proxies(self, auto_restart_list: List[int]):
        """Auto-restart proxies from saved state with improved error handling"""
        if not auto_restart_list:
            self.log_message(constants.LOG_NO_PROXIES_TO_RESTART, LogLevel.INFO)
            return
        self.log_message(constants.LOG_STARTING_AUTO_RESTART.format(count=len(auto_restart_list)), LogLevel.INFO)
        self.thread_pool.submit(self._auto_restart_worker, auto_restart_list)

    def _auto_restart_worker(self, auto_restart_list: List[int]):
        try:
            self.log_message(constants.LOG_AUTO_RESTART_THREAD_STARTED, LogLevel.INFO)
            if not self._wait_for_servers():
                return

            self.log_message(constants.LOG_SERVERS_LOADED_AUTO_RESTART, LogLevel.INFO)
            successful_restarts, failed_restarts = self._restart_proxies(auto_restart_list)
            self.log_message(
                constants.LOG_AUTO_RESTART_COMPLETED.format(successful=successful_restarts, failed=failed_restarts),
                LogLevel.INFO
            )
        except Exception as e:
            self.log_message(constants.LOG_AUTO_RESTART_WORKER_ERROR.format(error=str(e)), LogLevel.ERROR)

    def _wait_for_servers(self, max_attempts=60, delay=1) -> bool:
        for _ in range(max_attempts):
            if self.shutdown_event.is_set():
                self.log_message(constants.LOG_SHUTDOWN_REQUESTED_AUTO_RESTART, LogLevel.INFO)
                return False
            if self.state.get_servers():
                return True
            time.sleep(delay)
        self.log_message(constants.LOG_SERVERS_NOT_LOADED_AUTO_RESTART, LogLevel.ERROR)
        return False

    def _restart_proxies(self, auto_restart_list: List[int]) -> tuple[int, int]:
        successful_restarts = 0
        failed_restarts = 0
        for i, index in enumerate(auto_restart_list):
            if self.shutdown_event.is_set():
                self.log_message(constants.LOG_SHUTDOWN_REQUESTED_STOP_AUTO_RESTART, LogLevel.INFO)
                break
            try:
                self.log_message(constants.LOG_AUTO_RESTARTING_PROXY.format(i=i + 1, total=len(auto_restart_list), index=index), LogLevel.INFO)
                if self.main_window and self.main_window.root:
                    self.main_window.root.after(0, lambda idx=index: self._start_proxy_by_index(idx))
                    successful_restarts += 1
                time.sleep(3)
            except Exception as e:
                failed_restarts += 1
                self.log_message(constants.LOG_FAILED_TO_SCHEDULE_AUTO_RESTART.format(index=index, error=str(e)), LogLevel.ERROR)
        return successful_restarts, failed_restarts

    def on_closing(self):
        """Handle application shutdown with proper cleanup"""
        self.log_message("Application shutting down...", LogLevel.INFO)

        # Signal shutdown to monitoring thread
        self.shutdown_event.set()

        # Save state before stopping proxies
        StateManager.save_state(self.state, self.settings)

        # Stop all proxies with timeout
        proxy_instances = self.state.get_proxy_instances()
        running_count = sum(1 for instance in proxy_instances if instance.status == ProxyStatus.RUNNING)

        if running_count > 0:
            self.log_message(f"Stopping {running_count} running proxies...", LogLevel.INFO)
            self.stop_all_proxies()

        # Wait for monitor thread to finish
        if self.monitor_thread and self.monitor_thread.is_alive():
            self.monitor_thread.join(timeout=5)
            if self.monitor_thread.is_alive():
                self.log_message("Monitor thread did not finish cleanly", LogLevel.WARNING)

        # Shutdown thread pool
        try:
            self.thread_pool.shutdown(wait=True, cancel_futures=True)
        except Exception as e:
            self.log_message(f"Error shutting down thread pool: {e}", LogLevel.WARNING)

        # Clean up temp files
        StateManager.cleanup_temp_files(self.state)

        self.log_message("Application shutdown complete", LogLevel.INFO)

        if self.main_window and self.main_window.root:
            self.main_window.root.destroy()

    def run_headless(self):
        """Run the application in headless mode."""
        self.log_message("Running in headless mode.", LogLevel.INFO)
        StateManager.cleanup_temp_files(self.state)
        self.start_monitoring()
        self.load_servers()
        # In headless mode, we can wait for servers to load before proceeding
        self._wait_for_servers()
        auto_restart_list = StateManager.load_state(self.state)
        if self.settings.auto_start_proxies and auto_restart_list:
            self.auto_restart_proxies(auto_restart_list)

        # Keep the main thread alive to allow background threads to run
        try:
            while not self.shutdown_event.is_set():
                time.sleep(1)
        except KeyboardInterrupt:
            self.log_message("Received keyboard interrupt, shutting down...", LogLevel.INFO)
        finally:
            self.on_closing()
            self._cleanup()

    def run(self):
        """Main application entry point with improved startup sequence"""
        try:
            self._initialize_app()
            self._run_main_loop()
        except KeyboardInterrupt:
            self.log_message("Received keyboard interrupt, shutting down...", LogLevel.INFO)
            self.on_closing()
        except Exception as e:
            self.log_message(f"Unexpected error in main loop: {str(e)}", LogLevel.ERROR)
            logger.exception("Unexpected error in main loop")
            raise
        finally:
            self._cleanup()

    def _initialize_app(self):
        StateManager.cleanup_temp_files(self.state)
        self.main_window = MainWindow(self)
        root = self.main_window.create_gui()
        
        # Initialize theme system
        if root:
            initialize_theme(root, self.settings.dark_mode)
            # Apply theme to all existing widgets
            self.main_window.apply_theme_to_widgets()
        
        self.tray_manager = TrayIconManager(self)
        self.tray_manager.create_tray_icon()
        self._log_startup_info()
        self.start_monitoring()
        self.load_servers()
        if self.main_window.root:
            self.main_window.root.after(3000, self._delayed_state_load)
            self.process_gui_messages()

    def _log_startup_info(self):
        if not self.settings.start_minimized:
            self.log_message("=" * 60, LogLevel.INFO)
            self.log_message(constants.LOG_APP_STARTED, LogLevel.INFO)
            self.log_message(constants.LOG_PYTHON_VERSION.format(version=sys.version), LogLevel.INFO)
            self.log_message(constants.LOG_PLATFORM.format(platform=os.name), LogLevel.INFO)
            self.log_message(constants.LOG_WORKING_DIR.format(directory=os.getcwd()), LogLevel.INFO)
            self.log_message("=" * 60, LogLevel.INFO)

    def _delayed_state_load(self):
        if self._wait_for_servers(max_attempts=1, delay=0):
            if not self.settings.start_minimized:
                self.log_message(constants.LOG_SERVERS_LOADED_NOW_LOADING_STATE, LogLevel.INFO)
            auto_restart_list = StateManager.load_state(self.state)
            if self.main_window:
                self.main_window.update_gui_with_loaded_keys()
            self.gui_queue.put_proxy_list_update()
            if self.settings.auto_start_proxies and auto_restart_list:
                self.auto_restart_proxies(auto_restart_list)
        else:
            if not self.settings.start_minimized:
                self.log_message(constants.LOG_SERVERS_NOT_LOADED_RETRY, LogLevel.WARNING)
            if self.main_window and self.main_window.root and not self.shutdown_event.is_set():
                self.main_window.root.after(2000, self._delayed_state_load)

    def _run_main_loop(self):
        if self.settings.start_minimized:
            if self.main_window and self.main_window.root:
                self.main_window.root.after(100, self.hide_to_tray)
            if self.tray_manager:
                self.tray_manager.start_tray_if_minimized()
        if self.main_window and self.main_window.root:
            self.main_window.root.mainloop()

    def _cleanup(self):
        try:
            self.thread_pool.shutdown(wait=False, cancel_futures=True)
        except (RuntimeError, OSError):
            pass