"""State management for the WireProxy SurfShark GUI application."""

import json
import os
import logging
import threading
import contextlib
from datetime import datetime
from typing import Dict, List, Optional, Any

from models import AppSettings, LogLevel, ProxyInstance, ProxyStatus, ProcessInfo
import constants

logger = logging.getLogger(__name__)


class ThreadSafeState:
    """Thread-safe state management"""

    def __init__(self):
        self._lock = threading.RLock()
        self._proxy_instances: List[ProxyInstance] = []
        self._running_processes: Dict[int, ProcessInfo] = {}
        self._servers: List[Dict[str, Any]] = []
        self._client_private_key = ""
        self._client_public_key = ""
        self._temp_files: List[str] = []  # Track all temp files for cleanup

    @contextlib.contextmanager
    def lock(self):
        with self._lock:
            yield

    def get_proxy_instances(self) -> List[ProxyInstance]:
        with self._lock:
            return self._proxy_instances.copy()

    def set_proxy_instances(self, instances: List[ProxyInstance]):
        with self._lock:
            self._proxy_instances = instances.copy()

    def add_proxy_instance(self, instance: ProxyInstance):
        with self._lock:
            self._proxy_instances.append(instance)

    def remove_proxy_instance(self, index: int) -> Optional[ProxyInstance]:
        with self._lock:
            if 0 <= index < len(self._proxy_instances):
                return self._proxy_instances.pop(index)
            return None

    def get_proxy_instance(self, index: int) -> Optional[ProxyInstance]:
        with self._lock:
            if 0 <= index < len(self._proxy_instances):
                return self._proxy_instances[index]
            return None

    def update_proxy_status(self, index: int, status: ProxyStatus):
        with self._lock:
            if 0 <= index < len(self._proxy_instances):
                self._proxy_instances[index].status = status

    def get_running_processes(self) -> Dict[int, ProcessInfo]:
        with self._lock:
            return self._running_processes.copy()

    def add_running_process(self, index: int, process_info: ProcessInfo):
        with self._lock:
            self._running_processes[index] = process_info

    def remove_running_process(self, index: int) -> Optional[ProcessInfo]:
        with self._lock:
            return self._running_processes.pop(index, None)

    def get_running_process(self, index: int) -> Optional[ProcessInfo]:
        with self._lock:
            return self._running_processes.get(index)

    def get_servers(self) -> List[Dict[str, Any]]:
        with self._lock:
            return self._servers.copy()

    def set_servers(self, servers: List[Dict[str, Any]]):
        with self._lock:
            self._servers = servers.copy()

    def get_keys(self) -> tuple[str, str]:
        with self._lock:
            return self._client_private_key, self._client_public_key

    def set_keys(self, private_key: str, public_key: str):
        with self._lock:
            self._client_private_key = private_key
            self._client_public_key = public_key

    def add_temp_file(self, filepath: str):
        with self._lock:
            self._temp_files.append(filepath)

    def get_temp_files(self) -> List[str]:
        with self._lock:
            return self._temp_files.copy()

    def clear_temp_files(self):
        with self._lock:
            self._temp_files.clear()


class StateManager:
    """Handles saving and loading application state"""

    @staticmethod
    def save_settings(settings: AppSettings):
        """Save application settings"""
        try:
            settings_dict = {
                'start_minimized': settings.start_minimized,
                'minimize_to_tray': settings.minimize_to_tray,
                'auto_start_proxies': settings.auto_start_proxies,
                'log_level': settings.log_level.value,
                'api_endpoint': settings.api_endpoint,
                'dark_mode': settings.dark_mode
            }

            with open(constants.SETTINGS_FILE, 'w') as f:
                json.dump(settings_dict, f, indent=2)

            logger.debug("Settings saved successfully")

        except Exception as e:
            logger.error(f"Error saving settings: {str(e)}")

    @staticmethod
    def load_settings() -> AppSettings:
        """Load application settings, create default file if it doesn't exist"""
        try:
            if os.path.exists(constants.SETTINGS_FILE):
                # Load existing settings
                with open(constants.SETTINGS_FILE, 'r') as f:
                    settings_dict = json.load(f)

                settings = AppSettings(
                    start_minimized=settings_dict.get('start_minimized', False),
                    minimize_to_tray=settings_dict.get('minimize_to_tray', True),
                    auto_start_proxies=settings_dict.get('auto_start_proxies', True),
                    log_level=LogLevel(settings_dict.get('log_level', LogLevel.DEBUG.value)),
                    api_endpoint=settings_dict.get('api_endpoint', constants.API_ENDPOINT),
                    dark_mode=settings_dict.get('dark_mode', False)
                )

                logger.debug("Settings loaded successfully from existing file")
                return settings
            else:
                # Create default settings
                logger.info("No settings file found, creating default settings file")
                default_settings = AppSettings()

                # Save the default settings to file
                StateManager.save_settings(default_settings)

                logger.info(f"Created default settings file: {constants.SETTINGS_FILE}")
                return default_settings

        except Exception as e:
            logger.error(f"Error loading settings: {str(e)}")
            logger.info("Using default settings due to error")

            # Try to create default settings file even if loading failed
            try:
                default_settings = AppSettings()
                StateManager.save_settings(default_settings)
                logger.info("Created default settings file after load error")
                return default_settings
            except Exception as save_error:
                logger.error(f"Could not save default settings: {str(save_error)}")
                return AppSettings()  # Return in-memory defaults as last resort

    @staticmethod
    def save_servers_cache(servers: List[Dict[str, Any]]):
        """Save servers to cache file"""
        try:
            cache_data = {
                'servers': servers,
                'timestamp': datetime.now().isoformat(),
                'version': '1.0'
            }
            with open(constants.CACHE_FILE, 'w', encoding='utf-8') as f:
                json.dump(cache_data, f, indent=2, default=str)
            logger.debug(f"Cached {len(servers)} servers")
        except Exception as e:
            logger.error(f"Error saving servers cache: {str(e)}")

    @staticmethod
    def load_servers_cache() -> Optional[List[Dict[str, Any]]]:
        """Load servers from cache file"""
        try:
            if not os.path.exists(constants.CACHE_FILE):
                return None

            with open(constants.CACHE_FILE, 'r', encoding='utf-8') as f:
                cache_data = json.load(f)

            # Check cache age (24 hours)
            cached_time = datetime.fromisoformat(cache_data['timestamp'])
            if (datetime.now() - cached_time).total_seconds() > 86400:  # 24 hours
                logger.debug("Server cache is stale, ignoring")
                return None

            servers = cache_data.get('servers', [])
            logger.info(f"Loaded {len(servers)} servers from cache")
            return servers

        except Exception as e:
            logger.error(f"Error loading servers cache: {str(e)}")
            return None

    @staticmethod
    def save_state(state: ThreadSafeState, settings: AppSettings):
        """Save complete application state"""
        try:
            proxy_instances = state.get_proxy_instances()
            running_processes = state.get_running_processes()
            private_key, public_key = state.get_keys()

            state_dict = {
                'client_keys': {
                    'private_key': private_key,
                    'public_key': public_key
                },
                'proxies': [],
                'settings': {
                    'last_port': 1080  # This would need to be passed in
                }
            }

            # Save proxy instances with auto-restart info
            for i, instance in enumerate(proxy_instances):
                process_info = running_processes.get(i)
                is_actually_running = (
                        instance.status == ProxyStatus.RUNNING and
                        process_info is not None and
                        process_info.process.poll() is None
                )

                proxy_data = {
                    'country': instance.country,
                    'location': instance.location,
                    'port': instance.port,
                    'status': instance.status.value,
                    'server': instance.server,
                    'connection_attempts': instance.connection_attempts,
                    'created_at': instance.created_at.isoformat(),
                    'auto_restart': is_actually_running
                }
                state_dict['proxies'].append(proxy_data)

            with open(constants.STATE_FILE, 'w', encoding='utf-8') as f:
                json.dump(state_dict, f, indent=2, default=str)

            logger.info(f"Saved complete state with {len(proxy_instances)} proxies")

        except Exception as e:
            logger.error(f"Error saving state: {str(e)}")

    @staticmethod
    def load_state(state: ThreadSafeState) -> List[int]:
        """Load application state and return list of proxy indices to auto-restart"""
        auto_restart_list = []

        try:
            if not os.path.exists(constants.STATE_FILE):
                logger.debug("No saved state file found")
                return auto_restart_list

            with open(constants.STATE_FILE, 'r', encoding='utf-8') as f:
                state_dict = json.load(f)

            # Restore keys
            if 'client_keys' in state_dict:
                private_key = state_dict['client_keys'].get('private_key', '')
                public_key = state_dict['client_keys'].get('public_key', '')
                state.set_keys(private_key, public_key)

            # Restore proxies
            proxy_instances = []
            for i, proxy_data in enumerate(state_dict.get('proxies', [])):
                instance = ProxyInstance(
                    id=i,
                    country=proxy_data['country'],
                    location=proxy_data['location'],
                    port=proxy_data['port'],
                    server=proxy_data['server'],
                    status=ProxyStatus.STOPPED,  # Always start as stopped
                    created_at=datetime.fromisoformat(proxy_data.get('created_at', datetime.now().isoformat())),
                    connection_attempts=proxy_data.get('connection_attempts', 0)
                )

                proxy_instances.append(instance)

                # Check for auto-restart
                if proxy_data.get('auto_restart', False):
                    auto_restart_list.append(i)
                    logger.info(f"Marked proxy on port {proxy_data['port']} for auto-restart")

            state.set_proxy_instances(proxy_instances)
            logger.info(f"Loaded state with {len(proxy_instances)} proxies")

        except Exception as e:
            logger.error(f"Error loading state: {str(e)}")

        return auto_restart_list

    @staticmethod
    def cleanup_temp_files(state: ThreadSafeState):
        """Clean up all tracked temporary files"""
        temp_files = state.get_temp_files()
        cleaned = 0
        for filepath in temp_files:
            try:
                if os.path.exists(filepath):
                    os.unlink(filepath)
                    cleaned += 1
            except OSError as e:
                logger.warning(f"Failed to clean temp file {filepath}: {e}")

        if cleaned > 0:
            logger.info(f"Cleaned up {cleaned} temporary files")

        state.clear_temp_files()