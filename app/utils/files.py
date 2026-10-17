"""Delete only a verified job workspace beneath the configured temp root."""

import shutil
from pathlib import Path
from uuid import UUID


def remove_workspace(root: Path, job_id: str) -> None:
    if str(UUID(job_id)) != job_id:
        raise ValueError("Invalid workspace identifier")
    base = root.resolve()
    candidate = root / job_id
    target = candidate.resolve()
    if target == base or not target.is_relative_to(base) or candidate.is_symlink():
        raise ValueError("Workspace escapes configured temp root")
    if target.exists():
        shutil.rmtree(target)
