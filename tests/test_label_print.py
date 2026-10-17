import csv

import pytest
from pydantic import ValidationError

from app.schema import LabelRequest
from app.services.job_pipeline import batch_shape
from app.services.label_print import batch_rows, fieldnames, write_csv


def test_csv_union_order_quotes_unicode_null_and_boolean(tmp_path):
    rows = [{"ITEM": '中文,"quote"\nnext', "NULL": None}, {"FLAG": True, "ITEM": "B"}]
    path = tmp_path / "named.csv"
    columns = fieldnames(rows)
    assert columns == ["ITEM", "NULL", "FLAG"]
    write_csv(rows, path, columns)
    with path.open(encoding="utf-8", newline="") as stream:
        assert list(csv.reader(stream)) == [
            columns,
            ['中文,"quote"\nnext', "", ""],
            ["B", "", "true"],
        ]


@pytest.mark.parametrize(
    "payload",
    [
        {"data": []},
        {"data": [{}]},
        {"copies": 0},
        {"copies": 101},
        {"copies": "2"},
        {"copy_order": "renderer_native"},
        {"copy_order": "unknown"},
        {"labels_per_page": 0},
        {"labels_per_page": True},
        {"labels_per_page": "3"},
        {"template_name": "../demo.glabels"},
        {"template_name": "C:\\demo.glabels"},
        {"template_name": "demo.xml"},
        {"data": [{"ITEM": {"nested": "object"}}]},
        {"data": [{"ITEM": float("nan")}]},
        {"data": [{"ITEM": "\x00"}]},
        {"data": [{"ITEM": "x" * 2049}]},
        {"unknown": True},
    ],
)
def test_request_contract_rejects_unsupported_input(payload):
    request = {"template_name": "demo.glabels", "data": [{"ITEM": "A"}]} | payload
    with pytest.raises(ValidationError):
        LabelRequest.model_validate(request)


@pytest.mark.parametrize(
    "order,expected", [("sets", "ABCDABCDABCD"), ("per_record", "AAABBBCCCDDD")]
)
def test_virtual_copy_stream_keeps_order_across_arbitrary_batch_boundaries(
    order, expected
):
    req = LabelRequest(
        template_name="demo.glabels",
        data=[{"ITEM": x} for x in "ABCD"],
        copies=3,
        copy_order=order,
    )
    stream = batch_rows(req, 0, 5)
    assert iter(stream) is stream
    actual = list(stream) + list(batch_rows(req, 5, 10)) + list(batch_rows(req, 10, 15))
    assert "".join(str(row["ITEM"]) for row in actual) == expected
    assert all(any(row is original for original in req.data) for row in actual)


def test_page_aligned_batch_shape_and_admission_limits(service_settings):
    cfg = service_settings
    cfg.MAX_LABELS_PER_BATCH = 5
    req = LabelRequest(
        template_name="demo.glabels", data=[{"ITEM": x} for x in "ABCDE"], copies=2
    )
    with pytest.raises(ValueError, match="labels_per_page is required"):
        batch_shape(req, cfg)
    req.labels_per_page = 3
    assert batch_shape(req, cfg) == (3, 4)
    req.labels_per_page = 6
    with pytest.raises(ValueError, match="One declared page"):
        batch_shape(req, cfg)
    req.labels_per_page = 1
    cfg.MAX_BATCHES_PER_JOB = 1
    with pytest.raises(ValueError, match="Batch count"):
        batch_shape(req, cfg)
    cfg.MAX_BATCHES_PER_JOB = 100
    cfg.MAX_PDF_PAGES = 2
    with pytest.raises(ValueError, match="page limit"):
        batch_shape(req, cfg)
    cfg.MAX_PDF_PAGES = 100
    cfg.MAX_EFFECTIVE_LABELS = 9
    with pytest.raises(ValueError, match="effective label limit"):
        batch_shape(req, cfg)


def test_virtual_copies_can_span_batches_and_single_render_needs_no_page_declaration(
    service_settings,
):
    cfg = service_settings
    req = LabelRequest(
        template_name="demo.glabels", data=[{"ITEM": "A"}], copies=5, labels_per_page=1
    )
    assert batch_shape(req, cfg) == (2, 3)
    req.labels_per_page = None
    cfg.MAX_LABELS_PER_BATCH = 5
    assert batch_shape(req, cfg) == (5, 1)
    cfg.MAX_LABELS_PER_BATCH = 0
    assert batch_shape(req, cfg) == (5, 1)
