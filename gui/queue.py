"""Thread-safe message queue for GUI updates."""

import queue
from typing import List
from models import LogLevel


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