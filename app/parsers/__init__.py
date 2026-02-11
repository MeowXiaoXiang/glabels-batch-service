# app/parsers/__init__.py
# Template parser factory
# - Provides unified interface for all template parsers
# - Uses Python 3.12 match-case syntax
# - Exposes only factory function, hides implementation details

from .base_parser import BaseParser
from .csv_parser import CSVParser


def get_parser(format_type: str = "csv") -> BaseParser:
    """
    Get template parser instance based on format type.

    Args:
        format_type: Parser type to create
                    - "csv": CSV parser (supports both header/no-header)

    Returns:
        BaseParser: Parser instance

    Raises:
        ValueError: If format_type is not supported

    Examples:
        >>> parser = get_parser("csv")
        >>> info = parser.parse_template_info(Path("demo.glabels"))
    """
    match format_type.lower():
        case "csv":
            return CSVParser()
        case _:
            raise ValueError(
                f"Unsupported parser format: {format_type}. Supported formats: csv"
            )


# Public interface: only expose factory function
__all__ = ["get_parser"]
