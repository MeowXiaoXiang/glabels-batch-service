#!/usr/bin/env python3
"""
Unit tests for cpu_detect — container-aware CPU detection.
==========================================================

Covers:
- cgroup v2 cpu.max parsing
- cgroup v1 cfs_quota/cfs_period parsing
- unlimited / "max" values fall through
- fallback to os.cpu_count()
- result is always >= 1
"""

from unittest.mock import patch

import pytest

from app.utils.cpu_detect import (
    _read_cgroup_v1,
    _read_cgroup_v2,
    get_available_cpus,
)


# ---------------------------------------------------------------
# cgroup v2 tests
# ---------------------------------------------------------------
class TestCgroupV2:
    def test_normal_quota(self, tmp_path):
        """400000 100000 → 4 CPUs"""
        cpu_max = tmp_path / "cpu.max"
        cpu_max.write_text("400000 100000\n")
        with patch("app.utils.cpu_detect._CGROUP_V2_CPU_MAX", cpu_max):
            assert _read_cgroup_v2() == pytest.approx(4.0)

    def test_fractional_quota(self, tmp_path):
        """150000 100000 → 1.5 CPUs"""
        cpu_max = tmp_path / "cpu.max"
        cpu_max.write_text("150000 100000\n")
        with patch("app.utils.cpu_detect._CGROUP_V2_CPU_MAX", cpu_max):
            assert _read_cgroup_v2() == pytest.approx(1.5)

    def test_unlimited(self, tmp_path):
        """'max 100000' means no limit → None"""
        cpu_max = tmp_path / "cpu.max"
        cpu_max.write_text("max 100000\n")
        with patch("app.utils.cpu_detect._CGROUP_V2_CPU_MAX", cpu_max):
            assert _read_cgroup_v2() is None

    def test_missing_file(self, tmp_path):
        """Non-existent file → None (no crash)"""
        with patch("app.utils.cpu_detect._CGROUP_V2_CPU_MAX", tmp_path / "missing"):
            assert _read_cgroup_v2() is None


# ---------------------------------------------------------------
# cgroup v1 tests
# ---------------------------------------------------------------
class TestCgroupV1:
    def test_normal_quota(self, tmp_path):
        """200000 / 100000 → 2.0 CPUs"""
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
        """quota=-1 means no limit → None"""
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
        """Non-existent files → None"""
        with (
            patch("app.utils.cpu_detect._CGROUP_V1_QUOTA", tmp_path / "nope1"),
            patch("app.utils.cpu_detect._CGROUP_V1_PERIOD", tmp_path / "nope2"),
        ):
            assert _read_cgroup_v1() is None


# ---------------------------------------------------------------
# get_available_cpus integration
# ---------------------------------------------------------------
class TestGetAvailableCpus:
    def test_uses_cgroup_v2(self, tmp_path):
        """cgroup v2 available → uses it (floor of result)"""
        cpu_max = tmp_path / "cpu.max"
        cpu_max.write_text("400000 100000\n")
        with patch("app.utils.cpu_detect._CGROUP_V2_CPU_MAX", cpu_max):
            assert get_available_cpus() == 4

    def test_v2_fractional_rounds_down(self, tmp_path):
        """1.5 CPUs → floor → 1"""
        cpu_max = tmp_path / "cpu.max"
        cpu_max.write_text("150000 100000\n")
        with patch("app.utils.cpu_detect._CGROUP_V2_CPU_MAX", cpu_max):
            assert get_available_cpus() == 1

    def test_falls_through_to_v1(self, tmp_path):
        """v2 unlimited → falls through to v1"""
        v2_file = tmp_path / "cpu.max"
        v2_file.write_text("max 100000\n")
        quota = tmp_path / "cpu.cfs_quota_us"
        period = tmp_path / "cpu.cfs_period_us"
        quota.write_text("300000\n")
        period.write_text("100000\n")
        with (
            patch("app.utils.cpu_detect._CGROUP_V2_CPU_MAX", v2_file),
            patch("app.utils.cpu_detect._CGROUP_V1_QUOTA", quota),
            patch("app.utils.cpu_detect._CGROUP_V1_PERIOD", period),
        ):
            assert get_available_cpus() == 3

    def test_falls_through_to_os(self, tmp_path):
        """No cgroup → falls back to os.cpu_count()"""
        with (
            patch("app.utils.cpu_detect._CGROUP_V2_CPU_MAX", tmp_path / "nope"),
            patch("app.utils.cpu_detect._CGROUP_V1_QUOTA", tmp_path / "nope1"),
            patch("app.utils.cpu_detect._CGROUP_V1_PERIOD", tmp_path / "nope2"),
            patch("app.utils.cpu_detect.os.cpu_count", return_value=8),
        ):
            assert get_available_cpus() == 8

    def test_minimum_is_one(self, tmp_path):
        """Even with tiny quota, result is at least 1"""
        cpu_max = tmp_path / "cpu.max"
        cpu_max.write_text("10000 100000\n")  # 0.1 CPU → floor = 0 → clamp to 1
        with patch("app.utils.cpu_detect._CGROUP_V2_CPU_MAX", cpu_max):
            assert get_available_cpus() == 1
