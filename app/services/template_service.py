"""Opaque template catalog with path boundaries; never parse XML or gzip."""

from pathlib import Path

from app.schema import TemplateSummary, safe_template_name


class TemplateService:
    def __init__(self, templates_dir: str | Path = "templates") -> None:
        self.templates_dir = Path(templates_dir).resolve()

    def get_template_path(self, template_name: str) -> Path:
        safe_template_name(template_name)
        path = (self.templates_dir / template_name).resolve()
        if not path.is_relative_to(self.templates_dir):
            raise ValueError("Template path escapes configured directory")
        if not path.is_file():
            raise FileNotFoundError("Template not found")
        return path

    def list_templates(self) -> list[TemplateSummary]:
        if not self.templates_dir.is_dir():
            return []
        result = []
        for candidate in sorted(self.templates_dir.iterdir()):
            try:
                self.get_template_path(candidate.name)
            except ValueError, FileNotFoundError:
                continue
            result.append(TemplateSummary(name=candidate.name))
        return result
