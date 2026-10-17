import pytest

from app.services.template_service import TemplateService


def test_catalog_does_not_parse_opaque_or_malformed_template(tmp_path):
    (tmp_path / "opaque.glabels").write_bytes(b"not XML and not gzip")
    (tmp_path / "other.txt").write_text("ignore")
    catalog = TemplateService(tmp_path)
    assert [t.model_dump() for t in catalog.list_templates()] == [
        {"name": "opaque.glabels"}
    ]


@pytest.mark.parametrize(
    "name",
    [
        "../bad.glabels",
        "sub/bad.glabels",
        "sub\\bad.glabels",
        "C:bad.glabels",
        "bad.xml",
    ],
)
def test_catalog_rejects_paths(tmp_path, name):
    with pytest.raises(ValueError):
        TemplateService(tmp_path).get_template_path(name)


def test_catalog_rejects_symlink_escape(tmp_path):
    root = tmp_path / "templates"
    root.mkdir()
    outside = tmp_path / "outside.glabels"
    outside.write_text("opaque")
    try:
        (root / "escape.glabels").symlink_to(outside)
    except OSError:
        pytest.skip("Creating symlinks requires platform permission")
    assert TemplateService(root).list_templates() == []
