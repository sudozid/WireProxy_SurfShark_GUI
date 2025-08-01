"""Process manager for handling wireproxy processes."""

import os
import stat
import time
import signal
import shutil
import subprocess
import tempfile
import logging
import json
import platform
import tarfile
import urllib.request
import hashlib
import threading
from typing import Optional
try:
    import tkinter as tk
    from tkinter import messagebox
    HAS_TKINTER = True
except ImportError:
    HAS_TKINTER = False
    # Create dummy classes for headless operation
    class DummyMessagebox:
        @staticmethod
        def askyesnocancel(*args, **kwargs): return None
        @staticmethod
        def showerror(*args, **kwargs): pass
        @staticmethod
        def showwarning(*args, **kwargs): pass
        @staticmethod
        def showinfo(*args, **kwargs): pass
    messagebox = DummyMessagebox()

from models import ProcessInfo
import constants

logger = logging.getLogger(__name__)


class ProcessManager:
    """Manages wireproxy processes with proper lifecycle management"""

    @staticmethod
    def _download_wireproxy_with_ui(parent_window=None) -> bool:
        """Download wireproxy using the new UI dialog (deprecated - use gui.download_dialog)"""
        try:
            if not HAS_TKINTER or not parent_window:
                logger.error("Cannot download wireproxy without GUI support")
                return False
                
            from gui.download_dialog import WireproxyDownloadManager
            
            download_success = False
            error_message = None
            download_completed = threading.Event()
            
            def on_download_complete(success: bool, message: str):
                nonlocal download_success, error_message
                download_success = success
                error_message = message
                download_completed.set()
                
            # Start download with UI
            WireproxyDownloadManager.download_wireproxy_with_ui(
                parent_window, 
                on_complete=on_download_complete
            )
            
            # Wait for download to complete (with timeout)
            if download_completed.wait(timeout=300):  # 5 minute timeout
                return download_success
            else:
                logger.error("Download timed out")
                return False
                
        except Exception as e:
            logger.error(f"Error downloading wireproxy with UI: {e}")
            return False

    @staticmethod
    def find_wireproxy_executable() -> Optional[str]:
        """Find wireproxy executable with comprehensive logging and validation"""
        logger.debug("Starting wireproxy executable search...")
        
        # Method 1: Check using shutil.which (most reliable for PATH)
        try:
            wireproxy_path = shutil.which("wireproxy")
            if wireproxy_path:
                if ProcessManager._validate_wireproxy_executable(wireproxy_path):
                    logger.info(f"Found wireproxy using shutil.which: {wireproxy_path}")
                    return wireproxy_path
                else:
                    logger.warning(f"wireproxy found via shutil.which but validation failed: {wireproxy_path}")
        except Exception as e:
            logger.debug(f"shutil.which failed: {e}")

        # Method 2: Manual PATH search with multiple executable name variants
        path_env = os.environ.get("PATH", "")
        logger.debug(f"Searching PATH: {path_env}")
        
        executable_names = ["wireproxy", "wireproxy.exe"]
        
        for path in path_env.split(os.pathsep):
            if not path.strip():
                continue
                
            for exe_name in executable_names:
                potential_path = os.path.join(path, exe_name)
                try:
                    if os.path.isfile(potential_path) and ProcessManager._validate_wireproxy_executable(potential_path):
                        logger.info(f"Found wireproxy in PATH: {potential_path}")
                        return potential_path
                except Exception as e:
                    logger.debug(f"Error checking {potential_path}: {e}")

        # Method 3: Check current working directory
        logger.debug("Checking current working directory...")
        for exe_name in executable_names:
            try:
                if os.path.isfile(exe_name) and ProcessManager._validate_wireproxy_executable(exe_name):
                    abs_path = os.path.abspath(exe_name)
                    logger.info(f"Found wireproxy in current directory: {abs_path}")
                    return abs_path
            except Exception as e:
                logger.debug(f"Error checking current directory {exe_name}: {e}")

        # Method 4: Check common Linux installation paths
        if os.name != 'nt':
            logger.debug("Checking common Linux installation paths...")
            common_paths = [
                "/usr/local/bin/wireproxy",
                "/usr/bin/wireproxy", 
                "/opt/wireproxy/wireproxy",
                os.path.expanduser("~/.local/bin/wireproxy"),
                "/snap/bin/wireproxy",  # Snap package
                "/usr/local/sbin/wireproxy",
                "/usr/sbin/wireproxy"
            ]

            for path in common_paths:
                try:
                    if os.path.isfile(path) and ProcessManager._validate_wireproxy_executable(path):
                        logger.info(f"Found wireproxy in common path: {path}")
                        return path
                except Exception as e:
                    logger.debug(f"Error checking common path {path}: {e}")

        # Method 5: Check relative paths and application directory
        logger.debug("Checking relative and application-specific paths...")
        app_dir = os.path.dirname(os.path.abspath(__file__))
        relative_paths = [
            "./wireproxy",
            "./wireproxy.exe", 
            "../wireproxy",
            "../wireproxy.exe",
            os.path.join(app_dir, "wireproxy"),
            os.path.join(app_dir, "wireproxy.exe"),
            os.path.join(app_dir, "..", "wireproxy"),
            os.path.join(app_dir, "..", "wireproxy.exe"),
        ]
        
        for path in relative_paths:
            try:
                if os.path.isfile(path) and ProcessManager._validate_wireproxy_executable(path):
                    abs_path = os.path.abspath(path)
                    logger.info(f"Found wireproxy in relative path: {abs_path}")
                    return abs_path
            except Exception as e:
                logger.debug(f"Error checking relative path {path}: {e}")

        logger.warning("wireproxy executable not found in any searched location")
        logger.debug("Search locations included: PATH, current directory, common Linux paths, relative paths")
        return None
        
    @staticmethod 
    def _validate_wireproxy_executable(path: str) -> bool:
        """Validate that a file is a valid wireproxy executable"""
        try:
            # Check if file exists and is readable
            if not os.path.isfile(path):
                return False
                
            # Check if file is executable
            if not os.access(path, os.X_OK):
                return False
                
            # Check file size (wireproxy should be at least 1MB)
            file_size = os.path.getsize(path)
            if file_size < 1024 * 1024:  # Less than 1MB is suspicious
                logger.debug(f"File {path} is too small ({file_size} bytes) to be wireproxy")
                return False
                
            # Check if it's a binary file (not a script)
            try:
                with open(path, 'rb') as f:
                    header = f.read(4)
                    # Check for common executable headers
                    if os.name == 'nt':
                        # Windows PE header
                        if header[:2] == b'MZ':
                            logger.debug(f"File {path} has valid Windows PE header")
                            return True
                    else:
                        # Linux ELF header
                        if header == b'\x7fELF':
                            logger.debug(f"File {path} has valid ELF header")
                            return True
                        # macOS Mach-O headers
                        if header in [b'\xfe\xed\xfa\xce', b'\xfe\xed\xfa\xcf', 
                                     b'\xce\xfa\xed\xfe', b'\xcf\xfa\xed\xfe']:
                            logger.debug(f"File {path} has valid Mach-O header")
                            return True
                            
                    logger.debug(f"File {path} does not have a recognized binary header: {header.hex()}")
                    return False
                    
            except (IOError, OSError) as e:
                logger.debug(f"Could not read file header for {path}: {e}")
                # If we can't read the header, but other checks passed, assume it's valid
                return True
                
        except Exception as e:
            logger.debug(f"Error validating {path}: {e}")
            return False

    @staticmethod
    def start_wireproxy_process(config_content: str, state, parent_window=None) -> Optional[ProcessInfo]:
        """Start a wireproxy process with comprehensive error handling and improved UI"""
        config_file = None
        try:
            # Find executable with detailed logging
            logger.info("Searching for wireproxy executable...")
            wireproxy_path = ProcessManager.find_wireproxy_executable()
            
            if not wireproxy_path:
                logger.error("wireproxy executable not found in any searched location")
                
                # If no GUI available, return immediately 
                if not HAS_TKINTER or not parent_window:
                    logger.error("wireproxy executable not found and no GUI available for download")
                    return None

                # Check if we have a valid Tkinter root
                try:
                    # Try to access the parent window to ensure GUI is available
                    if not parent_window or not hasattr(parent_window, 'winfo_exists') or not parent_window.winfo_exists():
                        logger.error("wireproxy executable not found and no valid GUI window available")
                        return None
                except Exception as e:
                    logger.error(f"wireproxy executable not found and GUI validation failed: {e}")
                    return None

                logger.info("Prompting user for wireproxy download...")
                
                # Import the download manager
                try:
                    from gui.download_dialog import WireproxyDownloadManager
                except ImportError as e:
                    logger.error(f"Failed to import download dialog: {e}")
                    # Fallback to simple error message
                    messagebox.showerror(
                        constants.MISSING_DEPENDENCY_TITLE,
                        constants.MISSING_DEPENDENCY_MESSAGE
                    )
                    return None

                # Show download prompt
                user_wants_download = WireproxyDownloadManager.show_download_prompt(parent_window)
                
                if user_wants_download:
                    logger.info("User chose to download wireproxy")
                    
                    # Track download result
                    download_success = False
                    download_error = None
                    download_completed = threading.Event()
                    
                    def on_download_complete(success: bool, message: str):
                        nonlocal download_success, download_error
                        download_success = success
                        download_error = message
                        download_completed.set()
                        
                    # Start download with progress dialog
                    try:
                        WireproxyDownloadManager.download_wireproxy_with_ui(
                            parent_window,
                            on_complete=on_download_complete
                        )
                        
                        # Wait for download to complete (with reasonable timeout)
                        logger.info("Waiting for wireproxy download to complete...")
                        if download_completed.wait(timeout=300):  # 5 minute timeout
                            if download_success:
                                logger.info("wireproxy download completed successfully")
                                # Try to find wireproxy again after download
                                wireproxy_path = ProcessManager.find_wireproxy_executable()
                                if not wireproxy_path:
                                    logger.error("wireproxy executable still not found after download")
                                    messagebox.showerror(
                                        "Download Issue",
                                        "wireproxy was downloaded but cannot be found.\n\n"
                                        "Please check the current directory and try again."
                                    )
                                    return None
                            else:
                                logger.error(f"wireproxy download failed: {download_error}")
                                # Error message already shown by download dialog
                                return None
                        else:
                            logger.error("wireproxy download timed out")
                            messagebox.showerror(
                                constants.DOWNLOAD_ERROR_TITLE,
                                "Download timed out. Please try again or download manually."
                            )
                            return None
                            
                    except Exception as e:
                        logger.exception("Error during wireproxy download")
                        messagebox.showerror(
                            constants.DOWNLOAD_ERROR_TITLE,
                            f"Download failed with error: {e}\n\n"
                            f"Please download manually from:\n{constants.GITHUB_RELEASES_URL}"
                        )
                        return None
                else:
                    logger.info("User chose not to download wireproxy")
                    messagebox.showwarning(
                        "wireproxy Required",
                        "wireproxy is required to create SOCKS5 proxies.\n\n"
                        "You can download it manually from:\n"
                        f"{constants.GITHUB_RELEASES_URL}\n\n"
                        "Place the executable in your PATH or in the same directory as this application."
                    )
                    return None

            # Validate the found executable
            if not wireproxy_path or not ProcessManager._validate_wireproxy_executable(wireproxy_path):
                logger.error(f"wireproxy executable validation failed: {wireproxy_path}")
                messagebox.showerror(
                    "Invalid wireproxy Executable",
                    "The wireproxy executable found is invalid or corrupted.\n\n"
                    "Please download a fresh copy from:\n"
                    f"{constants.GITHUB_RELEASES_URL}"
                )
                return None

            logger.info(f"Using validated wireproxy executable: {wireproxy_path}")

            # Create temporary config file with proper permissions
            with tempfile.NamedTemporaryFile(mode='w', suffix='.conf', delete=False) as f:
                f.write(config_content)
                config_file = f.name
                state.add_temp_file(config_file)

            # Set proper permissions on Linux (readable by owner only for security)
            if os.name != 'nt':
                os.chmod(config_file, stat.S_IRUSR | stat.S_IWUSR)

            logger.info(f"Created wireproxy config file: {config_file}")

            # Start process with platform-specific settings
            cmd = [wireproxy_path, '-c', config_file]
            logger.info(f"Starting wireproxy with command: {' '.join(cmd)}")

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
                # Process died immediately - get more info
                exit_code = process.returncode
                logger.error(f"wireproxy process failed to start immediately (exit code: {exit_code})")
                
                # Try to get some diagnostic info
                try:
                    # Test the executable directly
                    test_result = subprocess.run([wireproxy_path, '--version'], 
                                               capture_output=True, text=True, timeout=5)
                    if test_result.returncode != 0:
                        logger.error(f"wireproxy version check failed: {test_result.stderr}")
                except Exception as e:
                    logger.error(f"Failed to test wireproxy executable: {e}")
                
                messagebox.showerror(
                    "Process Start Failed",
                    f"wireproxy process failed to start (exit code: {exit_code}).\n\n"
                    "This could be due to:\n"
                    "• Invalid configuration\n"
                    "• Port already in use\n"
                    "• Insufficient permissions\n"
                    "• Corrupted executable\n\n"
                    "Check the log for more details."
                )
                return None

            process_info = ProcessInfo(
                process=process,
                config_file=config_file,
                start_time=time.time()
            )

            logger.info(f"Successfully started wireproxy process (PID: {process.pid})")
            return process_info

        except Exception as e:
            logger.exception(f"Error starting wireproxy process: {str(e)}")
            # Clean up config file if process failed to start
            if config_file and os.path.exists(config_file):
                try:
                    os.unlink(config_file)
                    logger.debug(f"Cleaned up failed config file: {config_file}")
                except OSError as cleanup_error:
                    logger.warning(f"Failed to cleanup config file: {cleanup_error}")
                    
            messagebox.showerror(
                "Process Start Error",
                f"Failed to start wireproxy process: {str(e)}\n\n"
                "Please check the log for more details."
            )
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