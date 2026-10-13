from __future__ import annotations

import shutil
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from image_shrinker import cli


def png_bytes(payload_size: int = 64) -> bytes:
    return cli.PNG_SIGNATURE + (b"x" * payload_size)


class ShrinkPngTests(unittest.TestCase):
    def test_lossy_pipeline_selects_the_smallest_candidate(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "ART.PNG"
            destination = root / "crushed" / source.name
            source.write_bytes(png_bytes(100))
            commands: list[list[str]] = []

            def fake_run(command: list[str]) -> None:
                commands.append(command)
                tool = command[0]
                if tool == "pngquant":
                    Path(command[command.index("--output") + 1]).write_bytes(png_bytes(60))
                elif tool == "pngcrush":
                    Path(command[-1]).write_bytes(png_bytes(20))

            tools = {
                "pngquant": "pngquant",
                "optipng": "optipng",
                "pngcrush": "pngcrush",
                "advpng": "advpng",
            }
            with mock.patch.object(cli, "run_tool", side_effect=fake_run):
                result = cli.shrink_png(source, destination, tools)

            self.assertEqual(destination.read_bytes(), png_bytes(20))
            self.assertEqual(result.bytes_saved, 80)
            self.assertEqual([command[0] for command in commands], list(tools))

    def test_lossless_pipeline_never_calls_pngquant(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "art.png"
            destination = root / "output" / source.name
            source.write_bytes(png_bytes())
            commands: list[list[str]] = []

            def fake_run(command: list[str]) -> None:
                commands.append(command)
                if command[0] == "pngcrush":
                    shutil.copyfile(command[-2], command[-1])

            tools = {
                "optipng": "optipng",
                "pngcrush": "pngcrush",
                "advpng": "advpng",
            }
            with mock.patch.object(cli, "run_tool", side_effect=fake_run):
                cli.shrink_png(source, destination, tools, lossless=True)

            self.assertNotIn("pngquant", [command[0] for command in commands])
            self.assertEqual(destination.read_bytes(), source.read_bytes())

    def test_existing_output_is_protected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "art.png"
            destination = root / "output.png"
            source.write_bytes(png_bytes())
            destination.write_bytes(b"keep me")

            with self.assertRaisesRegex(cli.ShrinkError, "already exists"):
                cli.shrink_png(source, destination, {}, lossless=True)
            self.assertEqual(destination.read_bytes(), b"keep me")

    def test_output_symlink_is_rejected_even_with_overwrite(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "art.png"
            target = root / "valuable.png"
            output_directory = root / "crushed"
            destination = output_directory / source.name
            source.write_bytes(png_bytes())
            target.write_bytes(b"keep me")
            output_directory.mkdir()
            try:
                destination.symlink_to(target)
            except (NotImplementedError, OSError) as error:
                self.skipTest(f"symlinks unavailable: {error}")

            with self.assertRaisesRegex(cli.ShrinkError, "output symlink"):
                cli.shrink_png(
                    source,
                    destination,
                    {},
                    lossless=True,
                    overwrite=True,
                )

            self.assertTrue(destination.is_symlink())
            self.assertEqual(target.read_bytes(), b"keep me")

    def test_tool_failure_leaves_source_untouched_and_no_partial_output(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "art.png"
            output_directory = root / "crushed"
            destination = output_directory / source.name
            original = png_bytes(100)
            source.write_bytes(original)

            def fake_run(command: list[str]) -> None:
                if command[0] == "pngquant":
                    Path(command[command.index("--output") + 1]).write_bytes(
                        png_bytes(60)
                    )
                    return
                raise cli.ShrinkError("simulated optimizer failure")

            tools = {
                "pngquant": "pngquant",
                "optipng": "optipng",
                "pngcrush": "pngcrush",
                "advpng": "advpng",
            }
            with (
                mock.patch.object(cli, "run_tool", side_effect=fake_run),
                self.assertRaisesRegex(cli.ShrinkError, "simulated"),
            ):
                cli.shrink_png(source, destination, tools)

            self.assertEqual(source.read_bytes(), original)
            self.assertFalse(destination.exists())
            self.assertEqual(list(output_directory.iterdir()), [])

    def test_rejects_a_non_png_file(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "fake.png"
            source.write_text("not a PNG", encoding="utf-8")

            with self.assertRaisesRegex(cli.ShrinkError, "valid PNG signature"):
                cli.shrink_png(source, root / "output.png", {}, lossless=True)


class MainTests(unittest.TestCase):
    def test_output_directory_symlink_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            external = root / "external"
            source_directory = root / "source"
            external.mkdir()
            source_directory.mkdir()
            (source_directory / "art.png").write_bytes(png_bytes())
            try:
                (source_directory / "crushed").symlink_to(
                    external, target_is_directory=True
                )
            except (NotImplementedError, OSError) as error:
                self.skipTest(f"symlinks unavailable: {error}")

            with mock.patch("builtins.print"):
                exit_code = cli.main([str(source_directory)])

            self.assertEqual(exit_code, 1)
            self.assertEqual(list(external.iterdir()), [])

    def test_uppercase_png_extension_is_processed(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "ART.PNG"
            source.write_bytes(png_bytes())
            expected_result = cli.ShrinkResult(source, root / "crushed" / source.name, 72, 64)

            with (
                mock.patch.object(cli, "find_tools", return_value={}),
                mock.patch.object(cli, "shrink_png", return_value=expected_result) as shrink,
                mock.patch("builtins.print"),
            ):
                exit_code = cli.main([str(root)])

            self.assertEqual(exit_code, 0)
            self.assertEqual(shrink.call_args.args[0], source)

    def test_missing_tools_returns_configuration_error(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "art.png").write_bytes(png_bytes())

            with mock.patch.object(
                cli, "find_tools", side_effect=cli.ShrinkError("missing")
            ), mock.patch("builtins.print"):
                exit_code = cli.main([str(root)])

            self.assertEqual(exit_code, 3)

    def test_failure_does_not_stop_the_remaining_images(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            first = root / "first.png"
            second = root / "second.png"
            first.write_bytes(png_bytes())
            second.write_bytes(png_bytes())

            second_result = cli.ShrinkResult(
                second,
                root / "crushed" / second.name,
                72,
                64,
            )
            with (
                mock.patch.object(cli, "find_tools", return_value={}),
                mock.patch.object(
                    cli,
                    "shrink_png",
                    side_effect=[cli.ShrinkError("failed"), second_result],
                ) as shrink,
                mock.patch("builtins.print"),
            ):
                exit_code = cli.main([str(root)])

            self.assertEqual(exit_code, 1)
            self.assertEqual(shrink.call_count, 2)


if __name__ == "__main__":
    unittest.main()

