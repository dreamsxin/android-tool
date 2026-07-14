"""Small networking helpers used by local diagnostic tools."""

from __future__ import annotations

import socket
from contextlib import closing


def is_tcp_port_open(host: str, port: int, timeout_seconds: float) -> bool:
    """Return whether a TCP connection can be established."""
    with closing(socket.socket(socket.AF_INET, socket.SOCK_STREAM)) as sock:
        sock.settimeout(timeout_seconds)
        return sock.connect_ex((host, port)) == 0
