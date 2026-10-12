"""Compress a PDF by optimising structure and (optionally) re-sampling images.

Text and vector content is never rasterised.  Only raster images are touched,
and only when the chosen preset says so.  Some PDFs cannot shrink – the result
reports the real outcome and never promises a reduction.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from .common import (JobContext, Result, atomic_output, open_pdf, save_pdf, size_change, structure_warnings,
                     validate_output_pdf)


@dataclass(frozen=True)
class Preset:
    label: str
    dpi_threshold: Optional[int]  # only images above this resolution are touched
    dpi_target: int
    quality: int
    explanation: str


PRESETS: dict[str, Preset] = {
    "low": Preset("Low (best quality)", None, 0, 0,
                  "Lossless: rebuilds and deflates the file structure. Images are not changed."),
    "medium": Preset("Medium (balanced)", 170, 150, 75,
                     "Images above ~170 dpi are down-sampled to 150 dpi and re-encoded at quality 75."),
    "high": Preset("High (smallest file)", 110, 96, 50,
                   "Images above ~110 dpi are down-sampled to 96 dpi at quality 50. Fine detail will be visibly reduced."),
}


def compress_pdf(input_pdf: Path, output: Path, preset: str = "medium", *, image_dpi: Optional[int] = None,
                 image_quality: Optional[int] = None, overwrite: bool = False,
                 ctx: JobContext | None = None) -> Result:
    """``image_dpi`` / ``image_quality`` override the preset when given."""
    ctx = ctx or JobContext()
    input_pdf = Path(input_pdf)
    p = PRESETS[preset]
    dpi = image_dpi if image_dpi is not None else p.dpi_target
    quality = image_quality if image_quality is not None else p.quality
    before = input_pdf.stat().st_size
    with open_pdf(input_pdf, replacing=output) as doc:
        warnings = structure_warnings(doc, input_pdf.name)
        ctx.busy("Compressing (this step cannot report percentages)")
        if dpi and quality:
            threshold = max(dpi + 20, int(dpi * 1.15)) if image_dpi is not None else (p.dpi_threshold or dpi + 20)
            doc.rewrite_images(dpi_threshold=threshold, dpi_target=dpi, quality=quality,
                               lossy=True, lossless=True, bitonal=False)
        with atomic_output(output, overwrite) as tmp:
            save_pdf(doc, tmp, garbage=4, deflate_images=True, deflate_fonts=True, use_objstms=1)
        expected = doc.page_count
    validate_output_pdf(output, expected_pages=expected)
    after = Path(output).stat().st_size
    reduced = after < before
    msg = f"{size_change(before, after)}."
    if not reduced:
        msg += " This PDF could not be made smaller with these settings (it may already be optimised)."
    return Result([Path(output)], msg, warnings,
                  {"before": before, "after": after, "reduced": reduced, "percent": (before - after) / before * 100})
