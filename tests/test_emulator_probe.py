from android_tool.core.adb import AdbDevice, parse_adb_devices
from android_tool.tools.emulator_probe import EmulatorProbeResult, iter_console_ports


def test_iter_console_ports_starts_at_next_even_port() -> None:
    assert iter_console_ports(5553, 5558) == [5554, 5556, 5558]


def test_iter_console_ports_rejects_reversed_range() -> None:
    try:
        iter_console_ports(5682, 5554)
    except ValueError as exc:
        assert "start_port" in str(exc)
    else:
        raise AssertionError("Expected ValueError")


def test_probe_result_exposes_adb_connect_target() -> None:
    result = EmulatorProbeResult(
        host="127.0.0.1",
        console_port=5554,
        adb_port=5555,
        console_open=True,
        adb_open=True,
    )

    assert result.console_target == "127.0.0.1:5554"
    assert result.adb_connect_target == "127.0.0.1:5555"
    assert result.to_dict()["open_services"] == ["console", "adb"]


def test_parse_adb_devices_long_output() -> None:
    output = """List of devices attached
emulator-5554 device product:sdk_gphone64_x86_64 model:sdk_gphone64 transport_id:1
127.0.0.1:62001 offline transport_id:2
R58M123456 unauthorized usb:1-1
"""

    devices = parse_adb_devices(output)

    assert [device.serial for device in devices] == [
        "emulator-5554",
        "127.0.0.1:62001",
        "R58M123456",
    ]
    assert devices[0].attributes["model"] == "sdk_gphone64"
    assert devices[1].state == "offline"


def test_adb_device_exposes_connect_target_for_local_emulators() -> None:
    emulator = AdbDevice(serial="emulator-5554", state="device", attributes={})
    tcp_device = AdbDevice(serial="127.0.0.1:62001", state="device", attributes={})
    usb_device = AdbDevice(serial="R58M123456", state="device", attributes={})

    assert emulator.connect_target == "127.0.0.1:5555"
    assert tcp_device.connect_target == "127.0.0.1:62001"
    assert usb_device.connect_target is None
