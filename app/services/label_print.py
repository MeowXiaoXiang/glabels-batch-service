# app/services/label_print.py
# Label Print Service (Core Business Logic)
# - JSON → CSV → gLabels → PDF
# - Supports automatic batch splitting + PDF merging for large datasets
# - info logs: job success/failure
# - debug logs: job start, CSV writing, temp file cleanup

from __future__ import annotations

import asyncio
import csv
import os
import re
import time
from datetime import datetime
from pathlib import Path
from typing import Dict, Iterable, List, Optional

from loguru import logger
from pypdf import PdfWriter

from app.config import settings
from app.utils.glabels_engine import GlabelsEngine, GlabelsRunError


# Utility functions
def _collect_fieldnames(rows: List[Dict], exclude: Iterable[str] = ()) -> List[str]:
    """
    Collect field names from JSON rows in the order of appearance.
    Optionally exclude specific keys.
    """
    seen = set()
    order: List[str] = []
    for row in rows:
        for k in row.keys():
            if k in exclude:
                continue
            if k not in seen:
                seen.add(k)
                order.append(k)
    return order


def _slug(s: str) -> str:
    """
    Convert string to a safe filename.
    Allowed characters: A-Z, a-z, 0-9, dot, underscore, hyphen.
    """
    return re.sub(r"[^A-Za-z0-9._-]", "_", s or "")


def _chunk_list(data: List, chunk_size: int) -> List[List]:
    """
    Split a list into multiple chunks.
    """
    if chunk_size <= 0:
        return [data]
    return [data[i : i + chunk_size] for i in range(0, len(data), chunk_size)]


def _merge_pdfs(pdf_paths: List[Path], output_path: Path) -> None:
    """
    Merge multiple PDF files using pypdf.
    """
    writer = PdfWriter()
    for pdf_path in pdf_paths:
        writer.append(str(pdf_path))
    with output_path.open("wb") as f:
        writer.write(f)
    writer.close()


# Label Print Service
class LabelPrintService:
    def __init__(
        self,
        max_parallel: Optional[int] = None,
        default_timeout: int = 300,
        keep_csv: bool = False,
    ):
        if max_parallel is None:
            max_parallel = max(1, (os.cpu_count() or 2) - 1)

        self.keep_csv = keep_csv
        self.engine = GlabelsEngine(
            max_parallel=max_parallel,
            default_timeout=default_timeout,
        )

    # --------------------------------------------------------
    # Generate output filename
    # --------------------------------------------------------
    @staticmethod
    def make_output_filename(template_name: str) -> str:
        """
        Generate a safe output PDF filename based on template name + timestamp.
        """
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        base = Path(template_name).stem
        return f"{_slug(base)}_{ts}.pdf"

    # --------------------------------------------------------
    # JSON → CSV
    # --------------------------------------------------------
    def _json_to_csv(
        self,
        data: List[Dict],
        csv_path: Path,
        field_order: Optional[List[str]] = None,
    ) -> List[str]:
        """
        Write JSON rows into a CSV file.
        """
        if not data:
            raise ValueError("No label data to generate CSV")

        fieldnames = field_order or _collect_fieldnames(data)
        logger.debug(f"[LabelPrint] Writing CSV {csv_path}, fields={fieldnames}")

        with csv_path.open("w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            for row in data:
                writer.writerow({k: row.get(k, "") for k in fieldnames})

        return fieldnames

    # --------------------------------------------------------
    # Resolve template path
    # --------------------------------------------------------
    def _resolve_template(self, template_name: str) -> Path:
        """
        Verify template file exists inside the templates/ directory.
        """
        if not template_name.lower().endswith(".glabels"):
            raise ValueError("Only .glabels templates are allowed")

        lower_name = template_name.lower()
        for f in Path("templates").iterdir():
            if f.name.lower() == lower_name:
                return f

        raise FileNotFoundError(f"gLabels template not found: {template_name}")

    # --------------------------------------------------------
    # Generate single batch PDF (internal method)
    # --------------------------------------------------------
    async def _generate_single_batch(
        self,
        *,
        job_id: str,
        batch_index: int,
        template_path: Path,
        data: List[Dict],
        copies: int,
        temp_dir: Path,
        output_dir: Path,
        field_order: Optional[List[str]] = None,
    ) -> Path:
        """
        Generate a single batch PDF (internal method).
        Returns the generated PDF path.
        """
        # Batch-specific CSV and PDF paths
        csv_path = temp_dir / f"{job_id}_batch{batch_index}.csv"
        batch_pdf = output_dir / f"{job_id}_batch{batch_index}.pdf"

        logger.debug(
            f"[LabelPrint] Batch {batch_index} starting: "
            f"labels={len(data)}, csv={csv_path.name}, pdf={batch_pdf.name}"
        )

        # JSON → CSV
        self._json_to_csv(data, csv_path, field_order=field_order)

        try:
            await self.engine.run_batch(
                output_pdf=batch_pdf,
                template_path=template_path,
                csv_path=csv_path,
                extra_args=[f"--copies={copies}"] if copies > 1 else [],
            )
            logger.debug(f"[LabelPrint] batch {batch_index} done -> {batch_pdf}")
            return batch_pdf
        finally:
            # Cleanup temp CSV
            if csv_path.exists() and not self.keep_csv:
                try:
                    csv_path.unlink()
                except OSError:
                    pass

    # --------------------------------------------------------
    # Core method: Generate PDF (with auto batch splitting)
    # --------------------------------------------------------
    async def generate_pdf(
        self,
        *,
        job_id: str,
        template_name: str,
        data: List[Dict],
        copies: int = 1,
        filename: str,
        field_order: Optional[List[str]] = None,
    ) -> Path:
        """
        Generate PDF based on template and JSON data.

        When label count exceeds MAX_LABELS_PER_BATCH, it will automatically:
        1. Split data into multiple batches
        2. Generate multiple small PDFs in parallel
        3. Merge them into the final PDF

        This prevents glabels from running out of memory or timing out
        when processing large datasets.
        """
        template_path = self._resolve_template(template_name)

        # Ensure directories exist
        temp_dir = Path("temp")
        output_dir = Path("output")
        temp_dir.mkdir(exist_ok=True)
        output_dir.mkdir(exist_ok=True)

        output_pdf = output_dir / filename
        start_time = time.time()

        # Get batch size setting
        max_per_batch = settings.MAX_LABELS_PER_BATCH
        total_labels = len(data)

        # Determine if batching is needed
        need_batch = max_per_batch > 0 and total_labels > max_per_batch

        logger.debug(
            f"[LabelPrint] Batch config: total_labels={total_labels}, "
            f"max_per_batch={max_per_batch}, need_batch={need_batch}"
        )

        if not need_batch:
            # ============ Single batch processing (original logic) ============
            csv_path = temp_dir / f"{job_id}.csv"
            self._json_to_csv(data, csv_path, field_order=field_order)

            logger.debug(
                f"[LabelPrint] START job_id={job_id}, template={template_path}, "
                f"labels={total_labels}, copies={copies}"
            )

            try:
                await self.engine.run_batch(
                    output_pdf=output_pdf,
                    template_path=template_path,
                    csv_path=csv_path,
                    extra_args=[f"--copies={copies}"] if copies > 1 else [],
                )
                duration = time.time() - start_time
                logger.info(
                    f"[LabelPrint] job_id={job_id} finished in {duration:.2f}s -> {output_pdf}"
                )
            except GlabelsRunError as e:
                duration = time.time() - start_time
                logger.error(
                    f"[LabelPrint] job_id={job_id} failed after {duration:.2f}s "
                    f"(rc={e.returncode})\n{e.stderr}"
                )
                truncated_stderr = (
                    (e.stderr[:1024] + "...") if len(e.stderr) > 1024 else e.stderr
                )
                raise RuntimeError(
                    f"Label PDF generation failed (rc={e.returncode})\n{truncated_stderr}"
                ) from e
            finally:
                if csv_path.exists() and not self.keep_csv:
                    try:
                        csv_path.unlink()
                        logger.debug(f"[LabelPrint] Deleted temp CSV: {csv_path}")
                    except OSError:
                        logger.warning(
                            f"[LabelPrint] Cannot delete temp CSV: {csv_path}"
                        )

            return output_pdf

        # ============ Batch processing ============
        chunks = _chunk_list(data, max_per_batch)
        num_batches = len(chunks)

        logger.info(
            f"[LabelPrint] START job_id={job_id}, template={template_path}, "
            f"labels={total_labels} → split into {num_batches} batches (max {max_per_batch}/batch)"
        )

        # Collect field order first to ensure consistency across batches
        if field_order is None:
            field_order = _collect_fieldnames(data)

        # Log batch size distribution
        batch_sizes = [len(chunk) for chunk in chunks]
        logger.debug(
            f"[LabelPrint] Batch distribution: {batch_sizes} "
            f"(total={sum(batch_sizes)}, batches={num_batches})"
        )

        batch_pdfs: List[Path] = []
        batch_pdf_paths = [
            output_dir / f"{job_id}_batch{i}.pdf" for i in range(num_batches)
        ]
        try:
            # Generate all batch PDFs in parallel
            tasks = [
                self._generate_single_batch(
                    job_id=job_id,
                    batch_index=i,
                    template_path=template_path,
                    data=chunk,
                    copies=copies,
                    temp_dir=temp_dir,
                    output_dir=output_dir,
                    field_order=field_order,
                )
                for i, chunk in enumerate(chunks)
            ]
            results = await asyncio.gather(*tasks, return_exceptions=True)
            errors = [r for r in results if isinstance(r, Exception)]
            if errors:
                raise errors[0]
            batch_pdfs = [r for r in results if isinstance(r, Path)]

            # Merge all batch PDFs
            logger.debug(f"[LabelPrint] Merging {num_batches} PDFs...")
            merge_start = time.time()
            _merge_pdfs(batch_pdfs, output_pdf)
            merge_duration = time.time() - merge_start
            logger.debug(f"[LabelPrint] Merge completed in {merge_duration:.2f}s")

            duration = time.time() - start_time
            logger.info(
                f"[LabelPrint] job_id={job_id} finished in {duration:.2f}s "
                f"({num_batches} batches merged) -> {output_pdf}"
            )

        except Exception as e:
            duration = time.time() - start_time
            logger.error(
                f"[LabelPrint] job_id={job_id} failed after {duration:.2f}s: {e}"
            )
            raise RuntimeError(f"Label PDF generation failed: {e}") from e

        finally:
            # Cleanup all batch temp PDFs
            for batch_pdf in batch_pdf_paths:
                if batch_pdf.exists():
                    try:
                        batch_pdf.unlink()
                        logger.debug(f"[LabelPrint] Deleted batch PDF: {batch_pdf}")
                    except OSError:
                        logger.warning(
                            f"[LabelPrint] Cannot delete batch PDF: {batch_pdf}"
                        )

        return output_pdf
