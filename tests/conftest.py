import os
import shutil
import tempfile
import uuid
from pathlib import Path

import pytest


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
        shutil.rmtree(path, ignore_errors=True)
