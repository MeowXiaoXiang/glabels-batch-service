"""
glabels_engine.py
=================

Asynchronous wrapper for gLabels CLI (`glabels-3-batch`).

Design principles
-----------------
- Single responsibility: Only handles execution of "CSV + gLabels template → PDF".
- Encapsulation: `GlabelsEngine` manages binary path, concurrency control, and default timeout.
- Async/await: Uses asyncio, non-blocking for FastAPI / Starlette event loop.
- Clear error handling: Provides base `GlabelsRunError` and specific subclasses for timeout and execution failures.
- Caller responsibility:
    - Must prepare CSV and gLabels template file in advance.
    - Must ensure the output directory exists (this utility **will not** create it).
- Separation of concerns:
    - utils (this file): focuses on process execution and error reporting.
    - service/API layer: handles JSON→CSV conversion, file cleanup policy, and URL exposure.

Notes
-----
- Logging is done with loguru; log format remains consistent with the project.
- f-string is used throughout to avoid string concatenation pitfalls.
"""

from __future__ import annotations

import asyncio
import contextlib
from asyncio.subprocess import Process
from collections.abc import Sequence
from pathlib import Path

from loguru import logger

# Type alias: PathLike can be str or pathlib.Path
PathLike = str | Path

__all__ = [
    "GlabelsRunError",
    "GlabelsTimeoutError",
    "GlabelsExecutionError",
    "GlabelsEngine",
]


# Error classes
class GlabelsRunError(RuntimeError):
    """Base error for glabels-3-batch execution, carries returncode and stderr."""

    def __init__(self, message: str, rc: int | None = None, stderr: str | None = None):
        super().__init__(message)
        self.returncode = rc  # Subprocess return code (may be None if timeout)
        self.stderr = stderr or ""  # Captured stderr from the subprocess (may be empty)


class GlabelsTimeoutError(GlabelsRunError):
    """Raised when glabels-3-batch execution exceeds timeout."""

    def __init__(self, timeout: float | None):
        super().__init__(
            f"glabels execution timed out after {timeout}s", rc=None, stderr="timeout"
        )
        self.timeout = timeout


class GlabelsExecutionError(GlabelsRunError):
    """Raised when glabels-3-batch exits with non-zero code or PDF output is missing."""

    def __init__(self, rc: int, stderr: str):
        super().__init__(f"glabels execution failed (rc={rc})", rc=rc, stderr=stderr)


# Engine
class GlabelsEngine:
    """
    Asynchronous engine for running gLabels batch printing.

    - Controls concurrency using a semaphore to limit child processes.
    - Does not generate CSV; caller must supply it.
    - Does not create output directories; caller must ensure paths are valid.
    """

    def __init__(
        self,
        *,
        glabels_bin: str | Path = "glabels-3-batch",
        max_parallel: int = 1,
        default_timeout: float | None = None,
    ):
        self.glabels_bin = f"{glabels_bin}"  # CLI binary path
        self._semaphore = asyncio.Semaphore(
            max(1, int(max_parallel))
        )  # Concurrency control
        self.default_timeout = default_timeout  # Default timeout (can be overridden)

    async def _communicate_with_timeout(
        self, proc: Process, timeout: float | None
    ) -> tuple[bytes, bytes]:
        """
        Wait for subprocess to finish, with optional timeout.
        If timeout occurs, the process will be killed and awaited to avoid zombies.
        """
        try:
            return await asyncio.wait_for(proc.communicate(), timeout=timeout)
        except TimeoutError:
            with contextlib.suppress(ProcessLookupError):
                proc.kill()
                await proc.wait()
            raise GlabelsTimeoutError(timeout)

    async def run_batch(
        self,
        *,
        output_pdf: PathLike,
        template_path: PathLike,
        csv_path: PathLike,
        extra_args: Sequence[str] = (),
        timeout: float | None = None,
        log_truncate: int = 4096,  # Maximum log size to prevent flooding
    ) -> tuple[int, str, str]:
        """
        Execute glabels-3-batch with CSV + template to generate a PDF.

        Example command:
            glabels-3-batch -o output.pdf -i data.csv template.glabels

        Parameters
        ----------
        output_pdf : PathLike
            Path for the output PDF (must be writable).
        template_path : PathLike
            Path to .glabels template file (must exist).
        csv_path : PathLike
            Path to CSV file (must exist, UTF-8).
        extra_args : Sequence[str]
            Additional CLI args, e.g. ["--copies=2"].
        timeout : Optional[float]
            Timeout in seconds; defaults to self.default_timeout if not specified.
        log_truncate : int
            Maximum number of characters to keep in logged stdout/stderr.

        Returns
        -------
        tuple[int, str, str]
            (returncode, stdout, stderr)

        Raises
        ------
        FileNotFoundError
            If template or CSV file does not exist.
        GlabelsTimeoutError
            If execution times out.
        GlabelsExecutionError
            If return code is non-zero or PDF file is missing.
        """
        out = Path(output_pdf)
        tpl = Path(template_path)
        csv = Path(csv_path)

        # Safety check: Ensure input files exist
        if not tpl.exists():
            raise FileNotFoundError(f"gLabels template not found: {tpl}")
        if not csv.exists():
            raise FileNotFoundError(f"CSV file not found: {csv}")

        # Build command line
        cmd = [
            f"{self.glabels_bin}",
            "-o",
            f"{out}",
            "-i",
            f"{csv}",
            f"{tpl}",
            *map(str, extra_args),
        ]
        logger.debug(f"running glabels: {' '.join(cmd)}")

        # Determine effective timeout
        effective_timeout = timeout if timeout is not None else self.default_timeout

        # Limit concurrent processes
        async with self._semaphore:
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout_b, stderr_b = await self._communicate_with_timeout(
                proc, timeout=effective_timeout
            )

        rc = proc.returncode if proc.returncode is not None else -1
        stdout = stdout_b.decode("utf-8", errors="ignore") if stdout_b else ""
        stderr = stderr_b.decode("utf-8", errors="ignore") if stderr_b else ""

        # Guard: Sometimes rc=0 but file is not yet flushed to disk
        if rc == 0 and not out.exists():
            for _ in range(5):  # Retry for up to 0.5s
                await asyncio.sleep(0.1)
                if out.exists():
                    break

        # Failure condition: rc != 0 or PDF not created
        if rc != 0 or not out.exists():
            raise GlabelsExecutionError(rc=rc, stderr=stderr)

        # Success logging
        logger.info(f"glabels done → {out}")
        if stdout:
            chunk = stdout.strip()[:log_truncate]
            logger.debug(f"glabels stdout (truncated):\n{chunk}")
        if stderr:
            chunk = stderr.strip()[:log_truncate]
            logger.debug(f"glabels stderr (truncated):\n{chunk}")

        return rc, stdout, stderr
