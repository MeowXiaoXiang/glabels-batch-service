#!/usr/bin/env python3
"""
Unit tests for API Endpoints
============================

Covers essential API functionality:
- POST /labels/print (job submission validation)
- GET /labels/templates (template listing)
- GET /labels/jobs/{job_id}/stream (SSE streaming)
- Basic error handling
"""

from contextlib import asynccontextmanager
from datetime import UTC, datetime
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.services.job_manager import JobManager


class FakeJobManager:
    def __init__(self):
        self.jobs = {}

    def start_workers(self):
        return None

    async def stop_workers(self):
        return None

    async def submit_job(self, req):
        job_id = "test-job-id"
        now = datetime.now(UTC)
        self.jobs[job_id] = {
            "status": "pending",
            "filename": "test.pdf",
            "template": req.template_name,
            "error": None,
            "created_at": now,
            "started_at": None,
            "finished_at": None,
            "request": req.model_dump(),
        }
        return job_id

    def get_job(self, job_id):
        return self.jobs.get(job_id)

    def list_jobs(self, limit=10):
        items = list(self.jobs.items())
        return [dict(job_id=jid, **data) for jid, data in items[:limit]]


class TestAPIEndpoints:
    @pytest.fixture
    def client(self):
        """Create test client for FastAPI app."""
        with TestClient(app) as client:
            yield client

    @pytest.fixture
    def client_with_fake_manager(self):
        original_lifespan = app.router.lifespan_context

        @asynccontextmanager
        async def fake_lifespan(_app):
            _app.state.job_manager = FakeJobManager()
            yield
            del _app.state.job_manager

        app.router.lifespan_context = fake_lifespan
        with TestClient(app) as client:
            try:
                yield client
            finally:
                app.router.lifespan_context = original_lifespan

    def test_submit_labels_invalid_template_name(self, client):
        """Should reject invalid template name."""
        request_data = {
            "template_name": "invalid.txt",  # Not .glabels
            "data": [{"ITEM": "A001"}],
            "copies": 1,
        }

        response = client.post("/labels/print", json=request_data)

        assert response.status_code == 422
        data = response.json()
        assert "template_name must have .glabels extension" in str(data)

    def test_health_check(self, client):
        """Health endpoint should return status ok."""
        response = client.get("/health")
        assert response.status_code == 200
        assert response.json()["status"] == "ok"

    def test_api_root(self, client):
        """API root should return metadata."""
        response = client.get("/")
        assert response.status_code == 200
        body = response.json()
        assert "service" in body
        assert "version" in body
        assert body["docs"] == "/docs"

    def test_submit_labels_success(self, client_with_fake_manager):
        """Should submit a job successfully."""
        request_data = {
            "template_name": "demo.glabels",
            "data": [{"ITEM": "A001", "CODE": "X123"}],
            "copies": 1,
        }
        response = client_with_fake_manager.post("/labels/print", json=request_data)
        assert response.status_code == 200
        data = response.json()
        assert data["job_id"] == "test-job-id"

    def test_submit_labels_empty_data(self, client_with_fake_manager):
        """Should reject empty data array."""
        request_data = {
            "template_name": "demo.glabels",
            "data": [],
            "copies": 1,
        }
        response = client_with_fake_manager.post("/labels/print", json=request_data)
        assert response.status_code == 422

    def test_submit_labels_exceeds_field_length(
        self, client_with_fake_manager, monkeypatch
    ):
        """Should reject fields exceeding MAX_FIELD_LENGTH."""
        monkeypatch.setattr("app.schema.settings.MAX_FIELD_LENGTH", 5)
        request_data = {
            "template_name": "demo.glabels",
            "data": [{"ITEM": "TOO-LONG", "CODE": "X123"}],
            "copies": 1,
        }
        response = client_with_fake_manager.post("/labels/print", json=request_data)
        assert response.status_code == 422

    def test_submit_labels_exceeds_request_bytes(
        self, client_with_fake_manager, monkeypatch
    ):
        """Should reject request body larger than MAX_REQUEST_BYTES."""
        monkeypatch.setattr("app.api.print_jobs.settings.MAX_REQUEST_BYTES", 10)
        request_data = {
            "template_name": "demo.glabels",
            "data": [{"ITEM": "A001", "CODE": "X123"}],
            "copies": 1,
        }
        response = client_with_fake_manager.post(
            "/labels/print",
            json=request_data,
            headers={"Content-Length": "100"},
        )
        assert response.status_code == 413

    def test_submit_labels_exceeds_max_labels(
        self, client_with_fake_manager, monkeypatch
    ):
        """Should reject when label count exceeds MAX_LABELS_PER_JOB."""
        monkeypatch.setattr("app.schema.settings.MAX_LABELS_PER_JOB", 2)
        request_data = {
            "template_name": "demo.glabels",
            "data": [
                {"ITEM": "A001", "CODE": "X123"},
                {"ITEM": "A002", "CODE": "X124"},
                {"ITEM": "A003", "CODE": "X125"},
            ],
            "copies": 1,
        }
        response = client_with_fake_manager.post("/labels/print", json=request_data)
        assert response.status_code == 422

    def test_submit_labels_exceeds_field_count(
        self, client_with_fake_manager, monkeypatch
    ):
        """Should reject when field count exceeds MAX_FIELDS_PER_LABEL."""
        monkeypatch.setattr("app.schema.settings.MAX_FIELDS_PER_LABEL", 1)
        request_data = {
            "template_name": "demo.glabels",
            "data": [{"ITEM": "A001", "CODE": "X123"}],
            "copies": 1,
        }
        response = client_with_fake_manager.post("/labels/print", json=request_data)
        assert response.status_code == 422

    def test_list_jobs_empty(self, client_with_fake_manager):
        """Should return an empty list when no jobs exist."""
        response = client_with_fake_manager.get("/labels/jobs")
        assert response.status_code == 200
        assert response.json() == []

    def test_list_jobs_with_limit(self, client_with_fake_manager):
        """Should respect limit when listing jobs."""
        jm = app.state.job_manager
        now = datetime.now(UTC)
        for i in range(3):
            jm.jobs[f"job-{i}"] = {
                "status": "done",
                "filename": f"file-{i}.pdf",
                "template": "demo.glabels",
                "error": None,
                "created_at": now,
                "started_at": now,
                "finished_at": now,
                "request": {"template_name": "demo.glabels", "data": [], "copies": 1},
            }

        response = client_with_fake_manager.get("/labels/jobs?limit=2")
        assert response.status_code == 200
        assert len(response.json()) == 2

    def test_download_job_not_done(self, client_with_fake_manager):
        """Should return 409 when job is not done."""
        jm = app.state.job_manager
        now = datetime.now(UTC)
        jm.jobs["pending-job"] = {
            "status": "pending",
            "filename": "pending.pdf",
            "template": "demo.glabels",
            "error": None,
            "created_at": now,
            "started_at": None,
            "finished_at": None,
            "request": {"template_name": "demo.glabels", "data": [], "copies": 1},
        }

        response = client_with_fake_manager.get("/labels/jobs/pending-job/download")
        assert response.status_code == 409

    def test_download_job_success(
        self, client_with_fake_manager, tmp_path, monkeypatch
    ):
        """Should download PDF when job is done and file exists."""
        monkeypatch.chdir(tmp_path)
        output_dir = Path("output")
        output_dir.mkdir()
        pdf_path = output_dir / "done.pdf"
        pdf_path.write_text("pdf")

        jm = app.state.job_manager
        now = datetime.now(UTC)
        jm.jobs["done-job"] = {
            "status": "done",
            "filename": "done.pdf",
            "template": "demo.glabels",
            "error": None,
            "created_at": now,
            "started_at": now,
            "finished_at": now,
            "request": {"template_name": "demo.glabels", "data": [], "copies": 1},
        }

        response = client_with_fake_manager.get("/labels/jobs/done-job/download")
        assert response.status_code == 200

    def test_download_job_preview_inline(
        self, client_with_fake_manager, tmp_path, monkeypatch
    ):
        """Should return inline Content-Disposition when preview=true."""
        monkeypatch.chdir(tmp_path)
        output_dir = Path("output")
        output_dir.mkdir()
        pdf_path = output_dir / "done.pdf"
        pdf_path.write_text("pdf")

        jm = app.state.job_manager
        now = datetime.now(UTC)
        jm.jobs["done-job"] = {
            "status": "done",
            "filename": "done.pdf",
            "template": "demo.glabels",
            "error": None,
            "created_at": now,
            "started_at": now,
            "finished_at": now,
            "request": {"template_name": "demo.glabels", "data": [], "copies": 1},
        }

        response = client_with_fake_manager.get(
            "/labels/jobs/done-job/download?preview=true"
        )
        assert response.status_code == 200
        assert response.headers.get("content-disposition", "").startswith("inline")


class TestSSEEndpoint:
    """Tests for Server-Sent Events streaming endpoint"""

    @pytest.fixture
    def client_with_state(self):
        """Create test client with job_manager initialized."""
        # Initialize job_manager in app state for testing
        app.state.job_manager = JobManager()
        client = TestClient(app)
        yield client
        # Cleanup
        del app.state.job_manager

    def test_stream_job_not_found(self, client_with_state):
        """SSE should return 404 for non-existent job"""
        response = client_with_state.get("/labels/jobs/nonexistent-job-id/stream")
        assert response.status_code == 404
        assert "Job not found" in response.json()["detail"]

    def test_stream_completed_job(self, client_with_state):
        """SSE should stream status and close for completed job"""

        # Add a completed job to job_manager
        jm = app.state.job_manager
        job_id = "test-completed-job"
        jm.jobs[job_id] = {
            "status": "done",
            "filename": "test.pdf",
            "template": "demo.glabels",
            "error": None,
            "created_at": datetime.now(UTC),
            "started_at": datetime.now(UTC),
            "finished_at": datetime.now(UTC),
            "request": {"template_name": "demo.glabels", "data": [], "copies": 1},
        }

        # Stream should return event-stream content type
        response = client_with_state.get(f"/labels/jobs/{job_id}/stream")

        # For completed jobs, SSE returns immediately with final status
        assert response.status_code == 200
        assert response.headers["content-type"].startswith("text/event-stream")

        # Check response contains status event
        content = response.text
        assert "event: status" in content
        assert '"status": "done"' in content or '"status":"done"' in content

    def test_stream_failed_job(self, client_with_state):
        """SSE should stream error status for failed job"""

        jm = app.state.job_manager
        job_id = "test-failed-job"
        jm.jobs[job_id] = {
            "status": "failed",
            "filename": "failed_job.pdf",  # filename is set even for failed jobs
            "template": "demo.glabels",
            "error": "Test error message",
            "created_at": datetime.now(UTC),
            "started_at": datetime.now(UTC),
            "finished_at": datetime.now(UTC),
            "request": {"template_name": "demo.glabels", "data": [], "copies": 1},
        }

        response = client_with_state.get(f"/labels/jobs/{job_id}/stream")

        assert response.status_code == 200
        content = response.text
        assert "event: status" in content
        assert '"status": "failed"' in content or '"status":"failed"' in content
