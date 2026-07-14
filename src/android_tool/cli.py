"""Command line entry point for Android dev tools."""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence

from android_tool.core.adb import AdbError, list_adb_devices
from android_tool.tools.adb_connect import AdbConnectError, adb_connect
from android_tool.tools.app_control import AppControlError, control_app
from android_tool.tools.app_inspect import AppInspectError, inspect_app
from android_tool.tools.app_log import AppLogError, collect_app_logs
from android_tool.tools.app_list import AppListError, list_installed_packages
from android_tool.tools.app_export import AppExportError, export_app_data
from android_tool.tools.apk_install import ApkInstallError, install_apks, uninstall_package
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

    app_export = subparsers.add_parser(
        "app-export",
        help="Export an installed package's APKs and application data.",
    )
    app_export.add_argument("package", help="Android package name to export.")
    app_export.add_argument("--serial", help="ADB device serial; required when several are online.")
    app_export.add_argument(
        "--output",
        default="exports",
        help="Parent output directory; a package-named directory is created inside it.",
    )
    app_export.add_argument(
        "--overwrite",
        action="store_true",
        help="Replace an existing package output directory.",
    )
    app_export.add_argument(
        "--timeout", type=float, default=30.0, help="ADB inactivity timeout in seconds."
    )
    app_export.add_argument("--json", action="store_true", help="Print machine-readable JSON.")

    adb_connect_parser = subparsers.add_parser(
        "adb-connect",
        help="Connect or disconnect an ADB target and verify device state.",
    )
    adb_connect_parser.add_argument("target", nargs="?", help="ADB target such as 127.0.0.1:5555.")
    adb_connect_parser.add_argument(
        "--disconnect",
        action="store_true",
        help="Disconnect the target instead of connecting.",
    )
    adb_connect_parser.add_argument(
        "--check",
        action="store_true",
        help="Only verify whether the target is listed by ADB.",
    )
    adb_connect_parser.add_argument("--timeout", type=float, default=5.0, help="ADB timeout in seconds.")
    adb_connect_parser.add_argument("--json", action="store_true", help="Print machine-readable JSON.")

    app_inspect = subparsers.add_parser(
        "app-inspect",
        help="Inspect an installed application's package metadata and components.",
    )
    app_inspect.add_argument("package", help="Android package name to inspect.")
    app_inspect.add_argument("--serial", help="ADB device serial; required when several are online.")
    app_inspect.add_argument("--timeout", type=float, default=10.0, help="ADB timeout in seconds.")
    app_inspect.add_argument("--json", action="store_true", help="Print machine-readable JSON.")

    app_log = subparsers.add_parser(
        "app-log",
        help="Collect logcat output for a package or process ID.",
    )
    app_log.add_argument("package", nargs="?", help="Android package name to trace.")
    app_log.add_argument("--pid", help="Process ID to filter logcat with.")
    app_log.add_argument("--serial", help="ADB device serial; required when several are online.")
    app_log.add_argument("--lines", type=int, default=200, help="Number of logcat lines to read.")
    app_log.add_argument(
        "--priority",
        choices=["V", "D", "I", "W", "E", "F", "S"],
        help="Log priority filter passed to logcat.",
    )
    app_log.add_argument(
        "--crash-only",
        action="store_true",
        help="Keep only crash and ANR related lines after collection.",
    )
    app_log.add_argument("--timeout", type=float, default=10.0, help="ADB timeout in seconds.")
    app_log.add_argument("--json", action="store_true", help="Print machine-readable JSON.")

    app_control = subparsers.add_parser(
        "app-control",
        help="Start, stop, restart, or clear application state.",
    )
    app_control.add_argument("package", help="Android package name to control.")
    app_control.add_argument(
        "action",
        choices=["start", "stop", "restart", "clear-cache", "clear-data"],
        help="Lifecycle or cleanup action to run.",
    )
    app_control.add_argument("--serial", help="ADB device serial; required when several are online.")
    app_control.add_argument(
        "--yes",
        action="store_true",
        help="Confirm destructive actions such as clear-data.",
    )
    app_control.add_argument("--timeout", type=float, default=10.0, help="ADB timeout in seconds.")
    app_control.add_argument("--json", action="store_true", help="Print machine-readable JSON.")

    apk_install = subparsers.add_parser(
        "apk-install",
        help="Install or uninstall APKs on a connected Android device.",
    )
    apk_install.add_argument("apk_paths", nargs="*", help="APK file paths to install.")
    apk_install.add_argument(
        "--uninstall",
        metavar="PACKAGE",
        help="Uninstall the named package instead of installing APKs.",
    )
    apk_install.add_argument("--serial", help="ADB device serial; required when several are online.")
    apk_install.add_argument(
        "--replace",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Replace an existing installed version.",
    )
    apk_install.add_argument("--downgrade", action="store_true", help="Allow version downgrade.")
    apk_install.add_argument(
        "--grant-permissions",
        action="store_true",
        help="Grant runtime permissions during installation.",
    )
    apk_install.add_argument("--test", action="store_true", help="Allow test APKs.")
    apk_install.add_argument(
        "--keep-data",
        action="store_true",
        help="Keep app data when uninstalling.",
    )
    apk_install.add_argument("--timeout", type=float, default=120.0, help="ADB timeout in seconds.")
    apk_install.add_argument("--json", action="store_true", help="Print machine-readable JSON.")

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

    if args.command == "app-export":
        last_reported: dict[str, int] = {}

        def report_progress(kind: str, transferred: int, expected: int) -> None:
            previous = last_reported.get(kind, 0)
            if transferred - previous < 64 * 1024 * 1024 and transferred < expected:
                return
            last_reported[kind] = transferred
            percent = min(100, int(transferred * 100 / expected)) if expected else 0
            print(
                f"Exporting {kind}: {transferred / 1024 / 1024:.1f} MiB ({percent}%)",
                file=sys.stderr,
            )

        try:
            result = export_app_data(
                package_name=args.package,
                output_base=args.output,
                serial=args.serial,
                overwrite=args.overwrite,
                timeout_seconds=args.timeout,
                progress=report_progress,
            )
        except (AdbError, AppExportError) as exc:
            parser.exit(2, f"error: {exc}\n")

        if args.json:
            print(json.dumps(result.to_dict(), ensure_ascii=False, indent=2))
            return 0

        print(f"Exported {args.package} from {result.device.serial}")
        print(f"Output: {result.output_directory}")
        print(f"Sources: {len(result.entries)}, estimated bytes: {result.estimated_bytes}")
        return 0

    if args.command == "adb-connect":
        if not args.target:
            parser.exit(2, "error: target is required\n")
        action = "disconnect" if args.disconnect else "check" if args.check else "connect"
        try:
            result = adb_connect(args.target, action=action, timeout_seconds=args.timeout)
        except AdbConnectError as exc:
            parser.exit(2, f"error: {exc}\n")

        if args.json:
            print(json.dumps(result.to_dict(), ensure_ascii=False, indent=2))
            return 0

        print(f"{result.action} {result.target}: {result.message or 'ok'}")
        if result.matched_device:
            print(f"Matched device: {result.matched_device.serial} state={result.matched_device.state}")
        return 0

    if args.command == "app-inspect":
        try:
            result = inspect_app(args.package, serial=args.serial, timeout_seconds=args.timeout)
        except (AdbError, AppInspectError) as exc:
            parser.exit(2, f"error: {exc}\n")

        if args.json:
            print(json.dumps(result.to_dict(), ensure_ascii=False, indent=2))
            return 0

        print(f"{result.package_name} on {result.device.serial}")
        print(f"APK paths: {', '.join(result.apk_paths)}")
        if result.uid is not None:
            print(f"UID: {result.uid}")
        if result.version_name or result.version_code:
            print(f"Version: {result.version_name or '-'} ({result.version_code or '-'})")
        if result.target_sdk is not None or result.min_sdk is not None:
            print(
                "SDK: "
                f"min={result.min_sdk if result.min_sdk is not None else '-'} "
                f"target={result.target_sdk if result.target_sdk is not None else '-'}"
            )
        if result.requested_permissions:
            print(f"Requested permissions: {len(result.requested_permissions)}")
        for kind, values in result.components.items():
            if values:
                print(f"{kind}: {len(values)}")
        return 0

    if args.command == "app-log":
        try:
            result = collect_app_logs(
                package_name=args.package,
                pid=args.pid,
                serial=args.serial,
                lines=args.lines,
                priority=args.priority,
                crash_only=args.crash_only,
                timeout_seconds=args.timeout,
            )
        except (AdbError, AppLogError) as exc:
            parser.exit(2, f"error: {exc}\n")

        if args.json:
            print(json.dumps(result.to_dict(), ensure_ascii=False, indent=2))
            return 0

        header = f"Logcat on {result.device.serial}"
        if result.package_name:
            header += f" for {result.package_name}"
        if result.pid:
            header += f" pid={result.pid}"
        print(header)
        for line in result.lines:
            print(line)
        return 0

    if args.command == "app-control":
        if args.action in {"clear-cache", "clear-data"} and not args.yes:
            parser.exit(2, "error: --yes is required for clear-cache and clear-data\n")
        try:
            result = control_app(
                args.package,
                action=args.action,
                serial=args.serial,
                timeout_seconds=args.timeout,
            )
        except (AdbError, AppControlError) as exc:
            parser.exit(2, f"error: {exc}\n")

        if args.json:
            print(json.dumps(result.to_dict(), ensure_ascii=False, indent=2))
            return 0

        print(f"{result.action} {result.package_name} on {result.device.serial}")
        for step in result.steps:
            print(f"- {' '.join(step.command)} => {step.exit_code}")
            if step.stdout:
                print(step.stdout)
        return 0

    if args.command == "apk-install":
        try:
            if args.uninstall:
                result = uninstall_package(
                    args.uninstall,
                    serial=args.serial,
                    keep_data=args.keep_data,
                    timeout_seconds=args.timeout,
                )
            else:
                if not args.apk_paths:
                    parser.exit(2, "error: provide one or more APK paths or use --uninstall\n")
                result = install_apks(
                    args.apk_paths,
                    serial=args.serial,
                    replace=args.replace,
                    downgrade=args.downgrade,
                    grant_permissions=args.grant_permissions,
                    test_only=args.test,
                    timeout_seconds=args.timeout,
                )
        except (AdbError, ApkInstallError) as exc:
            parser.exit(2, f"error: {exc}\n")

        if args.json:
            print(json.dumps(result.to_dict(), ensure_ascii=False, indent=2))
            return 0

        print(f"{result.action} on {result.device.serial}")
        print(result.stdout or result.stderr or f"{result.action} completed")
        return 0

    parser.error(f"Unsupported command: {args.command}")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
