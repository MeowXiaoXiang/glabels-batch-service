import csv

import pytest
from pydantic import ValidationError

from app.schema import LabelRequest
from app.services.label_print import fieldnames, write_csv


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
