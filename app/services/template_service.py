# app/services/template_service.py
# Template management service
# - Lists available templates in templates/ directory
# - Provides template information including field details
# - Integrates with parser system for format detection

from pathlib import Path
from typing import Any

import defusedxml.ElementTree as SafeET
from loguru import logger

from app import parsers
from app.schema import TemplateInfo


class TemplateService:
    """
    Service for managing gLabels templates.

    Handles template discovery, information extraction, and validation.
    """

    def __init__(self, templates_dir: str = "templates"):
        """
        Initialize template service.

        Args:
            templates_dir: Directory containing template files
        """
        self.templates_dir = Path(templates_dir)
        # cache key: absolute template path -> (mtime, parsed TemplateInfo)
        self._template_cache: dict[str, tuple[float, TemplateInfo]] = {}
        logger.debug(
            f"[TemplateService] Initialized with templates directory: {self.templates_dir}"
        )

    def list_templates(self) -> list[TemplateInfo]:
        """
        List all available templates with their information.

        Returns:
            List[TemplateInfo]: List of template information objects

        Raises:
            FileNotFoundError: If templates directory doesn't exist
        """
        if not self.templates_dir.exists():
            logger.warning(
                f"[TemplateService] Templates directory not found: {self.templates_dir}"
            )
            return []

        if not self.templates_dir.is_dir():
            raise ValueError(f"Templates path is not a directory: {self.templates_dir}")

        templates = []
        glabels_files = list(self.templates_dir.glob("*.glabels"))
        logger.info(f"[TemplateService] Found {len(glabels_files)} template files")

        for template_path in glabels_files:
            try:
                template_info = self.get_template_info(template_path.name)
                templates.append(template_info)
                logger.debug(
                    f"[TemplateService] Successfully parsed: {template_path.name}"
                )
            except Exception as e:
                logger.error(
                    f"[TemplateService] Failed to parse {template_path.name}: {e}"
                )
                continue

        templates.sort(key=lambda t: t.name)
        logger.info(f"[TemplateService] Successfully parsed {len(templates)} templates")
        return templates

    def get_template_info(self, template_name: str) -> TemplateInfo:
        """
        Get detailed information for a specific template.

        Args:
            template_name: Template filename (e.g., "demo.glabels")

        Returns:
            TemplateInfo: Template information object

        Raises:
            FileNotFoundError: If template file doesn't exist
            ValueError: If template format is invalid
        """
        template_path = self._resolve_template_path(template_name)

        if not template_path.exists():
            raise FileNotFoundError(f"Template file not found: {template_name}")
        if not template_path.is_file():
            raise ValueError(f"Template path is not a file: {template_name}")

        logger.debug(f"[TemplateService] Getting template info: {template_name}")

        cache_key = str(template_path)
        mtime = template_path.stat().st_mtime
        cached = self._template_cache.get(cache_key)
        if cached and cached[0] == mtime:
            logger.debug(f"[TemplateService] Cache hit: {template_name}")
            return cached[1]

        # Detect template format and get appropriate parser
        format_type = self._detect_format(template_path)
        parser = parsers.get_parser(format_type)
        info = parser.parse_template_info(template_path)
        self._template_cache[cache_key] = (mtime, info)
        return info

    def template_exists(self, template_name: str) -> bool:
        """
        Check if a template file exists.

        Args:
            template_name: Template filename to check

        Returns:
            bool: True if template exists, False otherwise
        """
        try:
            template_path = self._resolve_template_path(template_name)
        except ValueError:
            return False
        return template_path.exists() and template_path.is_file()

    def get_template_path(self, template_name: str) -> Path:
        """
        Get full path to template file.

        Args:
            template_name: Template filename

        Returns:
            Path: Full path to template file

        Raises:
            FileNotFoundError: If template doesn't exist
        """
        template_path = self._resolve_template_path(template_name)
        if not self.template_exists(template_name):
            raise FileNotFoundError(f"Template file not found: {template_name}")
        return template_path

    def _resolve_template_path(self, template_name: str) -> Path:
        """
        Resolve a template path and prevent path traversal.
        """
        if Path(template_name).name != template_name:
            raise ValueError("Template name must not include path separators")

        base_dir = self.templates_dir.resolve()
        template_path = (self.templates_dir / template_name).resolve()

        if not template_path.is_relative_to(base_dir):
            raise ValueError("Template path escapes templates directory")

        return template_path

    def _detect_format(self, template_path: Path) -> str:
        """
        Detect internal data format of gLabels template by examining merge_type.

        Args:
            template_path: Path to .glabels template file

        Returns:
            str: Format type for parser selection (e.g., "csv", "tsv")

        Raises:
            ValueError: If template format is not supported
        """
        try:
            merge_type = self._extract_merge_type(template_path)

            # Determine parser type based on merge_type
            match merge_type:
                case s if "Comma" in s:
                    return "csv"

                # Future text-based format support (commented out until implemented):
                # case s if "Tab" in s:
                #     return "tsv"  # Tab-separated values
                #     # Supports: Text/Tab, Text/Tab/Line1Keys
                # case s if "Semicolon" in s:
                #     return "csv"  # Can reuse CSV parser for semicolon
                #     # Supports: Text/Semicolon, Text/Semicolon/Line1Keys
                # case s if "Colon" in s:
                #     return "csv"  # Can reuse CSV parser for colon
                #     # Supports: Text/Colon, Text/Colon/Line1Keys

                # Note: Binary formats like "ebook/vcard" are not supported
                # as they require different handling than text-based parsers
                case _:
                    raise ValueError(
                        "Unsupported merge type: "
                        f"{merge_type}. Only CSV/Comma templates are supported."
                    )

        except ValueError:
            raise
        except Exception as e:
            raise ValueError(f"Failed to detect template format: {e}")

    def _extract_merge_type(self, template_path: Path) -> str:
        """
        Extract merge type from a .glabels template.
        """
        import gzip

        with gzip.open(template_path, "rt", encoding="utf-8") as f:
            xml_content = f.read()

        root = SafeET.fromstring(xml_content)
        merge_element = self._find_merge_element(root)
        if merge_element is None:
            raise ValueError(f"Template missing Merge element: {template_path}")

        merge_type_raw = merge_element.get("type", "")
        merge_type = str(merge_type_raw)
        if not merge_type:
            raise ValueError(f"Template merge type is empty: {template_path}")
        return merge_type

    @staticmethod
    def _find_merge_element(root: Any) -> Any | None:
        """
        Find Merge element while handling namespace variants.
        """
        merge_element = root.find("Merge")
        if merge_element is None:
            merge_element = root.find(".//{http://glabels.org/xmlns/3.0/}Merge")
        if merge_element is None:
            merge_element = next(root.iter("Merge"), None)
        return merge_element
