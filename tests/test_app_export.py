import io
import tarfile
from pathlib import Path

import pytest

from android_tool.tools.app_export import (
    AppExportError,
    _safe_extract_tar,
    parse_apk_paths,
    validate_package_name,
)


def test_validate_package_name() -> None:
    assert validate_package_name("com.yoozoo.jgame.global") == "com.yoozoo.jgame.global"


@pytest.mark.parametrize("package", ["com.example;id", "../example", "single", ""])
def test_validate_package_name_rejects_unsafe_values(package: str) -> None:
    with pytest.raises(AppExportError, match="invalid Android package"):
        validate_package_name(package)


def test_parse_apk_paths_includes_base_and_splits() -> None:
    output = (
        "package:/data/app/com.example/base.apk\n"
        "package:/data/app/com.example/split_config.arm64_v8a.apk\n"
    )
    assert parse_apk_paths(output) == [
        "/data/app/com.example/base.apk",
        "/data/app/com.example/split_config.arm64_v8a.apk",
    ]


def test_safe_extract_tar_extracts_regular_file(tmp_path: Path) -> None:
    archive_path = tmp_path / "source.tar"
    payload = b"app data"
    with tarfile.open(archive_path, "w") as archive:
        info = tarfile.TarInfo("files/value.txt")
        info.size = len(payload)
        archive.addfile(info, io.BytesIO(payload))

    file_count, skipped_links, mappings = _safe_extract_tar(
        archive_path, tmp_path / "output"
    )

    assert file_count == 1
    assert skipped_links == 0
    assert mappings == []
    assert (tmp_path / "output/files/value.txt").read_bytes() == payload


def test_safe_extract_tar_encodes_windows_incompatible_name(tmp_path: Path) -> None:
    archive_path = tmp_path / "windows-name.tar"
    payload = b"settings"
    with tarfile.open(archive_path, "w") as archive:
        info = tarfile.TarInfo("shared_prefs/frc_1:123.xml")
        info.size = len(payload)
        archive.addfile(info, io.BytesIO(payload))

    file_count, skipped_links, mappings = _safe_extract_tar(
        archive_path, tmp_path / "output"
    )

    assert file_count == 1
    assert skipped_links == 0
    assert (tmp_path / "output/shared_prefs/frc_1%3A123.xml").read_bytes() == payload
    assert mappings[-1] == {
        "original_member": "shared_prefs/frc_1:123.xml",
        "local_member": "shared_prefs/frc_1%3A123.xml",
    }


def test_safe_extract_tar_rejects_parent_traversal(tmp_path: Path) -> None:
    archive_path = tmp_path / "unsafe.tar"
    with tarfile.open(archive_path, "w") as archive:
        info = tarfile.TarInfo("../outside.txt")
        info.size = 1
        archive.addfile(info, io.BytesIO(b"x"))

    with pytest.raises(AppExportError, match="unsafe path"):
        _safe_extract_tar(archive_path, tmp_path / "output")
