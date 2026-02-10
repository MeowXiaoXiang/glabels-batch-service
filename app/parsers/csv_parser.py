# app/parsers/csv_parser.py
# CSV template parser for gLabels files
# - Supports both header and no-header CSV formats
# - Auto-detects format based on Merge type in XML
# - Extracts field information from template

import gzip
import xml.etree.ElementTree as ET
from pathlib import Path

import defusedxml.ElementTree as SafeET
from loguru import logger

from app.schema import TemplateInfo

from .base_parser import BaseParser


class CSVParser(BaseParser):
    """
    Parser for gLabels templates that output CSV format.

    Supports both:
    - CSV with headers (Text/Comma/Line1Keys) - fields by name
    - CSV without headers (Text/Comma) - fields by position
    """

    def parse_template_info(self, template_path: Path) -> TemplateInfo:
        """
        Parse gLabels template file and extract CSV format information.

        Args:
            template_path: Path to .glabels template file

        Returns:
            TemplateInfo: Complete template metadata
        """
        self.validate_template_path(template_path)

        logger.debug(f"[CSVParser] Parsing template: {template_path}")

        try:
            xml_content = self._decompress_glabels_file(template_path)
            root = SafeET.fromstring(xml_content)

            # Find Merge element (handle namespaces)
            merge_element = root.find("Merge")
            if merge_element is None:
                merge_element = root.find(".//{http://glabels.org/xmlns/3.0/}Merge")
            if merge_element is None:
                merge_elements = root.iter("Merge")
                merge_element = next(merge_elements, None)

            if merge_element is None:
                raise ValueError(
                    f"Template file missing Merge element: {template_path}"
                )

            merge_type = merge_element.get("type", "")
            logger.debug(f"[CSVParser] Merge type: {merge_type}")

            if "Line1Keys" in merge_type:
                return self._parse_header_format(template_path, root, merge_type)
            else:
                return self._parse_no_header_format(template_path, root, merge_type)

        except ET.ParseError as e:
            raise ValueError(f"Failed to parse XML: {e}")
        except Exception as e:
            logger.error(f"[CSVParser] Template parsing failed: {e}")
            raise ValueError(f"Failed to parse template file: {e}")

    def _decompress_glabels_file(self, template_path: Path) -> str:
        """
        Decompress .glabels file (gzip compressed XML).

        Args:
            template_path: Path to .glabels file

        Returns:
            str: Decompressed XML content
        """
        try:
            with gzip.open(template_path, "rt", encoding="utf-8") as f:
                return f.read()
        except Exception as e:
            raise ValueError(f"Failed to decompress gLabels file: {e}")

    def _parse_header_format(
        self, template_path: Path, root: ET.Element, merge_type: str
    ) -> TemplateInfo:
        """
        Parse template with CSV headers format.

        Args:
            template_path: Template file path
            root: XML root element
            merge_type: Merge type string

        Returns:
            TemplateInfo: Template info for header format
        """
        fields = self._extract_field_names(root)
        logger.debug(f"[CSVParser] Header format, fields: {fields}")

        return TemplateInfo(
            name=template_path.name,
            format_type="CSV",
            has_headers=True,
            fields=fields,
            field_count=len(fields),
            merge_type=merge_type,
        )

    def _parse_no_header_format(
        self, template_path: Path, root: ET.Element, merge_type: str
    ) -> TemplateInfo:
        """
        Parse template with CSV no-headers format.

        Args:
            template_path: Template file path
            root: XML root element
            merge_type: Merge type string

        Returns:
            TemplateInfo: Template info for no-header format
        """
        field_positions = self._extract_field_positions(root)
        logger.debug(
            f"[CSVParser] No-header format, field positions: {field_positions}"
        )

        return TemplateInfo(
            name=template_path.name,
            format_type="CSV",
            has_headers=False,
            fields=field_positions,
            field_count=len(field_positions),
            merge_type=merge_type,
        )

    def _extract_field_names(self, root: ET.Element) -> list[str]:
        """
        Extract field names from template (for header format).

        Args:
            root: XML root element

        Returns:
            List[str]: List of field names (e.g., ['CODE', 'ITEM'])
        """
        fields = set()

        # Find all Field elements (handle namespaces)
        for field_elem in root.iter():
            if field_elem.tag.endswith("Field"):
                field_name = field_elem.get("name")
                if field_name:
                    fields.add(field_name)

        # Also search for field attributes in all elements
        for elem in root.iter():
            field_attr = elem.get("field")
            if field_attr:
                fields.add(field_attr)
        return sorted(list(fields))

    def _extract_field_positions(self, root: ET.Element) -> list[str]:
        """
        Extract field positions from template (for no-header format).

        Args:
            root: XML root element

        Returns:
            List[str]: List of field positions (e.g., ['1', '2'])
        """
        positions = set()

        # Find all Field elements (handle namespaces)
        for field_elem in root.iter():
            if field_elem.tag.endswith("Field"):
                field_name = field_elem.get("name")
                if field_name and field_name.isdigit():
                    positions.add(field_name)

        # Also search for field attributes in all elements
        for elem in root.iter():
            field_attr = elem.get("field")
            if field_attr and field_attr.isdigit():
                positions.add(field_attr)
        return sorted(list(positions), key=int)
