"""Extract Spine animation bundles from an exported Android app tree."""

from __future__ import annotations

import json
import shutil
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path

from android_tool.tools.app_export import validate_package_name


class SpineExtractError(RuntimeError):
    """Raised when Spine bundles cannot be discovered or copied."""


SKELETON_EXTENSIONS = {".skel", ".json", ".bytes"}
IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".webp"}


@dataclass(frozen=True)
class SpineBundle:
    """One copied Spine bundle directory."""

    relative_directory: str
    atlas_files: list[str]
    skeleton_files: list[str]
    image_files: list[str]
    file_count: int

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass(frozen=True)
class SpineExtractResult:
    """Summary of a Spine extraction run."""

    package_name: str
    source_directory: Path
    output_directory: Path
    bundle_count: int
    file_count: int
    bundles: list[SpineBundle]

    def to_dict(self) -> dict[str, object]:
        return {
            "package_name": self.package_name,
            "source_directory": str(self.source_directory),
            "output_directory": str(self.output_directory),
            "bundle_count": self.bundle_count,
            "file_count": self.file_count,
            "bundles": [bundle.to_dict() for bundle in self.bundles],
        }


def _has_matching_skeleton(atlas_path: Path) -> bool:
    return any(atlas_path.with_suffix(extension).is_file() for extension in SKELETON_EXTENSIONS)


def _is_relative_to(path: Path, other: Path) -> bool:
    try:
        path.relative_to(other)
    except ValueError:
        return False
    return True


def discover_spine_bundle_directories(source_directory: Path) -> list[Path]:
    """Find directories that contain a Spine atlas and a matching skeleton."""
    if not source_directory.is_dir():
        raise SpineExtractError(f"source directory does not exist: {source_directory}")

    candidates = {atlas_path.parent for atlas_path in source_directory.rglob("*.atlas") if _has_matching_skeleton(atlas_path)}
    selected: list[Path] = []
    for candidate in sorted(candidates, key=lambda path: (len(path.parts), path.as_posix().casefold())):
        if any(_is_relative_to(candidate, existing) for existing in selected):
            continue
        selected.append(candidate)
    return selected


def _bundle_file_lists(bundle_directory: Path) -> tuple[list[str], list[str], list[str], int]:
    atlas_files: list[str] = []
    skeleton_files: list[str] = []
    image_files: list[str] = []
    file_count = 0
    for path in sorted(bundle_directory.rglob("*")):
        if not path.is_file():
            continue
        file_count += 1
        relative = path.relative_to(bundle_directory).as_posix()
        suffix = path.suffix.casefold()
        if suffix == ".atlas":
            atlas_files.append(relative)
        elif suffix in SKELETON_EXTENSIONS:
            skeleton_files.append(relative)
        elif suffix in IMAGE_EXTENSIONS:
            image_files.append(relative)
    return atlas_files, skeleton_files, image_files, file_count


def extract_spine_bundles(
    package_name: str,
    source_base: Path | str = "exports",
    output_base: Path | str = "spine_exports",
    overwrite: bool = False,
) -> SpineExtractResult:
    """Copy all Spine bundle directories for one package into a local output tree."""
    validate_package_name(package_name)
    source_directory = Path(source_base).expanduser().resolve() / package_name
    if not source_directory.is_dir():
        raise SpineExtractError(f"source package directory does not exist: {source_directory}")

    bundle_directories = discover_spine_bundle_directories(source_directory)
    if not bundle_directories:
        raise SpineExtractError(f"no Spine bundles found in {source_directory}")

    output_directory = Path(output_base).expanduser().resolve() / package_name
    if output_directory.exists():
        if not overwrite:
            raise SpineExtractError(
                f"output directory already exists: {output_directory}; use --overwrite to replace it"
            )
        shutil.rmtree(output_directory)
    output_directory.mkdir(parents=True, exist_ok=True)

    bundles: list[SpineBundle] = []
    total_files = 0
    for bundle_directory in bundle_directories:
        relative_directory = bundle_directory.relative_to(source_directory)
        target_directory = output_directory / relative_directory
        target_directory.parent.mkdir(parents=True, exist_ok=True)
        shutil.copytree(bundle_directory, target_directory)

        atlas_files, skeleton_files, image_files, file_count = _bundle_file_lists(bundle_directory)
        bundles.append(
            SpineBundle(
                relative_directory=relative_directory.as_posix(),
                atlas_files=atlas_files,
                skeleton_files=skeleton_files,
                image_files=image_files,
                file_count=file_count,
            )
        )
        total_files += file_count

    manifest = {
        "package_name": package_name,
        "source_directory": str(source_directory),
        "output_directory": str(output_directory),
        "created_at": datetime.now(timezone.utc).isoformat(),
        "bundle_count": len(bundles),
        "file_count": total_files,
        "bundles": [bundle.to_dict() for bundle in bundles],
        "notes": [
            "A Spine bundle is detected by a .atlas file with a sibling .skel, .json, or .bytes file.",
            "Directories are copied recursively and preserve their original relative layout.",
        ],
    }
    (output_directory / "spine-manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    return SpineExtractResult(
        package_name=package_name,
        source_directory=source_directory,
        output_directory=output_directory,
        bundle_count=len(bundles),
        file_count=total_files,
        bundles=bundles,
    )
