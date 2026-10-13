from __future__ import annotations

import shutil
import struct
import tempfile
import unittest
import zlib
from pathlib import Path

from image_shrinker import cli


def png_chunk(chunk_type: bytes, data: bytes) -> bytes:
    checksum = zlib.crc32(chunk_type + data) & 0xFFFFFFFF
    return (
        struct.pack(">I", len(data))
        + chunk_type
        + data
        + struct.pack(">I", checksum)
    )


def create_test_png(path: Path, size: int = 32) -> None:
    rows = bytearray()
    for y in range(size):
        rows.append(0)
        for x in range(size):
            rows.extend((x * 7 % 256, y * 7 % 256, (x * 13 + y * 17) % 256, 255))

    header = struct.pack(">IIBBBBB", size, size, 8, 6, 0, 0, 0)
    path.write_bytes(
        cli.PNG_SIGNATURE
        + png_chunk(b"IHDR", header)
        + png_chunk(b"IDAT", zlib.compress(bytes(rows)))
        + png_chunk(b"IEND", b"")
    )


REQUIRED_TOOLS_AVAILABLE = all(
    shutil.which(name) for name in cli.required_tool_names(lossless=False)
)


@unittest.skipUnless(REQUIRED_TOOLS_AVAILABLE, "native PNG optimizers are not installed")
class NativePipelineTests(unittest.TestCase):
    def test_real_pipeline_produces_a_valid_png_without_touching_source(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "art.png"
            destination = root / "crushed" / source.name
            create_test_png(source)
            original = source.read_bytes()

            result = cli.shrink_png(
                source,
                destination,
                cli.find_tools(lossless=False),
            )

            self.assertEqual(source.read_bytes(), original)
            self.assertTrue(cli.is_png(destination))
            self.assertLessEqual(result.output_size, result.original_size)


if __name__ == "__main__":
    unittest.main()

