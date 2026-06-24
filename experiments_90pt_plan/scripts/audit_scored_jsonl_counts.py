#!/usr/bin/env python
"""Audit scored JSONL row counts and minimal provenance columns."""

from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path


REQUIRED_COLUMNS = {"id", "student", "candidate_teacher", "mean_lp", "sum_lp", "n_assistant_tokens"}
EXPECTED_ROWS = {"scored_gsm8k": 200, "scored_math": 200}


def audit_file(path: Path, expected_rows: int) -> dict[str, str | int]:
    row_count = 0
    columns: set[str] = set()
    malformed = 0
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            if not line.strip():
                continue
            row_count += 1
            try:
                columns.update(json.loads(line).keys())
            except json.JSONDecodeError:
                malformed += 1
    missing = sorted(REQUIRED_COLUMNS - columns)
    status = "pass"
    if row_count != expected_rows or missing or malformed:
        status = "review"
    return {
        "path": str(path).replace("\\", "/"),
        "matrix_group": path.parent.name,
        "expected_rows": expected_rows,
        "actual_rows": row_count,
        "missing_minimal_columns": ",".join(missing),
        "malformed_json_lines": malformed,
        "validation_status": status,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", default=".", help="W08 manuscript root")
    parser.add_argument(
        "--out",
        default="reproducibility_bundle/SCORES/scored_jsonl_row_count_audit.tsv",
        help="Output TSV",
    )
    args = parser.parse_args()

    root = Path(args.root)
    rows = []
    for group, expected in EXPECTED_ROWS.items():
        for path in sorted((root / "figures" / "source" / group).glob("*.jsonl")):
            rows.append(audit_file(path, expected))

    out_path = root / args.out
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with out_path.open("w", encoding="utf-8", newline="") as handle:
        fieldnames = [
            "path",
            "matrix_group",
            "expected_rows",
            "actual_rows",
            "missing_minimal_columns",
            "malformed_json_lines",
            "validation_status",
        ]
        writer = csv.DictWriter(handle, fieldnames=fieldnames, delimiter="\t")
        writer.writeheader()
        writer.writerows(rows)

    review = [row for row in rows if row["validation_status"] != "pass"]
    print(f"Wrote {len(rows)} scored-matrix audit rows to {out_path}")
    if review:
        print("Rows requiring review:")
        for row in review:
            print(f"- {row['path']}: {row['actual_rows']} / {row['expected_rows']}")


if __name__ == "__main__":
    main()
