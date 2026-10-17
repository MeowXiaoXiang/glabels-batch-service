import asyncio
import csv
import os
import shutil
import sys
import tempfile
import uuid
from pathlib import Path

import pikepdf
import pytest

from app.config import Settings
from app.utils.glabels_engine import GlabelsEngine, GlabelsRunError


def _select_base_dir():
    root = Path(__file__).resolve().parent.parent
    system_base = Path(tempfile.gettempdir()) / "labels-service-pytest"
    local_base = root / "temp" / "pytest"

    for candidate in (system_base, local_base):
        try:
            candidate.mkdir(parents=True, exist_ok=True)
            probe = candidate / ".probe"
            probe.write_text("ok")
            probe.unlink(missing_ok=True)
            return candidate
        except PermissionError:
            continue

    # Last resort: keep local_base even if probe failed
    local_base.mkdir(parents=True, exist_ok=True)
    return local_base


def pytest_configure(config):
    """
    Force pytest/tempfile to use a workspace-local temp directory.
    This avoids PermissionError when the system temp directory is not writable.
    """
    base = _select_base_dir()

    os.environ["TMPDIR"] = str(base)
    os.environ["TEMP"] = str(base)
    os.environ["TMP"] = str(base)
    tempfile.tempdir = str(base)
    config.option.basetemp = str(base / "basetemp")


@pytest.fixture
def tmp_path():
    """
    Provide a writable temp directory under system temp when possible.
    Overrides pytest's default tmp_path fixture.
    """
    base = _select_base_dir() / "pytest_tmp"
    base.mkdir(parents=True, exist_ok=True)
    base.mkdir(parents=True, exist_ok=True)
    path = base / uuid.uuid4().hex
    path.mkdir(parents=True, exist_ok=True)
    try:
        yield path
    finally:
        if (
            not path.resolve().is_relative_to(base.resolve())
            or path.resolve() == base.resolve()
        ):
            raise RuntimeError("Refusing cleanup outside fixture root")
        shutil.rmtree(path, ignore_errors=True)


@pytest.fixture
def service_settings(tmp_path):
    templates = tmp_path / "templates"
    templates.mkdir()
    (templates / "demo.glabels").write_bytes(
        b"opaque fixture: only renderer reads this"
    )
    return Settings(
        _env_file=None,
        ENVIRONMENT="development",
        RELOAD=False,
        GLABELS_EXECUTABLE=sys.executable,
        WORK_TOKENS=2,
        MAX_LABELS_PER_BATCH=2,
        MAX_PENDING_JOBS=2,
        MAX_INFLIGHT_JOBS=2,
        MIN_FREE_DISK_BYTES=0,
        SHUTDOWN_TIMEOUT=2,
        TEMPLATES_DIR=templates,
        OUTPUT_DIR=tmp_path / "output",
        TEMP_DIR=tmp_path / "temp",
        STATE_DIR=tmp_path / "state",
        LOG_DIR=str(tmp_path / "logs"),
    )


@pytest.fixture
def fake_renderer(monkeypatch):
    async def render(self, *, output_pdf, template_path, csv_path, copies=1):
        assert copies == 1, "Only the service may expand copies"
        if template_path.read_bytes().startswith(b"bad"):
            raise GlabelsRunError("invalid fixture")
        # Finish later batches first; pipeline must still merge by batch index.
        index = int(output_pdf.stem.rsplit("-", 1)[-1])
        await asyncio.sleep(0.01 / (index + 1))
        with csv_path.open(encoding="utf-8", newline="") as stream:
            rows = list(csv.DictReader(stream))
        with pikepdf.Pdf.new() as pdf:
            for _ in range(copies):
                for row in rows:
                    page = pdf.add_blank_page(page_size=(200, 100))
                    page.obj.ServiceItem = row.get("ITEM", "")
            pdf.save(output_pdf)

    monkeypatch.setattr(GlabelsEngine, "run_batch", render)
