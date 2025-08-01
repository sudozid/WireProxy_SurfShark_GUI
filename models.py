"""Data models and enums for the WireProxy SurfShark GUI application."""

import subprocess
from datetime import datetime
from dataclasses import dataclass, asdict
from enum import Enum
from typing import Dict, List, Optional, Any


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
    high_cpu_start: Optional[float] = None


@dataclass
class AppSettings:
    start_minimized: bool = False
    minimize_to_tray: bool = True
    auto_start_proxies: bool = True
    log_level: LogLevel = LogLevel.DEBUG
    api_endpoint: str = "https://api.surfshark.com/v4/server/clusters/generic"
    dark_mode: bool = False