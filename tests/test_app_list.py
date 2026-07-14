import pytest

from android_tool.core.adb import AdbDevice
from android_tool.tools.app_list import (
    AppListError,
    build_package_command,
    parse_package_list,
    select_device,
)


def make_device(serial: str, state: str = "device") -> AdbDevice:
    return AdbDevice(serial=serial, state=state, attributes={})


def test_parse_package_list_sorts_packages() -> None:
    packages = parse_package_list("package:org.example.zeta\npackage:com.example.alpha\n")

    assert [package.package_name for package in packages] == [
        "com.example.alpha",
        "org.example.zeta",
    ]


def test_parse_package_list_with_apk_paths() -> None:
    packages = parse_package_list(
        "package:/data/app/~~token/com.example.app/base.apk=com.example.app\n"
    )

    assert packages[0].package_name == "com.example.app"
    assert packages[0].apk_path == "/data/app/~~token/com.example.app/base.apk"


def test_select_device_uses_only_online_device() -> None:
    selected = select_device(
        [make_device("offline-device", "offline"), make_device("emulator-5554")]
    )

    assert selected.serial == "emulator-5554"


def test_select_device_requires_serial_for_multiple_devices() -> None:
    with pytest.raises(AppListError, match="multiple devices"):
        select_device([make_device("emulator-5554"), make_device("emulator-5556")])


def test_build_package_command_applies_filters() -> None:
    assert build_package_command("third-party", include_path=True) == [
        "pm",
        "list",
        "packages",
        "-f",
        "-3",
    ]
