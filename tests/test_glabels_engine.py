#!/usr/bin/env python3
"""
Unit tests for GlabelsEngine
============================

Covers:
- Successful execution (mock subprocess)
- Failure with non-zero return code
- Missing input files
- Timeout handling
- rc=0 but no PDF generated
- Long stderr output (logging truncation vs full return)
"""

import asyncio
from pathlib import Path

import pytest

from app.utils.glabels_engine import (
    GlabelsEngine,
    GlabelsExecutionError,
    GlabelsTimeoutError,
)


class TestGlabelsEngine:
    @pytest.mark.asyncio
    async def test_run_batch_success(self, monkeypatch, tmp_path):
        """Should succeed and produce PDF"""
        tpl = tmp_path / "demo.glabels"
        csv = tmp_path / "demo.csv"
        out = tmp_path / "out.pdf"
        tpl.write_text("dummy template")
        csv.write_text("MODEL,SN\nT01,SN001")

        class DummyProc:
            returncode = 0

            async def communicate(self):
                out.write_text("fake pdf content")
                return b"stdout ok", b""

        async def fake_exec(*a, **k):
            return DummyProc()

        monkeypatch.setattr(asyncio, "create_subprocess_exec", fake_exec)

        engine = GlabelsEngine()
        rc, stdout, stderr = await engine.run_batch(
            output_pdf=out, template_path=tpl, csv_path=csv
        )
        assert rc == 0
        assert "stdout ok" in stdout
        assert stderr == ""
        assert out.exists()

    @pytest.mark.asyncio
    async def test_run_batch_failure(self, monkeypatch, tmp_path):
        """Should raise GlabelsExecutionError on non-zero rc"""
        tpl = tmp_path / "demo.glabels"
        csv = tmp_path / "demo.csv"
        out = tmp_path / "out.pdf"
        tpl.write_text("dummy")
        csv.write_text("x")

        class DummyProc:
            returncode = 1

            async def communicate(self):
                return b"", b"error: bad template"

        async def fake_exec(*a, **k):
            return DummyProc()

        monkeypatch.setattr(asyncio, "create_subprocess_exec", fake_exec)

        engine = GlabelsEngine()
        with pytest.raises(GlabelsExecutionError) as e:
            await engine.run_batch(output_pdf=out, template_path=tpl, csv_path=csv)
        assert "bad template" in e.value.stderr
        assert e.value.stdout == ""

    @pytest.mark.asyncio
    async def test_run_batch_failure_keeps_stdout(self, monkeypatch, tmp_path):
        """Should preserve stdout on failure for easier diagnosis."""
        tpl = tmp_path / "demo.glabels"
        csv = tmp_path / "demo.csv"
        out = tmp_path / "out.pdf"
        tpl.write_text("dummy")
        csv.write_text("x")

        class DummyProc:
            returncode = 2

            async def communicate(self):
                return b"warning from glabels", b"error: bad template"

        async def fake_exec(*a, **k):
            return DummyProc()

        monkeypatch.setattr(asyncio, "create_subprocess_exec", fake_exec)

        engine = GlabelsEngine()
        with pytest.raises(GlabelsExecutionError) as e:
            await engine.run_batch(output_pdf=out, template_path=tpl, csv_path=csv)
        assert "warning from glabels" in e.value.stdout
        assert "bad template" in e.value.stderr

    @pytest.mark.asyncio
    async def test_file_not_found(self, tmp_path):
        """Missing template or CSV should raise FileNotFoundError"""
        tpl = tmp_path / "missing.glabels"
        csv = tmp_path / "missing.csv"
        out = tmp_path / "out.pdf"
        engine = GlabelsEngine()
        with pytest.raises(FileNotFoundError):
            await engine.run_batch(output_pdf=out, template_path=tpl, csv_path=csv)

    @pytest.mark.asyncio
    async def test_binary_not_found_message(self, monkeypatch, tmp_path):
        """Missing glabels binary should raise a clear FileNotFoundError message."""
        tpl = tmp_path / "demo.glabels"
        csv = tmp_path / "demo.csv"
        out = tmp_path / "out.pdf"
        tpl.write_text("dummy")
        csv.write_text("x")

        async def fake_exec(*a, **k):
            raise FileNotFoundError("no such file")

        monkeypatch.setattr(asyncio, "create_subprocess_exec", fake_exec)

        engine = GlabelsEngine(glabels_bin=Path("/missing/glabels-3-batch"))
        with pytest.raises(FileNotFoundError, match="glabels binary not found"):
            await engine.run_batch(output_pdf=out, template_path=tpl, csv_path=csv)

    @pytest.mark.asyncio
    async def test_timeout(self, monkeypatch, tmp_path):
        """Should raise GlabelsTimeoutError when process hangs"""
        tpl = tmp_path / "demo.glabels"
        csv = tmp_path / "demo.csv"
        out = tmp_path / "out.pdf"
        tpl.write_text("dummy")
        csv.write_text("x")

        class DummyProc:
            returncode = None

            async def communicate(self):
                await asyncio.sleep(10)
                return b"", b""

            def kill(self):
                pass

            async def wait(self):
                return

        async def fake_exec(*a, **k):
            return DummyProc()

        monkeypatch.setattr(asyncio, "create_subprocess_exec", fake_exec)

        engine = GlabelsEngine()
        with pytest.raises(GlabelsTimeoutError):
            await engine.run_batch(
                output_pdf=out, template_path=tpl, csv_path=csv, timeout=0.01
            )

    @pytest.mark.asyncio
    async def test_rc0_but_no_pdf(self, monkeypatch, tmp_path):
        """rc=0 but no PDF should still raise GlabelsExecutionError"""
        tpl = tmp_path / "demo.glabels"
        csv = tmp_path / "demo.csv"
        out = tmp_path / "out.pdf"
        tpl.write_text("dummy")
        csv.write_text("x")

        class DummyProc:
            returncode = 0

            async def communicate(self):
                return b"stdout ok", b""

        async def fake_exec(*a, **k):
            return DummyProc()

        monkeypatch.setattr(asyncio, "create_subprocess_exec", fake_exec)

        engine = GlabelsEngine()
        with pytest.raises(GlabelsExecutionError) as e:
            await engine.run_batch(output_pdf=out, template_path=tpl, csv_path=csv)
        assert "rc=0" in str(e.value)

    @pytest.mark.asyncio
    async def test_stderr_truncation(self, monkeypatch, tmp_path):
        """stderr should be truncated in logs but full in return"""
        tpl = tmp_path / "demo.glabels"
        csv = tmp_path / "demo.csv"
        out = tmp_path / "out.pdf"
        tpl.write_text("dummy")
        csv.write_text("x")

        long_err = ("E" * 6000).encode()

        class DummyProc:
            returncode = 0

            async def communicate(self):
                out.write_text("fake pdf content")
                return b"stdout ok", long_err

        async def fake_exec(*a, **k):
            return DummyProc()

        monkeypatch.setattr(asyncio, "create_subprocess_exec", fake_exec)

        engine = GlabelsEngine()
        rc, stdout, stderr = await engine.run_batch(
            output_pdf=out, template_path=tpl, csv_path=csv
        )
        assert rc == 0
        assert out.exists()
        assert len(stderr) == 6000

    @pytest.mark.asyncio
    async def test_stderr_truncation_logging(self, monkeypatch, tmp_path):
        """stderr log should be truncated while return stays full"""
        tpl = tmp_path / "demo.glabels"
        csv = tmp_path / "demo.csv"
        out = tmp_path / "out.pdf"
        tpl.write_text("dummy")
        csv.write_text("x")

        long_err = ("E" * 6000).encode()

        class DummyProc:
            returncode = 0

            async def communicate(self):
                out.write_text("fake pdf content")
                return b"stdout ok", long_err

        async def fake_exec(*a, **k):
            return DummyProc()

        from app.utils import glabels_engine as ge

        captured = {"stderr_chunk": None}

        def intercept_debug(message, *args, **kwargs):
            if isinstance(message, str) and message.startswith("glabels stderr"):
                if args and isinstance(args[0], str):
                    captured["stderr_chunk"] = args[0]
                else:
                    prefix = "glabels stderr (truncated):\n"
                    if message.startswith(prefix):
                        captured["stderr_chunk"] = message[len(prefix) :]
                    else:
                        captured["stderr_chunk"] = message

        monkeypatch.setattr(asyncio, "create_subprocess_exec", fake_exec)
        monkeypatch.setattr(ge.logger, "debug", intercept_debug)

        engine = GlabelsEngine()
        rc, stdout, stderr = await engine.run_batch(
            output_pdf=out, template_path=tpl, csv_path=csv, log_truncate=4096
        )

        assert rc == 0
        assert out.exists()
        assert len(stderr) == 6000
        assert captured["stderr_chunk"] is not None
        assert len(captured["stderr_chunk"]) == 4096
