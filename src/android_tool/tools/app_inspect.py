"""Inspect installed Android application metadata."""

from __future__ import annotations

import re
from dataclasses import dataclass

from android_tool.core.adb import AdbDevice, execute_adb_shell, list_adb_devices
from android_tool.tools.app_export import AppExportError, parse_apk_paths, validate_package_name
from android_tool.tools.app_list import AppListError, select_device


class AppInspectError(RuntimeError):
    """Raised when an application cannot be inspected."""


@dataclass(frozen=True)
class AppInspectResult:
    """Structured application information collected from package manager output."""

    package_name: str
    device: AdbDevice
    apk_paths: list[str]
    uid: int | None
    version_name: str | None
    version_code: str | None
    min_sdk: int | None
    target_sdk: int | None
    first_install_time: str | None
    last_update_time: str | None
    enabled: bool | None
    stopped: bool | None
    requested_permissions: list[str]
    granted_permissions: list[str]
    denied_permissions: list[str]
    components: dict[str, list[str]]

    def to_dict(self) -> dict[str, object]:
        return {
            "package_name": self.package_name,
            "device": self.device.to_dict(),
            "apk_paths": self.apk_paths,
            "uid": self.uid,
            "version_name": self.version_name,
            "version_code": self.version_code,
            "min_sdk": self.min_sdk,
            "target_sdk": self.target_sdk,
            "first_install_time": self.first_install_time,
            "last_update_time": self.last_update_time,
            "enabled": self.enabled,
            "stopped": self.stopped,
            "requested_permissions": self.requested_permissions,
            "granted_permissions": self.granted_permissions,
            "denied_permissions": self.denied_permissions,
            "components": self.components,
        }


def _first_match(pattern: str, output: str) -> str | None:
    match = re.search(pattern, output, flags=re.MULTILINE)
    return match.group(1).strip() if match else None


def _first_int(pattern: str, output: str) -> int | None:
    value = _first_match(pattern, output)
    return int(value) if value is not None else None


def parse_requested_permissions(output: str) -> list[str]:
    """Parse the requested permissions block from dumpsys package output."""
    permissions: list[str] = []
    in_block = False
    for raw_line in output.splitlines():
        line = raw_line.rstrip()
        stripped = line.strip()
        if stripped == "requested permissions:":
            in_block = True
            continue
        if not in_block:
            continue
        if not stripped:
            continue
        if not raw_line.startswith(" "):
            break
        if re.fullmatch(r"[A-Za-z0-9_.]+", stripped):
            permissions.append(stripped)
    return sorted(set(permissions))


def parse_permission_grants(output: str) -> tuple[list[str], list[str]]:
    """Parse granted and denied install/runtime permissions."""
    granted: set[str] = set()
    denied: set[str] = set()
    for match in re.finditer(
        r"^\s*([A-Za-z0-9_.]+):\s+granted=(true|false)\b",
        output,
        flags=re.MULTILINE,
    ):
        permission, state = match.groups()
        if state == "true":
            granted.add(permission)
        else:
            denied.add(permission)
    return sorted(granted), sorted(denied)


def parse_components(output: str, package_name: str) -> dict[str, list[str]]:
    """Best-effort extraction of package components from dumpsys package output."""
    section_map = {
        "Activity Resolver Table:": "activities",
        "Receiver Resolver Table:": "receivers",
        "Service Resolver Table:": "services",
        "Provider Resolver Table:": "providers",
        "activities:": "activities",
        "receivers:": "receivers",
        "services:": "services",
        "providers:": "providers",
    }
    components: dict[str, set[str]] = {
        "activities": set(),
        "receivers": set(),
        "services": set(),
        "providers": set(),
    }
    current_section: str | None = None
    component_pattern = re.compile(
        rf"\b{re.escape(package_name)}/[A-Za-z0-9_.$]+"
    )
    for raw_line in output.splitlines():
        stripped = raw_line.strip()
        if stripped in section_map:
            current_section = section_map[stripped]
            continue
        if stripped.endswith(":") and not raw_line.startswith(" "):
            current_section = None
        if current_section is None:
            continue
        for match in component_pattern.finditer(raw_line):
            components[current_section].add(match.group(0))
    return {kind: sorted(values) for kind, values in components.items()}


def parse_app_state(output: str) -> tuple[bool | None, bool | None]:
    """Parse enabled/stopped state when present in dumpsys package output."""
    enabled_value = _first_match(r"\benabled=(\d+)", output)
    enabled = None if enabled_value is None else enabled_value != "0"
    stopped_value = _first_match(r"\bstopped=(true|false)", output)
    stopped = None if stopped_value is None else stopped_value == "true"
    return enabled, stopped


def inspect_app(
    package_name: str,
    serial: str | None = None,
    timeout_seconds: float = 10.0,
) -> AppInspectResult:
    """Inspect an installed application on a selected online device."""
    try:
        validate_package_name(package_name)
    except AppExportError as exc:
        raise AppInspectError(str(exc)) from exc
    try:
        device = select_device(list_adb_devices(timeout_seconds=timeout_seconds), serial)
    except AppListError as exc:
        raise AppInspectError(str(exc)) from exc

    apk_output = execute_adb_shell(
        device.serial, ["pm", "path", package_name], timeout_seconds=timeout_seconds
    )
    apk_paths = parse_apk_paths(apk_output)
    if not apk_paths:
        raise AppInspectError(f"package is not installed on {device.serial}: {package_name}")

    package_output = execute_adb_shell(
        device.serial,
        ["dumpsys", "package", package_name],
        timeout_seconds=timeout_seconds,
    )
    uid = _first_int(r"\buserId=(\d+)", package_output) or _first_int(
        r"\buid=(\d+)", package_output
    )
    granted, denied = parse_permission_grants(package_output)
    enabled, stopped = parse_app_state(package_output)
    return AppInspectResult(
        package_name=package_name,
        device=device,
        apk_paths=apk_paths,
        uid=uid,
        version_name=_first_match(r"\bversionName=([^\s]+)", package_output),
        version_code=_first_match(r"\bversionCode=([^\s]+)", package_output),
        min_sdk=_first_int(r"\bminSdk=(\d+)", package_output),
        target_sdk=_first_int(r"\btargetSdk=(\d+)", package_output),
        first_install_time=_first_match(r"\bfirstInstallTime=([^\n]+)", package_output),
        last_update_time=_first_match(r"\blastUpdateTime=([^\n]+)", package_output),
        enabled=enabled,
        stopped=stopped,
        requested_permissions=parse_requested_permissions(package_output),
        granted_permissions=granted,
        denied_permissions=denied,
        components=parse_components(package_output, package_name),
    )
