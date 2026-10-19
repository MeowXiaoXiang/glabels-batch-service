from unittest.mock import patch

import pytest

from app.utils.cpu_detect import (
    _read_cgroup_v1,
    _read_cgroup_v2,
    get_cpu_capacity,
)


@pytest.mark.parametrize(
    "host,process,affinity,v2,v1,expected",
    [
        (16, 8, 4, None, None, 4),
        (16, 8, 4, 1.5, None, 1.5),
        (16, 8, 4, 0.5, None, 0.5),
        (16, 8, 4, 8, 2, 2),
        (4, 16, 8, None, None, 4),
    ],
)
def test_effective_capacity_uses_smallest_limit_and_preserves_fraction(
    monkeypatch, host, process, affinity, v2, v1, expected
):
    import app.utils.cpu_detect as module

    monkeypatch.setattr(module.os, "cpu_count", lambda: host)
    monkeypatch.setattr(module.os, "process_cpu_count", lambda: process)
    monkeypatch.setattr(
        module.os, "sched_getaffinity", lambda pid: set(range(affinity)), raising=False
    )
    monkeypatch.setattr(module, "_read_cgroup_v2", lambda: v2)
    monkeypatch.setattr(module, "_read_cgroup_v1", lambda: v1)
    assert get_cpu_capacity() == expected


@pytest.mark.parametrize(
    "host,process,affinity_error,expected",
    [(8, None, False, 8), (8, 2, True, 2), (None, None, False, 1)],
)
def test_capacity_without_usable_affinity(
    monkeypatch, host, process, affinity_error, expected
):
    import app.utils.cpu_detect as module

    monkeypatch.setattr(module.os, "cpu_count", lambda: host)
    monkeypatch.setattr(module.os, "process_cpu_count", lambda: process)
    if affinity_error:

        def unavailable(pid):
            raise OSError("Affinity unavailable")

        monkeypatch.setattr(module.os, "sched_getaffinity", unavailable, raising=False)
    else:
        monkeypatch.delattr(module.os, "sched_getaffinity", raising=False)
    monkeypatch.setattr(module, "_read_cgroup_v2", lambda: None)
    monkeypatch.setattr(module, "_read_cgroup_v1", lambda: None)
    assert get_cpu_capacity() == expected


class TestCgroupV2:
    def test_normal_quota(self, tmp_path):
        cpu_max = tmp_path / "cpu.max"
        cpu_max.write_text("400000 100000\n")
        with patch("app.utils.cpu_detect._CGROUP_V2_CPU_MAX", cpu_max):
            assert _read_cgroup_v2() == pytest.approx(4.0)

    def test_fractional_quota(self, tmp_path):
        cpu_max = tmp_path / "cpu.max"
        cpu_max.write_text("150000 100000\n")
        with patch("app.utils.cpu_detect._CGROUP_V2_CPU_MAX", cpu_max):
            assert _read_cgroup_v2() == pytest.approx(1.5)

    def test_unlimited(self, tmp_path):
        cpu_max = tmp_path / "cpu.max"
        cpu_max.write_text("max 100000\n")
        with patch("app.utils.cpu_detect._CGROUP_V2_CPU_MAX", cpu_max):
            assert _read_cgroup_v2() is None

    def test_missing_file(self, tmp_path):
        with patch("app.utils.cpu_detect._CGROUP_V2_CPU_MAX", tmp_path / "missing"):
            assert _read_cgroup_v2() is None


class TestCgroupV1:
    def test_normal_quota(self, tmp_path):
        quota = tmp_path / "cpu.cfs_quota_us"
        period = tmp_path / "cpu.cfs_period_us"
        quota.write_text("200000\n")
        period.write_text("100000\n")
        with (
            patch("app.utils.cpu_detect._CGROUP_V1_QUOTA", quota),
            patch("app.utils.cpu_detect._CGROUP_V1_PERIOD", period),
        ):
            assert _read_cgroup_v1() == pytest.approx(2.0)

    def test_unlimited(self, tmp_path):
        quota = tmp_path / "cpu.cfs_quota_us"
        period = tmp_path / "cpu.cfs_period_us"
        quota.write_text("-1\n")
        period.write_text("100000\n")
        with (
            patch("app.utils.cpu_detect._CGROUP_V1_QUOTA", quota),
            patch("app.utils.cpu_detect._CGROUP_V1_PERIOD", period),
        ):
            assert _read_cgroup_v1() is None

    def test_missing_file(self, tmp_path):
        with (
            patch("app.utils.cpu_detect._CGROUP_V1_QUOTA", tmp_path / "nope1"),
            patch("app.utils.cpu_detect._CGROUP_V1_PERIOD", tmp_path / "nope2"),
        ):
            assert _read_cgroup_v1() is None
