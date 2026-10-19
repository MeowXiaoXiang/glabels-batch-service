import json
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from loguru import logger

from app.core.errors import ExecutionUnavailable
from app.core.logger import setup_logger
from app.main import create_app
from app.schema import LabelRequest
from app.services.job_manager import JobManager
from app.services.resource_scheduler import ResourceScheduler


@pytest.mark.parametrize(
    "setting,strict,relaxed,data,copies",
    [
        ("MAX_LABELS_PER_JOB", 1, 2, [{"ITEM": "A"}, {"ITEM": "B"}], 1),
        ("MAX_COPIES", 1, 2, [{"ITEM": "A"}], 2),
        ("MAX_EFFECTIVE_LABELS", 1, 2, [{"ITEM": "A"}], 2),
        ("MAX_FIELDS_PER_LABEL", 1, 2, [{"ITEM": "A", "CODE": "B"}], 1),
        ("MAX_FIELD_LENGTH", 1, 2, [{"ITEM": "AB"}], 1),
    ],
)
def test_app_limits_are_applied_before_persistence(
    service_settings, monkeypatch, setting, strict, relaxed, data, copies
):
    monkeypatch.setattr(JobManager, "_pump", lambda self: None)
    service_settings.MAX_LABELS_PER_BATCH = 0
    service_settings.SHUTDOWN_TIMEOUT = 0.01
    payload = {"template_name": "demo.glabels", "data": data, "copies": copies}
    strict_cfg = service_settings.model_copy(update={setting: strict})
    relaxed_cfg = service_settings.model_copy(update={setting: relaxed})
    for cfg, expected in [(strict_cfg, 422), (relaxed_cfg, 202)]:
        with TestClient(create_app(cfg)) as client:
            result = client.post("/labels/print", json=payload)
            assert result.status_code == expected
            jobs = client.get("/labels/jobs").json()
            assert len(jobs) == (1 if expected == 202 else 0)
            assert not client.app.state.job_manager.active


def test_app_can_allow_values_above_global_defaults(service_settings, monkeypatch):
    monkeypatch.setattr(JobManager, "_pump", lambda self: None)
    service_settings.MAX_FIELD_LENGTH = 3000
    service_settings.MAX_COPIES = 200
    service_settings.MAX_LABELS_PER_BATCH = 0
    service_settings.SHUTDOWN_TIMEOUT = 0.01
    with TestClient(create_app(service_settings)) as client:
        response = client.post(
            "/labels/print",
            json={
                "template_name": "demo.glabels",
                "data": [{"ITEM": "x" * 2049}],
                "copies": 101,
            },
        )
        assert response.status_code == 202


def test_rate_limits_and_counters_belong_to_each_app(service_settings, monkeypatch):
    monkeypatch.setattr(JobManager, "_pump", lambda self: None)
    service_settings.SHUTDOWN_TIMEOUT = 0.01
    payload = {"template_name": "demo.glabels", "data": [{"ITEM": "A"}]}
    apps = [
        create_app(
            service_settings.model_copy(
                update={
                    "RATE_LIMIT": value,
                    "STATE_DIR": service_settings.STATE_DIR.with_name(f"state-{index}"),
                }
            )
        )
        for index, value in enumerate(["1/minute", "2/minute"])
    ]
    assert apps[0].state.limiter is not apps[1].state.limiter
    for app, allowance in zip(apps, [1, 2], strict=True):
        with TestClient(app) as client:
            for _ in range(allowance):
                assert client.post("/labels/print", json=payload).status_code == 202
            assert client.post("/labels/print", json=payload).status_code == 429
            assert len(client.get("/labels/jobs").json()) == allowance


@pytest.mark.parametrize("log_format", ["text", "json"])
@pytest.mark.parametrize(
    "level,threshold", [("DEBUG", 10), ("INFO", 20), ("WARNING", 30), ("ERROR", 40)]
)
def test_log_level_is_a_floor_for_all_sinks(
    tmp_path, capsys, log_format, level, threshold
):
    try:
        setup_logger(level, log_format, str(tmp_path))
        for name in ["DEBUG", "INFO", "WARNING", "ERROR"]:
            logger.log(name, "quality-token-" + name)
    finally:
        logger.remove()
    outputs = [
        (capsys.readouterr().out, threshold),
        ((tmp_path / "system.log").read_text(encoding="utf-8"), max(threshold, 20)),
        ((tmp_path / "error.log").read_text(encoding="utf-8"), max(threshold, 40)),
    ]
    for output, floor in outputs:
        for name in ["DEBUG", "INFO", "WARNING", "ERROR"]:
            assert ("quality-token-" + name in output) == (
                logger.level(name).no >= floor
            )
        if log_format == "json":
            for line in output.splitlines():
                assert isinstance(json.loads(line)["record"], dict)


@pytest.mark.parametrize("fault", ["directory", "system.log", "error.log"])
@pytest.mark.parametrize("log_format", ["text", "json"])
def test_log_failures_preserve_console_policy(
    tmp_path, monkeypatch, capsys, fault, log_format
):
    original_add, original_mkdir = logger.add, Path.mkdir
    directory = tmp_path / "logs"

    def mkdir(path, *args, **kwargs):
        if fault == "directory" and path == directory:
            raise PermissionError("No directory access")
        return original_mkdir(path, *args, **kwargs)

    def add(sink, *args, **kwargs):
        if isinstance(sink, Path) and sink.name == fault:
            raise PermissionError("No sink access")
        return original_add(sink, *args, **kwargs)

    monkeypatch.setattr(Path, "mkdir", mkdir)
    monkeypatch.setattr(logger, "add", add)
    try:
        setup_logger("ERROR", log_format, str(directory))
        logger.debug("hidden-debug-token")
        logger.warning("hidden-warning-token")
        logger.error("visible-error-token")
    finally:
        logger.remove()
    output = capsys.readouterr().out
    assert "visible-error-token" in output
    assert "hidden-debug-token" not in output and "hidden-warning-token" not in output
    if log_format == "json":
        for line in output.splitlines():
            json.loads(line)
    if fault != "directory":
        healthy = directory / ("error.log" if fault == "system.log" else "system.log")
        assert "visible-error-token" in healthy.read_text(encoding="utf-8")


def test_openapi_documents_media_errors_and_request_semantics(service_settings):
    schema = create_app(service_settings).openapi()
    paths = schema["paths"]
    for suffix, media in [
        ("stream", "text/event-stream"),
        ("download", "application/pdf"),
    ]:
        op = paths[f"/labels/jobs/{{job_id}}/{suffix}"]["get"]
        assert set(op["responses"]["200"]["content"]) == {media}
        assert op["description"]
    assert {"404", "413", "422", "429", "503"} <= paths["/labels/print"]["post"][
        "responses"
    ].keys()
    assert {"404", "409", "410"} <= paths["/labels/jobs/{job_id}/download"]["get"][
        "responses"
    ].keys()
    assert "404" in paths["/labels/jobs/{job_id}"]["get"]["responses"]
    assert "404" in paths["/labels/jobs/{job_id}/stream"]["get"]["responses"]
    assert "503" in paths["/ready"]["get"]["responses"]
    model = schema["components"]["schemas"]["LabelRequest"]
    for name in ["copies", "copy_order", "labels_per_page"]:
        assert model["properties"][name]["description"]
    LabelRequest.model_validate(model["examples"][0])


def test_documented_stream_and_download_match_http(service_settings, fake_renderer):
    with TestClient(create_app(service_settings)) as client:
        result = client.post(
            "/labels/print",
            json={"template_name": "demo.glabels", "data": [{"ITEM": "A"}]},
        )
        identifier = result.json()["job_id"]
        deadline = time.monotonic() + 15
        while time.monotonic() < deadline:
            job = client.get(f"/labels/jobs/{identifier}").json()
            if job["status"] in ["done", "failed"]:
                break
            time.sleep(0.02)
        assert job["status"] == "done"
        stream = client.get(f"/labels/jobs/{identifier}/stream")
        assert stream.headers["content-type"].startswith("text/event-stream")
        assert "event: status" in stream.text
        pdf = client.get(job["download_url"] + "?preview=true")
        assert pdf.headers["content-type"] == "application/pdf"
        assert pdf.headers["content-disposition"].startswith("inline;")
        assert pdf.content.startswith(b"%PDF-")


@pytest.mark.asyncio
async def test_unconfirmed_execution_retains_capacity():
    scheduler = ResourceScheduler(1)
    with pytest.raises(ExecutionUnavailable):
        async with await scheduler.acquire("render", "job"):
            raise ExecutionUnavailable("Exit not confirmed")
    assert not scheduler.healthy and scheduler.used == 1
    with pytest.raises(ExecutionUnavailable):
        await scheduler.acquire("merge", "next")
