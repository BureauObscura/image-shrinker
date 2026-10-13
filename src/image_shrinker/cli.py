"""Command-line interface for shrinking PNG files."""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Sequence

from . import __version__

PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"


class ShrinkError(RuntimeError):
    """Raised when an image cannot be safely optimized."""


@dataclass(frozen=True)
class ShrinkResult:
    """The size change produced for one image."""

    input_path: Path
    output_path: Path
    original_size: int
    output_size: int

    @property
    def bytes_saved(self) -> int:
        return self.original_size - self.output_size

    @property
    def percent_saved(self) -> float:
        if self.original_size == 0:
            return 0.0
        return self.bytes_saved / self.original_size * 100


def required_tool_names(*, lossless: bool) -> tuple[str, ...]:
    """Return the command-line tools required for the selected mode."""

    if lossless:
        return ("optipng", "pngcrush", "advpng")
    return ("pngquant", "optipng", "pngcrush", "advpng")


def find_tools(*, lossless: bool) -> dict[str, str]:
    """Resolve required executables from PATH and report all missing tools."""

    tools: dict[str, str] = {}
    missing: list[str] = []

    for name in required_tool_names(lossless=lossless):
        executable = shutil.which(name)
        if executable is None:
            missing.append(name)
        else:
            tools[name] = executable

    if missing:
        joined = ", ".join(missing)
        raise ShrinkError(
            f"Missing required tool{'s' if len(missing) > 1 else ''}: {joined}. "
            "See the README for installation instructions."
        )

    return tools


def run_tool(command: Sequence[str]) -> None:
    """Run one optimizer without invoking a shell."""

    completed = subprocess.run(
        command,
        check=False,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    if completed.returncode == 0:
        return

    tool_name = Path(command[0]).name
    details = completed.stderr.strip() or completed.stdout.strip()
    message = f"{tool_name} failed with exit code {completed.returncode}"
    if details:
        message = f"{message}: {details}"
    raise ShrinkError(message)


def is_png(path: Path) -> bool:
    """Check the PNG signature before passing a file to external tools."""

    try:
        with path.open("rb") as image:
            return image.read(len(PNG_SIGNATURE)) == PNG_SIGNATURE
    except OSError:
        return False


def shrink_png(
    input_path: Path,
    output_path: Path,
    tools: dict[str, str],
    *,
    lossless: bool = False,
    overwrite: bool = False,
) -> ShrinkResult:
    """Optimize one PNG and atomically place the smallest result in output_path."""

    input_path = input_path.expanduser().resolve()
    output_candidate = output_path.expanduser()
    output_path = output_candidate.parent.resolve() / output_candidate.name

    if input_path == output_path:
        raise ShrinkError("Input and output paths must be different.")
    if not input_path.is_file():
        raise ShrinkError(f"Input file does not exist: {input_path}")
    if not is_png(input_path):
        raise ShrinkError("File does not have a valid PNG signature.")
    if output_path.is_symlink():
        raise ShrinkError(f"Refusing to replace an output symlink: {output_path}")
    if output_path.is_dir():
        raise ShrinkError(f"Output path is a directory: {output_path}")
    if output_path.exists() and not overwrite:
        raise ShrinkError(f"Output already exists: {output_path}")

    output_path.parent.mkdir(parents=True, exist_ok=True)
    original_size = input_path.stat().st_size

    with tempfile.TemporaryDirectory(
        prefix=".image-shrinker-", dir=output_path.parent
    ) as temporary_directory:
        temporary_path = Path(temporary_directory)
        first_pass = temporary_path / "first-pass.png"

        if lossless:
            shutil.copyfile(input_path, first_pass)
        else:
            run_tool(
                [
                    tools["pngquant"],
                    "--strip",
                    "--output",
                    str(first_pass),
                    str(input_path),
                ]
            )

        run_tool([tools["optipng"], "-quiet", "-o7", str(first_pass)])
        if not is_png(first_pass):
            raise ShrinkError("The first optimization pass produced an invalid PNG.")

        final_pass = temporary_path / "final-pass.png"
        pngcrush_command = [tools["pngcrush"], "-q"]
        if not lossless:
            pngcrush_command.extend(["-rem", "alla"])
        pngcrush_command.extend(
            ["-reduce", "-brute", str(first_pass), str(final_pass)]
        )
        run_tool(pngcrush_command)
        run_tool([tools["advpng"], "-z", "-4", str(final_pass)])
        if not is_png(final_pass):
            raise ShrinkError("The final optimization pass produced an invalid PNG.")

        candidates = (input_path, first_pass, final_pass)
        available_candidates = [path for path in candidates if path.is_file()]
        if not available_candidates:
            raise ShrinkError("The optimization pipeline produced no output.")

        best_path = min(available_candidates, key=lambda path: path.stat().st_size)
        staged_output = temporary_path / "result.png"
        shutil.copyfile(best_path, staged_output)
        if output_path.is_symlink():
            raise ShrinkError(f"Refusing to replace an output symlink: {output_path}")
        if output_path.exists() and not overwrite:
            raise ShrinkError(f"Output appeared during optimization: {output_path}")
        os.replace(staged_output, output_path)

    return ShrinkResult(
        input_path=input_path,
        output_path=output_path,
        original_size=original_size,
        output_size=output_path.stat().st_size,
    )


def format_bytes(byte_count: int) -> str:
    """Format a byte count using binary units."""

    value = float(byte_count)
    for unit in ("B", "KiB", "MiB", "GiB"):
        if abs(value) < 1024 or unit == "GiB":
            return f"{value:.0f} {unit}" if unit == "B" else f"{value:.1f} {unit}"
        value /= 1024
    return f"{value:.1f} GiB"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="image-shrinker",
        description="Shrink PNG files with pngquant, OptiPNG, pngcrush, and AdvanceCOMP.",
    )
    parser.add_argument(
        "directory",
        nargs="?",
        default=".",
        type=Path,
        help="directory containing PNG files (default: current directory)",
    )
    parser.add_argument(
        "-o",
        "--output",
        type=Path,
        help="output directory (default: DIRECTORY/crushed)",
    )
    parser.add_argument(
        "--lossless",
        action="store_true",
        help="skip palette reduction and explicit metadata stripping",
    )
    parser.add_argument(
        "--overwrite",
        action="store_true",
        help="replace files that already exist in the output directory",
    )
    parser.add_argument(
        "--version", action="version", version=f"%(prog)s {__version__}"
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """Run the Image Shrinker CLI and return a process exit code."""

    parser = build_parser()
    args = parser.parse_args(argv)

    try:
        source_directory = args.directory.expanduser().resolve()
    except OSError as error:
        print(f"Error: cannot resolve input directory: {error}", file=sys.stderr)
        return 1
    if not source_directory.is_dir():
        parser.error(f"directory does not exist: {source_directory}")

    output_candidate = (
        args.output.expanduser()
        if args.output is not None
        else source_directory / "crushed"
    )
    if output_candidate.is_symlink():
        print(
            f"Error: refusing to use an output-directory symlink: {output_candidate}",
            file=sys.stderr,
        )
        return 1
    try:
        output_directory = output_candidate.resolve()
    except OSError as error:
        print(f"Error: cannot resolve output directory: {error}", file=sys.stderr)
        return 1
    if output_directory == source_directory:
        parser.error("the output directory must be different from the input directory")

    try:
        image_paths = sorted(
            (
                path
                for path in source_directory.iterdir()
                if path.is_file() and path.suffix.lower() == ".png"
            ),
            key=lambda path: path.name.lower(),
        )
    except OSError as error:
        print(f"Error: cannot read input directory: {error}", file=sys.stderr)
        return 1
    if not image_paths:
        print(f"No PNG files found in {source_directory}")
        return 0

    try:
        tools = find_tools(lossless=args.lossless)
    except ShrinkError as error:
        print(f"Error: {error}", file=sys.stderr)
        return 3

    try:
        output_directory.mkdir(parents=True, exist_ok=True)
    except OSError as error:
        print(f"Error: cannot create output directory: {error}", file=sys.stderr)
        return 1
    completed = 0
    skipped = 0
    failed = 0
    original_total = 0
    output_total = 0

    for input_path in image_paths:
        output_path = output_directory / input_path.name
        if output_path.exists() and not args.overwrite:
            print(f"Skipped: {input_path.name} (output already exists)")
            skipped += 1
            continue

        try:
            result = shrink_png(
                input_path,
                output_path,
                tools,
                lossless=args.lossless,
                overwrite=args.overwrite,
            )
        except (OSError, ShrinkError) as error:
            print(f"Failed: {input_path.name}: {error}", file=sys.stderr)
            failed += 1
            continue

        completed += 1
        original_total += result.original_size
        output_total += result.output_size
        print(
            f"Optimized: {input_path.name} — "
            f"{format_bytes(result.original_size)} → {format_bytes(result.output_size)} "
            f"({result.percent_saved:.1f}% smaller)"
        )

    summary = f"Completed: {completed}, skipped: {skipped}, failed: {failed}"
    if completed:
        saved = original_total - output_total
        percentage = saved / original_total * 100 if original_total else 0.0
        summary += f", saved: {format_bytes(saved)} ({percentage:.1f}%)"
    print(summary)
    return 1 if failed else 0

