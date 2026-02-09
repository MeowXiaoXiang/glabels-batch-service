# app/parsers/base_parser.py
# Abstract base class for template parsers
# - Defines the interface for all template parsers
# - Prevents direct instantiation
# - Enforces consistent parser implementation

from abc import ABC, abstractmethod
from pathlib import Path

from app.schema import TemplateInfo


class BaseParser(ABC):
    """
    Abstract base class for template parsers.

    All template parsers must inherit from this class and implement
    the parse_template_info method.
    """

    def __init__(self) -> None:
        """
        Prevent direct instantiation of abstract base class.
        """
        if self.__class__ == BaseParser:
            raise NotImplementedError(
                "BaseParser is abstract. Use parsers.get_parser() to get parser instance."
            )

    @abstractmethod
    def parse_template_info(self, template_path: Path) -> TemplateInfo:
        """
        Parse template file and extract field information.

        Args:
            template_path: Path to the template file

        Returns:
            TemplateInfo: Template metadata including fields and format info

        Raises:
            FileNotFoundError: If template file doesn't exist
            ValueError: If template format is invalid or unsupported
        """
        pass

    def validate_template_path(self, template_path: Path) -> None:
        """
        Common validation for template file path.

        Args:
            template_path: Path to validate

        Raises:
            FileNotFoundError: If file doesn't exist
            ValueError: If file is not a regular file
        """
        if not template_path.exists():
            raise FileNotFoundError(f"Template file not found: {template_path}")

        if not template_path.is_file():
            raise ValueError(f"Path is not a file: {template_path}")
