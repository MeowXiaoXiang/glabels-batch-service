"""Common GTK/Qt argv adapter with bounded diagnostics and owned cleanup."""

import asyncio
import contextlib
import os
import shutil
import signal
import sys
from asyncio.subprocess import Process
from pathlib import Path

from app.services.pdf_merger import WorkerUnavailable
from app.utils.tasks import owned, settle


class GlabelsRunError(RuntimeError):
    pass


class GlabelsTimeoutError(GlabelsRunError):
    pass


class GlabelsEngine:
    def __init__(
        self,
        *,
        glabels_bin: str = "glabels-3-batch",
        default_timeout: float = 600,
        reap_timeout: float = 5,
    ) -> None:
        self.glabels_bin = glabels_bin
        self.default_timeout = default_timeout
        self.reap_timeout = reap_timeout
        self.healthy = True

    def verify(self) -> None:
        if shutil.which(self.glabels_bin) is None:
            raise FileNotFoundError("Configured GLABELS_EXECUTABLE is unavailable")

    async def run_batch(
        self, *, output_pdf: Path, template_path: Path, csv_path: Path, copies: int = 1
    ) -> None:
        await owned(
            asyncio.create_task(self._run(output_pdf, template_path, csv_path, copies))
        )

    async def _read(self, stream: asyncio.StreamReader | None) -> str:
        if stream is None:
            raise RuntimeError("Renderer diagnostic pipe unavailable")
        tail = b""
        while data := await stream.read(65536):
            tail = (tail + data)[-4096:]
        return tail.decode("utf-8", errors="replace")

    async def _stop(self, proc: Process) -> None:
        if sys.platform != "win32":
            with contextlib.suppress(ProcessLookupError):
                os.killpg(proc.pid, signal.SIGTERM)
            await asyncio.sleep(0.1)
            with contextlib.suppress(ProcessLookupError):
                os.killpg(proc.pid, signal.SIGKILL)
        elif proc.returncode is None:
            # Windows native CLI / compatible wrappers: stop only this owned
            # child tree. Linux deployments use an isolated process group.
            killer = await asyncio.create_subprocess_exec(
                "taskkill.exe",
                "/PID",
                str(proc.pid),
                "/T",
                "/F",
                stdout=asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.DEVNULL,
            )
            try:
                await asyncio.wait_for(killer.wait(), self.reap_timeout)
            except TimeoutError:
                killer.kill()
                await killer.wait()
            if proc.returncode is None:
                with contextlib.suppress(ProcessLookupError):
                    proc.kill()
        try:
            await asyncio.wait_for(proc.wait(), self.reap_timeout)
        except TimeoutError as exc:
            self.healthy = False
            raise WorkerUnavailable("Renderer process exit not confirmed") from exc

    async def _terminate_and_drain(self, proc: Process) -> None:
        readers = [
            asyncio.create_task(self._read(proc.stdout)),
            asyncio.create_task(self._read(proc.stderr)),
        ]
        try:
            await self._stop(proc)
            # A Windows proactor transport can outlive wait() if its pipe EOF
            # callbacks were abandoned by cancelling the original readers.
            await asyncio.wait_for(asyncio.gather(*readers), self.reap_timeout)
        except BaseException as exc:
            for reader in readers:
                reader.cancel()
            await asyncio.gather(*readers, return_exceptions=True)
            self.healthy = False
            raise WorkerUnavailable(
                "Renderer exit or pipe cleanup not confirmed"
            ) from exc

    async def _run(self, output: Path, template: Path, data: Path, copies: int) -> None:
        output, template, data = output.resolve(), template.resolve(), data.resolve()
        if not template.is_file() or not data.is_file():
            raise FileNotFoundError("Template or CSV is missing")
        command = [
            self.glabels_bin,
            "-o",
            str(output),
            "-i",
            str(data),
            f"--copies={copies}",
            str(template),
        ]
        spawn = asyncio.create_task(
            asyncio.create_subprocess_exec(
                *command,
                cwd=template.parent,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                start_new_session=os.name == "posix",
            )
        )
        try:
            proc = await asyncio.shield(spawn)
        except asyncio.CancelledError:
            proc = await settle(spawn)
            await self._terminate_and_drain(proc)
            raise
        readers = [
            asyncio.create_task(self._read(proc.stdout)),
            asyncio.create_task(self._read(proc.stderr)),
        ]
        try:
            async with asyncio.timeout(self.default_timeout):
                await proc.wait()
                stdout, stderr = await asyncio.gather(*readers)
        except BaseException as exc:
            for reader in readers:
                reader.cancel()
            await asyncio.gather(*readers, return_exceptions=True)
            await self._terminate_and_drain(proc)
            if isinstance(exc, TimeoutError):
                raise GlabelsTimeoutError("Renderer deadline exceeded") from exc
            raise
        if proc.returncode != 0 or not output.is_file() or output.stat().st_size == 0:
            # Full details are bounded here; the public job error is sanitized.
            raise GlabelsRunError(
                f"Renderer failed (rc={proc.returncode}): {stderr or stdout}"
            )
