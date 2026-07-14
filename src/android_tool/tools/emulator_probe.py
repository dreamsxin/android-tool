"""Detect local Android emulator services by probing known port pairs."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass

from android_tool.core.network import is_tcp_port_open


@dataclass(frozen=True)
class ProbeOptions:
    """Configuration for local emulator service probing."""

    host: str = "127.0.0.1"
    start_port: int = 5554
    end_port: int = 5682
    timeout_seconds: float = 0.2


@dataclass(frozen=True)
class EmulatorProbeResult:
    """A detected emulator port pair."""

    host: str
    console_port: int
    adb_port: int
    console_open: bool
    adb_open: bool

    @property
    def console_target(self) -> str:
        return f"{self.host}:{self.console_port}"

    @property
    def adb_connect_target(self) -> str:
        return f"{self.host}:{self.adb_port}"

    @property
    def open_services(self) -> list[str]:
        services: list[str] = []
        if self.console_open:
            services.append("console")
        if self.adb_open:
            services.append("adb")
        return services

    def to_dict(self) -> dict[str, object]:
        return {
            "host": self.host,
            "console_port": self.console_port,
            "adb_port": self.adb_port,
            "console_open": self.console_open,
            "adb_open": self.adb_open,
            "console_target": self.console_target,
            "adb_connect_target": self.adb_connect_target,
            "open_services": self.open_services,
        }


def iter_console_ports(start_port: int, end_port: int) -> list[int]:
    """Return even console ports in the inclusive scan range."""
    if start_port > end_port:
        raise ValueError("start_port must be less than or equal to end_port")

    first_even = start_port if start_port % 2 == 0 else start_port + 1
    return list(range(first_even, end_port + 1, 2))


def probe_emulators(options: ProbeOptions) -> list[EmulatorProbeResult]:
    """Probe emulator console/adb port pairs and return detected services."""
    def probe_pair(console_port: int) -> EmulatorProbeResult | None:
        adb_port = console_port + 1
        console_open = is_tcp_port_open(options.host, console_port, options.timeout_seconds)
        adb_open = is_tcp_port_open(options.host, adb_port, options.timeout_seconds)
        if not console_open and not adb_open:
            return None
        return EmulatorProbeResult(
            host=options.host,
            console_port=console_port,
            adb_port=adb_port,
            console_open=console_open,
            adb_open=adb_open,
        )

    console_ports = iter_console_ports(options.start_port, options.end_port)
    if not console_ports:
        return []

    with ThreadPoolExecutor(max_workers=min(32, len(console_ports))) as executor:
        probed = executor.map(probe_pair, console_ports)
        return [result for result in probed if result is not None]
