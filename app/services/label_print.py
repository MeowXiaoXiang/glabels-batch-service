"""The service owns CSV encoding; gLabels owns all template interpretation."""

import csv
from collections.abc import Sequence
from pathlib import Path

from app.schema import Scalar


def fieldnames(rows: Sequence[dict[str, Scalar]]) -> list[str]:
    return list(dict.fromkeys(key for row in rows for key in row))


def csv_value(value: Scalar) -> str:
    if value is None:
        return ""
    if isinstance(value, bool):
        return "true" if value else "false"
    return str(value)


def write_csv(
    rows: Sequence[dict[str, Scalar]], path: Path, columns: list[str]
) -> None:
    with path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.writer(stream)
        writer.writerow(columns)
        for row in rows:
            writer.writerow([csv_value(row.get(key)) for key in columns])
