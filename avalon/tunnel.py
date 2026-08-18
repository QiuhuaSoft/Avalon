from __future__ import annotations

import re
import subprocess
import threading
from dataclasses import dataclass
from typing import Optional

URL_PATTERN = re.compile(r"https://[\w.-]+\.trycloudflare\.com")


@dataclass
class TunnelStatus:
    running: bool
    public_url: Optional[str]
    error: Optional[str]


class TunnelManager:
    def __init__(self, target_url: str) -> None:
        self._target_url = target_url
        self._process: Optional[subprocess.Popen[str]] = None
        self._public_url: Optional[str] = None
        self._error: Optional[str] = None
        self._lock = threading.RLock()
        self._reader_thread: Optional[threading.Thread] = None

    def start(self) -> TunnelStatus:
        with self._lock:
            if self._process and self._process.poll() is None:
                return self.status()
            self._public_url = None
            self._error = None
            try:
                self._process = subprocess.Popen(
                    ["cloudflared", "tunnel", "--url", self._target_url],
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT,
                    text=True,
                    bufsize=1,
                )
            except FileNotFoundError:
                self._error = "未找到 cloudflared。请安装它或使用 localhost.run。"
                return self.status()
            self._reader_thread = threading.Thread(target=self._read_output, daemon=True)
            self._reader_thread.start()
            return self.status()

    def _read_output(self) -> None:
        if not self._process or not self._process.stdout:
            return
        for line in self._process.stdout:
            match = URL_PATTERN.search(line)
            if match:
                with self._lock:
                    self._public_url = match.group(0)
            if self._process.poll() is not None:
                break

    def status(self) -> TunnelStatus:
        with self._lock:
            running = self._process is not None and self._process.poll() is None
            return TunnelStatus(running=running, public_url=self._public_url, error=self._error)

    def stop(self) -> TunnelStatus:
        with self._lock:
            if self._process and self._process.poll() is None:
                self._process.terminate()
            return self.status()
