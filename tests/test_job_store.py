import sqlite3
from contextlib import closing
from uuid import uuid4

import pytest

from app.services.job_store import JobStore, now_ms


@pytest.mark.asyncio
async def test_persistence_and_expiry_do_not_extend_on_restart(tmp_path):
    identifier = str(uuid4())
    path = tmp_path / "state" / "jobs.sqlite3"
    store = JobStore(path)
    await store.open()
    assert (await store.rows("PRAGMA user_version"))[0]["user_version"] == 1
    await store.create(
        identifier,
        "opaque.glabels",
        100,
        2,
        3,
        copy_order="per_record",
        labels_per_page=10,
    )
    await store.stage(identifier, "rendering")
    await store.started(identifier)
    await store.stage(identifier, "merging")
    await store.intent(identifier)
    await store.done(identifier)
    first = await store.get(identifier)
    await store.close()
    second = JobStore(path, retention_hours=48)
    await second.open()
    try:
        assert await second.get(identifier) == first
        assert first["status"] == "done"
        assert first["copy_order"] == "per_record" and first["labels_per_page"] == 10
        assert first["finished_at"] == first["publication_intent_at"]
        await second.execute(
            "UPDATE jobs SET expires_at=? WHERE job_id=?", (now_ms() - 1, identifier)
        )
        assert await second.get(identifier) is None
        assert await second.recent(10) == []
    finally:
        await second.close()


@pytest.mark.asyncio
async def test_exclusive_owner_and_schema_version(tmp_path):
    path = tmp_path / "jobs.sqlite3"
    first, second = JobStore(path), JobStore(path)
    await first.open()
    try:
        with pytest.raises(OSError):
            await second.open()
    finally:
        await second.close()
        await first.close()
    with closing(sqlite3.connect(path)) as db:
        db.execute("PRAGMA user_version=2")
        db.commit()
    unknown = JobStore(path)
    try:
        with pytest.raises(RuntimeError, match="Unsupported"):
            await unknown.open()
    finally:
        await unknown.close()


@pytest.mark.asyncio
async def test_terminal_constraints_and_failed_record_retention(tmp_path):
    store = JobStore(tmp_path / "jobs.sqlite3")
    await store.open()
    identifier = str(uuid4())
    try:
        await store.create(identifier, "opaque.glabels", 1, 1, 1)
        with pytest.raises(sqlite3.IntegrityError):
            await store.execute(
                "UPDATE jobs SET status='done' WHERE job_id=?", (identifier,)
            )
        await store.fail(identifier, "interrupted", "Service restarted")
        row = await store.get(identifier)
        assert row["finished_at"] is not None and row["expires_at"] > row["finished_at"]
        await store.stage(identifier, "rendering")
        assert (await store.get(identifier))["status"] == "failed"
    finally:
        await store.close()


@pytest.mark.asyncio
async def test_expired_publication_intent_is_not_renewed_by_recovery_failure(tmp_path):
    store = JobStore(tmp_path / "jobs.sqlite3")
    await store.open()
    identifier = str(uuid4())
    try:
        await store.create(identifier, "demo.glabels", 1, 1, 1)
        await store.stage(identifier, "rendering")
        await store.intent(identifier)
        expiry = now_ms() - 1
        await store.execute(
            "UPDATE jobs SET expires_at=? WHERE job_id=?", (expiry, identifier)
        )
        await store.fail(identifier, "interrupted", "Restart")
        assert await store.get(identifier) is None
        assert (
            await store.rows(
                "SELECT expires_at FROM jobs WHERE job_id=?", (identifier,)
            )
        )[0]["expires_at"] == expiry
    finally:
        await store.close()
