# Image Shrinker

[![Tests](https://github.com/BureauObscura/image-shrinker/actions/workflows/tests.yml/badge.svg)](https://github.com/BureauObscura/image-shrinker/actions/workflows/tests.yml)

Image Shrinker reduces PNG file sizes with a four-stage optimization pipeline built for storage-sensitive digital art. It keeps source images untouched, writes results to a separate directory, and retains the smallest output produced by the pipeline.

By default, Image Shrinker uses palette reduction and is **lossy**. Use `--lossless` to skip palette reduction and explicit metadata stripping.

## Requirements

- Python 3.10 or newer
- [pngquant](https://pngquant.org/)
- [OptiPNG](https://optipng.sourceforge.net/)
- [pngcrush](https://pmt.sourceforge.io/pngcrush/)
- [AdvanceCOMP](https://www.advancemame.it/comp-readme) (`advpng`)

Install the optimization tools on macOS with Homebrew:

```bash
brew install pngquant optipng pngcrush advancecomp
```

On Ubuntu or Debian:

```bash
sudo apt update
sudo apt install pngquant optipng pngcrush advancecomp
```

## Install

```bash
git clone https://github.com/BureauObscura/image-shrinker.git
cd image-shrinker
python3 -m pip install .
```

## Use

Shrink every PNG directly inside a folder:

```bash
image-shrinker ~/path/to/art
```

Results are written to `~/path/to/art/crushed`. The command does not search subdirectories.

Choose another output directory:

```bash
image-shrinker ~/path/to/art --output ~/path/to/optimized
```

Preserve decoded pixel values and avoid explicit metadata stripping:

```bash
image-shrinker ~/path/to/art --lossless
```

Replace files already present in the output directory:

```bash
image-shrinker ~/path/to/art --overwrite
```

You can also run the package as a module:

```bash
python3 -m image_shrinker ~/path/to/art
```

The command exits with `0` after a clean run, `1` if an image or filesystem operation fails, `2` for invalid command-line arguments, and `3` when a required optimizer is missing. For safety, it refuses output files and output directories that are symbolic links.

## What it does

The default pipeline runs each image through:

1. `pngquant` to reduce the palette and strip metadata.
2. `optipng -o7` to optimize PNG encoding.
3. `pngcrush -reduce -brute` to remove ancillary chunks and try additional compression strategies.
4. `advpng -z -4` for a final recompression pass.

Image Shrinker compares the original, intermediate, and final sizes and copies the smallest candidate to the output directory. Temporary files are isolated and automatically removed, even when a tool fails.

### Image fidelity

The default `pngquant` step can alter colors because it limits the image to a palette. This is often effective for illustrations and pixel art, but subtle gradients may show changes. Review compressed artwork before publishing it permanently.

In the default mode, optimized candidates remove ancillary PNG chunks, including embedded color-profile and textual metadata. With `--lossless`, Image Shrinker does not ask the optimizers to strip those chunks, though an optimizer may still normalize chunks as part of lossless PNG processing. If no optimized candidate is smaller, Image Shrinker copies the original unchanged.

## Development

Run the test suite with:

```bash
PYTHONPATH=src python3 -m unittest discover -s tests -v
```

The unit tests mock the external optimizers, so the four native tools are not required locally. An end-to-end test runs automatically when all four tools are installed; GitHub Actions installs them for the Python 3.12 job.

## License

MIT

