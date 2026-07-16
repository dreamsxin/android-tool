import json
from pathlib import Path

import pytest

from android_tool.tools.video_extract import (
    VideoExtractError,
    discover_video_files,
    extract_video_resources,
)


def _write_video(path: Path, payload: bytes = b"CRIDvideo") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(payload)


def test_discover_video_files_finds_known_containers(tmp_path: Path) -> None:
    source = tmp_path / "exports" / "com.example.demo"
    usm = source / "res" / "movie" / "intro_1920x1080_3000.usm"
    mp4 = source / "res" / "movie" / "trailer.mp4"
    _write_video(usm)
    _write_video(mp4, b"video")
    _write_video(source / "res" / "movie" / "config.json", b"{}")

    assert discover_video_files(source) == [usm, mp4]


def test_extract_video_resources_preserves_all_versions_and_indexes_latest(
    tmp_path: Path,
) -> None:
    package = "com.example.demo"
    source = tmp_path / "exports" / package
    logical = Path("res/common/movie/cg/intro_1334x750_4000.usm")
    apk = source / "apk" / "assets" / logical
    obb = source / "data" / "credential-protected" / "files" / "obb" / logical
    upgrade = source / "data" / "credential-protected" / "files" / "upgrade" / logical
    unique = source / "data" / "credential-protected" / "files" / "upgrade" / (
        "res/common/movie/pv/unique_1920x1080x1_92300.usm"
    )
    _write_video(apk, b"CRIDapk")
    _write_video(obb, b"CRIDobb")
    _write_video(upgrade, b"CRIDupgrade")
    _write_video(unique, b"CRIDunique")

    result = extract_video_resources(
        package,
        source_base=tmp_path / "exports",
        output_base=tmp_path / "video_exports",
    )

    assert result.resource_count == 4
    assert result.logical_count == 2
    assert result.total_bytes == sum(path.stat().st_size for path in (apk, obb, upgrade, unique))
    assert (result.output_directory / apk.relative_to(source)).read_bytes() == b"CRIDapk"
    assert (result.output_directory / obb.relative_to(source)).read_bytes() == b"CRIDobb"
    assert (result.output_directory / upgrade.relative_to(source)).read_bytes() == b"CRIDupgrade"
    index = json.loads((result.output_directory / "video-index.json").read_text())
    intro = next(video for video in index["videos"] if video["logical_path"] == logical.as_posix())
    assert intro["source_layer"] == "upgrade"
    assert intro["width"] == 1334
    assert intro["height"] == 750
    assert intro["duration_ms"] == 4000
    assert len(intro["variants"]) == 3
    unique_entry = next(video for video in index["videos"] if "unique_" in video["logical_path"])
    assert unique_entry["width"] == 1920
    assert unique_entry["height"] == 1080
    assert unique_entry["duration_ms"] == 92300
    assert (result.output_directory / "video-manifest.json").is_file()


def test_extract_video_resources_requires_overwrite(tmp_path: Path) -> None:
    package = "com.example.demo"
    source = tmp_path / "exports" / package
    _write_video(source / "movie" / "intro.usm")
    output = tmp_path / "video_exports" / package
    output.mkdir(parents=True)

    with pytest.raises(VideoExtractError, match="already exists"):
        extract_video_resources(
            package,
            source_base=tmp_path / "exports",
            output_base=tmp_path / "video_exports",
        )
