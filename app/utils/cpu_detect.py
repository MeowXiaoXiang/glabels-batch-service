"""CPU capacity bounded by host visibility, process affinity and cgroup quotas."""

import os
from pathlib import Path

_CGROUP_V2_CPU_MAX = Path("/sys/fs/cgroup/cpu.max")
_CGROUP_V1_QUOTA = Path("/sys/fs/cgroup/cpu/cpu.cfs_quota_us")
_CGROUP_V1_PERIOD = Path("/sys/fs/cgroup/cpu/cpu.cfs_period_us")


def _read_cgroup_v2() -> float | None:
    """Return quota / period, or None for absent, invalid or unlimited quotas."""
    try:
        text = _CGROUP_V2_CPU_MAX.read_text().strip()
        # cpu.max stores "quota period"; quota="max" means unlimited.
        parts = text.split()
        if len(parts) != 2 or parts[0] == "max":
            return None
        quota, period = int(parts[0]), int(parts[1])
        if quota <= 0 or period <= 0:
            return None
        return quota / period
    except OSError, ValueError:
        return None


def _read_cgroup_v1() -> float | None:
    """Read cgroup v1 cpu.cfs_quota_us / cpu.cfs_period_us."""
    try:
        quota = int(_CGROUP_V1_QUOTA.read_text().strip())
        period = int(_CGROUP_V1_PERIOD.read_text().strip())
        # quota == -1 means unlimited
        if quota <= 0 or period <= 0:
            return None
        return quota / period
    except OSError, ValueError:
        return None


def get_cpu_capacity() -> float:
    """Minimum of visible CPU count, affinity and fractional cgroup quotas."""
    candidates = [float(os.cpu_count() or 1)]
    process_count = os.process_cpu_count()
    if process_count:
        candidates.append(float(process_count))
    if hasattr(os, "sched_getaffinity"):
        try:
            candidates.append(float(len(os.sched_getaffinity(0))))
        except OSError:
            pass
    for quota in (_read_cgroup_v2(), _read_cgroup_v1()):
        if quota is not None and quota > 0:
            candidates.append(quota)
    return min(c for c in candidates if c > 0)
