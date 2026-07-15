from pathlib import Path

import pytest

from android_tool.tools.spine_extract import (
    SpineExtractError,
    discover_spine_bundle_directories,
    extract_spine_bundles,
)
from android_tool.tools.uf_extract import UF_KEY


def _write_file(path: Path, payload: bytes = b"x") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(payload)


def _encode_uf02(decoded: bytes, seed: int = 5) -> bytes:
    encoded = bytearray(b"UF\x00\x02" + bytes([seed]) + decoded[5:])
    for index in range(5, min(len(decoded), 100)):
        encoded[index] ^= UF_KEY[(seed + index) % len(UF_KEY)]
    encoded.extend(
        value ^ UF_KEY[(seed + index) % len(UF_KEY)] for index, value in enumerate(decoded[:5])
    )
    return bytes(encoded)


def test_discover_spine_bundle_directories_requires_atlas_and_skeleton(tmp_path: Path) -> None:
    source = tmp_path / "exports" / "com.example.demo"
    spine_bundle = source / "data" / "files" / "obb" / "res" / "common" / "pet_spine" / "1001"
    _write_file(spine_bundle / "1001.atlas", b"1001.png\nsize: 64,64\n")
    _write_file(spine_bundle / "1001.skel")
    _write_file(spine_bundle / "1001.png")

    ui_atlas = source / "data" / "files" / "obb" / "res" / "common" / "ui" / "home"
    _write_file(ui_atlas / "home.atlas", b"home.png\nsize: 64,64\n")
    _write_file(ui_atlas / "home.png")

    bundles = discover_spine_bundle_directories(source)

    assert bundles == [spine_bundle]


def test_extract_spine_bundles_preserves_relative_layout(tmp_path: Path) -> None:
    package_name = "com.example.demo"
    source_base = tmp_path / "exports"
    output_base = tmp_path / "spine_exports"
    bundle = source_base / package_name / "data" / "files" / "obb" / "res" / "common" / "pet_spine" / "1001"
    _write_file(bundle / "1001.atlas", b"1001.png\nsize: 64,64\n")
    _write_file(bundle / "1001.skel")
    decoded_png = b"\x89PNG\r\n\x1a\n" + b"decoded-texture"
    _write_file(bundle / "1001.png", _encode_uf02(decoded_png))
    _write_file(bundle / "unused.png")
    _write_file(bundle / "notes.txt")
    progress: list[tuple[str, int, int, Path]] = []

    result = extract_spine_bundles(
        package_name,
        source_base=source_base,
        output_base=output_base,
        progress_callback=lambda stage, current, total, path: progress.append(
            (stage, current, total, path)
        ),
    )

    copied = output_base / package_name / "data" / "files" / "obb" / "res" / "common" / "pet_spine" / "1001"
    assert result.bundle_count == 1
    assert result.file_count == 3
    assert (copied / "1001.atlas").is_file()
    assert (copied / "1001.skel").is_file()
    assert (copied / "1001.png").read_bytes() == decoded_png
    assert not (copied / "unused.png").exists()
    assert not (copied / "notes.txt").exists()
    assert (output_base / package_name / "spine-manifest.json").is_file()
    assert (output_base / package_name / "spine-index.json").is_file()
    assert any(stage == "filter" for stage, _, _, _ in progress)
    assert progress[-1][:3] == ("copy", 1, 1)


def test_extract_spine_bundles_requires_overwrite_for_existing_output(tmp_path: Path) -> None:
    package_name = "com.example.demo"
    source_base = tmp_path / "exports"
    output_base = tmp_path / "spine_exports"
    bundle = source_base / package_name / "data" / "files" / "spine" / "1001"
    _write_file(bundle / "1001.atlas")
    _write_file(bundle / "1001.skel")
    (output_base / package_name).mkdir(parents=True)

    with pytest.raises(SpineExtractError, match="already exists"):
        extract_spine_bundles(package_name, source_base=source_base, output_base=output_base)
