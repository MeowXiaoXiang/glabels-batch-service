import asyncio
import sqlite3
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


@pytest.mark.asyncio
@pytest.mark.parametrize("persistent", [False, True])
async def test_sqlite_write_failure_settles_pending_or_leaves_restart_evidence(
    service_settings, monkeypatch, persistent
):
    service_settings.MAX_INFLIGHT_JOBS = 1
    service_settings.MAX_PENDING_JOBS = 3
    service_settings.SHUTDOWN_TIMEOUT = 0.05
    manager = JobManager(service_settings)
    entered, release = asyncio.Event(), asyncio.Event()

    async def active_job(identifier, request):
        await manager.store.stage(identifier, "rendering")
        entered.set()
        await release.wait()
        await manager.store.fail(identifier, "test_finished", "Test operation stopped")

    monkeypatch.setattr(manager.pipeline, "run", active_job)
    await manager.start()
    request = LabelRequest(template_name="demo.glabels", data=[{"ITEM": "A"}])

    def deny_write(action, table, *args):
        denied = action == sqlite3.SQLITE_INSERT or (
            persistent and action == sqlite3.SQLITE_UPDATE
        )
        return sqlite3.SQLITE_DENY if table == "jobs" and denied else sqlite3.SQLITE_OK

    try:
        active = await manager.submit_job(request)
        await asyncio.wait_for(entered.wait(), 5)
        queued = [await manager.submit_job(request) for _ in range(2)]
        await manager.store._io(lambda: manager.store.db.set_authorizer(deny_write))
        with pytest.raises(sqlite3.DatabaseError):
            await manager.submit_job(request)
        await asyncio.wait_for(manager.failure.wait(), 2)
        assert not manager.ready and not manager.accepting
        await asyncio.wait_for(asyncio.shield(manager._failure_cleanup), 5)
        assert not manager.pending and active in manager.active
        rows = [await manager.store.get(identifier) for identifier in queued]
        if persistent:
            assert all(
                row["status"] == "pending" and row["expires_at"] is None for row in rows
            )
        else:
            assert all(
                row["status"] == "failed"
                and row["error_code"] == "execution_unavailable"
                and row["expires_at"] is not None
                for row in rows
            )
        with pytest.raises(CapacityError):
            await manager.submit_job(request)
        if not persistent:
            release.set()
            await asyncio.wait_for(manager._idle.wait(), 5)
            assert not manager.active
    finally:
        # Keep the persistent fault in place through cancellation/recovery: a
        # failed metadata write must not bypass child/store ownership cleanup.
        if not persistent:
            release.set()
        await manager.stop()
    assert not manager.active
    assert manager.merger._pool is None
    restored = JobManager(service_settings)
    await restored.start()
    try:
        for identifier in queued:
            job = await restored.get_job(identifier)
            assert job.status == "failed"
            assert job.error.code == (
                "interrupted" if persistent else "execution_unavailable"
            )
        assert (await restored.store.rows("PRAGMA integrity_check"))[0][
            "integrity_check"
        ] == "ok"
    finally:
        await restored.stop()


@pytest.mark.asyncio
async def test_shutdown_write_failure_still_cancels_active_work(
    service_settings, monkeypatch
):
    service_settings.MAX_INFLIGHT_JOBS = 1
    service_settings.SHUTDOWN_TIMEOUT = 0.01
    manager = JobManager(service_settings)
    cancelled = asyncio.Event()

    async def hang(*args):
        try:
            await asyncio.sleep(60)
        finally:
            cancelled.set()

    monkeypatch.setattr(manager.pipeline, "run", hang)
    await manager.start()
    request = LabelRequest(template_name="demo.glabels", data=[{"ITEM": "A"}])
    identifiers = [await manager.submit_job(request) for _ in range(2)]
    await manager.store._io(
        lambda: manager.store.db.set_authorizer(
            lambda action, *args: (
                sqlite3.SQLITE_DENY
                if action == sqlite3.SQLITE_UPDATE
                else sqlite3.SQLITE_OK
            )
        )
    )
    await asyncio.wait_for(manager.stop(), 10)
    assert cancelled.is_set() and not manager.active
    restored = JobManager(service_settings)
    await restored.start()
    try:
        assert all(
            [
                (await restored.get_job(identifier)).error.code == "interrupted"
                for identifier in identifiers
            ]
        )
    finally:
        await restored.stop()
