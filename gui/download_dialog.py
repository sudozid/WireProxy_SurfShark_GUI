"""Download dialog for wireproxy with real-time progress and cancellation support."""

import tkinter as tk
from tkinter import ttk, messagebox
import threading
import time
import urllib.request
import urllib.error
import json
import platform
import tarfile
import tempfile
import os
import hashlib
import logging
from typing import Optional, Callable

import constants

logger = logging.getLogger(__name__)


class DownloadProgressDialog:
    """Non-blocking download dialog with progress bar and cancellation"""
    
    def __init__(self, parent: tk.Tk, title: str = "Downloading wireproxy"):
        self.parent = parent
        self.dialog = None
        self.progress_var = None
        self.status_var = None
        self.progress_bar = None
        self.cancel_button = None
        self.close_button = None
        
        # Threading control
        self.download_thread = None
        self.cancel_event = threading.Event()
        self.download_success = False
        self.download_error = None
        
        # Download state
        self.total_size = 0
        self.downloaded_size = 0
        
        # Callbacks
        self.on_success: Optional[Callable] = None
        self.on_error: Optional[Callable[[str], None]] = None
        self.on_cancel: Optional[Callable] = None
        
        self._create_dialog(title)
        
    def _create_dialog(self, title: str):
        """Create the download dialog window"""
        self.dialog = tk.Toplevel(self.parent)
        self.dialog.title(title)
        self.dialog.geometry("500x250")
        self.dialog.transient(self.parent)
        self.dialog.grab_set()
        self.dialog.protocol("WM_DELETE_WINDOW", self._on_close)
        
        # Center the dialog
        self.dialog.update_idletasks()
        x = (self.dialog.winfo_screenwidth() // 2) - (500 // 2)
        y = (self.dialog.winfo_screenheight() // 2) - (250 // 2)
        self.dialog.geometry(f"500x250+{x}+{y}")
        
        # Main frame
        main_frame = ttk.Frame(self.dialog, padding="20")
        main_frame.pack(fill=tk.BOTH, expand=True)
        
        # Title
        title_label = ttk.Label(main_frame, text="Downloading wireproxy", 
                               font=("Arial", 12, "bold"))
        title_label.pack(pady=(0, 10))
        
        # Status label
        self.status_var = tk.StringVar(value="Preparing download...")
        status_label = ttk.Label(main_frame, textvariable=self.status_var, 
                                wraplength=450)
        status_label.pack(pady=(0, 10))
        
        # Progress bar
        self.progress_var = tk.DoubleVar()
        self.progress_bar = ttk.Progressbar(main_frame, variable=self.progress_var,
                                          maximum=100, length=400)
        self.progress_bar.pack(pady=(0, 10))
        
        # Progress text
        self.progress_text_var = tk.StringVar(value="0% (0 / 0 MB)")
        progress_text_label = ttk.Label(main_frame, textvariable=self.progress_text_var)
        progress_text_label.pack(pady=(0, 15))
        
        # Button frame
        button_frame = ttk.Frame(main_frame)
        button_frame.pack(pady=(10, 0))
        
        self.cancel_button = ttk.Button(button_frame, text="Cancel", 
                                       command=self._cancel_download)
        self.cancel_button.pack(side=tk.LEFT, padx=(0, 10))
        
        self.close_button = ttk.Button(button_frame, text="Close", 
                                      command=self._close_dialog, state=tk.DISABLED)
        self.close_button.pack(side=tk.LEFT)
        
    def _on_close(self):
        """Handle window close event"""
        if self.download_thread and self.download_thread.is_alive():
            self._cancel_download()
        else:
            self._close_dialog()
            
    def _cancel_download(self):
        """Cancel the download"""
        logger.info("User cancelled wireproxy download")
        self.cancel_event.set()
        self.status_var.set("Cancelling download...")
        self.cancel_button.config(state=tk.DISABLED)
        
        if self.on_cancel:
            self.on_cancel()
            
    def _close_dialog(self):
        """Close the dialog"""
        if self.dialog:
            self.dialog.destroy()
            self.dialog = None
            
    def _update_progress(self, downloaded: int, total: int):
        """Update progress display (called from download thread)"""
        def update_ui():
            if self.dialog and not self.cancel_event.is_set():
                self.downloaded_size = downloaded
                self.total_size = total
                
                if total > 0:
                    percentage = (downloaded / total) * 100
                    self.progress_var.set(percentage)
                    
                    # Convert to MB
                    downloaded_mb = downloaded / (1024 * 1024)
                    total_mb = total / (1024 * 1024)
                    
                    self.progress_text_var.set(f"{percentage:.1f}% ({downloaded_mb:.1f} / {total_mb:.1f} MB)")
                else:
                    self.progress_bar.config(mode='indeterminate')
                    self.progress_bar.start()
                    
        if self.dialog:
            self.dialog.after(0, update_ui)
            
    def _update_status(self, status: str):
        """Update status text (called from download thread)"""
        def update_ui():
            if self.dialog and not self.cancel_event.is_set():
                self.status_var.set(status)
                
        if self.dialog:
            self.dialog.after(0, update_ui)
            
    def _download_complete(self, success: bool, error_msg: str = None):
        """Handle download completion (called from download thread)"""
        def update_ui():
            if not self.dialog:
                return
                
            self.download_success = success
            self.download_error = error_msg
            
            if success:
                self.status_var.set("✓ Download completed successfully!")
                self.progress_var.set(100)
                self.progress_text_var.set("100% - Complete")
                
                if self.on_success:
                    self.on_success()
            else:
                self.status_var.set(f"✗ Download failed: {error_msg}")
                self.progress_var.set(0)
                
                if self.on_error:
                    self.on_error(error_msg)
                    
            # Enable close button, disable cancel
            self.cancel_button.config(state=tk.DISABLED)
            self.close_button.config(state=tk.NORMAL)
            
        if self.dialog:
            self.dialog.after(0, update_ui)
            
    def start_download(self, download_url: str, output_path: str, 
                      on_success: Optional[Callable] = None,
                      on_error: Optional[Callable[[str], None]] = None,
                      on_cancel: Optional[Callable] = None):
        """Start the download in a background thread"""
        self.on_success = on_success
        self.on_error = on_error
        self.on_cancel = on_cancel
        
        logger.info(f"Starting wireproxy download: {download_url}")
        
        self.download_thread = threading.Thread(
            target=self._download_worker,
            args=(download_url, output_path),
            daemon=True
        )
        self.download_thread.start()
        
    def _download_worker(self, download_url: str, output_path: str):
        """Download worker thread"""
        try:
            self._update_status("Connecting to GitHub...")
            
            # Create request with proper headers
            headers = {
                'User-Agent': f'{constants.APP_NAME}/{constants.APP_VERSION}',
                'Accept': 'application/octet-stream'
            }
            
            req = urllib.request.Request(download_url, headers=headers)
            
            # Check if cancelled before starting
            if self.cancel_event.is_set():
                return
                
            # Open connection
            try:
                response = urllib.request.urlopen(req, timeout=30)
            except urllib.error.URLError as e:
                error_msg = f"Connection failed: {e.reason}"
                logger.error(error_msg)
                self._download_complete(False, error_msg)
                return
                
            # Get file size
            content_length = response.headers.get('Content-Length')
            if content_length:
                total_size = int(content_length)
                self._update_status(f"Downloading {total_size / (1024*1024):.1f} MB...")
            else:
                total_size = 0
                self._update_status("Downloading...")
                
            # Download in chunks
            downloaded = 0
            chunk_size = 8192
            
            try:
                with open(output_path, 'wb') as f:
                    while True:
                        if self.cancel_event.is_set():
                            logger.info("Download cancelled by user")
                            try:
                                os.unlink(output_path)
                            except OSError:
                                pass
                            return
                            
                        chunk = response.read(chunk_size)
                        if not chunk:
                            break
                            
                        f.write(chunk)
                        downloaded += len(chunk)
                        
                        # Update progress
                        self._update_progress(downloaded, total_size)
                        
            except IOError as e:
                error_msg = f"File write error: {e}"
                logger.error(error_msg)
                self._download_complete(False, error_msg)
                return
                
            # Verify download
            if self.cancel_event.is_set():
                return
                
            self._update_status("Verifying download...")
            
            # Basic verification
            if not os.path.exists(output_path):
                self._download_complete(False, "Downloaded file not found")
                return
                
            file_size = os.path.getsize(output_path)
            if file_size < 1024:  # Less than 1KB is suspicious
                self._download_complete(False, "Downloaded file is too small")
                return
                
            if total_size > 0 and abs(file_size - total_size) > 1024:  # Allow 1KB difference
                self._download_complete(False, f"File size mismatch: expected {total_size}, got {file_size}")
                return
                
            logger.info(f"Download completed: {output_path} ({file_size} bytes)")
            self._download_complete(True)
            
        except Exception as e:
            error_msg = f"Unexpected error: {e}"
            logger.exception("Download worker error")
            self._download_complete(False, error_msg)


class WireproxyDownloadManager:
    """Manages wireproxy download with platform detection and UI integration"""
    
    @staticmethod
    def detect_platform_and_architecture():
        """Detect current platform and architecture for wireproxy download"""
        system = platform.system().lower()
        machine = platform.machine().lower()
        
        logger.info(f"Detected platform: {system}, architecture: {machine}")
        
        # Map platform/arch to GitHub release filename
        if system == "windows":
            if "64" in machine or "amd64" in machine or "x86_64" in machine:
                filename = constants.FILENAME_TEMPLATE_WINDOWS_AMD64
            else:
                filename = constants.FILENAME_TEMPLATE_WINDOWS_386
            exe_name = constants.EXE_NAME_WINDOWS
        elif system == "linux":
            if "aarch64" in machine or "arm64" in machine:
                filename = constants.FILENAME_TEMPLATE_LINUX_ARM64
            elif "arm" in machine:
                filename = constants.FILENAME_TEMPLATE_LINUX_ARM
            elif "mips" in machine:
                if "mipsle" in machine:
                    filename = constants.FILENAME_TEMPLATE_LINUX_MIPSLE
                else:
                    filename = constants.FILENAME_TEMPLATE_LINUX_MIPS
            elif "riscv64" in machine:
                filename = constants.FILENAME_TEMPLATE_LINUX_RISCV64
            elif "s390x" in machine:
                filename = constants.FILENAME_TEMPLATE_LINUX_S390X
            elif "386" in machine or "i386" in machine:
                filename = constants.FILENAME_TEMPLATE_LINUX_386
            else:  # Default to amd64
                filename = constants.FILENAME_TEMPLATE_LINUX_AMD64
            exe_name = constants.EXE_NAME_LINUX
        elif system == "darwin":  # macOS
            if "arm64" in machine or "aarch64" in machine:
                filename = constants.FILENAME_TEMPLATE_MACOS_ARM64
            else:
                filename = constants.FILENAME_TEMPLATE_MACOS_AMD64
            exe_name = constants.EXE_NAME_MACOS
        else:
            raise ValueError(f"Unsupported platform: {system}")
            
        return filename, exe_name
        
    @staticmethod
    def get_latest_release_info():
        """Get latest wireproxy release information from GitHub API"""
        try:
            logger.info("Fetching latest wireproxy release info...")
            
            headers = {
                'User-Agent': f'{constants.APP_NAME}/{constants.APP_VERSION}',
                'Accept': 'application/vnd.github.v3+json'
            }
            
            req = urllib.request.Request(constants.GITHUB_API_URL, headers=headers)
            
            with urllib.request.urlopen(req, timeout=10) as response:
                release_data = json.loads(response.read().decode())
                
            latest_version = release_data.get('tag_name', 'unknown')
            logger.info(f"Latest wireproxy version: {latest_version}")
            
            return release_data
            
        except Exception as e:
            logger.warning(f"Failed to get latest release info: {e}")
            # Return fallback data
            return {
                'tag_name': 'v1.0.9',
                'assets': [],
                'published_at': 'unknown'
            }
            
    @staticmethod
    def find_download_url(release_data: dict, filename: str):
        """Find download URL for specific filename from release data"""
        # Try to find in assets first
        for asset in release_data.get('assets', []):
            if asset['name'] == filename:
                return asset['browser_download_url']
                
        # Fallback to constructed URL
        version = release_data.get('tag_name', 'v1.0.9')
        download_url = f"https://github.com/whyvl/wireproxy/releases/download/{version}/{filename}"
        logger.info(f"Using constructed download URL: {download_url}")
        
        return download_url
        
    @staticmethod
    def extract_wireproxy_executable(tar_path: str, exe_name: str):
        """Extract wireproxy executable from downloaded tar.gz file"""
        logger.info(f"Extracting wireproxy from {tar_path}")
        
        try:
            with tarfile.open(tar_path, 'r:gz') as tar:
                # Find wireproxy executable
                for member in tar.getmembers():
                    if member.name.endswith(exe_name) and member.isfile():
                        # Extract to current directory with correct name
                        member.name = exe_name
                        tar.extract(member, path='.')
                        logger.info(f"Extracted {exe_name}")
                        
                        # Make executable on Unix systems
                        if os.name != 'nt':
                            os.chmod(exe_name, 0o755)
                            logger.info(f"Set executable permissions for {exe_name}")
                            
                        return True
                        
            logger.error(f"wireproxy executable ({exe_name}) not found in {tar_path}")
            return False
            
        except Exception as e:
            logger.error(f"Failed to extract wireproxy: {e}")
            return False
            
    @staticmethod
    def show_download_prompt(parent: tk.Tk) -> bool:
        """Show download prompt to user and return their choice"""
        result = messagebox.askyesno(
            "Missing wireproxy Executable",
            "wireproxy executable not found in PATH or current directory.\n\n"
            "wireproxy is required to create SOCKS5 proxies through WireGuard connections.\n\n"
            "Would you like to download the latest version automatically?\n\n"
            "• Yes: Download from GitHub (recommended)\n"
            "• No: Continue without wireproxy (proxy creation will fail)",
            icon=messagebox.QUESTION
        )
        
        logger.info(f"User download choice: {'Yes' if result else 'No'}")
        return result
        
    @staticmethod
    def download_wireproxy_with_ui(parent: tk.Tk, on_complete: Optional[Callable[[bool, str], None]] = None):
        """Download wireproxy with progress dialog"""
        logger.info("Starting wireproxy download with UI...")
        
        try:
            # Validate parent window
            if not parent or not hasattr(parent, 'winfo_exists') or not parent.winfo_exists():
                error_msg = "Invalid parent window for download dialog"
                logger.error(error_msg)
                if on_complete:
                    on_complete(False, error_msg)
                return
                
            # Detect platform
            logger.info("Detecting platform and architecture...")
            filename, exe_name = WireproxyDownloadManager.detect_platform_and_architecture()
            logger.info(f"Target file: {filename}, executable: {exe_name}")
            
            # Get release info
            logger.info("Fetching release information...")
            release_data = WireproxyDownloadManager.get_latest_release_info()
            
            if not release_data:
                error_msg = "Failed to get release information"
                logger.error(error_msg)
                if on_complete:
                    on_complete(False, error_msg)
                return
            
            # Find download URL
            logger.info("Finding download URL...")
            download_url = WireproxyDownloadManager.find_download_url(release_data, filename)
            
            if not download_url:
                error_msg = f"No download URL found for {filename}"
                logger.error(error_msg)
                if on_complete:
                    on_complete(False, error_msg)
                return
                
            logger.info(f"Download URL: {download_url}")
            
            # Create temporary file for download
            temp_file = tempfile.mktemp(suffix='.tar.gz')
            logger.info(f"Temporary file: {temp_file}")
            
            # Create download dialog
            logger.info("Creating download dialog...")
            download_dialog = DownloadProgressDialog(parent, f"Downloading {filename}")
            
            if not download_dialog.dialog:
                error_msg = "Failed to create download dialog"
                logger.error(error_msg)
                if on_complete:
                    on_complete(False, error_msg)
                return
            
            def on_success():
                """Handle successful download"""
                try:
                    # Extract executable
                    if WireproxyDownloadManager.extract_wireproxy_executable(temp_file, exe_name):
                        # Clean up temp file
                        try:
                            os.unlink(temp_file)
                        except OSError:
                            pass
                            
                        logger.info("wireproxy download and extraction completed successfully")
                        
                        if on_complete:
                            on_complete(True, exe_name)
                            
                        # Show success message
                        messagebox.showinfo(
                            constants.DOWNLOAD_SUCCESS_TITLE,
                            f"wireproxy downloaded successfully!\n\n"
                            f"Location: {os.path.abspath(exe_name)}\n"
                            f"Version: {release_data.get('tag_name', 'unknown')}"
                        )
                    else:
                        error_msg = "Failed to extract wireproxy executable"
                        logger.error(error_msg)
                        
                        if on_complete:
                            on_complete(False, error_msg)
                            
                        messagebox.showerror(
                            constants.DOWNLOAD_ERROR_TITLE,
                            f"Extraction failed: {error_msg}"
                        )
                        
                except Exception as e:
                    error_msg = f"Post-download processing failed: {e}"
                    logger.exception("Post-download processing error")
                    
                    if on_complete:
                        on_complete(False, error_msg)
                        
                    messagebox.showerror(
                        constants.DOWNLOAD_ERROR_TITLE,
                        error_msg
                    )
                    
            def on_error(error_msg: str):
                """Handle download error"""
                logger.error(f"Download failed: {error_msg}")
                
                # Clean up temp file
                try:
                    os.unlink(temp_file)
                except OSError:
                    pass
                    
                if on_complete:
                    on_complete(False, error_msg)
                    
                messagebox.showerror(
                    constants.DOWNLOAD_ERROR_TITLE,
                    f"Download failed: {error_msg}\n\n"
                    f"Please download manually from:\n"
                    f"{constants.GITHUB_RELEASES_URL}"
                )
                
            def on_cancel():
                """Handle download cancellation"""
                logger.info("Download cancelled by user")
                
                # Clean up temp file
                try:
                    os.unlink(temp_file)
                except OSError:
                    pass
                    
                if on_complete:
                    on_complete(False, "Download cancelled by user")
                    
            # Start download
            download_dialog.start_download(
                download_url, 
                temp_file,
                on_success=on_success,
                on_error=on_error,
                on_cancel=on_cancel
            )
            
        except Exception as e:
            error_msg = f"Failed to initiate download: {e}"
            logger.exception("Download initiation error")
            
            if on_complete:
                on_complete(False, error_msg)
                
            messagebox.showerror(
                constants.DOWNLOAD_ERROR_TITLE,
                error_msg
            )