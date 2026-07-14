"""List applications installed on an Android device."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from android_tool.core.adb import AdbDevice, execute_adb_shell, list_adb_devices

PackageScope = Literal["all", "third-party", "system"]


class AppListError(RuntimeError):
    """Raised when an installed-package query cannot be prepared."""


@dataclass(frozen=True)
class InstalledPackage:
    """An installed Android package."""

    package_name: str
    apk_path: str | None = None

    def to_dict(self) -> dict[str, object]:
        return {"package_name": self.package_name, "apk_path": self.apk_path}


@dataclass(frozen=True)
class AppListResult:
    """Installed packages returned for one device."""

    device: AdbDevice
    scope: PackageScope
    packages: list[InstalledPackage]

    def to_dict(self) -> dict[str, object]:
        return {
            "device": self.device.to_dict(),
            "scope": self.scope,
            "count": len(self.packages),
            "packages": [package.to_dict() for package in self.packages],
        }


def select_device(devices: list[AdbDevice], serial: str | None = None) -> AdbDevice:
    """Select an online device, requiring a serial when several are ready."""
    if serial:
        matching = next((device for device in devices if device.serial == serial), None)
        if matching is None:
            raise AppListError(f"device not found: {serial}")
        if matching.state != "device":
            raise AppListError(f"device {serial} is not ready: state={matching.state}")
        return matching

    ready_devices = [device for device in devices if device.state == "device"]
    if not ready_devices:
        raise AppListError("no online Android devices found")
    if len(ready_devices) > 1:
        serials = ", ".join(device.serial for device in ready_devices)
        raise AppListError(f"multiple devices found; use --serial with one of: {serials}")
    return ready_devices[0]


def parse_package_list(output: str) -> list[InstalledPackage]:
    """Parse output from ``pm list packages`` with or without ``-f``."""
    packages: list[InstalledPackage] = []
    for raw_line in output.splitlines():
        line = raw_line.strip()
        if not line.startswith("package:"):
            continue

        value = line.removeprefix("package:")
        if "=" in value:
            apk_path, package_name = value.rsplit("=", 1)
            packages.append(InstalledPackage(package_name=package_name, apk_path=apk_path))
        elif value:
            packages.append(InstalledPackage(package_name=value))
    return sorted(packages, key=lambda package: package.package_name.casefold())


def build_package_command(scope: PackageScope, include_path: bool) -> list[str]:
    """Build a package-manager command from supported filters."""
    command = ["pm", "list", "packages"]
    if include_path:
        command.append("-f")
    if scope == "third-party":
        command.append("-3")
    elif scope == "system":
        command.append("-s")
    elif scope != "all":
        raise ValueError(f"unsupported package scope: {scope}")
    return command


def list_installed_packages(
    serial: str | None = None,
    scope: PackageScope = "all",
    include_path: bool = False,
    timeout_seconds: float = 10.0,
) -> AppListResult:
    """List installed packages on a selected online device."""
    device = select_device(list_adb_devices(timeout_seconds=timeout_seconds), serial)
    command = build_package_command(scope, include_path)
    output = execute_adb_shell(device.serial, command, timeout_seconds=timeout_seconds)
    return AppListResult(
        device=device,
        scope=scope,
        packages=parse_package_list(output),
    )
