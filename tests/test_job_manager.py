import asyncio
from uuid import uuid4

import pikepdf
import pytest

from app.schema import LabelRequest
from app.services.job_manager import ArtifactError, CapacityError, JobManager
from app.services.job_store import now_ms


async def completed(manager, identifier):
    async with asyncio.timeout(20):
        while True:
            job = await manager.get_job(identifier)
            if job.status in ("done", "failed"):
                return job
            await asyncio.sleep(0.02)


@pytest.mark.asyncio
async def test_pipeline_order_single_final_restart_and_expiry(
    service_settings, fake_renderer
):
    cfg = service_settings
    manager = JobManager(cfg)
    await manager.start()
    request = LabelRequest(
        template_name="demo.glabels",
        data=[{"ITEM": str(i)} for i in range(5)],
        labels_per_page=1,
    )
    identifier = await manager.submit_job(request)
    job = await completed(manager, identifier)
    assert job.status == "done" and job.progress.rendered_batches == 3
    with pikepdf.open(cfg.OUTPUT_DIR / f"{identifier}.pdf") as pdf:
        assert [str(p.obj.ServiceItem) for p in pdf.pages] == ["0", "1", "2", "3", "4"]
    await manager.stop()
    assert list(cfg.TEMP_DIR.iterdir()) == []
    assert [p.name for p in cfg.OUTPUT_DIR.iterdir()] == [f"{identifier}.pdf"]
    restored = JobManager(cfg)
    await restored.start()
    try:
        after = await restored.get_job(identifier)
        assert (
            after.finished_at == job.finished_at and after.expires_at == job.expires_at
        )
        handle = await restored.open_download(identifier)
        await restored.store.execute(
            "UPDATE jobs SET expires_at=? WHERE job_id=?", (now_ms() - 1, identifier)
        )
        assert await restored.get_job(identifier) is None
        await restored.cleanup()
        assert (
            cfg.OUTPUT_DIR / f"{identifier}.pdf"
        ).exists()  # already-open download protected
        await restored.release_download(identifier, handle)
        await restored.cleanup()
        assert not (cfg.OUTPUT_DIR / f"{identifier}.pdf").exists()
        assert await restored.store.rows("SELECT * FROM jobs") == []
    finally:
        await restored.stop()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "order,expected", [("sets", "ABCDABCD"), ("per_record", "AABBCCDD")]
)
async def test_copy_policy_survives_batch_completion_order_and_restart(
    service_settings, fake_renderer, order, expected
):
    cfg = service_settings
    manager = JobManager(cfg)
    await manager.start()
    try:
        identifier = await manager.submit_job(
            LabelRequest(
                template_name="demo.glabels",
                data=[{"ITEM": x} for x in "ABCD"],
                copies=2,
                copy_order=order,
                labels_per_page=1,
            )
        )
        job = await completed(manager, identifier)
        assert job.status == "done"
        with pikepdf.open(cfg.OUTPUT_DIR / f"{identifier}.pdf") as pdf:
            assert "".join(str(p.obj.ServiceItem) for p in pdf.pages) == expected
        assert job.copy_order == order and job.labels_per_page == 1 and job.copies == 2
    finally:
        await manager.stop()
    restored = JobManager(cfg)
    await restored.start()
    try:
        job = await restored.get_job(identifier)
        assert job.copy_order == order and job.labels_per_page == 1
    finally:
        await restored.stop()


@pytest.mark.asyncio
async def test_page_declaration_mismatch_never_publishes_a_final(
    service_settings, fake_renderer
):
    manager = JobManager(service_settings)
    await manager.start()
    try:
        identifier = await manager.submit_job(
            LabelRequest(
                template_name="demo.glabels",
                data=[{"ITEM": x} for x in "ABC"],
                labels_per_page=2,
            )
        )
        assert (await completed(manager, identifier)).status == "failed"
        assert list(service_settings.OUTPUT_DIR.iterdir()) == []
        await manager._idle.wait()
        assert list(service_settings.TEMP_DIR.iterdir()) == []
    finally:
        await manager.stop()


@pytest.mark.asyncio
async def test_restart_reconciles_intent_but_does_not_resume_pending(service_settings):
    manager = JobManager(service_settings)
    await manager.start()
    pending, published = str(uuid4()), str(uuid4())
    for identifier in (pending, published):
        await manager.store.create(identifier, "demo.glabels", 1, 1, 1)
    await manager.store.stage(published, "rendering")
    await manager.store.intent(published)
    with pikepdf.Pdf.new() as pdf:
        pdf.add_blank_page()
        pdf.save(service_settings.OUTPUT_DIR / f"{published}.pdf")
    before = await manager.store.get(published)
    await manager.stop()
    restored = JobManager(service_settings)
    await restored.start()
    try:
        assert (await restored.get_job(pending)).error.code == "interrupted"
        done = await restored.store.get(published)
        assert done["status"] == "done" and done["expires_at"] == before["expires_at"]
    finally:
        await restored.stop()


@pytest.mark.asyncio
async def test_failed_template_and_missing_artifact(service_settings, fake_renderer):
    cfg = service_settings
    (cfg.TEMPLATES_DIR / "bad.glabels").write_bytes(b"bad")
    manager = JobManager(cfg)
    await manager.start()
    try:
        bad = await manager.submit_job(
            LabelRequest(template_name="bad.glabels", data=[{"ITEM": "A"}])
        )
        assert (await completed(manager, bad)).status == "failed"
        good = await manager.submit_job(
            LabelRequest(template_name="demo.glabels", data=[{"ITEM": "A"}])
        )
        assert (await completed(manager, good)).status == "done"
        (cfg.OUTPUT_DIR / f"{good}.pdf").unlink()
        with pytest.raises(ArtifactError) as error:
            await manager.open_download(good)
        assert error.value.status == 410
    finally:
        await manager.stop()


@pytest.mark.asyncio
async def test_bounded_admission_and_shutdown_marks_pending_failed(
    service_settings, monkeypatch
):
    service_settings.SHUTDOWN_TIMEOUT = 0.1
    service_settings.MAX_INFLIGHT_JOBS = 1
    manager = JobManager(service_settings)
    await manager.start()

    async def hang(*args):
        await asyncio.sleep(60)

    monkeypatch.setattr(manager.pipeline, "run", hang)
    request = LabelRequest(template_name="demo.glabels", data=[{"ITEM": "A"}])
    identifiers = [await manager.submit_job(request) for _ in range(3)]
    with pytest.raises(CapacityError):
        await manager.submit_job(request)
    await manager.stop()
    restored = JobManager(service_settings)
    await restored.start()
    try:
        for identifier in identifiers:
            assert (
                await restored.get_job(identifier)
            ).error.code == "shutdown_cancelled"
    finally:
        await restored.stop()


@pytest.mark.asyncio
async def test_cleanup_keeps_index_until_artifact_deletion_succeeds(
    service_settings, fake_renderer, monkeypatch
):
    from pathlib import Path

    manager = JobManager(service_settings)
    await manager.start()
    try:
        identifier = await manager.submit_job(
            LabelRequest(template_name="demo.glabels", data=[{"ITEM": "A"}])
        )
        assert (await completed(manager, identifier)).status == "done"
        await manager._idle.wait()
        await manager.store.execute(
            "UPDATE jobs SET expires_at=? WHERE job_id=?", (now_ms() - 1, identifier)
        )
        original = Path.unlink

        def deny(path, *args, **kwargs):
            if path.name == f"{identifier}.pdf":
                raise PermissionError("artifact busy")
            return original(path, *args, **kwargs)

        monkeypatch.setattr(Path, "unlink", deny)
        await manager.cleanup()
        assert len(await manager.store.rows("SELECT * FROM jobs")) == 1
        monkeypatch.setattr(Path, "unlink", original)
        await manager.cleanup()
        assert await manager.store.rows("SELECT * FROM jobs") == []
    finally:
        await manager.stop()
