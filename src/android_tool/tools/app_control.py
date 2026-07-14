"""Start, stop, restart, and clear application state."""

from __future__ import annotations

from dataclasses import dataclass

from android_tool.core.adb import AdbDevice, execute_adb_shell_v2, list_adb_devices
from android_tool.tools.app_export import AppExportError, validate_package_name
from android_tool.tools.app_list import AppListError, select_device


class AppControlError(RuntimeError):
    """Raised when an application control action cannot be performed."""


@dataclass(frozen=True)
class AppControlStep:
    """One shell command executed as part of an app control action."""

    command: list[str]
    exit_code: int
    stdout: str
    stderr: str

    def to_dict(self) -> dict[str, object]:
        return {
            "command": self.command,
            "exit_code": self.exit_code,
            "stdout": self.stdout,
            "stderr": self.stderr,
        }


@dataclass(frozen=True)
class AppControlResult:
    """Result of controlling an application on one device."""

    package_name: str
    action: str
    device: AdbDevice
    steps: list[AppControlStep]

    def to_dict(self) -> dict[str, object]:
        return {
            "package_name": self.package_name,
            "action": self.action,
            "device": self.device.to_dict(),
            "steps": [step.to_dict() for step in self.steps],
        }


def build_control_steps(package_name: str, action: str) -> list[list[str]]:
    """Build shell commands for the requested application control action."""
    if action == "start":
        return [["monkey", "-p", package_name, "-c", "android.intent.category.LAUNCHER", "1"]]
    if action == "stop":
        return [["am", "force-stop", package_name]]
    if action == "restart":
        return [
            ["am", "force-stop", package_name],
            ["monkey", "-p", package_name, "-c", "android.intent.category.LAUNCHER", "1"],
        ]
    if action == "clear-data":
        return [["pm", "clear", package_name]]
    if action == "clear-cache":
        return [["pm", "clear", "--cache-only", package_name]]
    raise AppControlError(f"unsupported action: {action}")


def control_app(
    package_name: str,
    action: str,
    serial: str | None = None,
    timeout_seconds: float = 10.0,
) -> AppControlResult:
    """Run an application lifecycle or cleanup action."""
    try:
        validate_package_name(package_name)
    except AppExportError as exc:
        raise AppControlError(str(exc)) from exc
    try:
        device = select_device(list_adb_devices(timeout_seconds=timeout_seconds), serial)
    except AppListError as exc:
        raise AppControlError(str(exc)) from exc

    steps: list[AppControlStep] = []
    for command in build_control_steps(package_name, action):
        result = execute_adb_shell_v2(
            device.serial,
            command,
            timeout_seconds=timeout_seconds,
        )
        steps.append(
            AppControlStep(
                command=command,
                exit_code=result.exit_code,
                stdout=result.stdout.strip(),
                stderr=result.stderr.strip(),
            )
        )
        if result.exit_code != 0:
            break

    if any(step.exit_code != 0 for step in steps):
        failing = next(step for step in steps if step.exit_code != 0)
        raise AppControlError(
            failing.stderr or failing.stdout or f"action {action} failed for {package_name}"
        )

    return AppControlResult(package_name=package_name, action=action, device=device, steps=steps)
