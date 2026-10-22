import sqlite3
import time
from contextlib import closing
from uuid import uuid4

import pikepdf
from fastapi.testclient import TestClient

from app.main import create_app
from app.services.job_store import SCHEMA, now_ms


def test_full_public_contract_and_download(service_settings, fake_renderer):
    with TestClient(create_app(service_settings)) as client:
        assert client.get("/health").status_code == 200
        assert client.get("/ready").json() == {"ready": True}
        assert client.get("/labels/templates").json() == [{"name": "demo.glabels"}]
        response = client.post(
            "/labels/print",
            json={"template_name": "demo.glabels", "data": [{"ITEM": "A"}]},
        )
        assert response.status_code == 202
        identifier = response.json()["job_id"]
        deadline = time.monotonic() + 15
        while time.monotonic() < deadline:
            job = client.get(f"/labels/jobs/{identifier}").json()
            if job["status"] in ("done", "failed"):
                break
            time.sleep(0.02)
        assert job["status"] == "done"
        assert job["copy_order"] == "sets" and job["labels_per_page"] is None
        assert "filename" not in job and "parent_id" not in job
        assert job["download_url"] == f"/labels/jobs/{identifier}/download"
        pdf = client.get(job["download_url"])
        assert pdf.status_code == 200 and pdf.content.startswith(b"%PDF-")
        assert "data: " in client.get(f"/labels/jobs/{identifier}/stream").text
        metrics = client.get("/metrics").text
        assert "jobs_submitted_total 1.0" in metrics
        assert identifier not in metrics
        assert client.get("/labels/jobs?limit=-1").status_code == 422


def test_body_limit_before_json_and_missing_template(service_settings, fake_renderer):
    service_settings.MAX_REQUEST_BYTES = 128
    with TestClient(create_app(service_settings)) as client:
        # A chunked request has no Content-Length: actual bytes must be counted.
        response = client.post(
            "/labels/print",
            content=iter([b"x" * 80, b"x" * 80]),
            headers={"Content-Type": "application/json"},
        )
        assert response.status_code == 413
        response = client.post(
            "/labels/print",
            json={"template_name": "missing.glabels", "data": [{"ITEM": "A"}]},
        )
        assert response.status_code == 404


def test_batching_requires_valid_page_declaration_before_creating_job(
    service_settings, fake_renderer
):
    with TestClient(create_app(service_settings)) as client:
        payload = {
            "template_name": "demo.glabels",
            "data": [{"ITEM": x} for x in "ABC"],
        }
        for declaration, message in [
            ({}, "labels_per_page is required"),
            ({"labels_per_page": 3}, "One declared page"),
        ]:
            response = client.post("/labels/print", json=payload | declaration)
            assert response.status_code == 422
            assert message in response.json()["detail"]
        assert client.get("/labels/jobs").json() == []


def test_completed_job_still_downloads_after_restart(service_settings):
    cfg = service_settings
    identifier, timestamp = str(uuid4()), now_ms()
    cfg.STATE_DIR.mkdir()
    cfg.OUTPUT_DIR.mkdir()
    artifact = cfg.OUTPUT_DIR / f"{identifier}.pdf"
    with pikepdf.Pdf.new() as pdf:
        pdf.add_blank_page()
        pdf.save(artifact)
    original = artifact.read_bytes()
    with closing(sqlite3.connect(cfg.STATE_DIR / "jobs.sqlite3")) as db:
        db.executescript(SCHEMA)
        db.execute(
            "INSERT INTO jobs(job_id,status,template_name,record_count,copies,copy_order,labels_per_page,batch_count,created_at,finished_at,expires_at,final_name,publication_intent_at) VALUES (?,'done','demo.glabels',1,1,'per_record',3,1,?,?,?,?,?)",
            (
                identifier,
                timestamp,
                timestamp,
                timestamp + 60000,
                identifier + ".pdf",
                timestamp,
            ),
        )
        db.commit()
    with TestClient(create_app(cfg)) as client:
        response = client.get(f"/labels/jobs/{identifier}")
        assert response.status_code == 200
        job = response.json()
        assert job["status"] == "done" and job["copy_order"] == "per_record"
        assert job["labels_per_page"] == 3
        assert job["expires_at"] is not None
        assert client.get(job["download_url"]).content == original
