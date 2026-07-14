"""Install or uninstall Android application packages."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from android_tool.core.adb import AdbCommandResult, AdbDevice, execute_adb_command, list_adb_devices
from android_tool.tools.app_list import AppListError, select_device


class ApkInstallError(RuntimeError):
    """Raised when an APK install or uninstall action cannot be completed."""


@dataclass(frozen=True)
class ApkInstallResult:
    """Result of an install or uninstall command."""

    action: str
    device: AdbDevice
    command: list[str]
    exit_code: int
    stdout: str
    stderr: str

    def to_dict(self) -> dict[str, object]:
        return {
            "action": self.action,
            "device": self.device.to_dict(),
            "command": self.command,
            "exit_code": self.exit_code,
            "stdout": self.stdout,
            "stderr": self.stderr,
        }


def build_install_command(
    apk_paths: list[Path],
    replace: bool = True,
    downgrade: bool = False,
    grant_permissions: bool = False,
    test_only: bool = False,
) -> list[str]:
    """Build an adb install command for one or multiple APKs."""
    if not apk_paths:
        raise ApkInstallError("at least one APK path is required")
    command = ["install-multiple" if len(apk_paths) > 1 else "install"]
    if replace:
        command.append("-r")
    if downgrade:
        command.append("-d")
    if grant_permissions:
        command.append("-g")
    if test_only:
        command.append("-t")
    command.extend(str(path) for path in apk_paths)
    return command


def build_uninstall_command(keep_data: bool = False) -> list[str]:
    """Build an adb uninstall command."""
    command = ["uninstall"]
    if keep_data:
        command.append("-k")
    return command


def _run_adb_command(
    action: str,
    arguments: list[str],
    serial: str | None,
    timeout_seconds: float,
) -> AdbCommandResult:
    result = execute_adb_command(arguments, serial=serial, timeout_seconds=timeout_seconds)
    if result.exit_code != 0:
        raise ApkInstallError(result.stderr.strip() or result.stdout.strip() or f"{action} failed")
    return result


def install_apks(
    apk_paths: list[Path | str],
    serial: str | None = None,
    replace: bool = True,
    downgrade: bool = False,
    grant_permissions: bool = False,
    test_only: bool = False,
    timeout_seconds: float = 120.0,
) -> ApkInstallResult:
    """Install one or more APK files on a selected Android device."""
    if not apk_paths:
        raise ApkInstallError("at least one APK path is required")

    paths = [Path(path).expanduser().resolve() for path in apk_paths]
    missing = [str(path) for path in paths if not path.is_file()]
    if missing:
        raise ApkInstallError(f"APK file not found: {missing[0]}")

    try:
        device = select_device(list_adb_devices(timeout_seconds=timeout_seconds), serial)
    except AppListError as exc:
        raise ApkInstallError(str(exc)) from exc

    command = build_install_command(paths, replace, downgrade, grant_permissions, test_only)
    result = _run_adb_command("install", command, device.serial, timeout_seconds)
    return ApkInstallResult(
        action="install",
        device=device,
        command=result.args,
        exit_code=result.exit_code,
        stdout=result.stdout.strip(),
        stderr=result.stderr.strip(),
    )


def uninstall_package(
    package_name: str,
    serial: str | None = None,
    keep_data: bool = False,
    timeout_seconds: float = 60.0,
) -> ApkInstallResult:
    """Uninstall an app package from a selected Android device."""
    if not package_name:
        raise ApkInstallError("package name must not be empty")
    try:
        device = select_device(list_adb_devices(timeout_seconds=timeout_seconds), serial)
    except AppListError as exc:
        raise ApkInstallError(str(exc)) from exc

    command = build_uninstall_command(keep_data)
    command.append(package_name)
    result = _run_adb_command("uninstall", command, device.serial, timeout_seconds)
    return ApkInstallResult(
        action="uninstall",
        device=device,
        command=result.args,
        exit_code=result.exit_code,
        stdout=result.stdout.strip(),
        stderr=result.stderr.strip(),
    )
