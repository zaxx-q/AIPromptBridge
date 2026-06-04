#!/usr/bin/env python3
"""
Pack Emoji Assets into a ZIP file.

This script compresses the emoji PNG assets from 'assets/emojis/72x72'
into a single 'assets/emojis.zip' file. This improves distribution
cleanliness and allows for RAM-based loading in the application.

Usage:
    python tools/pack_emojis.py
"""

import sys
import zipfile
from pathlib import Path


def pack_emojis():
    # Define paths
    root_dir = Path(__file__).parent.parent
    assets_dir = root_dir / "assets"
    source_dir = assets_dir / "emojis" / "72x72"
    output_zip = assets_dir / "emojis.zip"

    if not source_dir.exists():
        print(f"Error: Source directory not found: {source_dir}")
        sys.exit(1)

    print(f"Packing emojis from {source_dir}...")
    print(f"Output: {output_zip}")

    count = 0
    with zipfile.ZipFile(output_zip, 'w', zipfile.ZIP_DEFLATED) as zf:
        for file_path in source_dir.glob("*.png"):
            # Store just the filename in the zip (flattened structure)
            zf.write(file_path, arcname=file_path.name)
            count += 1
            if count % 100 == 0:
                print(f"Packed {count} files...", end='\r')

    print(f"\nSuccess! Packed {count} emoji files into {output_zip}")
    print(f"Zip size: {output_zip.stat().st_size / 1024 / 1024:.2f} MB")

if __name__ == "__main__":
    pack_emojis()
