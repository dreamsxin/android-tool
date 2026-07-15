import struct
import zlib
from pathlib import Path

from android_tool.tools.uf_extract import UF_KEY, decode_uf02, extract_uf_resources


def _encode_uf02(decoded: bytes, seed: int = 7) -> bytes:
    encoded = bytearray(b"UF\x00\x02" + bytes([seed]) + decoded[5:])
    for index in range(5, min(len(decoded), 100)):
        encoded[index] ^= UF_KEY[(seed + index) % len(UF_KEY)]
    encoded.extend(
        value ^ UF_KEY[(seed + index) % len(UF_KEY)] for index, value in enumerate(decoded[:5])
    )
    return bytes(encoded)


def test_decode_uf02_restores_payload_and_detects_ccz() -> None:
    payload = b"CCZ!" + b"payload" * 20
    encoded = _encode_uf02(payload)

    decoded, version, seed, inner_format = decode_uf02(encoded)

    assert decoded == payload
    assert (version, seed, inner_format) == (2, 7, "ccz")


def test_extract_uf_resources_decompresses_ccz(tmp_path: Path) -> None:
    package = "com.example.demo"
    source = tmp_path / "exports" / package / "assets"
    source.mkdir(parents=True)
    inner = b"PVR\x03" + b"texture-payload"
    ccz = b"CCZ!" + bytes(8) + struct.pack(">I", len(inner)) + zlib.compress(inner)
    (source / "demo.png").write_bytes(_encode_uf02(ccz, seed=3))
    progress: list[tuple[int, int, Path]] = []

    result = extract_uf_resources(
        package,
        source_base=tmp_path / "exports",
        output_base=tmp_path / "uf_exports",
        progress_callback=lambda processed, decoded, path: progress.append(
            (processed, decoded, path)
        ),
    )

    output = tmp_path / "uf_exports" / package / "assets" / "demo.png.decoded"
    assert result.resource_count == 1
    assert output.read_bytes() == inner
    assert result.resources[0].inner_format == "pvr"
    assert progress[0][:2] == (0, 0)
    assert progress[-1][:2] == (1, 1)


def test_extract_uf_resources_merges_into_existing_spine_tree(tmp_path: Path) -> None:
    package = "com.example.demo"
    source = tmp_path / "exports" / package / "bundle"
    source.mkdir(parents=True)
    (source / "demo.png").write_bytes(_encode_uf02(b"PVR\x03payload"))

    output = tmp_path / "spine_exports" / package / "bundle"
    output.mkdir(parents=True)
    (output / "demo.atlas").write_text("demo.png\n", encoding="utf-8")
    (output / "demo.skel").write_bytes(b"skeleton")

    extract_uf_resources(
        package,
        source_base=tmp_path / "exports",
        output_base=tmp_path / "spine_exports",
    )

    assert (output / "demo.atlas").is_file()
    assert (output / "demo.skel").read_bytes() == b"skeleton"
    assert (output / "demo.png.decoded").read_bytes() == b"PVR\x03payload"
