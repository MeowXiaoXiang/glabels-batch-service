import asyncio
import os
import time
from concurrent.futures.process import BrokenProcessPool
from pathlib import Path

import pikepdf
import pytest

import app.services.pdf_merger as merger_module
from app.services.pdf_merger import PdfMerger
from app.utils.pdf_worker import PdfOperationError, assemble_pdf


def hang_pdf(*args):
    time.sleep(60)


def crash_pdf(*args):
    os._exit(17)


def create_pdf(path: Path, sequence: int) -> Path:
    with pikepdf.Pdf.new() as pdf:
        page = pdf.add_blank_page(page_size=(200, 100))
        page.obj.ServiceSequence = sequence
        pdf.save(path)
    return path


@pytest.mark.asyncio
async def test_order_validation_and_single_input_copy(tmp_path):
    paths = [create_pdf(tmp_path / f"{i}.pdf", i) for i in (3, 1, 2)]
    merger = PdfMerger()
    await merger.start()
    try:
        assert await merger.merge(paths, tmp_path / "final.pdf") == 3
        with pikepdf.open(tmp_path / "final.pdf") as pdf:
            assert [p.obj.ServiceSequence for p in pdf.pages] == [3, 1, 2]
        await merger.merge(paths[:1], tmp_path / "single.pdf")
        assert (tmp_path / "single.pdf").read_bytes() == paths[0].read_bytes()
        bad = tmp_path / "bad.pdf"
        bad.write_bytes(b"invalid")
        with pytest.raises(PdfOperationError):
            await merger.merge([bad], None)
        assert await merger.merge(paths[:1], None) == 1
        assert merger.restarts == 0
        with pytest.raises(PdfOperationError, match="labels_per_page declaration"):
            await merger.merge(
                paths[:1], tmp_path / "wrong-pages.pdf", expected_pages=[2]
            )
        assert not (tmp_path / "wrong-pages.pdf").exists()
        assert await merger.merge(paths[:1], None, expected_pages=[1]) == 1
    finally:
        await merger.close()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "operation,exception", [(hang_pdf, TimeoutError), (crash_pdf, BrokenProcessPool)]
)
async def test_hard_failure_reaped_then_next_job_recovers(
    tmp_path, monkeypatch, operation, exception
):
    source = create_pdf(tmp_path / "source.pdf", 1)
    merger = PdfMerger(timeout=0.2 if operation is hang_pdf else 10)
    await merger.start()
    child = merger._child
    monkeypatch.setattr(merger_module, "assemble_pdf", operation)
    try:
        with pytest.raises(exception):
            await merger.merge([source], None)
        assert child.exitcode is not None and not child.is_alive()
        assert merger.healthy and merger.restarts == 1
        monkeypatch.setattr(merger_module, "assemble_pdf", assemble_pdf)
        merger.timeout = 10
        assert await merger.merge([source], None) == 1
    finally:
        await merger.close()


@pytest.mark.asyncio
async def test_cancellation_waits_for_real_process_exit(tmp_path, monkeypatch):
    source = create_pdf(tmp_path / "source.pdf", 1)
    merger = PdfMerger()
    await merger.start()
    child = merger._child
    monkeypatch.setattr(merger_module, "assemble_pdf", hang_pdf)
    task = asyncio.create_task(merger.merge([source], None))
    await asyncio.sleep(0.1)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert child.exitcode is not None and not child.is_alive()
    await merger.close()


@pytest.mark.asyncio
async def test_worker_limits_reject_before_publication_and_remain_usable(tmp_path):
    paths = [create_pdf(tmp_path / f"{i}.pdf", i) for i in range(2)]
    merger = PdfMerger(max_pages=1)
    await merger.start()
    try:
        with pytest.raises(PdfOperationError, match="page limit"):
            await merger.merge(paths, tmp_path / "final.pdf")
        assert not (tmp_path / "final.pdf").exists()
        merger.max_pages = 10
        merger.max_bytes = 1
        with pytest.raises(PdfOperationError, match="size limit"):
            await merger.merge(paths, None)
        merger.max_bytes = 1_000_000
        assert await merger.merge(paths, tmp_path / "final.pdf") == 2
        assert merger.restarts == 0
    finally:
        await merger.close()


@pytest.mark.asyncio
async def test_repeated_cold_start_and_external_kill_rebuild(tmp_path):
    source = create_pdf(tmp_path / "source.pdf", 1)

    async def cold_start():
        merger = PdfMerger()
        try:
            await merger.start()
            child = merger._child
            assert child is not None and child.is_alive()
            assert await merger.merge([source], None) == 1
        finally:
            await merger.close()
        assert child.exitcode == 0 and not child.is_alive()

    for _ in range(3):
        await asyncio.gather(*(cold_start() for _ in range(3)))
    merger = PdfMerger()
    try:
        await merger.start()
        for expected_restarts in range(1, 6):
            child = merger._child
            child.kill()
            with pytest.raises(BrokenProcessPool):
                await merger.merge([source], None)
            assert child.exitcode is not None and not child.is_alive()
            assert merger.healthy and merger.restarts == expected_restarts
            assert await merger.merge([source], None) == 1
    finally:
        await merger.close()
