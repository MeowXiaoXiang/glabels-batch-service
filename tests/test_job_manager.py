#!/usr/bin/env python3
"""
Unit tests for JobManager
=========================

Covers:
- Submit job increments jobs_total and creates record
- Worker processes job and updates status to done
- Worker failure updates status to failed with error
- Cleanup removes expired jobs
- list_jobs returns most recent jobs, sorted by created_at
- get_job returns correct job or None
- jobs_total counter increases across multiple submissions
- cleanup removes old PDFs from output directory
- start/stop workers manage worker tasks
"""

import asyncio
from datetime import datetime, timedelta, timezone

import pytest

from app.schema import LabelRequest
from app.services.job_manager import JobManager


@pytest.mark.asyncio
async def test_submit_and_complete_job(monkeypatch):
    """Submitting a job should increment counter and complete with 'done' status"""

    jm = JobManager()

    # Mock generate_pdf to simulate success
    async def fake_generate_pdf(*a, **k):
        return "dummy.pdf"

    monkeypatch.setattr(jm.service, "generate_pdf", fake_generate_pdf)

    jm.start_workers()

    req = LabelRequest(template_name="demo.glabels", data=[{"A": 1}], copies=1)
    job_id = await jm.submit_job(req)

    # Wait for queue to drain
    await asyncio.wait_for(jm.queue.join(), timeout=1)

    job = jm.get_job(job_id)
    assert job["status"] == "done"
    assert jm.jobs_total == 1
    assert "filename" in job
    assert job["template"] == "demo.glabels"

    await jm.stop_workers()


@pytest.mark.asyncio
async def test_submit_and_fail_job(monkeypatch):
    """If generate_pdf raises, job should be marked failed with error"""

    jm = JobManager()

    async def fake_generate_pdf(*a, **k):
        raise RuntimeError("boom")

    monkeypatch.setattr(jm.service, "generate_pdf", fake_generate_pdf)

    jm.start_workers()

    req = LabelRequest(template_name="demo.glabels", data=[{"A": 1}], copies=1)
    job_id = await jm.submit_job(req)

    await asyncio.wait_for(jm.queue.join(), timeout=1)

    job = jm.get_job(job_id)
    assert job["status"] == "failed"
    assert "boom" in job["error"]

    await jm.stop_workers()


@pytest.mark.asyncio
async def test_jobs_total_multiple(monkeypatch):
    """jobs_total should increase as multiple jobs are submitted"""

    jm = JobManager()

    # Always succeed
    async def fake_generate_pdf(*a, **k):
        return "dummy.pdf"

    monkeypatch.setattr(jm.service, "generate_pdf", fake_generate_pdf)

    jm.start_workers()

    req = LabelRequest(template_name="demo.glabels", data=[{"x": 1}], copies=1)
    ids = [await jm.submit_job(req) for _ in range(3)]

    await asyncio.wait_for(jm.queue.join(), timeout=1)

    # Ensure all jobs done
    for jid in ids:
        assert jm.get_job(jid)["status"] == "done"

    assert jm.jobs_total == 3

    await jm.stop_workers()


def test_cleanup_jobs():
    """Expired jobs should be removed from JobManager"""

    jm = JobManager()
    jm.retention = timedelta(seconds=0)  # expire immediately

    req = LabelRequest(template_name="demo.glabels", data=[{"A": 1}], copies=1)
    job_id = "jid"
    jm.jobs[job_id] = {
        "status": "done",
        "filename": "out.pdf",
        "template": "demo.glabels",
        "error": None,
        "created_at": datetime.now(timezone.utc) - timedelta(hours=1),
        "started_at": datetime.now(timezone.utc) - timedelta(hours=1),
        "finished_at": datetime.now(timezone.utc) - timedelta(hours=1),
        "request": req.model_dump(),
    }

    jm._cleanup_jobs()
    assert job_id not in jm.jobs


def test_cleanup_jobs_skips_unfinished():
    """Unfinished jobs should not be removed by cleanup."""
    jm = JobManager()
    jm.retention = timedelta(seconds=0)

    req = LabelRequest(template_name="demo.glabels", data=[{"A": 1}], copies=1)
    job_id = "running"
    jm.jobs[job_id] = {
        "status": "running",
        "filename": "out.pdf",
        "template": "demo.glabels",
        "error": None,
        "created_at": datetime.now(timezone.utc) - timedelta(hours=1),
        "started_at": datetime.now(timezone.utc) - timedelta(hours=1),
        "finished_at": None,
        "request": req.model_dump(),
    }

    jm._cleanup_jobs()
    assert job_id in jm.jobs


def test_get_job_and_list_jobs():
    """list_jobs should return jobs sorted by created_at, get_job returns correct job"""

    jm = JobManager()

    now = datetime.now(timezone.utc)
    req = LabelRequest(template_name="demo.glabels", data=[{"A": 1}], copies=1)

    # Insert 3 jobs with different timestamps
    jm.jobs["jid1"] = {
        "status": "done",
        "filename": "a.pdf",
        "template": "demo",
        "error": None,
        "created_at": now - timedelta(seconds=5),
        "started_at": now - timedelta(seconds=4),
        "finished_at": now,
        "request": req.model_dump(),
    }
    jm.jobs["jid2"] = {
        "status": "pending",
        "filename": None,
        "template": "demo",
        "error": None,
        "created_at": now - timedelta(seconds=1),
        "started_at": None,
        "finished_at": None,
        "request": req.model_dump(),
    }
    jm.jobs["jid3"] = {
        "status": "running",
        "filename": None,
        "template": "demo",
        "error": None,
        "created_at": now - timedelta(seconds=3),
        "started_at": now - timedelta(seconds=2),
        "finished_at": None,
        "request": req.model_dump(),
    }

    # list_jobs should be sorted (latest first)
    jobs = jm.list_jobs(limit=2)
    assert len(jobs) == 2
    assert jobs[0]["job_id"] == "jid2"
    assert jobs[1]["job_id"] == "jid3"

    # get_job should return correct record
    job = jm.get_job("jid1")
    assert job is not None
    assert job["filename"] == "a.pdf"

    # get_job for missing id returns None
    assert jm.get_job("missing") is None


def test_cleanup_old_pdfs(monkeypatch, tmp_path):
    """Expired PDFs in output/ should be deleted"""
    jm = JobManager()

    monkeypatch.chdir(tmp_path)
    output_dir = tmp_path / "output"
    output_dir.mkdir()

    old_pdf = output_dir / "old.pdf"
    old_pdf.write_text("old")
    old_time = (datetime.now() - timedelta(hours=25)).timestamp()
    import os

    os.utime(old_pdf, (old_time, old_time))

    new_pdf = output_dir / "new.pdf"
    new_pdf.write_text("new")

    jm._cleanup_jobs()

    assert not old_pdf.exists()
    assert new_pdf.exists()


@pytest.mark.asyncio
async def test_start_stop_workers():
    """Workers should start and stop cleanly"""
    jm = JobManager()
    jm.start_workers()
    assert len(jm.workers) == jm.max_parallel
    for worker in jm.workers:
        assert not worker.done()

    await jm.stop_workers()
    assert len(jm.workers) == 0
