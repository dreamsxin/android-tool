from pathlib import Path

from android_tool.core.adb import AdbDevice
from android_tool.tools.adb_connect import find_matching_device
from android_tool.tools.app_control import build_control_steps
from android_tool.tools.app_inspect import (
    parse_app_state,
    parse_components,
    parse_permission_grants,
    parse_requested_permissions,
)
from android_tool.tools.app_log import build_logcat_command, filter_log_lines, parse_pids
from android_tool.tools.apk_install import build_install_command, build_uninstall_command


def test_find_matching_device_uses_connect_target() -> None:
    devices = [
        AdbDevice(serial="emulator-5554", state="device", attributes={}),
        AdbDevice(serial="127.0.0.1:62001", state="device", attributes={}),
    ]

    assert find_matching_device(devices, "127.0.0.1:5555").serial == "emulator-5554"


def test_parse_requested_permissions_and_states() -> None:
    output = """
requested permissions:
  android.permission.INTERNET
  android.permission.ACCESS_NETWORK_STATE
install permissions:
  android.permission.INTERNET: granted=true
  android.permission.ACCESS_NETWORK_STATE: granted=false
enabled=1
stopped=false
"""

    assert parse_requested_permissions(output) == [
        "android.permission.ACCESS_NETWORK_STATE",
        "android.permission.INTERNET",
    ]
    assert parse_permission_grants(output) == (
        ["android.permission.INTERNET"],
        ["android.permission.ACCESS_NETWORK_STATE"],
    )
    assert parse_app_state(output) == (True, False)


def test_parse_components_extracts_package_members() -> None:
    output = """
activities:
  ActivityRecord{1 com.example.demo/.MainActivity}
services:
  ServiceRecord{2 com.example.demo/.SyncService}
"""

    components = parse_components(output, "com.example.demo")

    assert components["activities"] == ["com.example.demo/.MainActivity"]
    assert components["services"] == ["com.example.demo/.SyncService"]


def test_logcat_helpers_build_and_filter() -> None:
    command = build_logcat_command(lines=50, pid="1234", priority="e")
    assert command == ["logcat", "-d", "-t", "50", "--pid", "1234", "*:E"]
    assert parse_pids("1234 5678") == ["1234", "5678"]
    assert filter_log_lines(
        "12-12 00:00:00 I tag: com.example.demo ready\n12-12 00:00:01 E tag: crash\n",
        package_name="com.example.demo",
        crash_only=False,
    ) == ["12-12 00:00:00 I tag: com.example.demo ready"]


def test_build_control_steps_and_install_commands() -> None:
    assert build_control_steps("com.example.demo", "restart") == [
        ["am", "force-stop", "com.example.demo"],
        ["monkey", "-p", "com.example.demo", "-c", "android.intent.category.LAUNCHER", "1"],
    ]
    assert build_install_command([Path("demo.apk")]) == ["install", "-r", "demo.apk"]
    assert build_uninstall_command(keep_data=True) == ["uninstall", "-k"]
