# app/utils/cpu_detect.py
# Container-aware CPU count detection.
#
# In containerised environments (Docker/K8s), os.cpu_count() reports the
# **host** CPU count, not the cgroup-enforced limit.  This module reads the
# cgroup (v2 then v1) CPU quota so that auto-scaling parameters such as
# MAX_PARALLEL are calculated from the *actual* available capacity.

from __future__ import annotations

import math
import os
from pathlib import Path

from loguru import logger

__all__ = ["get_available_cpus"]

# ---------------------------------------------------------------------------
# cgroup filesystem paths
# ---------------------------------------------------------------------------
_CGROUP_V2_CPU_MAX = Path("/sys/fs/cgroup/cpu.max")
_CGROUP_V1_QUOTA = Path("/sys/fs/cgroup/cpu/cpu.cfs_quota_us")
_CGROUP_V1_PERIOD = Path("/sys/fs/cgroup/cpu/cpu.cfs_period_us")


def _read_cgroup_v2() -> float | None:
    """Read cgroup v2 cpu.max → effective CPU count (float)."""
    try:
        text = _CGROUP_V2_CPU_MAX.read_text().strip()
        # Format: "<quota> <period>"  e.g. "400000 100000" → 4 CPUs
        # "max 100000" means unlimited
        parts = text.split()
        if len(parts) != 2 or parts[0] == "max":
            return None
        quota, period = int(parts[0]), int(parts[1])
        if period <= 0:
            return None
        return quota / period
    except (OSError, ValueError):
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
    except (OSError, ValueError):
        return None


def get_available_cpus() -> int:
    """Return the number of CPUs available to this process.

    Resolution order:
    1. cgroup v2 ``cpu.max``
    2. cgroup v1 ``cpu.cfs_quota_us / cpu.cfs_period_us``
    3. ``os.cpu_count()`` fallback (host CPU count)

    The result is always ``>= 1``.
    """
    # Try cgroup v2 first (modern Docker / K8s / systemd)
    cpus = _read_cgroup_v2()
    if cpus is not None:
        result = max(1, math.floor(cpus))
        logger.debug("CPU detection: cgroup v2 quota={:.1f} → {} CPUs", cpus, result)
        return result

    # Try cgroup v1
    cpus = _read_cgroup_v1()
    if cpus is not None:
        result = max(1, math.floor(cpus))
        logger.debug("CPU detection: cgroup v1 quota={:.1f} → {} CPUs", cpus, result)
        return result

    # Fallback: host CPU count
    host_cpus = os.cpu_count() or 2
    logger.debug(
        "CPU detection: no cgroup limit found, using os.cpu_count()={}",
        host_cpus,
    )
    return host_cpus
