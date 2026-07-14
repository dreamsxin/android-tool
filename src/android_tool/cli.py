"""Command line entry point for Android dev tools."""

from __future__ import annotations

import argparse
import json
from collections.abc import Sequence

from android_tool.core.adb import AdbError, list_adb_devices
from android_tool.tools.app_list import AppListError, list_installed_packages
from android_tool.tools.emulator_probe import ProbeOptions, probe_emulators


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="android-tool",
        description="Local Android development and debugging toolbox.",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    emulator_probe = subparsers.add_parser(
        "emulator-probe",
        help="List local emulator services known to ADB.",
    )
    emulator_probe.add_argument(
        "--scan",
        action="store_true",
        help="Scan local TCP ports instead of querying ADB.",
    )
    emulator_probe.add_argument("--host", default="127.0.0.1", help="Host used with --scan.")
    emulator_probe.add_argument("--start", type=int, default=5554, help="First port used with --scan.")
    emulator_probe.add_argument("--end", type=int, default=5682, help="Last port used with --scan.")
    emulator_probe.add_argument(
        "--timeout",
        type=float,
        default=0.2,
        help="Per-port socket timeout used with --scan.",
    )
    emulator_probe.add_argument(
        "--adb-timeout",
        type=float,
        default=5.0,
        help="Timeout for adb devices in seconds.",
    )
    emulator_probe.add_argument("--json", action="store_true", help="Print machine-readable JSON.")

    app_list = subparsers.add_parser(
        "app-list",
        help="List packages installed on an Android device.",
    )
    app_list.add_argument("--serial", help="ADB device serial; required when several are online.")
    scope = app_list.add_mutually_exclusive_group()
    scope.add_argument("--third-party", action="store_true", help="Show third-party packages only.")
    scope.add_argument("--system", action="store_true", help="Show system packages only.")
    app_list.add_argument("--include-path", action="store_true", help="Include each APK path.")
    app_list.add_argument("--timeout", type=float, default=10.0, help="ADB timeout in seconds.")
    app_list.add_argument("--json", action="store_true", help="Print machine-readable JSON.")

    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.command == "emulator-probe":
        if not args.scan:
            try:
                devices = list_adb_devices(timeout_seconds=args.adb_timeout)
            except AdbError as exc:
                parser.exit(2, f"error: {exc}\n")

            payload = [device.to_dict() for device in devices]
            if args.json:
                print(json.dumps(payload, ensure_ascii=False, indent=2))
                return 0

            if not devices:
                print("ADB is available, but no devices are listed.")
                return 1

            print("Devices known to ADB:")
            for device in devices:
                details = []
                if model := device.attributes.get("model"):
                    details.append(f"model={model}")
                if device.connect_target:
                    details.append(f"connect={device.connect_target}")
                suffix = f" {' '.join(details)}" if details else ""
                print(f"- {device.serial} state={device.state}{suffix}")
            return 0

        options = ProbeOptions(
            host=args.host,
            start_port=args.start,
            end_port=args.end,
            timeout_seconds=args.timeout,
        )
        results = probe_emulators(options)
        payload = [result.to_dict() for result in results]

        if args.json:
            print(json.dumps(payload, ensure_ascii=False, indent=2))
            return 0

        if not results:
            print("No local emulator services detected.")
            print(f"Scanned {args.host}:{args.start}-{args.end}")
            return 1

        print("Detected local emulator services:")
        for result in results:
            status = ", ".join(result.open_services)
            print(
                f"- emulator-{result.console_port}: "
                f"console={result.console_target} "
                f"adb={result.adb_connect_target} "
                f"status={status}"
            )
        return 0

    if args.command == "app-list":
        scope = "third-party" if args.third_party else "system" if args.system else "all"
        try:
            result = list_installed_packages(
                serial=args.serial,
                scope=scope,
                include_path=args.include_path,
                timeout_seconds=args.timeout,
            )
        except (AdbError, AppListError) as exc:
            parser.exit(2, f"error: {exc}\n")

        if args.json:
            print(json.dumps(result.to_dict(), ensure_ascii=False, indent=2))
            return 0

        print(f"Installed applications on {result.device.serial} ({len(result.packages)}):")
        for package in result.packages:
            path = f" path={package.apk_path}" if package.apk_path else ""
            print(f"- {package.package_name}{path}")
        return 0

    parser.error(f"Unsupported command: {args.command}")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
