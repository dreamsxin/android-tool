"""Connect, disconnect, and check ADB targets."""

from __future__ import annotations

from dataclasses import dataclass

from android_tool.core.adb import (
    AdbDevice,
    execute_adb_host_action,
    list_adb_devices,
)


class AdbConnectError(RuntimeError):
    """Raised when an ADB connection action cannot be completed."""


@dataclass(frozen=True)
class AdbConnectResult:
    """Result of connecting, disconnecting, or checking an ADB target."""

    action: str
    target: str
    message: str
    matched_device: AdbDevice | None
    devices: list[AdbDevice]

    def to_dict(self) -> dict[str, object]:
        return {
            "action": self.action,
            "target": self.target,
            "message": self.message,
            "matched_device": self.matched_device.to_dict() if self.matched_device else None,
            "devices": [device.to_dict() for device in self.devices],
        }


def find_matching_device(devices: list[AdbDevice], target: str) -> AdbDevice | None:
    """Find a device by serial or derived connect target."""
    return next(
        (
            device
            for device in devices
            if device.serial == target or device.connect_target == target
        ),
        None,
    )


def adb_connect(
    target: str,
    action: str = "connect",
    timeout_seconds: float = 5.0,
) -> AdbConnectResult:
    """Run an ADB connect/disconnect/check action and return current device state."""
    if action not in {"connect", "disconnect", "check"}:
        raise AdbConnectError(f"unsupported action: {action}")
    if not target:
        raise AdbConnectError("target must not be empty")

    message = ""
    if action in {"connect", "disconnect"}:
        response = execute_adb_host_action(
            action=action,
            target=target,
            timeout_seconds=timeout_seconds,
        )
        message = response.message

    devices = list_adb_devices(timeout_seconds=timeout_seconds)
    matched_device = find_matching_device(devices, target)
    if action == "check":
        if matched_device:
            message = f"{target} is {matched_device.state}"
        else:
            message = f"{target} is not listed by ADB"
    return AdbConnectResult(
        action=action,
        target=target,
        message=message,
        matched_device=matched_device,
        devices=devices,
    )
