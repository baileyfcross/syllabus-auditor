#!/usr/bin/env python3
"""Create a native macOS .icns from the Windows ICO used by Syllabus Auditor.

Usage: python packaging/macos/create_icon.py INPUT.ico OUTPUT.icns

The macOS build script invokes this helper after installing Pillow. It writes
Apple's standard .iconset PNG sizes and uses the macOS iconutil command to
produce the .icns consumed by PyInstaller. Temporary PNGs are cleaned up.
"""
from __future__ import annotations

import argparse
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile

from PIL import Image, ImageOps, UnidentifiedImageError


ICON_SIZES = (
    ("icon_16x16.png", 16),
    ("icon_16x16@2x.png", 32),
    ("icon_32x32.png", 32),
    ("icon_32x32@2x.png", 64),
    ("icon_128x128.png", 128),
    ("icon_128x128@2x.png", 256),
    ("icon_256x256.png", 256),
    ("icon_256x256@2x.png", 512),
    ("icon_512x512.png", 512),
    ("icon_512x512@2x.png", 1024),
)


def select_largest_image(input_path: Path) -> Image.Image:
    """Select highest-resolution ICO representation, preserving transparency."""
    with Image.open(input_path) as source:
        if source.format == "ICO":
            sizes = source.ico.sizes()
            if not sizes:
                raise ValueError(f"No usable images in ICO: {input_path}")
            source.size = max(sizes, key=lambda pair: pair[0] * pair[1])
        image = source.convert("RGBA")
        image.load()
        return image.copy()


def render_icon_png(source: Image.Image, size: int, destination: Path) -> None:
    # Contain rather than stretch in case the original image isn't square.
    thumb = ImageOps.contain(source, (size, size), method=Image.Resampling.LANCZOS)
    canvas = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    canvas.alpha_composite(thumb, ((size - thumb.width) // 2, (size - thumb.height) // 2))
    canvas.save(destination, format="PNG")


def convert(source_path: Path, destination_path: Path) -> None:
    source_path = source_path.expanduser().resolve()
    destination_path = destination_path.expanduser().resolve()
    if not source_path.is_file():
        raise FileNotFoundError(f"Source icon not found: {source_path}")
    if source_path.suffix.lower() not in {".ico", ".png"}:
        raise ValueError("Source icon must be .ico or .png")
    if destination_path.suffix.lower() != ".icns":
        raise ValueError("Destination icon must have an .icns extension")
    executable = shutil.which("iconutil")
    if not executable:
        raise RuntimeError("macOS iconutil was not found. Run this script on a Mac with Xcode Command Line Tools installed.")

    image = select_largest_image(source_path)
    destination_path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="sa-macos-icon-") as directory:
        iconset = Path(directory) / "SyllabusAuditor.iconset"
        iconset.mkdir()
        for name, size in ICON_SIZES:
            render_icon_png(image, size, iconset / name)
        subprocess.run([executable, "-c", "icns", "-o", str(destination_path), str(iconset)], check=True)
    if not destination_path.is_file() or destination_path.stat().st_size == 0:
        raise RuntimeError(f"iconutil did not create a usable icon: {destination_path}")
    print(f"macOS icon generated: {destination_path}")


def main() -> int:
    parser = argparse.ArgumentParser(description="Convert Syllabus Auditor's ICO into macOS ICNS")
    parser.add_argument("source", type=Path, help="Windows .ico (or PNG) source")
    parser.add_argument("output", type=Path, help="Output .icns file")
    args = parser.parse_args()
    try:
        convert(args.source, args.output)
    except (OSError, ValueError, RuntimeError, UnidentifiedImageError, subprocess.CalledProcessError) as exc:
        print(f"ERROR: Could not convert macOS app icon: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
