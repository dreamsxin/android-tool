"""Extract Spine animation bundles from an exported Android app tree."""

from __future__ import annotations

import json
import os
import shutil
import time
from concurrent.futures import Future, ThreadPoolExecutor, as_completed
from collections.abc import Callable
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path

from android_tool.tools.app_export import validate_package_name
from android_tool.tools.uf_extract import UfExtractError, decode_uf_texture_to_png


class SpineExtractError(RuntimeError):
    """Raised when Spine bundles cannot be discovered or copied."""


SKELETON_EXTENSIONS = (".skel", ".json", ".bytes")
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


def discover_spine_bundle_directories(
    source_directory: Path,
    progress_callback: Callable[[str, int, int, Path], None] | None = None,
) -> list[Path]:
    """Find directories that contain a Spine atlas and a matching skeleton."""
    if not source_directory.is_dir():
        raise SpineExtractError(f"source directory does not exist: {source_directory}")

    candidates: set[Path] = set()
    processed_files = 0
    last_progress = time.monotonic()
    if progress_callback is not None:
        progress_callback("scan", 0, 0, source_directory)
    # os.walk keeps the scan in the directory tree and avoids constructing a
    # Path object for every unrelated file in large APK/OBB exports.
    for root, directories, filenames in os.walk(source_directory):
        directories[:] = [directory for directory in directories if directory != "apk"]
        root_path = Path(root)
        for filename in filenames:
            processed_files += 1
            if filename.casefold().endswith(".atlas"):
                atlas_path = root_path / filename
                if _has_matching_skeleton(atlas_path):
                    candidates.add(root_path)
            if (
                progress_callback is not None
                and (processed_files % 1000 == 0 or time.monotonic() - last_progress >= 1)
            ):
                progress_callback("scan", processed_files, len(candidates), root_path)
                last_progress = time.monotonic()
    selected: list[Path] = []
    selected_paths: set[Path] = set()
    sorted_candidates = sorted(
        candidates, key=lambda path: (len(path.parts), path.as_posix().casefold())
    )
    for candidate_index, candidate in enumerate(sorted_candidates, start=1):
        if any(parent in selected_paths for parent in candidate.parents):
            continue
        selected.append(candidate)
        selected_paths.add(candidate)
        if progress_callback is not None and candidate_index % 1000 == 0:
            progress_callback("filter", candidate_index, len(sorted_candidates), candidate)
    if progress_callback is not None:
        progress_callback("filter", len(sorted_candidates), len(selected), source_directory)
        progress_callback("scan", processed_files, len(selected), source_directory)
    return selected


def _bundle_file_lists(bundle_directory: Path) -> tuple[list[str], list[str], list[str], int]:
    selected_files: set[Path] = set()
    atlas_files: list[str] = []
    skeleton_files: list[str] = []
    image_files: list[str] = []

    for atlas_path in sorted(bundle_directory.rglob("*.atlas")):
        if not atlas_path.is_file():
            continue
        selected_files.add(atlas_path)
        atlas_files.append(atlas_path.relative_to(bundle_directory).as_posix())

        for extension in SKELETON_EXTENSIONS:
            skeleton_path = atlas_path.with_suffix(extension)
            if skeleton_path.is_file():
                selected_files.add(skeleton_path)
                skeleton_files.append(skeleton_path.relative_to(bundle_directory).as_posix())
                break

        for page_name in _atlas_page_names(atlas_path):
            image_path = (atlas_path.parent / page_name).resolve()
            if not _is_relative_to(image_path, bundle_directory.resolve()) or not image_path.is_file():
                continue
            selected_files.add(image_path)
            image_files.append(image_path.relative_to(bundle_directory.resolve()).as_posix())

    # Keep manifest ordering stable when an atlas references the same page more than once.
    atlas_files = sorted(set(atlas_files))
    skeleton_files = sorted(set(skeleton_files))
    image_files = sorted(set(image_files))
    return atlas_files, skeleton_files, image_files, len(selected_files)


def _atlas_page_names(atlas_path: Path) -> list[str]:
    """Read page names from a text Spine atlas without treating region names as pages."""
    lines = atlas_path.read_text(encoding="utf-8", errors="replace").splitlines()
    pages: list[str] = []
    for index, line in enumerate(lines[:-1]):
        candidate = line.strip()
        following = lines[index + 1].strip().casefold()
        if candidate and ":" not in candidate and following.startswith("size:"):
            pages.append(candidate)
    return pages


def _extract_one_bundle(
    source_directory: Path,
    output_directory: Path,
    bundle_directory: Path,
) -> SpineBundle:
    relative_directory = bundle_directory.relative_to(source_directory)
    target_directory = output_directory / relative_directory
    target_directory.parent.mkdir(parents=True, exist_ok=True)
    atlas_files, skeleton_files, image_files, file_count = _bundle_file_lists(bundle_directory)
    selected_relative_files = set(atlas_files + skeleton_files + image_files)
    for relative_file in sorted(selected_relative_files):
        source_file = bundle_directory / Path(relative_file)
        target_file = target_directory / Path(relative_file)
        target_file.parent.mkdir(parents=True, exist_ok=True)
        _copy_spine_file(source_file, target_file, relative_file in image_files)
    return SpineBundle(
        relative_directory=relative_directory.as_posix(),
        atlas_files=atlas_files,
        skeleton_files=skeleton_files,
        image_files=image_files,
        file_count=file_count,
    )


def _copy_spine_file(source_file: Path, target_file: Path, is_image: bool) -> None:
    target_file.parent.mkdir(parents=True, exist_ok=True)
    if is_image:
        with source_file.open("rb") as handle:
            header = handle.read(4)
        if header == b"UF\x00\x02":
            try:
                decode_uf_texture_to_png(source_file.read_bytes(), target_file)
            except UfExtractError as exc:
                raise SpineExtractError(
                    f"could not decode Spine texture {source_file}: {exc}"
                ) from exc
            return
    shutil.copy2(source_file, target_file)


def _fallback_obb_atlas(
    source_directory: Path,
    skeleton_path: Path,
) -> Path | None:
    relative_path = skeleton_path.relative_to(source_directory)
    parts = list(relative_path.parts)
    try:
        upgrade_index = next(
            index for index, part in enumerate(parts) if part.casefold() == "upgrade"
        )
    except StopIteration:
        return None
    parts[upgrade_index] = "obb"
    candidate = (source_directory / Path(*parts)).with_suffix(".atlas")
    return candidate if candidate.is_file() else None


def _discover_upgrade_overlay_skeletons(
    source_directory: Path,
) -> list[tuple[Path, Path]]:
    overlays: list[tuple[Path, Path]] = []
    for root, directories, filenames in os.walk(source_directory):
        directories[:] = [directory for directory in directories if directory != "apk"]
        root_path = Path(root)
        for filename in filenames:
            skeleton_path = root_path / filename
            if skeleton_path.suffix.casefold() not in SKELETON_EXTENSIONS:
                continue
            if skeleton_path.with_suffix(".atlas").is_file():
                continue
            fallback_atlas = _fallback_obb_atlas(source_directory, skeleton_path)
            if fallback_atlas is not None:
                overlays.append((skeleton_path, fallback_atlas))
    return sorted(overlays, key=lambda item: item[0].as_posix().casefold())


def _extract_overlay_bundle(
    source_directory: Path,
    output_directory: Path,
    skeleton_path: Path,
    fallback_atlas: Path,
) -> SpineBundle:
    relative_directory = skeleton_path.parent.relative_to(source_directory)
    target_directory = output_directory / relative_directory
    target_directory.mkdir(parents=True, exist_ok=True)
    target_skeleton = target_directory / skeleton_path.name
    target_atlas = target_directory / fallback_atlas.name
    _copy_spine_file(skeleton_path, target_skeleton, False)
    _copy_spine_file(fallback_atlas, target_atlas, False)

    image_files: list[str] = []
    for page_name in _atlas_page_names(fallback_atlas):
        source_image = (fallback_atlas.parent / page_name).resolve()
        if not _is_relative_to(source_image, fallback_atlas.parent.resolve()):
            continue
        if not source_image.is_file():
            continue
        relative_image = source_image.relative_to(fallback_atlas.parent.resolve())
        target_image = target_directory / relative_image
        _copy_spine_file(source_image, target_image, True)
        image_files.append(relative_image.as_posix())

    image_files = sorted(set(image_files))
    return SpineBundle(
        relative_directory=relative_directory.as_posix(),
        atlas_files=[fallback_atlas.name],
        skeleton_files=[skeleton_path.name],
        image_files=image_files,
        file_count=2 + len(image_files),
    )


def _build_spine_index_entries(
    output_directory: Path,
    bundles: list[SpineBundle],
) -> list[dict[str, object]]:
    entries: list[dict[str, object]] = []
    for bundle in bundles:
        atlas_by_stem = {
            Path(atlas_file).with_suffix("").as_posix(): atlas_file
            for atlas_file in bundle.atlas_files
        }
        for skeleton_file in bundle.skeleton_files:
            atlas_file = atlas_by_stem.get(Path(skeleton_file).with_suffix("").as_posix())
            if atlas_file is None:
                continue
            atlas_path = output_directory / Path(bundle.relative_directory) / Path(atlas_file)
            atlas_parent = Path(atlas_file).parent
            image_files = sorted(
                {
                    (atlas_parent / Path(page_name)).as_posix()
                    for page_name in _atlas_page_names(atlas_path)
                    if (atlas_parent / Path(page_name)).as_posix() in bundle.image_files
                }
            )
            entries.append(
                {
                    "name": Path(skeleton_file).stem,
                    "relative_directory": bundle.relative_directory,
                    "atlas_files": [atlas_file],
                    "skeleton_files": [skeleton_file],
                    "image_files": image_files,
                    "file_count": 2 + len(image_files),
                }
            )
    entries.sort(
        key=lambda entry: (
            str(entry["relative_directory"]).casefold(),
            str(entry["skeleton_files"][0]).casefold(),
        )
    )
    return [{"id": index, **entry} for index, entry in enumerate(entries)]


def extract_spine_bundles(
    package_name: str,
    source_base: Path | str = "exports",
    output_base: Path | str = "spine_exports",
    overwrite: bool = False,
    progress_callback: Callable[[str, int, int, Path], None] | None = None,
) -> SpineExtractResult:
    """Copy all Spine bundle directories for one package into a local output tree."""
    validate_package_name(package_name)
    source_directory = Path(source_base).expanduser().resolve() / package_name
    if not source_directory.is_dir():
        raise SpineExtractError(f"source package directory does not exist: {source_directory}")

    output_directory = Path(output_base).expanduser().resolve() / package_name
    if output_directory.exists():
        if not overwrite:
            raise SpineExtractError(
                f"output directory already exists: {output_directory}; use --overwrite to replace it"
            )
        shutil.rmtree(output_directory)
    output_directory.mkdir(parents=True, exist_ok=True)

    bundle_directories = discover_spine_bundle_directories(
        source_directory, progress_callback=progress_callback
    )
    overlay_skeletons = _discover_upgrade_overlay_skeletons(source_directory)
    if not bundle_directories and not overlay_skeletons:
        raise SpineExtractError(f"no Spine bundles found in {source_directory}")

    total_bundle_count = len(bundle_directories) + len(overlay_skeletons)
    bundles: list[SpineBundle | None] = [None] * total_bundle_count
    last_copy_progress = time.monotonic()
    if progress_callback is not None:
        progress_callback("copy", 0, total_bundle_count, output_directory)
    with ThreadPoolExecutor(max_workers=min(4, os.cpu_count() or 1)) as executor:
        futures: dict[Future[SpineBundle], tuple[int, Path]] = {}
        for index, bundle_directory in enumerate(bundle_directories):
            future = executor.submit(
                _extract_one_bundle,
                source_directory,
                output_directory,
                bundle_directory,
            )
            futures[future] = (index, bundle_directory)
        overlay_offset = len(bundle_directories)
        for overlay_index, (skeleton_path, fallback_atlas) in enumerate(overlay_skeletons):
            future = executor.submit(
                _extract_overlay_bundle,
                source_directory,
                output_directory,
                skeleton_path,
                fallback_atlas,
            )
            futures[future] = (overlay_offset + overlay_index, skeleton_path.parent)
        completed = 0
        for future in as_completed(futures):
            index, current_path = futures[future]
            bundles[index] = future.result()
            completed += 1
            if (
                progress_callback is not None
                and (
                    completed == 1
                    or completed % 50 == 0
                    or time.monotonic() - last_copy_progress >= 1
                    or completed == total_bundle_count
                )
            ):
                progress_callback("copy", completed, total_bundle_count, current_path)
                last_copy_progress = time.monotonic()

    completed_bundles = [bundle for bundle in bundles if bundle is not None]
    total_files = sum(bundle.file_count for bundle in completed_bundles)
    if progress_callback is not None:
        progress_callback("copy", total_bundle_count, total_bundle_count, output_directory)

    manifest = {
        "package_name": package_name,
        "source_directory": str(source_directory),
        "output_directory": str(output_directory),
        "created_at": datetime.now(timezone.utc).isoformat(),
        "bundle_count": len(completed_bundles),
        "file_count": total_files,
        "bundles": [bundle.to_dict() for bundle in completed_bundles],
        "notes": [
            "A Spine bundle is detected by a .atlas file with a sibling .skel, .json, or .bytes file.",
            "Upgrade-only skeletons reuse atlas and texture files from the same logical OBB path.",
            "Only atlas files, matching skeletons, and atlas-referenced texture pages are copied.",
            "Referenced UF 00 02 textures are decoded to standard PNG files during extraction.",
        ],
    }
    (output_directory / "spine-manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    index_entries = _build_spine_index_entries(output_directory, completed_bundles)
    index = {
        "version": 1,
        "package_name": package_name,
        "bundle_count": len(index_entries),
        "bundles": index_entries,
    }
    (output_directory / "spine-index.json").write_text(
        json.dumps(index, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    return SpineExtractResult(
        package_name=package_name,
        source_directory=source_directory,
        output_directory=output_directory,
        bundle_count=len(completed_bundles),
        file_count=total_files,
        bundles=completed_bundles,
    )
