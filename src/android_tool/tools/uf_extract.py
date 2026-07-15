"""Decode the game's UF texture wrapper and optional ETC2 texture payloads."""

from __future__ import annotations

import json
import os
import struct
import time
import zlib
from collections.abc import Callable
from dataclasses import asdict, dataclass
from pathlib import Path

from android_tool.tools.app_export import validate_package_name


class UfExtractError(RuntimeError):
    """Raised when a UF resource cannot be decoded or exported."""


# This is the 33-byte table referenced by FileUtils::decryptUF in libcocos2dlua.so.
UF_KEY = bytes.fromhex(
    "13 5b 0c 0d 66 16 22 2b 11 19 58 40 24 10 0e 42 "
    "31 57 38 2c 35 1c 0b 05 74 25 3a 69 14 0f 4d 07 1d"
)


@dataclass(frozen=True)
class UfResource:
    """One decoded UF resource."""

    relative_path: str
    version: int
    seed: int
    source_size: int
    decoded_size: int
    inner_format: str
    output_path: str

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass(frozen=True)
class UfExtractResult:
    """Summary of a UF extraction run."""

    package_name: str
    source_directory: Path
    output_directory: Path
    resource_count: int
    resources: list[UfResource]

    def to_dict(self) -> dict[str, object]:
        return {
            "package_name": self.package_name,
            "source_directory": str(self.source_directory),
            "output_directory": str(self.output_directory),
            "resource_count": self.resource_count,
            "resources": [resource.to_dict() for resource in self.resources],
        }


def _key_byte(seed: int, index: int) -> int:
    return UF_KEY[(seed + index) % len(UF_KEY)]


def decode_uf02(payload: bytes) -> tuple[bytes, int, int, str]:
    """Decode one UF 00 02 resource into its wrapped payload.

    The native decoder strips the five-byte UF header, restores five bytes
    stored at the tail, and XORs only the first 100 payload bytes. The rest of
    the resource is left untouched by the game as well.
    """
    if len(payload) < 5 or payload[:2] != b"UF":
        raise UfExtractError("resource does not start with UF")
    if payload[2] != 0 or payload[3] != 2:
        raise UfExtractError(f"unsupported UF header: {payload[:5].hex(' ')}")

    seed = payload[4]
    decoded_length = len(payload) - 5
    if decoded_length < 5:
        raise UfExtractError("UF 00 02 resource is too short")

    decoded = bytearray(payload[:decoded_length])
    tail_offset = decoded_length
    for index in range(5):
        decoded[index] = payload[tail_offset + index] ^ _key_byte(seed, index)
    for index in range(5, min(decoded_length, 100)):
        decoded[index] ^= _key_byte(seed, index)

    inner_format = _detect_inner_format(decoded)
    return bytes(decoded), 2, seed, inner_format


def _detect_inner_format(payload: bytes | bytearray) -> str:
    if payload.startswith(b"CCZ!"):
        return "ccz"
    if payload.startswith(b"PVR\x03"):
        return "pvr"
    if payload.startswith(b"\x89PNG\r\n\x1a\n"):
        return "png"
    return "unknown"


def decompress_ccz(payload: bytes) -> bytes:
    """Decompress a Cocos2d-x CCZ payload and verify its declared size."""
    if not payload.startswith(b"CCZ!") or len(payload) < 16:
        raise UfExtractError("payload is not a valid CCZ resource")
    expected_size = struct.unpack_from(">I", payload, 12)[0]
    try:
        decompressed = zlib.decompress(payload[16:])
    except zlib.error as exc:
        raise UfExtractError(f"CCZ zlib decompression failed: {exc}") from exc
    if expected_size and len(decompressed) != expected_size:
        raise UfExtractError(
            f"CCZ size mismatch: header={expected_size}, actual={len(decompressed)}"
        )
    return decompressed


def pvr_etc2_to_png(payload: bytes, output_path: Path) -> None:
    """Convert this game's ETC2 RGBA PVR payload to PNG when the optional decoder is installed."""
    if not payload.startswith(b"PVR\x03") or len(payload) < 52:
        raise UfExtractError("payload is not a PVR v3 resource")
    pixel_format = struct.unpack_from("<I", payload, 8)[0]
    height, width = struct.unpack_from("<II", payload, 24)
    if pixel_format != 23 or not width or not height:
        raise UfExtractError(
            f"unsupported PVR payload: pixel_format={pixel_format}, size={width}x{height}"
        )
    try:
        import texture2ddecoder
        from PIL import Image
    except ImportError as exc:
        raise UfExtractError(
            "PNG conversion requires optional packages: pip install texture2ddecoder Pillow"
        ) from exc
    try:
        rgba = texture2ddecoder.decode_etc2a8(payload[52:], width, height)
        image = Image.frombytes("RGBA", (width, height), rgba)
        image.save(output_path, format="PNG")
    except Exception as exc:
        raise UfExtractError(f"ETC2 to PNG conversion failed: {exc}") from exc


def decode_uf_texture_to_png(payload: bytes, output_path: Path) -> None:
    """Decode one UF 00 02 texture and write a standard PNG file."""
    decoded, _, _, inner_format = decode_uf02(payload)
    if inner_format == "ccz":
        decoded = decompress_ccz(decoded)
        inner_format = _detect_inner_format(decoded)
    if inner_format == "pvr":
        pvr_etc2_to_png(decoded, output_path)
        return
    if inner_format == "png":
        output_path.write_bytes(decoded)
        return
    raise UfExtractError(f"unsupported decoded texture format: {inner_format}")


def _output_name(source_path: Path, png: bool) -> str:
    if png and source_path.suffix.casefold() in {".png", ".jpg", ".jpeg", ".webp"}:
        return source_path.name
    return f"{source_path.name}.decoded"


def extract_uf_resources(
    package_name: str,
    source_base: Path | str = "exports",
    output_base: Path | str = "uf_exports",
    overwrite: bool = False,
    png: bool = False,
    progress_callback: Callable[[int, int, Path], None] | None = None,
) -> UfExtractResult:
    """Extract UF 00 02 resources from one app-export directory."""
    validate_package_name(package_name)
    source_directory = Path(source_base).expanduser().resolve() / package_name
    if not source_directory.is_dir():
        raise UfExtractError(f"source package directory does not exist: {source_directory}")

    output_directory = Path(output_base).expanduser().resolve() / package_name
    output_directory.mkdir(parents=True, exist_ok=True)

    resources: list[UfResource] = []
    processed_files = 0
    last_progress = time.monotonic()
    if progress_callback is not None:
        progress_callback(0, 0, source_directory)
    for root, _, filenames in os.walk(source_directory):
        for filename in filenames:
            source_path = Path(root) / filename
            processed_files += 1
            with source_path.open("rb") as handle:
                header = handle.read(5)
            if header[:4] != b"UF\x00\x02":
                if (
                    progress_callback is not None
                    and (processed_files % 1000 == 0 or time.monotonic() - last_progress >= 1)
                ):
                    progress_callback(processed_files, len(resources), source_path)
                    last_progress = time.monotonic()
                continue
            payload = source_path.read_bytes()
            decoded, version, seed, inner_format = decode_uf02(payload)
            if inner_format == "ccz":
                decoded = decompress_ccz(decoded)
                inner_format = _detect_inner_format(decoded)

            relative_path = source_path.relative_to(source_directory)
            relative_output = relative_path.with_name(_output_name(source_path, png and inner_format == "pvr"))
            target_path = output_directory / relative_output
            target_path.parent.mkdir(parents=True, exist_ok=True)
            if png and inner_format == "pvr":
                pvr_etc2_to_png(decoded, target_path)
            else:
                target_path.write_bytes(decoded)
            resources.append(
                UfResource(
                    relative_path=relative_path.as_posix(),
                    version=version,
                    seed=seed,
                    source_size=len(payload),
                    decoded_size=len(decoded),
                    inner_format=inner_format,
                    output_path=relative_output.as_posix(),
                )
            )
            if (
                progress_callback is not None
                and (processed_files % 1000 == 0 or time.monotonic() - last_progress >= 1)
            ):
                progress_callback(processed_files, len(resources), source_path)
                last_progress = time.monotonic()

    if progress_callback is not None:
        progress_callback(processed_files, len(resources), source_directory)

    manifest = {
        "package_name": package_name,
        "source_directory": str(source_directory),
        "output_directory": str(output_directory),
        "resource_count": len(resources),
        "resources": [resource.to_dict() for resource in resources],
        "notes": [
            "UF 00 02 is decoded with the native cocos2d::FileUtils::decryptUF table.",
            "CCZ payloads are zlib-decompressed; --png converts this app's ETC2 RGBA PVR textures.",
        ],
    }
    (output_directory / "uf-manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return UfExtractResult(
        package_name=package_name,
        source_directory=source_directory,
        output_directory=output_directory,
        resource_count=len(resources),
        resources=resources,
    )
