#!/usr/bin/env python3
"""
PDF Processor - PDF helper tools for File Processor

Handles:
- PDF page counting
- PDF page range parsing (e.g., '1-5', '3,5,7')
- PDF page splitting using pypdf
"""

import sys
from pathlib import Path
from typing import List, Optional, Set

try:
    from pypdf import PdfReader, PdfWriter

    HAVE_PYPDF = True
except ImportError:
    HAVE_PYPDF = False

from src.console import print_error, print_info, print_warning


def is_pypdf_available() -> bool:
    """Check if pypdf library is available"""
    return HAVE_PYPDF


def get_pdf_page_count(filepath: Path) -> Optional[int]:
    """
    Get the total page count of a PDF file.

    Args:
        filepath: Path to the PDF file

    Returns:
        Number of pages, or None if error/not installed
    """
    if not HAVE_PYPDF:
        print_error("pypdf is not installed. Run `uv pip install -r requirements.txt`.")
        return None

    try:
        reader = PdfReader(filepath)
        return len(reader.pages)
    except Exception as e:
        print_error(f"Failed to read PDF pages from {filepath.name}: {e}")
        return None


def parse_page_range(range_str: str, max_pages: int) -> List[int]:
    """
    Parse a user-input page range string into 0-based page indices.

    Supports:
    - 'all': All pages
    - Single numbers: '1', '5'
    - Ranges: '1-5', '10-12'
    - Lists: '1, 3, 5'
    - Combined: '1-3, 5, 7-9'

    Args:
        range_str: User input string (1-based page numbers)
        max_pages: Total number of pages in the PDF

    Returns:
        Sorted list of 0-based page indices
    """
    cleaned = range_str.strip().lower()
    if not cleaned or cleaned == "all":
        return list(range(max_pages))

    pages: Set[int] = set()
    parts = [p.strip() for p in cleaned.split(",")]

    for part in parts:
        if not part:
            continue
        if "-" in part:
            try:
                start_str, end_str = part.split("-", 1)
                start = int(start_str.strip())
                end = int(end_str.strip())
                # Clamp boundaries (1-based to 0-based)
                start_idx = max(0, start - 1)
                end_idx = min(max_pages, end)
                for idx in range(start_idx, end_idx):
                    pages.add(idx)
            except ValueError:
                print_warning(f"Skipping invalid range part: '{part}'")
        else:
            try:
                page_num = int(part)
                if 1 <= page_num <= max_pages:
                    pages.add(page_num - 1)
                else:
                    print_warning(f"Skipping page number out of bounds: {page_num} (Max: {max_pages})")
            except ValueError:
                print_warning(f"Skipping invalid page part: '{part}'")

    return sorted(list(pages))


def split_pdf(filepath: Path, pages: List[int], output_dir: Path) -> List[Path]:
    """
    Split specific pages of a PDF into individual PDF files.

    Args:
        filepath: Path to the source PDF
        pages: List of 0-based page indices to split
        output_dir: Directory to save the split PDFs

    Returns:
        List of paths to the split PDF files
    """
    if not HAVE_PYPDF:
        raise RuntimeError("pypdf is not installed.")

    filepath = Path(filepath)
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    reader = PdfReader(filepath)
    if reader.is_encrypted:
        # Try to decrypt empty password, common for some PDFs
        try:
            reader.decrypt("")
        except Exception:
            raise ValueError(f"PDF '{filepath.name}' is encrypted and could not be decrypted.")

    split_paths: List[Path] = []
    base_name = filepath.stem

    for idx in pages:
        if idx < 0 or idx >= len(reader.pages):
            continue

        writer = PdfWriter()
        writer.add_page(reader.pages[idx])

        # Name with short page suffix: <pdf_name>_p<1-based_page_num>.pdf
        page_num = idx + 1
        output_filename = f"{base_name}_p{page_num}.pdf"
        output_path = output_dir / output_filename

        try:
            with open(output_path, "wb") as f:
                writer.write(f)
            split_paths.append(output_path)
        except Exception as e:
            print_error(f"Failed to write page {page_num} of {filepath.name}: {e}")
            # Clean up partial file if created
            if output_path.exists():
                output_path.unlink()
            raise

    return split_paths
