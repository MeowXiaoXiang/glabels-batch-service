import time

from fastapi.testclient import TestClient

from app.main import create_app


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
