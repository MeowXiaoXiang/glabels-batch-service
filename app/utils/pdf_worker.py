"""Importable path-only PDF operations. No API, settings or logging imports."""

import os
import shutil
from pathlib import Path


class PdfOperationError(RuntimeError):
    """Serializable error that does not load native PDF modules in the parent."""


def worker_identity() -> int:
    import pikepdf

    with pikepdf.Pdf.new():
        return os.getpid()


def assemble_pdf(
    paths: list[str], destination: str | None, max_bytes: int, max_pages: int
) -> int:
    try:
        return _assemble_pdf(paths, destination, max_bytes, max_pages)
    except Exception as exc:
        # Native exception classes otherwise import pikepdf when unpickled in
        # the API process. Send only our small, pure-Python error boundary.
        raise PdfOperationError(f"{type(exc).__name__}: {str(exc)[:300]}") from None


def _assemble_pdf(
    paths: list[str], destination: str | None, max_bytes: int, max_pages: int
) -> int:
    """Validate inputs and concatenate pages in caller order in this process."""
    import pikepdf

    if not paths or sum(Path(p).stat().st_size for p in paths) > max_bytes:
        raise ValueError("PDF input size limit exceeded or no inputs")
    page_count = 0
    with pikepdf.Pdf.new() as merged:
        for path in paths:
            if Path(path).stat().st_size == 0:
                raise ValueError("Empty PDF")
            with pikepdf.Pdf.open(path) as source:
                count = len(source.pages)
                if count == 0:
                    raise ValueError("PDF contains no pages")
                page_count += count
                if page_count > max_pages:
                    raise ValueError("PDF page limit exceeded")
                if destination is not None and len(paths) > 1:
                    merged.pages.extend(source.pages)
        if destination is not None:
            if len(paths) == 1:
                shutil.copyfile(paths[0], destination)
            else:
                merged.save(destination)
            if Path(destination).stat().st_size > max_bytes:
                raise ValueError("Final PDF size limit exceeded")
    return page_count
