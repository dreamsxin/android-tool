"""Export an installed application's APKs and standard data directories."""

from __future__ import annotations

import hashlib
import json
import os
import re
import shlex
import shutil
import tarfile
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from typing import Callable, Literal

from android_tool.core.adb import (
    AdbDevice,
    AdbError,
    execute_adb_shell,
    list_adb_devices,
    stream_adb_shell,
)
from android_tool.tools.app_list import AppListError, select_device

AccessMode = Literal["shell", "root", "run-as"]
PACKAGE_PATTERN = re.compile(r"^[A-Za-z][A-Za-z0-9_]*(?:\.[A-Za-z0-9_]+)+$")


class AppExportError(RuntimeError):
    """Raised when application data cannot be exported safely."""


@dataclass(frozen=True)
class ExportSource:
    kind: str
    remote_path: str
    local_path: str
    access: AccessMode
    is_directory: bool
    size_bytes: int


@dataclass(frozen=True)
class ExportEntry:
    kind: str
    remote_path: str
    local_path: str
    status: str
    size_bytes: int
    transferred_bytes: int = 0
    detail: str | None = None


@dataclass(frozen=True)
class AppExportResult:
    package_name: str
    device: AdbDevice
    output_directory: Path
    root_access: bool
    estimated_bytes: int
    entries: list[ExportEntry]

    def to_dict(self) -> dict[str, object]:
        return {
            "package_name": self.package_name,
            "device": self.device.to_dict(),
            "output_directory": str(self.output_directory),
            "root_access": self.root_access,
            "estimated_bytes": self.estimated_bytes,
            "entries": [asdict(entry) for entry in self.entries],
        }


def validate_package_name(package_name: str) -> str:
    """Reject malformed package names before using them in device shell commands."""
    if not PACKAGE_PATTERN.fullmatch(package_name):
        raise AppExportError(f"invalid Android package name: {package_name}")
    return package_name


def parse_apk_paths(output: str) -> list[str]:
    """Parse all base and split APK paths returned by ``pm path``."""
    return [
        line.removeprefix("package:").strip()
        for line in output.splitlines()
        if line.strip().startswith("package:/")
    ]


def _access_arguments(access: AccessMode, package_name: str, command: str) -> list[str]:
    if access == "root":
        return ["su", "-c", command]
    if access == "run-as":
        return ["run-as", package_name, "sh", "-c", command]
    return ["sh", "-c", command]


def _inspect_remote_path(
    device: AdbDevice,
    package_name: str,
    remote_path: str,
    access: AccessMode,
    timeout_seconds: float,
) -> int | None:
    quoted_path = shlex.quote(remote_path)
    command = (
        f"if [ -e {quoted_path} ]; then "
        f"du -sk {quoted_path} 2>/dev/null | head -n 1; "
        "else echo MISSING; fi"
    )
    output = execute_adb_shell(
        device.serial,
        _access_arguments(access, package_name, command),
        timeout_seconds=timeout_seconds,
    ).strip()
    if output == "MISSING" or not output:
        return None
    first_field = output.split()[0]
    try:
        return int(first_field) * 1024
    except ValueError as exc:
        raise AppExportError(f"could not inspect {remote_path}: {output}") from exc


def _has_root(device: AdbDevice, timeout_seconds: float) -> bool:
    output = execute_adb_shell(
        device.serial, ["su", "-c", "id"], timeout_seconds=timeout_seconds
    )
    return "uid=0(root)" in output


def _has_run_as(device: AdbDevice, package_name: str, timeout_seconds: float) -> bool:
    output = execute_adb_shell(
        device.serial, ["run-as", package_name, "id"], timeout_seconds=timeout_seconds
    )
    return "uid=" in output and "is not debuggable" not in output and "unknown package" not in output


def discover_export_sources(
    device: AdbDevice,
    package_name: str,
    apk_paths: list[str],
    root_access: bool,
    run_as_access: bool,
    timeout_seconds: float,
) -> tuple[list[ExportSource], list[ExportEntry]]:
    """Find standard Android locations attributable to one package."""
    sources: list[ExportSource] = []
    unavailable_entries: list[ExportEntry] = []
    used_apk_names: set[str] = set()
    for index, remote_path in enumerate(apk_paths):
        name = PurePosixPath(remote_path).name or f"package-{index}.apk"
        if name in used_apk_names:
            name = f"{index}-{name}"
        used_apk_names.add(name)
        size = _inspect_remote_path(
            device, package_name, remote_path, "shell", timeout_seconds
        )
        if size is not None:
            sources.append(ExportSource("apk", remote_path, f"apk/{name}", "shell", False, size))
        else:
            unavailable_entries.append(
                ExportEntry("apk", remote_path, f"apk/{name}", "not-found", 0)
            )

    private_access: AccessMode | None = "root" if root_access else "run-as" if run_as_access else None
    candidates: list[tuple[str, str, str, AccessMode | None]] = [
        ("credential-protected-data", f"/data/user/0/{package_name}", "data/credential-protected", private_access),
        ("device-protected-data", f"/data/user_de/0/{package_name}", "data/device-protected", "root" if root_access else None),
        ("external-data", f"/sdcard/Android/data/{package_name}", "external/data", "shell"),
        ("external-media", f"/sdcard/Android/media/{package_name}", "external/media", "shell"),
        ("obb", f"/sdcard/Android/obb/{package_name}", "external/obb", "shell"),
        ("shared-package-directory", f"/sdcard/{package_name}", "external/shared-package-directory", "shell"),
    ]
    for kind, remote_path, local_path, access in candidates:
        if access is None:
            unavailable_entries.append(
                ExportEntry(
                    kind,
                    remote_path,
                    local_path,
                    "unavailable",
                    0,
                    detail="requires root access or a debuggable package",
                )
            )
            continue
        size = _inspect_remote_path(
            device, package_name, remote_path, access, timeout_seconds
        )
        if size is not None:
            sources.append(ExportSource(kind, remote_path, local_path, access, True, size))
        else:
            unavailable_entries.append(
                ExportEntry(kind, remote_path, local_path, "not-found", 0)
            )
    return sources, unavailable_entries


WINDOWS_RESERVED_NAMES = {
    "con",
    "prn",
    "aux",
    "nul",
    *(f"com{number}" for number in range(1, 10)),
    *(f"lpt{number}" for number in range(1, 10)),
}


def _portable_component(component: str) -> str:
    """Encode a device path component into a case-safe Windows filename."""
    encoded_parts: list[str] = []
    for character in component:
        if "a" <= character <= "z" or "0" <= character <= "9" or character in "._-":
            encoded_parts.append(character)
        else:
            encoded_parts.extend(f"%{byte:02X}" for byte in character.encode("utf-8"))
    encoded = "".join(encoded_parts)
    if encoded.endswith("."):
        encoded = f"{encoded[:-1]}%2E"
    if encoded.partition(".")[0].casefold() in WINDOWS_RESERVED_NAMES:
        first = encoded[0].encode("utf-8")
        encoded = "".join(f"%{byte:02X}" for byte in first) + encoded[1:]
    if len(encoded) > 180:
        digest = hashlib.sha256(component.encode("utf-8")).hexdigest()[:16]
        encoded = f"{encoded[:150]}~{digest}"
    return encoded


def _safe_extract_tar(
    archive_path: Path, destination: Path
) -> tuple[int, int, list[dict[str, str]]]:
    """Extract regular files and directories without allowing path traversal."""
    file_count = 0
    skipped_links = 0
    path_mappings: list[dict[str, str]] = []
    destination.mkdir(parents=True, exist_ok=True)
    root = destination.resolve()
    with tarfile.open(archive_path, mode="r:*") as archive:
        for member in archive:
            relative = PurePosixPath(member.name)
            parts = [part for part in relative.parts if part not in ("", ".")]
            if relative.is_absolute() or ".." in parts:
                raise AppExportError(f"unsafe path in device archive: {member.name}")
            portable_parts = [_portable_component(part) for part in parts]
            target = destination.joinpath(*portable_parts)
            portable_name = PurePosixPath(*portable_parts).as_posix()
            original_name = PurePosixPath(*parts).as_posix()
            if portable_name != original_name:
                path_mappings.append(
                    {"original_member": original_name, "local_member": portable_name}
                )
            resolved_target = target.resolve()
            if os.path.commonpath((root, resolved_target)) != str(root):
                raise AppExportError(f"unsafe path in device archive: {member.name}")
            if member.isdir():
                target.mkdir(parents=True, exist_ok=True)
                continue
            if not member.isfile():
                skipped_links += 1
                continue
            target.parent.mkdir(parents=True, exist_ok=True)
            source = archive.extractfile(member)
            if source is None:
                raise AppExportError(f"could not read archived file: {member.name}")
            with source, target.open("wb") as output:
                shutil.copyfileobj(source, output, length=1024 * 1024)
            file_count += 1
    return file_count, skipped_links, path_mappings


def _export_file(
    device: AdbDevice,
    package_name: str,
    source: ExportSource,
    target: Path,
    timeout_seconds: float,
    progress: Callable[[str, int, int], None] | None,
) -> int:
    target.parent.mkdir(parents=True, exist_ok=True)
    partial = target.with_name(f"{target.name}.partial")
    arguments = _access_arguments(source.access, package_name, f"cat {shlex.quote(source.remote_path)}")
    with partial.open("wb") as output:
        result = stream_adb_shell(
            device.serial,
            arguments,
            output,
            timeout_seconds=timeout_seconds,
            progress=(lambda count: progress(source.kind, count, source.size_bytes)) if progress else None,
        )
    if result.exit_code != 0:
        partial.unlink(missing_ok=True)
        raise AppExportError(result.stderr or f"failed to read {source.remote_path}")
    partial.replace(target)
    return result.bytes_written


def _export_directory(
    device: AdbDevice,
    package_name: str,
    source: ExportSource,
    target: Path,
    timeout_seconds: float,
    progress: Callable[[str, int, int], None] | None,
) -> tuple[int, str | None, list[dict[str, str]]]:
    archive_path = target.with_name(f".{target.name}.tar.partial")
    archive_path.parent.mkdir(parents=True, exist_ok=True)
    inner_command = shlex.join(["tar", "-C", source.remote_path, "-cf", "-", "."])
    arguments = _access_arguments(source.access, package_name, inner_command)
    with archive_path.open("wb") as output:
        result = stream_adb_shell(
            device.serial,
            arguments,
            output,
            timeout_seconds=timeout_seconds,
            progress=(lambda count: progress(source.kind, count, source.size_bytes)) if progress else None,
        )
    if result.exit_code != 0:
        archive_path.unlink(missing_ok=True)
        raise AppExportError(result.stderr or f"failed to archive {source.remote_path}")
    try:
        file_count, skipped_links, path_mappings = _safe_extract_tar(archive_path, target)
    finally:
        archive_path.unlink(missing_ok=True)
    detail = f"files={file_count}"
    if skipped_links:
        detail += f", skipped_links={skipped_links}"
    if path_mappings:
        detail += f", renamed_paths={len(path_mappings)}"
    return result.bytes_written, detail, path_mappings


def export_app_data(
    package_name: str,
    output_base: Path | str = "exports",
    serial: str | None = None,
    overwrite: bool = False,
    timeout_seconds: float = 30.0,
    progress: Callable[[str, int, int], None] | None = None,
) -> AppExportResult:
    """Export APKs, app-private data, and standard external package directories."""
    validate_package_name(package_name)
    try:
        device = select_device(list_adb_devices(timeout_seconds=timeout_seconds), serial)
    except AppListError as exc:
        raise AppExportError(str(exc)) from exc

    apk_output = execute_adb_shell(
        device.serial, ["pm", "path", package_name], timeout_seconds=timeout_seconds
    )
    apk_paths = parse_apk_paths(apk_output)
    if not apk_paths:
        raise AppExportError(f"package is not installed on {device.serial}: {package_name}")

    root_access = _has_root(device, timeout_seconds)
    run_as_access = False if root_access else _has_run_as(device, package_name, timeout_seconds)
    sources, unavailable_entries = discover_export_sources(
        device,
        package_name,
        apk_paths,
        root_access,
        run_as_access,
        timeout_seconds,
    )
    estimated_bytes = sum(source.size_bytes for source in sources)
    largest_directory = max(
        (source.size_bytes for source in sources if source.is_directory), default=0
    )

    output_directory = Path(output_base).expanduser().resolve() / package_name
    if output_directory.exists():
        if not overwrite:
            raise AppExportError(
                f"output directory already exists: {output_directory}; use --overwrite to replace it"
            )
        shutil.rmtree(output_directory)
    output_directory.parent.mkdir(parents=True, exist_ok=True)
    free_bytes = shutil.disk_usage(output_directory.parent).free
    required_bytes = int((estimated_bytes + largest_directory) * 1.05) + 128 * 1024 * 1024
    if free_bytes < required_bytes:
        raise AppExportError(
            f"insufficient disk space: need about {required_bytes} bytes, have {free_bytes} bytes"
        )
    output_directory.mkdir()

    metadata_directory = output_directory / "metadata"
    metadata_directory.mkdir()
    package_details = execute_adb_shell(
        device.serial,
        ["dumpsys", "package", package_name],
        timeout_seconds=timeout_seconds,
    )
    (metadata_directory / "package.txt").write_text(package_details, encoding="utf-8")

    entries: list[ExportEntry] = list(unavailable_entries)
    all_path_mappings: list[dict[str, str]] = []
    for source in sources:
        target = output_directory / Path(source.local_path)
        try:
            if source.is_directory:
                transferred, detail, path_mappings = _export_directory(
                    device, package_name, source, target, timeout_seconds, progress
                )
                all_path_mappings.extend(
                    {
                        "kind": source.kind,
                        "remote_root": source.remote_path,
                        **mapping,
                    }
                    for mapping in path_mappings
                )
            else:
                transferred = _export_file(
                    device, package_name, source, target, timeout_seconds, progress
                )
                detail = None
            entries.append(
                ExportEntry(
                    source.kind,
                    source.remote_path,
                    source.local_path,
                    "exported",
                    source.size_bytes,
                    transferred,
                    detail,
                )
            )
        except (AdbError, AppExportError, OSError, tarfile.TarError) as exc:
            entries.append(
                ExportEntry(
                    source.kind,
                    source.remote_path,
                    source.local_path,
                    "failed",
                    source.size_bytes,
                    detail=str(exc),
                )
            )

    result = AppExportResult(
        package_name,
        device,
        output_directory,
        root_access,
        estimated_bytes,
        entries,
    )
    if all_path_mappings:
        (metadata_directory / "path-map.json").write_text(
            json.dumps(all_path_mappings, ensure_ascii=False, indent=2), encoding="utf-8"
        )
    manifest = {
        **result.to_dict(),
        "created_at": datetime.now(timezone.utc).isoformat(),
        "coverage": [
            "base and split APKs",
            "credential-protected private data when root or run-as is available",
            "device-protected private data when root is available",
            "Android/data, Android/media, Android/obb, and /sdcard/<package>",
        ],
    }
    (output_directory / "export-manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    if any(entry.status == "failed" for entry in entries):
        raise AppExportError(
            f"export completed with failures; inspect {output_directory / 'export-manifest.json'}"
        )
    return result
