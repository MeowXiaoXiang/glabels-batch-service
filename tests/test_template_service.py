#!/usr/bin/env python3
"""
Unit tests for TemplateService
==============================

Covers essential functionality:
- Template discovery and listing
- Template information retrieval
- Basic error handling
"""

from pathlib import Path
from unittest.mock import Mock, patch

import pytest

from app.schema import TemplateInfo
from app.services.template_service import TemplateService


class TestTemplateService:

    @pytest.fixture
    def service(self):
        """Create TemplateService instance for testing."""
        return TemplateService(templates_dir="test_templates")

    @patch("app.services.template_service.Path.exists")
    @patch("app.services.template_service.Path.is_dir")
    @patch("app.services.template_service.Path.glob")
    def test_list_templates_success(self, mock_glob, mock_is_dir, mock_exists, service):
        """Should list all templates with their information."""
        # Setup mocks
        mock_exists.return_value = True
        mock_is_dir.return_value = True

        # Mock template files
        mock_file1 = Mock()
        mock_file1.name = "demo.glabels"
        mock_file2 = Mock()
        mock_file2.name = "test.glabels"
        mock_glob.return_value = [mock_file1, mock_file2]

        # Mock get_template_info calls
        template_info1 = TemplateInfo(
            name="demo.glabels",
            format_type="CSV",
            has_headers=True,
            fields=["CODE", "ITEM"],
            field_count=2,
            merge_type="Text/Comma/Line1Keys",
        )
        template_info2 = TemplateInfo(
            name="test.glabels",
            format_type="CSV",
            has_headers=False,
            fields=["1", "2"],
            field_count=2,
            merge_type="Text/Comma",
        )

        with patch.object(service, "get_template_info") as mock_get_info:
            mock_get_info.side_effect = [template_info1, template_info2]

            templates = service.list_templates()

            assert len(templates) == 2
            assert templates[0].name == "demo.glabels"
            assert templates[1].name == "test.glabels"

    @patch("app.services.template_service.Path.exists")
    def test_list_templates_directory_not_exists(self, mock_exists, service):
        """Should return empty list when templates directory doesn't exist."""
        mock_exists.return_value = False

        templates = service.list_templates()

        assert templates == []

    @patch("app.services.template_service.Path.exists")
    @patch("app.parsers.get_parser")
    def test_get_template_info_success(self, mock_get_parser, mock_exists, service):
        """Should get template information successfully."""
        mock_exists.return_value = True

        # Mock parser
        mock_parser = Mock()
        expected_info = TemplateInfo(
            name="demo.glabels",
            format_type="CSV",
            has_headers=True,
            fields=["CODE", "ITEM"],
            field_count=2,
            merge_type="Text/Comma/Line1Keys",
        )
        mock_parser.parse_template_info.return_value = expected_info
        mock_get_parser.return_value = mock_parser

        with patch.object(service, "_detect_format", return_value="csv"):
            result = service.get_template_info("demo.glabels")

            assert result == expected_info
            mock_parser.parse_template_info.assert_called_once()

    @patch("app.services.template_service.Path.exists")
    def test_get_template_info_not_found(self, mock_exists, service):
        """Should raise FileNotFoundError when template doesn't exist."""
        mock_exists.return_value = False

        with pytest.raises(FileNotFoundError, match="Template file not found"):
            service.get_template_info("missing.glabels")

    def test_get_template_info_rejects_path_traversal(self, service):
        """Should reject template names with path separators."""
        with pytest.raises(ValueError, match="must not include path separators"):
            service.get_template_info("../secrets.glabels")

    @patch("gzip.open")
    @patch("xml.etree.ElementTree.fromstring")
    def test_detect_format_csv(self, mock_fromstring, mock_gzip_open, service):
        """Should detect CSV format for comma-based merge types."""
        # Mock XML content
        mock_root = Mock()
        mock_merge = Mock()
        mock_merge.get.return_value = "Text/Comma/Line1Keys"
        mock_root.find.return_value = mock_merge
        mock_fromstring.return_value = mock_root

        mock_gzip_open.return_value.__enter__.return_value.read.return_value = (
            "<xml>content</xml>"
        )

        result = service._detect_format(Path("demo.glabels"))

        assert result == "csv"

    @patch("gzip.open")
    @patch("xml.etree.ElementTree.fromstring")
    def test_detect_format_unsupported(self, mock_fromstring, mock_gzip_open, service):
        """Should raise ValueError for unsupported merge type."""
        # Mock XML content
        mock_root = Mock()
        mock_merge = Mock()
        mock_merge.get.return_value = "UnsupportedType"
        mock_root.find.return_value = mock_merge
        mock_fromstring.return_value = mock_root

        mock_gzip_open.return_value.__enter__.return_value.read.return_value = (
            "<xml>content</xml>"
        )

        with pytest.raises(ValueError, match="Unsupported merge type"):
            service._detect_format(Path("demo.glabels"))
