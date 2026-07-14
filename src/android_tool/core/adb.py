"""ADB executable discovery and device listing helpers."""

from __future__ import annotations

import os
import shlex
import shutil
import socket
import struct
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import BinaryIO, Callable


class AdbError(RuntimeError):
    """Base error raised while invoking ADB."""


class AdbNotFoundError(AdbError):
    """Raised when no ADB executable can be located."""


class AdbServerError(AdbError):
    """Raised when the local ADB server cannot answer a request."""


@dataclass(frozen=True)
class AdbStreamResult:
    """Result of a streamed ADB shell-v2 command."""

    exit_code: int
    stderr: str
    bytes_written: int


@dataclass(frozen=True)
class AdbDevice:
    """One row returned by ``adb devices -l``."""

    serial: str
    state: str
    attributes: dict[str, str]

    @property
    def is_emulator(self) -> bool:
        return self.serial.startswith("emulator-") or self.serial.startswith(
            ("127.0.0.1:", "localhost:", "[::1]:")
        )

    @property
    def connect_target(self) -> str | None:
        if self.serial.startswith("emulator-"):
            try:
                console_port = int(self.serial.removeprefix("emulator-"))
            except ValueError:
                return None
            return f"127.0.0.1:{console_port + 1}"

        if self.serial.startswith(("127.0.0.1:", "localhost:", "[::1]:")):
            return self.serial
        return None

    def to_dict(self) -> dict[str, object]:
        return {
            "serial": self.serial,
            "state": self.state,
            "attributes": self.attributes,
            "is_emulator": self.is_emulator,
            "connect_target": self.connect_target,
        }


def find_adb_executable() -> str:
    """Find ADB in PATH or a configured Android SDK."""
    executable_name = "adb.exe" if os.name == "nt" else "adb"
    configured_adb = os.environ.get("ADB")
    if configured_adb and Path(configured_adb).is_file():
        return configured_adb

    path_result = shutil.which("adb")
    if path_result:
        return path_result

    for variable in ("ANDROID_SDK_ROOT", "ANDROID_HOME"):
        sdk_root = os.environ.get(variable)
        if not sdk_root:
            continue
        candidate = Path(sdk_root) / "platform-tools" / executable_name
        if candidate.is_file():
            return str(candidate)

    if os.name == "nt" and (local_app_data := os.environ.get("LOCALAPPDATA")):
        candidate = Path(local_app_data) / "Android" / "Sdk" / "platform-tools" / executable_name
        if candidate.is_file():
            return str(candidate)

    raise AdbNotFoundError(
        "adb was not found; add Android SDK platform-tools to PATH or set "
        "ANDROID_SDK_ROOT or ADB"
    )


def parse_adb_devices(output: str) -> list[AdbDevice]:
    """Parse the output of ``adb devices -l``."""
    devices: list[AdbDevice] = []
    for raw_line in output.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("List of devices attached") or line.startswith("*"):
            continue

        fields = line.split()
        if len(fields) < 2:
            continue

        attributes: dict[str, str] = {}
        for field in fields[2:]:
            key, separator, value = field.partition(":")
            if separator:
                attributes[key] = value

        devices.append(AdbDevice(serial=fields[0], state=fields[1], attributes=attributes))
    return devices


def _receive_exact(connection: socket.socket, byte_count: int) -> bytes:
    chunks: list[bytes] = []
    remaining = byte_count
    while remaining:
        chunk = connection.recv(remaining)
        if not chunk:
            raise AdbServerError("ADB server closed the connection unexpectedly")
        chunks.append(chunk)
        remaining -= len(chunk)
    return b"".join(chunks)


def _send_adb_request(connection: socket.socket, request: str) -> None:
    encoded_request = request.encode("utf-8")
    connection.sendall(f"{len(encoded_request):04x}".encode("ascii") + encoded_request)


def _read_adb_status(connection: socket.socket, operation: str) -> None:
    status = _receive_exact(connection, 4)
    if status == b"OKAY":
        return
    if status == b"FAIL":
        response_length = int(_receive_exact(connection, 4), 16)
        response = _receive_exact(connection, response_length).decode("utf-8", errors="replace")
        raise AdbServerError(f"ADB server rejected {operation}: {response}")
    raise AdbServerError(f"unexpected ADB server response during {operation}: {status!r}")


def query_adb_server(
    host: str = "127.0.0.1",
    port: int | None = None,
    timeout_seconds: float = 3.0,
) -> list[AdbDevice]:
    """Query the ADB host protocol without starting another process."""
    server_port = port or int(os.environ.get("ANDROID_ADB_SERVER_PORT", "5037"))

    try:
        with socket.create_connection((host, server_port), timeout_seconds) as connection:
            _send_adb_request(connection, "host:devices-l")
            _read_adb_status(connection, "device listing")
            response_length = int(_receive_exact(connection, 4), 16)
            response = _receive_exact(connection, response_length).decode("utf-8", errors="replace")
    except AdbServerError:
        raise
    except (OSError, ValueError) as exc:
        raise AdbServerError(f"could not query ADB server at {host}:{server_port}") from exc

    return parse_adb_devices(response)


def execute_adb_shell(
    serial: str,
    arguments: list[str],
    host: str = "127.0.0.1",
    port: int | None = None,
    timeout_seconds: float = 10.0,
) -> str:
    """Execute a shell command through the running ADB server."""
    if not arguments:
        raise ValueError("arguments must not be empty")

    server_port = port or int(os.environ.get("ANDROID_ADB_SERVER_PORT", "5037"))
    command = shlex.join(arguments)
    chunks: list[bytes] = []
    try:
        with socket.create_connection((host, server_port), timeout_seconds) as connection:
            _send_adb_request(connection, f"host:transport:{serial}")
            _read_adb_status(connection, f"device selection for {serial}")
            _send_adb_request(connection, f"shell:{command}")
            _read_adb_status(connection, command)
            while chunk := connection.recv(65536):
                chunks.append(chunk)
    except AdbServerError:
        raise
    except OSError as exc:
        raise AdbServerError(f"could not execute shell command on {serial}: {exc}") from exc

    return b"".join(chunks).decode("utf-8", errors="replace")


def stream_adb_shell(
    serial: str,
    arguments: list[str],
    destination: BinaryIO,
    host: str = "127.0.0.1",
    port: int | None = None,
    timeout_seconds: float = 30.0,
    progress: Callable[[int], None] | None = None,
) -> AdbStreamResult:
    """Stream stdout from a shell-v2 command while retaining exit status and stderr."""
    if not arguments:
        raise ValueError("arguments must not be empty")

    server_port = port or int(os.environ.get("ANDROID_ADB_SERVER_PORT", "5037"))
    command = shlex.join(arguments)
    bytes_written = 0
    stderr_chunks: list[bytes] = []
    exit_code: int | None = None

    try:
        with socket.create_connection((host, server_port), timeout_seconds) as connection:
            _send_adb_request(connection, f"host:transport:{serial}")
            _read_adb_status(connection, f"device selection for {serial}")
            _send_adb_request(connection, f"shell,v2,raw:{command}")
            _read_adb_status(connection, command)

            while True:
                header = connection.recv(5)
                if not header:
                    break
                if len(header) < 5:
                    header += _receive_exact(connection, 5 - len(header))
                stream_id = header[0]
                payload_length = struct.unpack("<I", header[1:])[0]
                payload = _receive_exact(connection, payload_length)

                if stream_id == 1:
                    destination.write(payload)
                    bytes_written += len(payload)
                    if progress:
                        progress(bytes_written)
                elif stream_id == 2:
                    stderr_chunks.append(payload)
                elif stream_id == 3:
                    exit_code = payload[0] if payload else 0
    except AdbServerError:
        raise
    except OSError as exc:
        raise AdbServerError(f"could not stream shell command on {serial}: {exc}") from exc

    if exit_code is None:
        raise AdbServerError(f"ADB shell command ended without an exit status: {command}")
    return AdbStreamResult(
        exit_code=exit_code,
        stderr=b"".join(stderr_chunks).decode("utf-8", errors="replace").strip(),
        bytes_written=bytes_written,
    )


def list_adb_devices(adb_path: str | None = None, timeout_seconds: float = 3.0) -> list[AdbDevice]:
    """Return devices from the running ADB server, starting it when necessary."""
    try:
        return query_adb_server(timeout_seconds=timeout_seconds)
    except AdbServerError:
        pass

    executable = adb_path or find_adb_executable()
    try:
        completed = subprocess.run(
            [executable, "devices", "-l"],
            check=False,
            capture_output=True,
            text=True,
            timeout=timeout_seconds,
        )
    except subprocess.TimeoutExpired as exc:
        raise AdbError(f"adb devices timed out after {timeout_seconds:g} seconds") from exc
    except OSError as exc:
        raise AdbError(f"failed to run adb: {exc}") from exc

    if completed.returncode != 0:
        message = completed.stderr.strip() or completed.stdout.strip() or "unknown error"
        raise AdbError(f"adb devices failed: {message}")
    return parse_adb_devices(completed.stdout)
