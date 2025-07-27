import tkinter as tk
from tkinter import ttk, messagebox, scrolledtext, filedialog
import requests
import json
import threading
import subprocess
import os
import tempfile
import time
import psutil
from datetime import datetime
import pystray
from PIL import Image, ImageDraw
import atexit
from tkinter import BooleanVar
import queue
import contextlib
from typing import Dict, List, Optional, Any
from dataclasses import dataclass, asdict
from enum import Enum
import logging
import sys
import concurrent.futures
import signal
from pathlib import Path
import shutil
import stat

# Configure proper logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(sys.stdout)
    ]
)
logger = logging.getLogger(__name__)


class LogLevel(Enum):
    DEBUG = 0
    INFO = 1
    WARNING = 2
    ERROR = 3


class ProxyStatus(Enum):
    STOPPED = "Stopped"
    STARTING = "Starting"
    RUNNING = "Running"
    ERROR = "Error"


@dataclass
class ProxyInstance:
    id: int
    country: str
    location: str
    port: int
    server: Dict[str, Any]
    status: ProxyStatus = ProxyStatus.STOPPED
    created_at: datetime = None
    start_time: Optional[datetime] = None
    connection_attempts: int = 0

    def __post_init__(self):
        if self.created_at is None:
            self.created_at = datetime.now()


@dataclass
class ProcessInfo:
    process: subprocess.Popen
    config_file: str
    start_time: float
    high_cpu_start: Optional[float] = None  # Add this line


@dataclass
class AppSettings:
    start_minimized: bool = False
    minimize_to_tray: bool = True
    auto_start_proxies: bool = True
    log_level: LogLevel = LogLevel.DEBUG
    api_endpoint: str = "https://api.surfshark.com/v4/server/clusters/generic"


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


class GUIMessageQueue:
    """Thread-safe message queue for GUI updates"""

    def __init__(self):
        self.queue = queue.Queue()

    def put_log_message(self, message: str, level: LogLevel):
        self.queue.put(('log', message, level))

    def put_status_update(self, message: str):
        self.queue.put(('status', message))

    def put_proxy_list_update(self):
        self.queue.put(('proxy_list_update',))

    def put_server_update(self, country_options: List[str]):
        self.queue.put(('server_update', country_options))

    def get_messages(self):
        messages = []
        try:
            while True:
                messages.append(self.queue.get_nowait())
        except queue.Empty:
            pass
        return messages


class NetworkManager:
    """Handles all network operations with proper error handling and retries"""

    @staticmethod
    def test_connectivity(api_endpoint: str, timeout: int = 5) -> bool:
        """Test network connectivity with timeout"""
        try:
            logger.debug("Testing network connectivity...")
            # Add more robust validation
            response = requests.get(api_endpoint, timeout=timeout, verify=True)
            if response.status_code == 200:
                # Validate JSON structure
                try:
                    data = response.json()
                    if isinstance(data, list) and len(data) > 0:
                        # Basic validation that it looks like server data
                        if 'country' in data[0] and 'location' in data[0]:
                            logger.info("Network connectivity test passed")
                            return True
                except (json.JSONDecodeError, KeyError, IndexError):
                    logger.warning("API returned invalid JSON structure")
                    return False
            else:
                logger.warning(f"Network test failed with status code: {response.status_code}")
                return False
        except requests.exceptions.SSLError as e:
            logger.error(f"SSL verification failed: {str(e)}")
            return False
        except requests.exceptions.RequestException as e:
            logger.error(f"Network connectivity test failed: {str(e)}")
            return False

    @staticmethod
    def fetch_servers_with_retry(api_endpoint: str, max_retries: int = 3, timeout: int = 10) -> Optional[
        List[Dict[str, Any]]]:
        """Fetch servers with retry logic and session reuse"""

        for attempt in range(max_retries):
            try:
                logger.debug(f"Fetching servers (attempt {attempt + 1}/{max_retries})")

                if not NetworkManager.test_connectivity(api_endpoint):
                    logger.error("Network connectivity test failed")
                    if attempt < max_retries - 1:
                        time.sleep(2 ** attempt)  # Exponential backoff
                        continue
                    return None

                with requests.Session() as session:
                    session.timeout = timeout

                    start_time = time.time()
                    response = session.get(api_endpoint, timeout=timeout, verify=True)
                    end_time = time.time()

                    logger.debug(f"API request completed in {end_time - start_time:.2f} seconds")
                    response.raise_for_status()

                    servers = response.json()

                    # Validate server data structure
                    if not isinstance(servers, list) or len(servers) == 0:
                        raise ValueError("Invalid server data structure")

                    # Check required fields in first server
                    required_fields = ['country', 'location', 'pubKey', 'connectionName']
                    if not all(field in servers[0] for field in required_fields):
                        raise ValueError("Server data missing required fields")

                    logger.info(f"Successfully fetched {len(servers)} servers")
                    return servers

            except (requests.exceptions.RequestException, ValueError, json.JSONDecodeError) as e:
                logger.error(f"Error fetching servers (attempt {attempt + 1}): {str(e)}")
                if attempt < max_retries - 1:
                    time.sleep(2 ** attempt)  # Exponential backoff
                    continue
                else:
                    logger.error("All retry attempts failed")
                    return None

        return None


class ProcessManager:
    """Manages wireproxy processes with proper lifecycle management"""

    @staticmethod
    @staticmethod
    def _download_wireproxy() -> bool:
        """Download wireproxy binary automatically from latest GitHub release"""
        try:
            import platform
            import tarfile
            import urllib.request
            import urllib.parse
            import hashlib

            logger.info("Getting latest wireproxy release info...")

            # Get latest release info from GitHub API
            api_url = "https://api.github.com/repos/whyvl/wireproxy/releases/latest"

            try:
                with urllib.request.urlopen(api_url, timeout=10) as response:
                    release_data = json.loads(response.read().decode())

                latest_version = release_data.get('tag_name', 'unknown')
                logger.info(f"Latest wireproxy version: {latest_version}")

            except Exception as e:
                logger.warning(f"Failed to get latest release info, using fallback: {e}")
                # Fallback to known release
                release_data = {
                    'assets': [],
                    'tag_name': 'v1.0.9'
                }

            # Detect platform and architecture
            system = platform.system().lower()
            machine = platform.machine().lower()

            # Map platform/arch to GitHub release filename
            if system == "windows":
                if "64" in machine or "amd64" in machine or "x86_64" in machine:
                    filename = "wireproxy_windows_amd64.tar.gz"
                else:
                    filename = "wireproxy_windows_386.tar.gz"
                exe_name = "wireproxy.exe"
            elif system == "linux":
                if "aarch64" in machine or "arm64" in machine:
                    filename = "wireproxy_linux_arm64.tar.gz"
                elif "arm" in machine:
                    filename = "wireproxy_linux_arm.tar.gz"
                elif "mips" in machine:
                    if "mipsle" in machine:
                        filename = "wireproxy_linux_mipsle.tar.gz"
                    else:
                        filename = "wireproxy_linux_mips.tar.gz"
                elif "riscv64" in machine:
                    filename = "wireproxy_linux_riscv64.tar.gz"
                elif "s390x" in machine:
                    filename = "wireproxy_linux_s390x.tar.gz"
                elif "386" in machine or "i386" in machine:
                    filename = "wireproxy_linux_386.tar.gz"
                else:  # Default to amd64
                    filename = "wireproxy_linux_amd64.tar.gz"
                exe_name = "wireproxy"
            elif system == "darwin":  # macOS
                if "arm64" in machine or "aarch64" in machine:
                    filename = "wireproxy_darwin_arm64.tar.gz"
                else:
                    filename = "wireproxy_darwin_amd64.tar.gz"
                exe_name = "wireproxy"
            else:
                logger.error(f"Unsupported platform: {system}")
                return False

            logger.info(f"Detected platform: {system} {machine}, using: {filename}")

            # Find download URL from assets
            download_url = None
            if release_data.get('assets'):
                for asset in release_data['assets']:
                    if asset['name'] == filename:
                        download_url = asset['browser_download_url']
                        break

            # Fallback to constructed URL if not found in assets
            if not download_url:
                version = release_data.get('tag_name', 'v1.0.9')
                download_url = f"https://github.com/whyvl/wireproxy/releases/download/{version}/{filename}"

            logger.debug(f"Download URL: {download_url}")

            try:
                # Download the file
                logger.info("Downloading wireproxy...")
                tar_path = f"{filename}"
                urllib.request.urlretrieve(download_url, tar_path)

                # Verify file is not corrupted (basic check)
                try:
                    with open(tar_path, 'rb') as f:
                        file_hash = hashlib.sha256(f.read()).hexdigest()
                    logger.debug(f"Downloaded file hash: {file_hash}")

                    # Basic size check
                    if os.path.getsize(tar_path) < 1024:  # Less than 1KB is suspicious
                        raise Exception("Downloaded file is too small, possibly corrupted")

                except Exception as e:
                    logger.error(f"Download verification failed: {e}")
                    os.unlink(tar_path)
                    return False

                logger.info("Extracting wireproxy...")

                # Extract the tar.gz file
                with tarfile.open(tar_path, 'r:gz') as tar:
                    # Extract wireproxy executable
                    for member in tar.getmembers():
                        if member.name.endswith(exe_name) and member.isfile():
                            member.name = exe_name  # Rename to just the executable name
                            tar.extract(member, path='.')
                            break
                    else:
                        raise Exception(f"wireproxy executable not found in {filename}")

                # Make executable on Unix systems
                if os.name != 'nt':
                    os.chmod(exe_name, 0o755)

                # Clean up tar file
                os.unlink(tar_path)

                # Verify the download
                if os.path.isfile(exe_name) and os.access(exe_name, os.X_OK):
                    logger.info(f"Successfully downloaded wireproxy to {os.path.abspath(exe_name)}")
                    messagebox.showinfo(
                        "Download Complete",
                        f"wireproxy downloaded successfully!\n\n"
                        f"Location: {os.path.abspath(exe_name)}"
                    )
                    return True
                else:
                    raise Exception("Downloaded file is not executable")

            except Exception as e:
                logger.error(f"Download/extraction failed: {e}")
                return False

        except Exception as e:
            logger.error(f"Error downloading wireproxy: {str(e)}")
            return False
    @staticmethod
    def find_wireproxy_executable() -> Optional[str]:
        """Find wireproxy executable in PATH with better validation and Linux support"""
        # Check using shutil.which first (most reliable)
        wireproxy_path = shutil.which("wireproxy")
        if wireproxy_path:
            logger.debug(f"Found wireproxy using shutil.which: {wireproxy_path}")
            return wireproxy_path

        # Manual PATH search for edge cases
        for path in os.environ.get("PATH", "").split(os.pathsep):
            for exe_name in ["wireproxy", "wireproxy.exe"]:
                potential_path = os.path.join(path, exe_name)
                if os.path.isfile(potential_path) and os.access(potential_path, os.X_OK):
                    logger.debug(f"Found wireproxy in PATH: {potential_path}")
                    return potential_path

        # Check current directory
        for exe_name in ["wireproxy", "wireproxy.exe"]:
            if os.path.isfile(exe_name) and os.access(exe_name, os.X_OK):
                logger.debug(f"Found wireproxy in current directory: {exe_name}")
                return os.path.abspath(exe_name)

        # Check common Linux installation paths
        if os.name != 'nt':
            common_paths = [
                "/usr/local/bin/wireproxy",
                "/usr/bin/wireproxy",
                "/opt/wireproxy/wireproxy",
                os.path.expanduser("~/.local/bin/wireproxy"),
                "/snap/bin/wireproxy"  # Snap package
            ]

            for path in common_paths:
                if os.path.isfile(path) and os.access(path, os.X_OK):
                    logger.debug(f"Found wireproxy in common path: {path}")
                    return path

        return None

    @staticmethod
    def start_wireproxy_process(config_content: str, state: ThreadSafeState) -> Optional[ProcessInfo]:
        """Start a wireproxy process with proper error handling and Linux compatibility"""
        config_file = None
        try:
            # Find executable
            wireproxy_path = ProcessManager.find_wireproxy_executable()
            if not wireproxy_path:
                logger.error("wireproxy executable not found")

                # Check if GUI is available before showing messageboxes
                try:
                    if not tk._default_root:
                        logger.error("wireproxy executable not found and no GUI available")
                        return None
                except:
                    logger.error("wireproxy executable not found and no GUI available")
                    return None

                # Ask user if they want to auto-download
                download_choice = messagebox.askyesnocancel(
                    "Missing Dependency - wireproxy",
                    "wireproxy executable not found.\n\n"
                    "Would you like to automatically download the latest version from GitHub?\n\n"
                    "• Yes: Download automatically\n"
                    "• No: Continue without wireproxy (proxy starting will fail)\n"
                    "• Cancel: Exit application and download manually"
                )

                if download_choice is True:  # Yes - auto download
                    logger.info("User chose to auto-download wireproxy")
                    if ProcessManager._download_wireproxy():
                        logger.info("wireproxy downloaded successfully")
                        # Try to find wireproxy again after download
                        wireproxy_path = ProcessManager.find_wireproxy_executable()
                    else:
                        logger.error("Failed to download wireproxy")
                        messagebox.showerror(
                            "Download Failed",
                            "Failed to download wireproxy automatically.\n\n"
                            "Please download manually from:\n"
                            "https://github.com/whyvl/wireproxy/releases/latest\n\n"
                            "The application will continue but proxy starting will fail."
                        )
                        return None
                elif download_choice is False:  # No - continue without
                    logger.warning("User chose to continue without wireproxy")
                    messagebox.showwarning(
                        "No wireproxy",
                        "Continuing without wireproxy.\n\n"
                        "Proxy starting will fail until wireproxy is installed.\n\n"
                        "Download from: https://github.com/whyvl/wireproxy/releases/latest"
                    )
                    return None
                else:  # Cancel - exit application
                    logger.info("User chose to exit and download manually")
                    messagebox.showinfo(
                        "Manual Download Required",
                        "Please download wireproxy manually from:\n"
                        "https://github.com/whyvl/wireproxy/releases/latest\n\n"
                        "Choose the appropriate file for your system:\n"
                        "• Windows: wireproxy_windows_amd64.tar.gz\n"
                        "• Linux 64-bit: wireproxy_linux_amd64.tar.gz\n"
                        "• Linux ARM64: wireproxy_linux_arm64.tar.gz\n"
                        "• macOS: wireproxy_darwin_amd64.tar.gz or wireproxy_darwin_arm64.tar.gz\n\n"
                        "Extract and place in PATH or same directory as this application."
                    )
                    return None

            if not wireproxy_path:
                logger.error("wireproxy executable not found after download attempt")
                return None

            logger.info(f"Found wireproxy at: {wireproxy_path}")

            # Create temporary config file with proper permissions
            with tempfile.NamedTemporaryFile(mode='w', suffix='.conf', delete=False) as f:
                f.write(config_content)
                config_file = f.name
                state.add_temp_file(config_file)

            # Set proper permissions on Linux (readable by owner only for security)
            if os.name != 'nt':
                os.chmod(config_file, stat.S_IRUSR | stat.S_IWUSR)

            # Start process with platform-specific settings
            cmd = [wireproxy_path, '-c', config_file]

            if os.name == 'nt':
                # Windows-specific process creation
                process = subprocess.Popen(
                    cmd,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    creationflags=subprocess.CREATE_NEW_PROCESS_GROUP
                )
            else:
                # Linux/Unix-specific process creation
                process = subprocess.Popen(
                    cmd,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    start_new_session=True,  # Linux equivalent of CREATE_NEW_PROCESS_GROUP
                    preexec_fn=os.setsid if hasattr(os, 'setsid') and os.name != 'nt' else None
                )

            # Wait a moment and check if process started successfully
            time.sleep(0.5)

            if process.poll() is not None:
                # Process died immediately
                logger.error(f"Wireproxy process failed to start (exit code: {process.returncode})")
                return None

            process_info = ProcessInfo(
                process=process,
                config_file=config_file,
                start_time=time.time()
            )

            logger.info(f"Successfully started wireproxy process (PID: {process.pid})")
            return process_info

        except Exception as e:
            logger.error(f"Error starting wireproxy process: {str(e)}")
            # Clean up config file if process failed to start
            if config_file and os.path.exists(config_file):
                try:
                    os.unlink(config_file)
                except OSError:
                    pass
            return None

    @staticmethod
    def stop_process_gracefully(process_info: ProcessInfo, timeout: int = 5) -> bool:
        """Stop a process gracefully with timeout, returns success status"""
        try:
            process = process_info.process

            if os.name == 'nt':
                # Windows: use terminate
                process.terminate()
            else:
                # Linux/Unix: try SIGTERM first, then SIGKILL
                try:
                    # Send SIGTERM to the process group
                    os.killpg(os.getpgid(process.pid), signal.SIGTERM)
                except (ProcessLookupError, OSError):
                    # Process already dead or not a process group leader
                    try:
                        os.kill(process.pid, signal.SIGTERM)
                    except ProcessLookupError:
                        return True  # Process already dead

            try:
                process.wait(timeout=timeout)
                logger.info(f"Process {process.pid} terminated gracefully")
            except subprocess.TimeoutExpired:
                # Force kill if timeout exceeded
                logger.warning(f"Process {process.pid} didn't terminate gracefully, forcing kill")
                if os.name == 'nt':
                    process.kill()
                else:
                    try:
                        # Send SIGKILL to process group
                        os.killpg(os.getpgid(process.pid), signal.SIGKILL)
                    except (ProcessLookupError, OSError):
                        try:
                            os.kill(process.pid, signal.SIGKILL)
                        except ProcessLookupError:
                            pass
                process.wait()

            return True

        except Exception as e:
            logger.error(f"Error stopping process: {str(e)}")
            return False
        finally:
            # Always clean up config file
            try:
                if os.path.exists(process_info.config_file):
                    os.unlink(process_info.config_file)
                    logger.debug(f"Cleaned up config file: {process_info.config_file}")
            except OSError as e:
                logger.warning(f"Failed to clean up config file: {e}")


class ConfigurationManager:
    """Handles WireGuard and wireproxy configuration generation"""

    @staticmethod
    def generate_wireguard_config(server: Dict[str, Any], private_key: str) -> str:
        """Generate WireGuard configuration"""
        server_pub_key = server['pubKey']
        server_host = server['connectionName']
        endpoint = f"{server_host}:51820"
        server_location = f"{server['country']} - {server['location']}"

        config = f"""# Surfshark WireGuard Config for {server_location}
[Interface]
PrivateKey = {private_key}
Address = 10.14.0.2/16
DNS = 162.252.172.57, 149.154.159.92

[Peer]
PublicKey = {server_pub_key}
Endpoint = {endpoint}
AllowedIPs = 0.0.0.0/0, ::/0
PersistentKeepalive = 25
"""
        return config.strip()

    @staticmethod
    def generate_wireproxy_config(wg_config: str, socks_port: int) -> str:
        """Generate wireproxy configuration"""
        wireproxy_config = f"""{wg_config}

[Socks5]
BindAddress = 127.0.0.1:{socks_port}
"""
        return wireproxy_config


class StateManager:
    """Handles saving and loading application state"""

    SETTINGS_FILE = 'wireproxy_settings.json'
    STATE_FILE = 'wireproxy_state.json'
    CACHE_FILE = 'wireproxy_servers_cache.json'

    @staticmethod
    def save_settings(settings: AppSettings):
        """Save application settings"""
        try:
            settings_dict = {
                'start_minimized': settings.start_minimized,
                'minimize_to_tray': settings.minimize_to_tray,
                'auto_start_proxies': settings.auto_start_proxies,
                'log_level': settings.log_level.value,
                'api_endpoint': settings.api_endpoint
            }

            with open(StateManager.SETTINGS_FILE, 'w') as f:
                json.dump(settings_dict, f, indent=2)

            logger.debug("Settings saved successfully")

        except Exception as e:
            logger.error(f"Error saving settings: {str(e)}")

    @staticmethod
    def load_settings() -> AppSettings:
        """Load application settings, create default file if it doesn't exist"""
        try:
            if os.path.exists(StateManager.SETTINGS_FILE):
                # Load existing settings
                with open(StateManager.SETTINGS_FILE, 'r') as f:
                    settings_dict = json.load(f)

                settings = AppSettings(
                    start_minimized=settings_dict.get('start_minimized', False),
                    minimize_to_tray=settings_dict.get('minimize_to_tray', True),
                    auto_start_proxies=settings_dict.get('auto_start_proxies', True),
                    log_level=LogLevel(settings_dict.get('log_level', LogLevel.DEBUG.value)),
                    api_endpoint=settings_dict.get('api_endpoint',
                                                   "https://api.surfshark.com/v4/server/clusters/generic")
                )

                logger.debug("Settings loaded successfully from existing file")
                return settings
            else:
                # Create default settings
                logger.info("No settings file found, creating default settings file")
                default_settings = AppSettings()

                # Save the default settings to file
                StateManager.save_settings(default_settings)

                logger.info(f"Created default settings file: {StateManager.SETTINGS_FILE}")
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
            with open(StateManager.CACHE_FILE, 'w', encoding='utf-8') as f:
                json.dump(cache_data, f, indent=2, default=str)
            logger.debug(f"Cached {len(servers)} servers")
        except Exception as e:
            logger.error(f"Error saving servers cache: {str(e)}")

    @staticmethod
    def load_servers_cache() -> Optional[List[Dict[str, Any]]]:
        """Load servers from cache file"""
        try:
            if not os.path.exists(StateManager.CACHE_FILE):
                return None

            with open(StateManager.CACHE_FILE, 'r', encoding='utf-8') as f:
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

            with open(StateManager.STATE_FILE, 'w', encoding='utf-8') as f:
                json.dump(state_dict, f, indent=2, default=str)

            logger.info(f"Saved complete state with {len(proxy_instances)} proxies")

        except Exception as e:
            logger.error(f"Error saving state: {str(e)}")

    @staticmethod
    def load_state(state: ThreadSafeState) -> List[int]:
        """Load application state and return list of proxy indices to auto-restart"""
        auto_restart_list = []

        try:
            if not os.path.exists(StateManager.STATE_FILE):
                logger.debug("No saved state file found")
                return auto_restart_list

            with open(StateManager.STATE_FILE, 'r', encoding='utf-8') as f:
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


class ServerManager:
    """Manages server data and selection logic"""

    @staticmethod
    def process_servers(servers: List[Dict[str, Any]]) -> List[str]:
        """Process server data into dropdown options"""
        countries = {}
        for server in servers:
            country = server['country']
            location = server['location']

            if country not in countries:
                countries[country] = set()

            countries[country].add(location)

        # Create dropdown options
        country_options = []
        for country in sorted(countries.keys()):
            locations = sorted(countries[country])

            if len(locations) == 1:
                country_options.append(country)
            else:
                country_options.append(country)
                for location in locations:
                    country_options.append(f"{country} - {location}")

        return country_options

    @staticmethod
    def get_servers_by_selection(servers: List[Dict[str, Any]], selection: str) -> List[Dict[str, Any]]:
        """Get servers based on country or country-city selection"""
        if " - " in selection:
            # Specific city selected
            parts = selection.split(" - ", 1)
            if len(parts) == 2:
                country, location = parts

                # Try exact match first
                country_servers = [
                    server for server in servers
                    if server['country'] == country and server['location'] == location
                ]

                # Fallback to fuzzy matching if needed
                if not country_servers:
                    location_clean = location.strip().lower()
                    country_servers = [
                        server for server in servers
                        if (server['country'] == country and
                            server['location'].strip().lower() == location_clean)
                    ]

                return country_servers
        else:
            # Whole country selected
            return [server for server in servers if server['country'] == selection]

        return []

    @staticmethod
    def select_best_server(servers: List[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
        """Select the best server based on load"""
        if not servers:
            return None

        return min(servers, key=lambda x: x.get('load', 100))


class WireproxyManager:
    """Main application class that coordinates all components"""

    def __init__(self):
        self.state = ThreadSafeState()
        self.gui_queue = GUIMessageQueue()
        self.settings = StateManager.load_settings()

        # GUI elements (will be set during GUI creation)
        self.root = None
        self.country_var = None
        self.port_var = None
        self.proxy_listbox = None
        self.log_text = None
        self.status_label = None
        self.private_key_entry = None
        self.public_key_entry = None
        self.country_combo = None
        self.tray_icon = None
        self.log_level_label = None

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
            self._update_proxy_list_display()
            if self.root:
                self.root.update_idletasks()
        except Exception as e:
            logger.error(f"Force GUI update failed: {e}")

    def process_gui_messages(self):
        """Process messages with better error handling"""
        try:
            messages = self.gui_queue.get_messages()

            for message in messages:
                try:
                    if message[0] == 'log':
                        self._update_log_display(message[1], message[2])
                    elif message[0] == 'status':
                        self._update_status_display(message[1])
                    elif message[0] == 'proxy_list_update':
                        self._update_proxy_list_display()
                    elif message[0] == 'server_update':
                        self._update_server_dropdown(message[1])
                except Exception as e:
                    logger.error(f"Error processing message {message[0]}: {e}")

            # Controlled force update every 10 seconds (reduced frequency)
            current_time = time.time()
            if current_time - self._last_force_update > 10:
                proxy_instances = self.state.get_proxy_instances()
                if len(proxy_instances) <= 50:  # Only for reasonable number of proxies
                    self._update_proxy_list_display()
                self._last_force_update = current_time

            # Schedule next update
            if self.root:
                self.root.after(100, self.process_gui_messages)

        except Exception as e:
            logger.error(f"Error processing GUI messages: {e}")
            # Ensure we keep trying even if queue fails
            if self.root:
                self.root.after(500, self.process_gui_messages)

    def _update_log_display(self, message: str, level: LogLevel):
        """Update log display (called from main thread only)"""
        if not self.log_text or level.value < self.settings.log_level.value:
            return

        timestamp = datetime.now().strftime("%H:%M:%S.%f")[:-3]

        level_colors = {
            LogLevel.DEBUG: "#808080",
            LogLevel.INFO: "#000000",
            LogLevel.WARNING: "#FFA500",
            LogLevel.ERROR: "#FF0000"
        }

        level_names = {
            LogLevel.DEBUG: "DEBUG",
            LogLevel.INFO: "INFO",
            LogLevel.WARNING: "WARN",
            LogLevel.ERROR: "ERROR"
        }

        level_name = level_names.get(level, "INFO")
        color = level_colors.get(level, "#000000")

        self.log_text.tag_configure(f"level_{level.value}", foreground=color)
        log_entry = f"[{timestamp}] [{level_name:5}] {message}\n"
        self.log_text.insert(tk.END, log_entry, f"level_{level.value}")
        self.log_text.see(tk.END)

    def _update_status_display(self, message: str):
        """Update status display (called from main thread only)"""
        if self.status_label:
            self.status_label.config(text=f"Status: {message}")

    def _update_proxy_list_display(self):
        """Update proxy list with fallback safety and diff-based updates"""
        if not self.proxy_listbox:
            return

        try:
            # Save current selection
            current_selection = self.proxy_listbox.curselection()
            current_size = self.proxy_listbox.size()

            proxy_instances = self.state.get_proxy_instances()
            running_processes = self.state.get_running_processes()

            # Only update if size changed or forced
            if current_size != len(proxy_instances):
                self.proxy_listbox.delete(0, tk.END)
                need_full_update = True
            else:
                need_full_update = False

            for i, instance in enumerate(proxy_instances):
                # Check actual process status with better error handling
                actual_status = instance.status
                process_info = running_processes.get(i)

                if (instance.status == ProxyStatus.RUNNING and process_info):
                    try:
                        if process_info.process.poll() is not None:
                            actual_status = ProxyStatus.STOPPED
                            self.state.update_proxy_status(i, ProxyStatus.STOPPED)
                            self.state.remove_running_process(i)
                    except Exception as e:
                        logger.error(f"Error checking process status: {e}")
                        actual_status = ProxyStatus.ERROR

                # Create display text
                status_icons = {
                    ProxyStatus.RUNNING: "[RUNNING]",
                    ProxyStatus.STARTING: "[STARTING]",
                    ProxyStatus.ERROR: "[ERROR]",
                    ProxyStatus.STOPPED: "[STOPPED]"
                }

                status_icon = status_icons.get(actual_status, "[UNKNOWN]")
                load = instance.server.get('load', 'unknown')

                # Calculate runtime
                runtime = ""
                if instance.start_time and actual_status == ProxyStatus.RUNNING:
                    try:
                        delta = datetime.now() - instance.start_time
                        hours, remainder = divmod(int(delta.total_seconds()), 3600)
                        minutes, seconds = divmod(remainder, 60)
                        if hours > 0:
                            runtime = f" [{hours:02d}:{minutes:02d}:{seconds:02d}]"
                        else:
                            runtime = f" [{minutes:02d}:{seconds:02d}]"
                    except Exception:
                        runtime = " [??:??]"

                text = (f"{status_icon} Port {instance.port} - {instance.country} "
                        f"({instance.location}) - Load: {load}%{runtime}")

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

                # Add color coding
                colors = {
                    ProxyStatus.RUNNING: 'green',
                    ProxyStatus.ERROR: 'red',
                    ProxyStatus.STARTING: 'orange',
                    ProxyStatus.STOPPED: 'gray'
                }

                try:
                    self.proxy_listbox.itemconfig(i, {'fg': colors.get(actual_status, 'black')})
                except Exception:
                    pass  # Color setting is non-critical

            # Restore selection
            if current_selection:
                for index in current_selection:
                    if index < self.proxy_listbox.size():
                        try:
                            self.proxy_listbox.selection_set(index)
                        except Exception:
                            pass

        except Exception as e:
            logger.error(f"Error updating proxy list display: {e}")

    def _update_server_dropdown(self, country_options: List[str]):
        """Update server dropdown (called from main thread only)"""
        if self.country_combo and self.country_var:
            self.country_var.set('')
            self.country_combo['values'] = country_options

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
                proxy_instances = self.state.get_proxy_instances()
                running_processes = self.state.get_running_processes()

                for i, instance in enumerate(proxy_instances):
                    if (instance.status == ProxyStatus.RUNNING and
                            i in running_processes):

                        process_info = running_processes[i]

                        if process_info.process.poll() is not None:
                            self.log_message(
                                f"Process for port {instance.port} has died unexpectedly",
                                LogLevel.ERROR
                            )

                            self.state.update_proxy_status(i, ProxyStatus.STOPPED)
                            removed_process = self.state.remove_running_process(i)

                            if removed_process:
                                try:
                                    os.unlink(removed_process.config_file)
                                except OSError:
                                    pass

                            self.gui_queue.put_proxy_list_update()

                        else:
                            # Monitor resource usage with limits
                            try:
                                ps_process = psutil.Process(process_info.process.pid)
                                cpu_percent = ps_process.cpu_percent()
                                memory_mb = ps_process.memory_info().rss / 1024 / 1024

                                # Kill process if using too many resources
                                if cpu_percent > 90:  # 90% CPU for 30 seconds
                                    if process_info.high_cpu_start is None:  # Changed from hasattr
                                        process_info.high_cpu_start = time.time()
                                    elif time.time() - process_info.high_cpu_start > 30:
                                        self.log_message(
                                            f"Killing process on port {instance.port} due to high CPU usage",
                                            LogLevel.WARNING
                                        )
                                        ProcessManager.stop_process_gracefully(process_info, timeout=2)
                                        self.state.update_proxy_status(i, ProxyStatus.ERROR)
                                        self.state.remove_running_process(i)
                                        self.gui_queue.put_proxy_list_update()
                                else:
                                    # Reset high CPU timer
                                    process_info.high_cpu_start = None  # Changed from delattr

                                if cpu_percent > 1.0 or memory_mb > 50:  # Only log significant usage
                                    self.log_message(
                                        f"Port {instance.port}: CPU: {cpu_percent:.1f}%, "
                                        f"Memory: {memory_mb:.1f}MB",
                                        LogLevel.DEBUG
                                    )
                            except (psutil.NoSuchProcess, psutil.AccessDenied, AttributeError):
                                pass

                # Check every 5 seconds
                self.shutdown_event.wait(5)

            except Exception as e:
                self.log_message(f"Error in process monitor: {str(e)}", LogLevel.ERROR)
                self.shutdown_event.wait(10)  # Wait longer on error

    def load_servers(self):
        """Load servers from API with caching fallback"""

        def fetch_servers():
            try:
                self.update_status("Loading servers...")
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
                        self.update_status("Error loading servers")
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

                self.update_status(f"Ready - {total_countries} countries, {total_locations} locations")
                self.gui_queue.put_server_update(country_options)

            except Exception as e:
                self.log_message(f"Error loading servers: {str(e)}", LogLevel.ERROR)
                self.update_status("Error loading servers")

        # Use thread pool for better management
        self.thread_pool.submit(fetch_servers)

    def add_proxy(self):
        """Add a new SOCKS5 proxy with comprehensive validation"""
        try:
            if not self.country_var or not self.port_var:
                self.log_message("GUI not properly initialized", LogLevel.ERROR)
                return

            country = self.country_var.get()
            port = self.port_var.get()

            self.log_message(f"Attempting to add proxy: Country={country}, Port={port}", LogLevel.DEBUG)

            # Validation
            if not country:
                self.log_message("No country selected", LogLevel.WARNING)
                messagebox.showerror("Error", "Please select a country")
                return

            if not port or port < 1024 or port > 65535:
                self.log_message(f"Invalid port number: {port}", LogLevel.WARNING)
                messagebox.showerror("Error", "Please enter a valid port (1024-65535)")
                return

            # Check for port conflicts
            proxy_instances = self.state.get_proxy_instances()
            for instance in proxy_instances:
                if instance.port == port:
                    self.log_message(f"Port {port} already in use", LogLevel.WARNING)
                    messagebox.showerror("Error", f"Port {port} is already in use")
                    return

            # Check if port is available on system
            try:
                import socket
                with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                    s.bind(('127.0.0.1', port))
                self.log_message(f"Port {port} is available", LogLevel.DEBUG)
            except OSError:
                self.log_message(f"Port {port} is in use by another application", LogLevel.WARNING)
                messagebox.showerror("Error", f"Port {port} is already in use by another application")
                return

            # Get servers for selection
            servers = self.state.get_servers()
            if not servers:
                self.log_message("No servers loaded", LogLevel.ERROR)
                messagebox.showerror("Error", "Servers not loaded. Please wait or reload servers.")
                return

            country_servers = ServerManager.get_servers_by_selection(servers, country)
            if not country_servers:
                self.log_message(f"No servers found for {country}", LogLevel.ERROR)
                messagebox.showerror("Error", f"No servers found for {country}")
                return

            chosen_server = ServerManager.select_best_server(country_servers)
            if not chosen_server:
                self.log_message(f"Could not select server for {country}", LogLevel.ERROR)
                messagebox.showerror("Error", f"Could not select server for {country}")
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
            self.port_var.set(port + 1)

            # Save state
            StateManager.save_state(self.state, self.settings)

        except Exception as e:
            self.log_message(f"Error adding proxy: {str(e)}", LogLevel.ERROR)
            messagebox.showerror("Error", f"Failed to add proxy: {str(e)}")

    def remove_proxy(self):
        """Remove selected proxy with proper cleanup"""
        try:
            if not self.proxy_listbox:
                return

            selection = self.proxy_listbox.curselection()
            if not selection:
                self.log_message("No proxy selected for removal", LogLevel.WARNING)
                messagebox.showwarning("Warning", "Please select a proxy to remove")
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
            messagebox.showerror("Error", f"Failed to remove proxy: {str(e)}")

    def start_proxy(self):
        """Start selected proxy with comprehensive error handling"""
        try:
            if not self.proxy_listbox:
                return

            selection = self.proxy_listbox.curselection()
            if not selection:
                self.log_message("No proxy selected for start operation", LogLevel.WARNING)
                messagebox.showwarning("Warning", "Please select a proxy to start")
                return

            index = selection[0]
            self._start_proxy_by_index(index)

        except Exception as e:
            self.log_message(f"Error starting proxy: {str(e)}", LogLevel.ERROR)
            messagebox.showerror("Error", f"Failed to start proxy: {str(e)}")

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
            messagebox.showerror("Error", "Please configure WireGuard keys first")
            return

        # Update status immediately
        self.state.update_proxy_status(index, ProxyStatus.STARTING)
        instance.connection_attempts += 1

        # Force immediate GUI update
        self._update_proxy_list_display()

        try:
            # Generate configurations
            wg_config = ConfigurationManager.generate_wireguard_config(instance.server, private_key)
            wireproxy_config = ConfigurationManager.generate_wireproxy_config(wg_config, instance.port)

            # Start process
            process_info = ProcessManager.start_wireproxy_process(wireproxy_config, self.state)

            if not process_info:
                self.state.update_proxy_status(index, ProxyStatus.ERROR)
                self._update_proxy_list_display()
                return

            # Store process info and update status
            self.state.add_running_process(index, process_info)
            self.state.update_proxy_status(index, ProxyStatus.RUNNING)
            instance.start_time = datetime.now()

            # Force GUI update
            self._update_proxy_list_display()

            # Save state
            StateManager.save_state(self.state, self.settings)

            self.log_message(f"Successfully started proxy on port {instance.port}", LogLevel.INFO)

            # Test connection in background
            self.thread_pool.submit(self._test_proxy_connection, instance.port)

        except Exception as e:
            self.state.update_proxy_status(index, ProxyStatus.ERROR)
            self._update_proxy_list_display()
            self.log_message(f"Error starting proxy: {str(e)}", LogLevel.ERROR)

    def _test_proxy_connection(self, port: int):
        """Test proxy connection (runs in background)"""
        time.sleep(2)  # Wait for proxy to be ready
        try:
            import socket
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
            if not self.proxy_listbox:
                return

            selection = self.proxy_listbox.curselection()
            if not selection:
                self.log_message("No proxy selected for stop operation", LogLevel.WARNING)
                messagebox.showwarning("Warning", "Please select a proxy to stop")
                return

            index = selection[0]
            self._stop_proxy_by_index(index)

            # Save state
            StateManager.save_state(self.state, self.settings)

        except Exception as e:
            self.log_message(f"Error stopping proxy: {str(e)}", LogLevel.ERROR)
            messagebox.showerror("Error", f"Failed to stop proxy: {str(e)}")

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
        if not self.private_key_entry or not self.public_key_entry:
            return

        new_private_key = self.private_key_entry.get().strip()
        new_public_key = self.public_key_entry.get().strip()

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
            if not self.proxy_listbox:
                return

            selection = self.proxy_listbox.curselection()
            if not selection:
                self.log_message("No proxy selected for config export", LogLevel.WARNING)
                messagebox.showwarning("Warning", "Please select a proxy to export")
                return

            index = selection[0]
            instance = self.state.get_proxy_instance(index)

            if not instance:
                return

            private_key, _ = self.state.get_keys()
            if not private_key:
                messagebox.showerror("Error", "WireGuard keys not configured")
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
                messagebox.showinfo("Success", f"Config exported to {filename}")

        except Exception as e:
            self.log_message(f"Error exporting config: {str(e)}", LogLevel.ERROR)
            messagebox.showerror("Error", f"Failed to export config: {str(e)}")

    def show_config(self):
        """Show generated config in a popup"""
        try:
            if not self.proxy_listbox:
                return

            selection = self.proxy_listbox.curselection()
            if not selection:
                messagebox.showwarning("Warning", "Please select a proxy")
                return

            index = selection[0]
            instance = self.state.get_proxy_instance(index)

            if not instance:
                return

            private_key, _ = self.state.get_keys()
            if not private_key:
                messagebox.showerror("Error", "WireGuard keys not configured")
                return

            wg_config = ConfigurationManager.generate_wireguard_config(instance.server, private_key)
            wireproxy_config = ConfigurationManager.generate_wireproxy_config(wg_config, instance.port)

            config_window = tk.Toplevel(self.root)
            config_window.title("Generated Config")
            config_window.geometry("600x400")
            config_window.transient(self.root)
            config_window.grab_set()

            text_widget = scrolledtext.ScrolledText(config_window)
            text_widget.pack(fill="both", expand=True, padx=10, pady=10)
            text_widget.insert("1.0", wireproxy_config)
            text_widget.config(state="disabled")  # Make read-only

        except Exception as e:
            self.log_message(f"Error showing config: {str(e)}", LogLevel.ERROR)

    def clear_log(self):
        """Clear the log window"""
        if self.log_text:
            self.log_text.delete(1.0, tk.END)
            self.log_message("Log cleared", LogLevel.INFO)

    def save_log(self):
        """Save log to file"""
        try:
            if not self.log_text:
                return

            filename = filedialog.asksaveasfilename(
                defaultextension=".log",
                filetypes=[("Log files", "*.log"), ("Text files", "*.txt"), ("All files", "*.*")],
                initialfile=f"wireproxy_log_{datetime.now().strftime('%Y%m%d_%H%M%S')}.log"
            )

            if filename:
                with open(filename, 'w') as f:
                    f.write(self.log_text.get(1.0, tk.END))

                file_size = os.path.getsize(filename)
                self.log_message(f"Log saved to {filename} ({file_size} bytes)", LogLevel.INFO)
                messagebox.showinfo("Success", f"Log saved to {filename}")

        except Exception as e:
            self.log_message(f"Error saving log: {str(e)}", LogLevel.ERROR)
            messagebox.showerror("Error", f"Failed to save log: {str(e)}")

    def change_log_level(self):
        """Unified log level change method"""
        self._show_log_level_dialog(self.root)

    def _show_log_level_dialog(self, parent):
        """Show log level selection dialog"""
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
            if hasattr(self, 'log_level_label') and self.log_level_label:
                self.log_level_label.config(text=new_level_name)

            if hasattr(self, 'prefs_log_level_label') and self.prefs_log_level_label:
                self.prefs_log_level_label.config(text=new_level_name)

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
        """Show preferences window with improved structure"""
        # Reuse existing window if available
        if hasattr(self, 'preferences_window') and self.preferences_window.winfo_exists():
            self.preferences_window.lift()
            self.preferences_window.focus_set()
            return

        # Helper functions
        def close_window():
            self.preferences_window.grab_release()
            self.preferences_window.destroy()

        def save_and_close():
            self._save_preferences(
                start_min_var.get(),
                min_to_tray_var.get(),
                auto_start_var.get(),
                api_endpoint_var.get()
            )
            close_window()

        def on_mousewheel(event):
            """Cross-platform mousewheel scroll handler"""
            if event.num == 4 or event.delta > 0:
                canvas.yview_scroll(-1, "units")
            elif event.num == 5 or event.delta < 0:
                canvas.yview_scroll(1, "units")

        # Window setup
        self.preferences_window = tk.Toplevel(self.root)
        self.preferences_window.title("Preferences")
        self.preferences_window.resizable(True, True)
        self.preferences_window.transient(self.root)
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

        # Improved mousewheel binding
        for widget in (canvas, scrollable_frame):
            widget.bind_all("<MouseWheel>", on_mousewheel)  # Windows/macOS
            widget.bind_all("<Button-4>", on_mousewheel)  # Linux scroll up
            widget.bind_all("<Button-5>", on_mousewheel)  # Linux scroll down

        canvas.pack(side="left", fill="both", expand=True, padx=(10, 0), pady=10)
        scrollbar.pack(side="right", fill="y", padx=(0, 10), pady=10)

        # Content setup
        content_frame = ttk.Frame(scrollable_frame, padding=20)
        content_frame.pack(fill="x", expand=True)

        start_min_var = tk.BooleanVar(value=self.settings.start_minimized)
        min_to_tray_var = tk.BooleanVar(value=self.settings.minimize_to_tray)
        auto_start_var = tk.BooleanVar(value=self.settings.auto_start_proxies)
        api_endpoint_var = tk.StringVar(value=self.settings.api_endpoint)

        sections = [
            self._create_title_section(content_frame),
            self._create_startup_section(content_frame, start_min_var, auto_start_var),
            self._create_api_section(content_frame, api_endpoint_var),
            self._create_tray_section(content_frame, min_to_tray_var),
            self._create_logging_section(content_frame),
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

    def _center_window(self, window, width, height):
        """Center a window on screen"""
        window.update_idletasks()
        screen_width = window.winfo_screenwidth()
        screen_height = window.winfo_screenheight()
        x = (screen_width // 2) - (width // 2)
        y = (screen_height // 2) - (height // 2)
        window.geometry(f"{width}x{height}+{x}+{y}")

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
                  foreground="gray").pack(anchor="w", pady=(5, 0))

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
                  foreground="gray").pack(anchor="w", pady=(5, 0))

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
        current_level = level_names.get(self.settings.log_level, "UNKNOWN")

        # Store reference to the label so it can be updated later
        self.prefs_log_level_label = ttk.Label(level_frame, text=current_level,
                                               font=("Arial", 10, "bold"))
        self.prefs_log_level_label.pack(side="left", padx=(10, 0))

        def change_log_level_for_prefs():
            """Change log level from preferences window"""
            self._show_log_level_dialog(self.preferences_window)

        ttk.Button(frame, text="Change Log Level",
                   command=change_log_level_for_prefs).pack(anchor="w", pady=(10, 0))

        return frame

    def _create_about_section(self, parent):
        """Create about section with wireproxy management"""
        frame = ttk.LabelFrame(parent, text="About & System Info", padding=15)

        # Application info
        about_text = (
            "SurfShark Wireproxy Manager\n"
            "Version 1.0.0\n"
            "Manage multiple SOCKS5 proxies via WireGuard"
        )
        ttk.Label(frame, text=about_text, foreground="gray").pack(anchor="w")

        # Add separator
        ttk.Separator(frame, orient='horizontal').pack(fill='x', pady=(15, 15))

        # Wireproxy status section
        wireproxy_section = ttk.LabelFrame(frame, text="wireproxy Binary", padding=10)
        wireproxy_section.pack(fill="x", pady=(0, 10))

        # Check current wireproxy version and info
        current_wireproxy = ProcessManager.find_wireproxy_executable()

        status_frame = ttk.Frame(wireproxy_section)
        status_frame.pack(fill="x", pady=(0, 10))

        if current_wireproxy:
            # Status
            status_label = ttk.Label(status_frame, text="Status: ", font=("Arial", 9, "bold"))
            status_label.pack(side="left")
            ttk.Label(status_frame, text="✓ Found", foreground="green",
                      font=("Arial", 9, "bold")).pack(side="left")

            # Location
            location_frame = ttk.Frame(wireproxy_section)
            location_frame.pack(fill="x", pady=(2, 0))
            ttk.Label(location_frame, text="Location: ", font=("Arial", 9, "bold")).pack(side="left")
            location_text = current_wireproxy
            if len(location_text) > 60:  # Truncate long paths
                location_text = "..." + location_text[-57:]
            ttk.Label(location_frame, text=location_text, font=("Arial", 8),
                      foreground="gray").pack(side="left")

            # File size and modification date
            try:
                import os
                from datetime import datetime

                stat_info = os.stat(current_wireproxy)
                file_size = stat_info.st_size
                mod_time = datetime.fromtimestamp(stat_info.st_mtime)

                # File size
                size_frame = ttk.Frame(wireproxy_section)
                size_frame.pack(fill="x", pady=(2, 0))
                ttk.Label(size_frame, text="Size: ", font=("Arial", 9, "bold")).pack(side="left")

                if file_size < 1024:
                    size_text = f"{file_size} bytes"
                elif file_size < 1024 * 1024:
                    size_text = f"{file_size / 1024:.1f} KB"
                else:
                    size_text = f"{file_size / (1024 * 1024):.1f} MB"

                ttk.Label(size_frame, text=size_text, font=("Arial", 8),
                          foreground="gray").pack(side="left")

                # Modification date
                date_frame = ttk.Frame(wireproxy_section)
                date_frame.pack(fill="x", pady=(2, 0))
                ttk.Label(date_frame, text="Modified: ", font=("Arial", 9, "bold")).pack(side="left")
                ttk.Label(date_frame, text=mod_time.strftime("%Y-%m-%d %H:%M:%S"),
                          font=("Arial", 8), foreground="gray").pack(side="left")

            except Exception as e:
                # If we can't get file info, just show that it exists
                pass

            # Try to get version info if possible
            try:
                import subprocess
                result = subprocess.run([current_wireproxy, '--version'],
                                        capture_output=True, text=True, timeout=5)
                if result.returncode == 0 and result.stdout.strip():
                    version_frame = ttk.Frame(wireproxy_section)
                    version_frame.pack(fill="x", pady=(2, 0))
                    ttk.Label(version_frame, text="Version: ", font=("Arial", 9, "bold")).pack(side="left")
                    version_text = result.stdout.strip().replace('\n', ' ')[:50]  # Limit length
                    ttk.Label(version_frame, text=version_text, font=("Arial", 8),
                              foreground="gray").pack(side="left")
            except:
                # Version check failed, that's ok
                pass

        else:
            # Not found
            ttk.Label(status_frame, text="Status: ", font=("Arial", 9, "bold")).pack(side="left")
            ttk.Label(status_frame, text="✗ Not found", foreground="red",
                      font=("Arial", 9, "bold")).pack(side="left")

            ttk.Label(wireproxy_section, text="wireproxy binary not found in PATH or common locations.",
                      font=("Arial", 8), foreground="gray").pack(anchor="w", pady=(5, 0))

        # Separator
        ttk.Separator(wireproxy_section, orient='horizontal').pack(fill='x', pady=(10, 10))

        # Download section
        download_frame = ttk.Frame(wireproxy_section)
        download_frame.pack(fill="x")

        def download_latest_wireproxy():
            """Download latest wireproxy version with progress feedback"""
            try:
                # Disable button during download
                download_btn.config(state="disabled", text="Downloading...")
                self.preferences_window.update()

                if ProcessManager._download_wireproxy():
                    self.log_message("Latest wireproxy downloaded successfully", LogLevel.INFO)
                    messagebox.showinfo("Success", "Latest wireproxy version downloaded successfully!")
                    # Refresh the preferences window to show new info
                    self.preferences_window.destroy()
                    self.show_preferences()
                else:
                    self.log_message("Failed to download wireproxy", LogLevel.ERROR)
                    messagebox.showerror("Error",
                                         "Failed to download wireproxy. Please check your internet connection and try again.")
            except Exception as e:
                self.log_message(f"Error during wireproxy download: {str(e)}", LogLevel.ERROR)
                messagebox.showerror("Error", f"Download failed: {str(e)}")
            finally:
                # Re-enable button
                try:
                    download_btn.config(state="normal", text="Download Latest Version")
                except:
                    pass

        def check_latest_version():
            """Check what the latest version is without downloading"""
            try:
                import urllib.request
                api_url = "https://api.github.com/repos/whyvl/wireproxy/releases/latest"
                with urllib.request.urlopen(api_url, timeout=10) as response:
                    release_data = json.loads(response.read().decode())
                latest_version = release_data.get('tag_name', 'unknown')
                published_date = release_data.get('published_at', '')
                if published_date:
                    from datetime import datetime
                    pub_date = datetime.fromisoformat(published_date.replace('Z', '+00:00'))
                    date_str = pub_date.strftime("%Y-%m-%d")
                else:
                    date_str = "unknown date"

                messagebox.showinfo("Latest Version",
                                    f"Latest wireproxy version: {latest_version}\n"
                                    f"Published: {date_str}\n\n"
                                    f"GitHub: https://github.com/whyvl/wireproxy/releases/latest")
            except Exception as e:
                messagebox.showerror("Error", f"Failed to check latest version: {str(e)}")

        # Buttons
        button_frame = ttk.Frame(download_frame)
        button_frame.pack(anchor="w")

        download_btn = ttk.Button(button_frame, text="Download Latest Version",
                                  command=download_latest_wireproxy)
        download_btn.pack(side="left", padx=(0, 10))

        ttk.Button(button_frame, text="Check Latest Version",
                   command=check_latest_version).pack(side="left", padx=(0, 10))

        # Info text
        info_text = (
            "• Downloads from: https://github.com/whyvl/wireproxy/releases\n"
            "• Automatically detects your platform and architecture\n"
            "• Replaces existing binary if found"
        )
        ttk.Label(wireproxy_section, text=info_text, font=("Arial", 8),
                  foreground="gray").pack(anchor="w", pady=(10, 0))

        return frame

    def _save_preferences(self, start_minimized, minimize_to_tray, auto_start_proxies, api_endpoint):
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
        api_changed = self.settings.api_endpoint != api_endpoint

        # Update settings
        self.settings.start_minimized = start_minimized
        self.settings.minimize_to_tray = minimize_to_tray
        self.settings.auto_start_proxies = auto_start_proxies
        self.settings.api_endpoint = api_endpoint

        # Persist changes
        StateManager.save_settings(self.settings)
        self.log_message("Preferences saved", LogLevel.INFO)

        # Debug log to verify what was saved
        self.log_message(
            f"Saved: start_minimized={start_minimized}, minimize_to_tray={minimize_to_tray}, "
            f"auto_start_proxies={auto_start_proxies}, api_endpoint={api_endpoint}",
            LogLevel.DEBUG)

        # Handle API endpoint change
        if api_changed:
            self.log_message(f"API endpoint changed to: {api_endpoint}", LogLevel.INFO)
            messagebox.showinfo(
                "API Endpoint Changed",
                "API endpoint has been updated. You may want to reload servers to test the new endpoint."
            )

    def create_tray_icon(self):
        """Create system tray icon"""

        def create_icon_image():
            width = 64
            height = 64
            image = Image.new('RGB', (width, height), color='blue')
            draw = ImageDraw.Draw(image)
            draw.ellipse([16, 16, 48, 48], fill='white')
            return image

        menu = pystray.Menu(
            pystray.MenuItem("Show", self.show_from_tray),
            pystray.MenuItem("Preferences", self.show_preferences),
            pystray.MenuItem("Quit", self.quit_from_tray)
        )

        self.tray_icon = pystray.Icon("wireproxy", create_icon_image(), "Wireproxy Manager", menu)

    def show_from_tray(self, icon=None, item=None):
        """Show window from tray"""
        if self.root:
            self.root.after(0, lambda: [self.root.deiconify(), self.root.lift(), self.root.focus_force()])

    def hide_to_tray(self):
        """Hide window to tray"""
        if self.settings.minimize_to_tray and self.root:
            self.root.withdraw()
            if self.tray_icon and not self.tray_icon.visible:
                threading.Thread(target=self.tray_icon.run, daemon=True).start()

    def quit_from_tray(self, icon=None, item=None):
        """Quit from tray"""
        if self.tray_icon:
            self.tray_icon.stop()
        if self.root:
            self.root.after(0, self.on_closing)

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

        if self.root:
            self.root.destroy()

    def create_gui(self):
        """Create the main GUI with wireproxy executable check"""
        self.root = tk.Tk()
        self.root.title("SurfShark Wireproxy Manager")
        self.root.geometry("1000x700")
        self.root.protocol("WM_DELETE_WINDOW", self.on_closing)

        # Check for wireproxy executable
        if not ProcessManager.find_wireproxy_executable():
            self.log_message("wireproxy executable not found in PATH", LogLevel.ERROR)
            messagebox.showerror(
                "Missing Dependency",
                "wireproxy executable not found in PATH or current directory.\n\n"
                "Please install wireproxy and ensure it's in your PATH, or place the executable "
                "in the same directory as this application.\n\n"
                "Download from: https://github.com/octeep/wireproxy"
            )

        # Hide window initially if starting minimized
        if self.settings.start_minimized:
            self.root.withdraw()

        # Main frame
        main_frame = ttk.Frame(self.root, padding="10")
        main_frame.grid(row=0, column=0, sticky=(tk.W, tk.E, tk.N, tk.S))

        # Configure grid weights
        self.root.columnconfigure(0, weight=1)
        self.root.rowconfigure(0, weight=1)
        main_frame.columnconfigure(1, weight=1)
        main_frame.rowconfigure(3, weight=1)

        # Title
        title_label = ttk.Label(main_frame, text="SurfShark Wireproxy Manager", font=("Arial", 16, "bold"))
        title_label.grid(row=0, column=0, columnspan=3, pady=(0, 20))

        # Keys Configuration Frame
        keys_frame = ttk.LabelFrame(main_frame, text="WireGuard Keys", padding="10")
        keys_frame.grid(row=1, column=0, columnspan=3, sticky=(tk.W, tk.E), pady=(0, 10))
        keys_frame.columnconfigure(1, weight=1)

        # Private Key
        ttk.Label(keys_frame, text="Private Key:").grid(row=0, column=0, sticky=tk.W, padx=(0, 5))
        self.private_key_entry = ttk.Entry(keys_frame, width=60, show="*")  # Hide key for security
        self.private_key_entry.grid(row=0, column=1, sticky=(tk.W, tk.E), padx=(0, 5))

        # Public Key
        ttk.Label(keys_frame, text="Public Key:").grid(row=1, column=0, sticky=tk.W, padx=(0, 5))
        self.public_key_entry = ttk.Entry(keys_frame, width=60)
        self.public_key_entry.grid(row=1, column=1, sticky=(tk.W, tk.E), padx=(0, 5))

        # Update keys button
        ttk.Button(keys_frame, text="Update Keys", command=self.update_keys).grid(row=0, column=2, rowspan=2,
                                                                                  padx=(5, 0))

        # Proxy Configuration Frame
        config_frame = ttk.LabelFrame(main_frame, text="Add New Proxy", padding="10")
        config_frame.grid(row=2, column=0, columnspan=3, sticky=(tk.W, tk.E), pady=(0, 10))

        # Country selection
        ttk.Label(config_frame, text="Country:").grid(row=0, column=0, sticky=tk.W, padx=(0, 5))
        self.country_var = tk.StringVar()
        self.country_combo = ttk.Combobox(config_frame, textvariable=self.country_var, state="readonly", width=30)
        self.country_combo.grid(row=0, column=1, sticky=(tk.W, tk.E), padx=(0, 10))

        # Port selection
        ttk.Label(config_frame, text="SOCKS5 Port:").grid(row=0, column=2, sticky=tk.W, padx=(10, 5))
        self.port_var = tk.IntVar(value=1080)
        port_spinbox = ttk.Spinbox(config_frame, from_=1024, to=65535, textvariable=self.port_var, width=10)
        port_spinbox.grid(row=0, column=3, sticky=tk.W, padx=(0, 10))

        # Buttons
        ttk.Button(config_frame, text="+ Add Proxy", command=self.add_proxy).grid(row=0, column=4, padx=(10, 0))
        ttk.Button(config_frame, text="🔄 Reload Servers", command=self.load_servers).grid(row=0, column=5, padx=(5, 0))
        ttk.Button(config_frame, text="⚙️ Preferences", command=self.show_preferences).grid(row=0, column=6,
                                                                                            padx=(5, 0))

        # Proxy Management Frame
        mgmt_frame = ttk.Frame(main_frame)
        mgmt_frame.grid(row=3, column=0, columnspan=3, sticky=(tk.W, tk.E, tk.N, tk.S), pady=(0, 10))
        mgmt_frame.columnconfigure(0, weight=2)
        mgmt_frame.columnconfigure(1, weight=1)
        mgmt_frame.rowconfigure(0, weight=1)

        # Left side - Proxy list
        left_frame = ttk.LabelFrame(mgmt_frame, text="Active Proxies", padding="5")
        left_frame.grid(row=0, column=0, sticky=(tk.W, tk.E, tk.N, tk.S), padx=(0, 5))
        left_frame.columnconfigure(0, weight=1)
        left_frame.rowconfigure(0, weight=1)

        # Proxy listbox with scrollbar
        listbox_frame = ttk.Frame(left_frame)
        listbox_frame.grid(row=0, column=0, sticky=(tk.W, tk.E, tk.N, tk.S))
        listbox_frame.columnconfigure(0, weight=1)
        listbox_frame.rowconfigure(0, weight=1)

        self.proxy_listbox = tk.Listbox(listbox_frame)
        self.proxy_listbox.grid(row=0, column=0, sticky=(tk.W, tk.E, tk.N, tk.S))

        scrollbar = ttk.Scrollbar(listbox_frame, orient="vertical", command=self.proxy_listbox.yview)
        scrollbar.grid(row=0, column=1, sticky=(tk.N, tk.S))
        self.proxy_listbox.configure(yscrollcommand=scrollbar.set)

        # Control buttons
        btn_frame = ttk.Frame(left_frame)
        btn_frame.grid(row=1, column=0, sticky=(tk.W, tk.E), pady=(5, 0))

        ttk.Button(btn_frame, text="▶ Start", command=self.start_proxy).grid(row=0, column=0, padx=(0, 5))
        ttk.Button(btn_frame, text="⏹ Stop", command=self.stop_proxy).grid(row=0, column=1, padx=(0, 5))
        ttk.Button(btn_frame, text="🗑 Remove", command=self.remove_proxy).grid(row=0, column=2, padx=(0, 5))
        ttk.Button(btn_frame, text="💾 Export Config", command=self.export_config).grid(row=0, column=3, padx=(0, 5))
        ttk.Button(btn_frame, text="⏹ Stop All", command=self.stop_all_proxies).grid(row=0, column=4, padx=(0, 5))
        ttk.Button(btn_frame, text="🔍 Show Config", command=self.show_config).grid(row=0, column=5, padx=(0, 5))

        # Right side - Log
        right_frame = ttk.LabelFrame(mgmt_frame, text="Log", padding="5")
        right_frame.grid(row=0, column=1, sticky=(tk.W, tk.E, tk.N, tk.S), padx=(5, 0))
        right_frame.columnconfigure(0, weight=1)
        right_frame.rowconfigure(0, weight=1)

        self.log_text = scrolledtext.ScrolledText(right_frame, height=20, width=50)
        self.log_text.grid(row=0, column=0, sticky=(tk.W, tk.E, tk.N, tk.S))

        # Log control buttons
        log_btn_frame = ttk.Frame(right_frame)
        log_btn_frame.grid(row=1, column=0, sticky=(tk.W, tk.E), pady=(5, 0))

        ttk.Button(log_btn_frame, text="Clear Log", command=self.clear_log).grid(row=0, column=0, padx=(0, 5))
        ttk.Button(log_btn_frame, text="Save Log", command=self.save_log).grid(row=0, column=1, padx=(0, 5))
        ttk.Button(log_btn_frame, text="Log Level", command=self.change_log_level).grid(row=0, column=2)

        # Add log level display
        level_names = {
            LogLevel.DEBUG: "DEBUG",
            LogLevel.INFO: "INFO",
            LogLevel.WARNING: "WARNING",
            LogLevel.ERROR: "ERROR"
        }
        current_level = level_names.get(self.settings.log_level, "UNKNOWN")
        self.log_level_label = ttk.Label(log_btn_frame, text=current_level, font=("Arial", 8))
        self.log_level_label.grid(row=0, column=3, padx=(5, 0))

        # Status bar
        self.status_label = ttk.Label(main_frame, text="Status: Starting...", relief="sunken")
        self.status_label.grid(row=4, column=0, columnspan=3, sticky=(tk.W, tk.E), pady=(10, 0))

        # Handle window minimize
        def on_minimize(event=None):
            if self.settings.minimize_to_tray:
                self.root.after(100, self.hide_to_tray)

        self.root.bind('<Unmap>', on_minimize)

        return self.root

    def auto_restart_proxies(self, auto_restart_list: List[int]):
        """Auto-restart proxies from saved state with improved error handling"""
        if not auto_restart_list:
            self.log_message("No proxies marked for auto-restart", LogLevel.INFO)
            return

        self.log_message(f"Starting auto-restart for {len(auto_restart_list)} proxies", LogLevel.INFO)

        def restart_worker():
            try:
                self.log_message("Auto-restart thread started", LogLevel.INFO)

                # Wait for servers to be loaded with better timeout handling
                servers = self.state.get_servers()
                attempts = 0
                max_attempts = 60  # Wait up to 60 seconds

                while not servers and attempts < max_attempts:
                    if self.shutdown_event.is_set():
                        self.log_message("Shutdown requested, cancelling auto-restart", LogLevel.INFO)
                        return

                    time.sleep(1)
                    servers = self.state.get_servers()
                    attempts += 1

                if not servers:
                    self.log_message("Servers never loaded, cannot auto-restart proxies", LogLevel.ERROR)
                    return

                self.log_message("Servers loaded, starting auto-restart...", LogLevel.INFO)

                successful_restarts = 0
                failed_restarts = 0

                for i, index in enumerate(auto_restart_list):
                    if self.shutdown_event.is_set():
                        self.log_message("Shutdown requested, stopping auto-restart", LogLevel.INFO)
                        break

                    try:
                        self.log_message(
                            f"Auto-restarting proxy {i + 1}/{len(auto_restart_list)} (index {index})",
                            LogLevel.INFO
                        )

                        # Schedule restart on main thread
                        if self.root:
                            self.root.after(0, lambda idx=index: self._start_proxy_by_index(idx))
                            successful_restarts += 1

                        time.sleep(3)  # Increased delay between restarts

                    except Exception as e:
                        failed_restarts += 1
                        self.log_message(
                            f"Failed to schedule auto-restart for proxy {index}: {str(e)}",
                            LogLevel.ERROR
                        )

                self.log_message(
                    f"Auto-restart completed: {successful_restarts} successful, {failed_restarts} failed",
                    LogLevel.INFO
                )

            except Exception as e:
                self.log_message(f"Auto-restart worker error: {str(e)}", LogLevel.ERROR)

        # Use thread pool for better management
        self.thread_pool.submit(restart_worker)

    def run(self):
        """Main application entry point with improved startup sequence"""
        try:
            # Clean up any leftover temp files from previous runs
            StateManager.cleanup_temp_files(self.state)

            # Create GUI
            self.create_gui()

            # Create tray icon
            self.create_tray_icon()

            # Initialize logging
            if not self.settings.start_minimized:
                self.log_message("=" * 60, LogLevel.INFO)
                self.log_message("SurfShark Wireproxy Manager started", LogLevel.INFO)
                self.log_message(f"Python version: {sys.version}", LogLevel.INFO)
                self.log_message(f"Platform: {os.name}", LogLevel.INFO)
                self.log_message(f"Working directory: {os.getcwd()}", LogLevel.INFO)
                self.log_message("=" * 60, LogLevel.INFO)

            # Start process monitoring
            self.start_monitoring()

            # Load servers
            self.load_servers()

            # Load saved state and get auto-restart list
            def delayed_state_load():
                servers = self.state.get_servers()
                if servers:
                    if not self.settings.start_minimized:
                        self.log_message("Servers loaded, now loading state...", LogLevel.INFO)

                    auto_restart_list = StateManager.load_state(self.state)

                    # Update GUI with loaded keys
                    private_key, public_key = self.state.get_keys()
                    if self.private_key_entry and private_key:
                        self.private_key_entry.delete(0, tk.END)
                        self.private_key_entry.insert(0, private_key)
                    if self.public_key_entry and public_key:
                        self.public_key_entry.delete(0, tk.END)
                        self.public_key_entry.insert(0, public_key)

                    # Update proxy list
                    self.gui_queue.put_proxy_list_update()

                    # Auto-restart if enabled
                    if self.settings.auto_start_proxies and auto_restart_list:
                        self.auto_restart_proxies(auto_restart_list)

                else:
                    if not self.settings.start_minimized:
                        self.log_message("Servers not loaded yet, retrying in 2 seconds...", LogLevel.WARNING)
                    if self.root and not self.shutdown_event.is_set():
                        self.root.after(2000, delayed_state_load)

            # Delay state loading to ensure servers are loaded first
            if self.root:
                self.root.after(3000, delayed_state_load)

            # Start GUI message processing
            self.process_gui_messages()

            # Handle startup minimized
            if self.settings.start_minimized:
                self.root.after(100, self.hide_to_tray)
                threading.Thread(target=self.tray_icon.run, daemon=True).start()

            # Start GUI main loop
            self.root.mainloop()

        except KeyboardInterrupt:
            self.log_message("Received keyboard interrupt, shutting down...", LogLevel.INFO)
            self.on_closing()
        except Exception as e:
            self.log_message(f"Unexpected error in main loop: {str(e)}", LogLevel.ERROR)
            logger.exception("Unexpected error in main loop")
            raise
        finally:
            # Ensure cleanup
            try:
                self.thread_pool.shutdown(wait=False, cancel_futures=True)
            except:
                pass


def main():
    """Application entry point"""
    try:
        app = WireproxyManager()
        app.run()
    except Exception as e:
        logger.exception("Fatal error starting application")
        try:
            import tkinter.messagebox as mb
            mb.showerror("Fatal Error", f"Failed to start application: {str(e)}")
        except:
            print(f"Fatal error: {e}")


if __name__ == "__main__":
    main()