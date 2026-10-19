"""The service owns CSV encoding; gLabels owns all template interpretation."""

import csv
from collections.abc import Iterable, Iterator, Sequence
from pathlib import Path

from app.schema import LabelRequest, Scalar


def fieldnames(rows: Sequence[dict[str, Scalar]]) -> list[str]:
    return list(dict.fromkeys(key for row in rows for key in row))


def csv_value(value: Scalar) -> str:
    if value is None:
        return ""
    if isinstance(value, bool):
        return "true" if value else "false"
    return str(value)


def batch_rows(req: LabelRequest, start: int, stop: int) -> Iterator[dict[str, Scalar]]:
    """Index a virtual expanded stream without copying the input or prior batches."""
    records = len(req.data)
    for position in range(start, min(stop, records * req.copies)):
        index = (
            position % records if req.copy_order == "sets" else position // req.copies
        )
        yield req.data[index]


def write_csv(
    rows: Iterable[dict[str, Scalar]], path: Path, columns: list[str]
) -> None:
    with path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.writer(stream)
        writer.writerow(columns)
        for row in rows:
            writer.writerow([csv_value(row.get(key)) for key in columns])
