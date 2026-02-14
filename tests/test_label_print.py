#!/usr/bin/env python3
"""
Unit tests for LabelPrintService
================================

Covers:
- _chunk_list utility function
- _merge_pdfs utility function
- Batch splitting logic (when labels exceed MAX_LABELS_PER_BATCH)
- Single batch processing (when labels fit in one batch)
"""

import csv
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest
from pypdf import PdfWriter

from app.services.label_print import (
    LabelPrintService,
    _chunk_list,
    _collect_fieldnames,
    _merge_pdfs,
    _slug,
)


class TestUtilityFunctions:
    """Tests for utility functions"""

    def test_chunk_list_basic(self):
        """Should split list into chunks of specified size"""
        data = [1, 2, 3, 4, 5, 6, 7]
        result = _chunk_list(data, 3)
        assert result == [[1, 2, 3], [4, 5, 6], [7]]

    def test_chunk_list_exact_fit(self):
        """Should handle exact multiples correctly"""
        data = [1, 2, 3, 4, 5, 6]
        result = _chunk_list(data, 3)
        assert result == [[1, 2, 3], [4, 5, 6]]

    def test_chunk_list_smaller_than_chunk(self):
        """Should return single chunk if data is smaller"""
        data = [1, 2]
        result = _chunk_list(data, 5)
        assert result == [[1, 2]]

    def test_chunk_list_zero_size(self):
        """Should return original list if chunk_size is 0"""
        data = [1, 2, 3]
        result = _chunk_list(data, 0)
        assert result == [[1, 2, 3]]

    def test_chunk_list_negative_size(self):
        """Should return original list if chunk_size is negative"""
        data = [1, 2, 3]
        result = _chunk_list(data, -1)
        assert result == [[1, 2, 3]]

    def test_collect_fieldnames_basic(self):
        """Should collect field names in order of appearance"""
        data = [{"A": 1, "B": 2}, {"B": 3, "C": 4}]
        result = _collect_fieldnames(data)
        assert result == ["A", "B", "C"]

    def test_collect_fieldnames_with_exclude(self):
        """Should exclude specified fields"""
        data = [{"A": 1, "B": 2, "C": 3}]
        result = _collect_fieldnames(data, exclude=["B"])
        assert result == ["A", "C"]

    def test_slug_basic(self):
        """Should convert string to safe filename"""
        assert _slug("hello world") == "hello_world"
        assert _slug("file.name") == "file.name"
        assert _slug("a-b_c") == "a-b_c"
        # Special characters get replaced with underscores
        assert _slug("test@#$%") == "test____"
        assert _slug("file<>name") == "file__name"


class TestMergePdfs:
    """Tests for PDF merging"""

    def test_merge_pdfs_creates_output(self, tmp_path):
        """Should merge multiple PDFs into one"""
        # Create 3 simple PDFs
        pdf_paths = []
        for i in range(3):
            pdf_path = tmp_path / f"test_{i}.pdf"
            writer = PdfWriter()
            writer.add_blank_page(width=100, height=100)
            with pdf_path.open("wb") as f:
                writer.write(f)
            pdf_paths.append(pdf_path)

        # Merge them
        output_path = tmp_path / "merged.pdf"
        _merge_pdfs(pdf_paths, output_path)

        # Verify output exists and has content
        assert output_path.exists()
        assert output_path.stat().st_size > 0


class TestLabelPrintServiceBatching:
    """Tests for batch splitting logic"""

    @pytest.fixture
    def service(self):
        """Create a LabelPrintService with mocked engine"""
        svc = LabelPrintService(max_parallel=2, default_timeout=60, keep_csv=False)
        return svc

    @pytest.mark.asyncio
    async def test_no_batching_when_disabled(self, service, monkeypatch, tmp_path):
        """Should not batch when MAX_LABELS_PER_BATCH=0"""
        # Mock settings
        mock_settings = MagicMock()
        mock_settings.MAX_LABELS_PER_BATCH = 0  # Disabled
        monkeypatch.setattr("app.services.label_print.settings", mock_settings)

        # Create temp template
        template_dir = tmp_path / "templates"
        template_dir.mkdir()
        template_file = template_dir / "test.glabels"
        template_file.touch()

        # Mock engine and paths
        service.engine.run_batch = AsyncMock()
        monkeypatch.setattr(Path, "cwd", lambda: tmp_path)

        # Track run_batch calls
        call_count = 0

        async def mock_run_batch(**kwargs):
            nonlocal call_count
            call_count += 1
            # Create fake output PDF
            output_pdf = kwargs["output_pdf"]
            writer = PdfWriter()
            writer.add_blank_page(width=100, height=100)
            with output_pdf.open("wb") as f:
                writer.write(f)

        service.engine.run_batch = mock_run_batch
        service._resolve_template = lambda x: template_file

        # Generate with 10 labels (should NOT batch since limit=0)
        data = [{"CODE": f"A{i}"} for i in range(10)]
        (tmp_path / "temp").mkdir(exist_ok=True)
        (tmp_path / "output").mkdir(exist_ok=True)

        await service.generate_pdf(
            job_id="test1",
            template_name="test.glabels",
            data=data,
            copies=1,
            filename="test.pdf",
        )

        # Should only call run_batch once (no batching)
        assert call_count == 1

    @pytest.mark.asyncio
    async def test_batching_when_exceeds_limit(self, service, monkeypatch, tmp_path):
        """Should split into batches when labels exceed MAX_LABELS_PER_BATCH"""
        # Mock settings with small batch size for testing
        mock_settings = MagicMock()
        mock_settings.MAX_LABELS_PER_BATCH = 3  # Small for testing
        monkeypatch.setattr("app.services.label_print.settings", mock_settings)

        # Create temp template
        template_dir = tmp_path / "templates"
        template_dir.mkdir()
        template_file = template_dir / "test.glabels"
        template_file.touch()

        # Track run_batch calls
        call_count = 0
        batch_sizes = []

        async def mock_run_batch(**kwargs):
            nonlocal call_count
            call_count += 1
            csv_path = kwargs["csv_path"]
            # Count lines in CSV (minus header)
            with csv_path.open() as f:
                lines = f.readlines()
                batch_sizes.append(len(lines) - 1)  # Exclude header
            # Create fake output PDF
            output_pdf = kwargs["output_pdf"]
            writer = PdfWriter()
            writer.add_blank_page(width=100, height=100)
            with output_pdf.open("wb") as f:
                writer.write(f)

        service.engine.run_batch = mock_run_batch
        service._resolve_template = lambda x: template_file

        # Generate with 7 labels, batch size 3 → should create 3 batches (3+3+1)
        data = [{"CODE": f"A{i}"} for i in range(7)]
        (tmp_path / "temp").mkdir(exist_ok=True)
        (tmp_path / "output").mkdir(exist_ok=True)

        await service.generate_pdf(
            job_id="test2",
            template_name="test.glabels",
            data=data,
            copies=1,
            filename="test.pdf",
        )

        # Should call run_batch 3 times (7 labels / 3 per batch = 3 batches)
        assert call_count == 3
        assert sorted(batch_sizes) == [1, 3, 3]  # 3+3+1 = 7

    @pytest.mark.asyncio
    async def test_no_batching_when_under_limit(self, service, monkeypatch, tmp_path):
        """Should not batch when labels are under MAX_LABELS_PER_BATCH"""
        # Mock settings
        mock_settings = MagicMock()
        mock_settings.MAX_LABELS_PER_BATCH = 10  # Higher than our data count
        monkeypatch.setattr("app.services.label_print.settings", mock_settings)

        # Create temp template
        template_dir = tmp_path / "templates"
        template_dir.mkdir()
        template_file = template_dir / "test.glabels"
        template_file.touch()

        call_count = 0

        async def mock_run_batch(**kwargs):
            nonlocal call_count
            call_count += 1
            output_pdf = kwargs["output_pdf"]
            writer = PdfWriter()
            writer.add_blank_page(width=100, height=100)
            with output_pdf.open("wb") as f:
                writer.write(f)

        service.engine.run_batch = mock_run_batch
        service._resolve_template = lambda x: template_file

        # Generate with 5 labels (under limit of 10)
        data = [{"CODE": f"A{i}"} for i in range(5)]
        (tmp_path / "temp").mkdir(exist_ok=True)
        (tmp_path / "output").mkdir(exist_ok=True)

        await service.generate_pdf(
            job_id="test3",
            template_name="test.glabels",
            data=data,
            copies=1,
            filename="test.pdf",
        )

        # Should only call run_batch once (no batching needed)
        assert call_count == 1

    @pytest.mark.asyncio
    async def test_batch_pdfs_are_cleaned_up(self, service, monkeypatch, tmp_path):
        """Batch PDFs should be deleted after merging"""
        mock_settings = MagicMock()
        mock_settings.MAX_LABELS_PER_BATCH = 2
        monkeypatch.setattr("app.services.label_print.settings", mock_settings)

        template_dir = tmp_path / "templates"
        template_dir.mkdir()
        template_file = template_dir / "test.glabels"
        template_file.touch()

        created_pdfs = []

        async def mock_run_batch(**kwargs):
            output_pdf = kwargs["output_pdf"]
            created_pdfs.append(output_pdf)
            writer = PdfWriter()
            writer.add_blank_page(width=100, height=100)
            with output_pdf.open("wb") as f:
                writer.write(f)

        service.engine.run_batch = mock_run_batch
        service._resolve_template = lambda x: template_file

        data = [{"CODE": f"A{i}"} for i in range(5)]
        temp_dir = tmp_path / "temp"
        temp_dir.mkdir(exist_ok=True)
        output_dir = tmp_path / "output"
        output_dir.mkdir(exist_ok=True)

        # Monkeypatch Path to use tmp_path-based directories
        original_path = Path

        class MockPath(type(Path())):
            def __new__(cls, *args):
                path_str = str(args[0]) if args else ""
                if path_str == "temp":
                    return original_path(temp_dir)
                elif path_str == "output":
                    return original_path(output_dir)
                return original_path(*args)

        monkeypatch.setattr("app.services.label_print.Path", MockPath)

        await service.generate_pdf(
            job_id="test4",
            template_name="test.glabels",
            data=data,
            copies=1,
            filename="final.pdf",
        )

        # Final PDF should exist
        final_pdf = output_dir / "final.pdf"
        assert final_pdf.exists()

        # Batch PDFs should be cleaned up (they have _batch{n} in name)
        batch_pdfs = [p for p in created_pdfs if "_batch" in str(p.name)]
        for batch_pdf in batch_pdfs:
            assert not batch_pdf.exists(), f"Batch PDF {batch_pdf} should be deleted"


class TestJsonToCsv:
    """Tests for JSON to CSV conversion"""

    def test_json_to_csv_writes_header_and_rows(self, tmp_path):
        """Should write header and rows with expected fields"""
        service = LabelPrintService(max_parallel=1, default_timeout=10, keep_csv=False)
        csv_path = tmp_path / "out.csv"
        data = [
            {"ITEM": "A001", "CODE": "X123"},
            {"ITEM": "A002", "CODE": "X124"},
        ]

        fields = service._json_to_csv(data, csv_path)

        assert fields == ["ITEM", "CODE"]
        with csv_path.open("r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            rows = list(reader)
        assert rows == data

    def test_json_to_csv_empty_raises(self, tmp_path):
        """Should raise for empty data"""
        service = LabelPrintService(max_parallel=1, default_timeout=10, keep_csv=False)
        csv_path = tmp_path / "out.csv"
        with pytest.raises(ValueError, match="No label data"):
            service._json_to_csv([], csv_path)

    def test_json_to_csv_custom_field_order(self, tmp_path):
        """Should respect custom field order"""
        service = LabelPrintService(max_parallel=1, default_timeout=10, keep_csv=False)
        csv_path = tmp_path / "out.csv"
        data = [{"C": "c1", "B": "b1", "A": "a1"}]

        fields = service._json_to_csv(data, csv_path, field_order=["A", "B", "C"])

        assert fields == ["A", "B", "C"]
        with csv_path.open("r", encoding="utf-8") as f:
            header = f.readline().strip()
        assert header == "A,B,C"
