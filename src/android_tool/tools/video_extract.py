"""Extract video resources from an exported Android app tree."""

from __future__ import annotations

import json
import os
import re
import shutil
import time
from collections.abc import Callable
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath

from android_tool.tools.app_export import validate_package_name


class VideoExtractError(RuntimeError):
    """Raised when video resources cannot be discovered or copied."""


VIDEO_EXTENSIONS = {
    ".usm",
    ".mp4",
    ".webm",
    ".mov",
    ".m4v",
    ".avi",
    ".mkv",
    ".flv",
    ".ogv",
    ".mpeg",
    ".mpg",
}
SOURCE_PRIORITY = {"other": 0, "apk": 1, "obb": 2, "upgradelang": 3, "upgrade": 4}
VIDEO_NAME_PATTERN = re.compile(
    r"_(?P<width>\d+)x(?P<height>\d+)(?:x\d+)?_(?P<duration_ms>\d+)$",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class VideoResource:
    """One physical video file copied from the app export."""

    relative_path: str
    logical_path: str
    source_layer: str
    container: str
    size: int
    width: int | None
    height: int | None
    duration_ms: int | None

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass(frozen=True)
class VideoExtractResult:
    """Summary of a video extraction run."""

    package_name: str
    source_directory: Path
    output_directory: Path
    resource_count: int
    logical_count: int
    total_bytes: int
    resources: list[VideoResource]

    def to_dict(self) -> dict[str, object]:
        return {
            "package_name": self.package_name,
            "source_directory": str(self.source_directory),
            "output_directory": str(self.output_directory),
            "resource_count": self.resource_count,
            "logical_count": self.logical_count,
            "total_bytes": self.total_bytes,
            "resources": [resource.to_dict() for resource in self.resources],
        }


def discover_video_files(source_directory: Path) -> list[Path]:
    """Find files with known video container extensions."""
    if not source_directory.is_dir():
        raise VideoExtractError(f"source directory does not exist: {source_directory}")
    videos: list[Path] = []
    for root, _, filenames in os.walk(source_directory):
        root_path = Path(root)
        for filename in filenames:
            if Path(filename).suffix.casefold() in VIDEO_EXTENSIONS:
                videos.append(root_path / filename)
    return sorted(videos, key=lambda path: path.as_posix().casefold())


def _source_layer_and_logical_path(relative_path: PurePosixPath) -> tuple[str, str]:
    parts = relative_path.parts
    folded_parts = tuple(part.casefold() for part in parts)
    if len(parts) >= 2 and folded_parts[:2] == ("apk", "assets"):
        return "apk", PurePosixPath(*parts[2:]).as_posix()
    for layer in ("upgrade", "upgradelang", "obb"):
        try:
            layer_index = folded_parts.index(layer)
        except ValueError:
            continue
        return layer, PurePosixPath(*parts[layer_index + 1 :]).as_posix()
    return "other", relative_path.as_posix()


def _video_metadata(path: Path) -> tuple[str, int | None, int | None, int | None]:
    with path.open("rb") as handle:
        magic = handle.read(4)
    if magic == b"CRID":
        container = "cri-usm"
    else:
        container = path.suffix.casefold().lstrip(".") or "unknown"
    match = VIDEO_NAME_PATTERN.search(path.stem)
    if match is None:
        return container, None, None, None
    return (
        container,
        int(match.group("width")),
        int(match.group("height")),
        int(match.group("duration_ms")),
    )


def _build_resource(source_directory: Path, path: Path) -> VideoResource:
    relative_path = PurePosixPath(path.relative_to(source_directory).as_posix())
    source_layer, logical_path = _source_layer_and_logical_path(relative_path)
    container, width, height, duration_ms = _video_metadata(path)
    return VideoResource(
        relative_path=relative_path.as_posix(),
        logical_path=logical_path,
        source_layer=source_layer,
        container=container,
        size=path.stat().st_size,
        width=width,
        height=height,
        duration_ms=duration_ms,
    )


def _build_video_index(resources: list[VideoResource]) -> list[dict[str, object]]:
    grouped: dict[str, list[VideoResource]] = {}
    for resource in resources:
        grouped.setdefault(resource.logical_path.casefold(), []).append(resource)
    entries: list[dict[str, object]] = []
    for variants in grouped.values():
        ordered_variants = sorted(
            variants,
            key=lambda resource: (
                SOURCE_PRIORITY.get(resource.source_layer, 0),
                resource.relative_path.casefold(),
            ),
        )
        selected = ordered_variants[-1]
        entries.append(
            {
                **selected.to_dict(),
                "variants": [resource.relative_path for resource in ordered_variants],
            }
        )
    entries.sort(key=lambda entry: str(entry["logical_path"]).casefold())
    return [{"id": index, **entry} for index, entry in enumerate(entries)]


def extract_video_resources(
    package_name: str,
    source_base: Path | str = "exports",
    output_base: Path | str = "video_exports",
    overwrite: bool = False,
    progress_callback: Callable[[int, int, int, Path], None] | None = None,
) -> VideoExtractResult:
    """Copy all video resources for one package and generate audit indexes."""
    validate_package_name(package_name)
    source_directory = Path(source_base).expanduser().resolve() / package_name
    if not source_directory.is_dir():
        raise VideoExtractError(f"source package directory does not exist: {source_directory}")

    output_directory = Path(output_base).expanduser().resolve() / package_name
    if output_directory.exists():
        if not overwrite:
            raise VideoExtractError(
                f"output directory already exists: {output_directory}; use --overwrite to replace it"
            )
        shutil.rmtree(output_directory)
    output_directory.mkdir(parents=True, exist_ok=True)

    video_files = discover_video_files(source_directory)
    if not video_files:
        raise VideoExtractError(f"no video resources found in {source_directory}")
    resources = [_build_resource(source_directory, path) for path in video_files]
    total_bytes = sum(resource.size for resource in resources)
    copied_bytes = 0
    last_progress = time.monotonic()
    if progress_callback is not None:
        progress_callback(0, len(resources), 0, source_directory)
    for index, (source_file, resource) in enumerate(zip(video_files, resources), start=1):
        target_file = output_directory / Path(resource.relative_path)
        target_file.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source_file, target_file)
        if target_file.stat().st_size != resource.size:
            raise VideoExtractError(f"copied video size mismatch: {target_file}")
        copied_bytes += resource.size
        if (
            progress_callback is not None
            and (
                index == 1
                or index % 25 == 0
                or time.monotonic() - last_progress >= 1
                or index == len(resources)
            )
        ):
            progress_callback(index, len(resources), copied_bytes, source_file)
            last_progress = time.monotonic()

    index_entries = _build_video_index(resources)
    created_at = datetime.now(timezone.utc).isoformat()
    manifest = {
        "version": 1,
        "package_name": package_name,
        "source_directory": str(source_directory),
        "output_directory": str(output_directory),
        "created_at": created_at,
        "resource_count": len(resources),
        "logical_count": len(index_entries),
        "total_bytes": total_bytes,
        "resources": [resource.to_dict() for resource in resources],
        "notes": [
            "All physical video files are retained under their original relative paths.",
            "CRI USM resources are exported without transcoding or stream modification.",
            "The logical index prefers upgrade over upgradelang, OBB, and APK variants.",
        ],
    }
    (output_directory / "video-manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    index = {
        "version": 1,
        "package_name": package_name,
        "created_at": created_at,
        "video_count": len(index_entries),
        "videos": index_entries,
    }
    (output_directory / "video-index.json").write_text(
        json.dumps(index, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return VideoExtractResult(
        package_name=package_name,
        source_directory=source_directory,
        output_directory=output_directory,
        resource_count=len(resources),
        logical_count=len(index_entries),
        total_bytes=total_bytes,
        resources=resources,
    )
