"""Collect logcat output for an Android package or process."""

from __future__ import annotations

from dataclasses import dataclass

from android_tool.core.adb import AdbDevice, execute_adb_shell, list_adb_devices
from android_tool.tools.app_export import AppExportError, validate_package_name
from android_tool.tools.app_list import AppListError, select_device


class AppLogError(RuntimeError):
    """Raised when log collection cannot be prepared."""


@dataclass(frozen=True)
class AppLogResult:
    """Logcat lines collected from one device."""

    package_name: str | None
    pid: str | None
    device: AdbDevice
    lines: list[str]
    pid_filter_used: bool
    crash_only: bool

    def to_dict(self) -> dict[str, object]:
        return {
            "package_name": self.package_name,
            "pid": self.pid,
            "device": self.device.to_dict(),
            "count": len(self.lines),
            "pid_filter_used": self.pid_filter_used,
            "crash_only": self.crash_only,
            "lines": self.lines,
        }


def parse_pids(output: str) -> list[str]:
    """Parse pidof output."""
    return [part for part in output.replace(",", " ").split() if part.isdigit()]


def filter_log_lines(
    output: str,
    package_name: str | None = None,
    crash_only: bool = False,
) -> list[str]:
    """Filter logcat output by package text and crash-related markers."""
    crash_markers = ("FATAL EXCEPTION", "AndroidRuntime", "ANR", "am_crash")
    lines: list[str] = []
    for raw_line in output.splitlines():
        line = raw_line.rstrip()
        if package_name and package_name not in line:
            continue
        if crash_only and not any(marker in line for marker in crash_markers):
            continue
        if line:
            lines.append(line)
    return lines


def build_logcat_command(
    lines: int = 200,
    pid: str | None = None,
    priority: str | None = None,
) -> list[str]:
    """Build a bounded logcat dump command."""
    if lines < 1:
        raise AppLogError("lines must be greater than zero")
    command = ["logcat", "-d", "-t", str(lines)]
    if pid:
        command.extend(["--pid", pid])
    if priority:
        command.append(f"*:{priority.upper()}")
    return command


def collect_app_logs(
    package_name: str | None = None,
    pid: str | None = None,
    serial: str | None = None,
    lines: int = 200,
    priority: str | None = None,
    crash_only: bool = False,
    timeout_seconds: float = 10.0,
) -> AppLogResult:
    """Collect a bounded logcat snapshot for a package or PID."""
    if not package_name and not pid:
        raise AppLogError("provide a package name or --pid")
    if package_name:
        try:
            validate_package_name(package_name)
        except AppExportError as exc:
            raise AppLogError(str(exc)) from exc
    if pid and not pid.isdigit():
        raise AppLogError(f"invalid PID: {pid}")

    try:
        device = select_device(list_adb_devices(timeout_seconds=timeout_seconds), serial)
    except AppListError as exc:
        raise AppLogError(str(exc)) from exc

    resolved_pid = pid
    if package_name and resolved_pid is None:
        pid_output = execute_adb_shell(
            device.serial,
            ["pidof", package_name],
            timeout_seconds=timeout_seconds,
        )
        pids = parse_pids(pid_output)
        resolved_pid = pids[0] if pids else None

    command = build_logcat_command(lines=lines, pid=resolved_pid, priority=priority)
    output = execute_adb_shell(device.serial, command, timeout_seconds=timeout_seconds)
    filtered = filter_log_lines(
        output,
        package_name=None if resolved_pid else package_name,
        crash_only=crash_only,
    )
    return AppLogResult(
        package_name=package_name,
        pid=resolved_pid,
        device=device,
        lines=filtered,
        pid_filter_used=resolved_pid is not None,
        crash_only=crash_only,
    )
