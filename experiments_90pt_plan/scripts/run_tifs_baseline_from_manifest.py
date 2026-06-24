#!/usr/bin/env python
"""Append real baseline metrics from a staged manifest into the TIFS baseline table."""

from __future__ import annotations

import argparse
import csv
from pathlib import Path

REQUIRED = [
    "experiment",
    "method",
    "dataset",
    "student_base",
    "teacher_family",
    "condition",
    "seed",
    "auroc",
    "tpr_at_1pct_fpr",
    "fpr_zero",
    "ci_low",
    "ci_high",
    "n_students",
    "access_tier",
    "source_run_id",
]


def read_csv_or_tsv(path: Path) -> list[dict[str, str]]:
    if not path.exists() or path.stat().st_size == 0:
        return []
    delimiter = "\t" if path.suffix.lower() == ".tsv" else ","
    with path.open("r", encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle, delimiter=delimiter))


def write_csv(path: Path, rows: list[dict[str, str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=REQUIRED)
        writer.writeheader()
        writer.writerows(rows)


def validate_rows(
    rows: list[dict[str, str]], method: str, dataset: str
) -> list[dict[str, str]]:
    filtered = [
        row
        for row in rows
        if row.get("method", "").lower() == method.lower()
        and row.get("dataset", "").lower() == dataset.lower()
    ]
    if not filtered:
        raise SystemExit(f"No baseline rows for method={method}, dataset={dataset}")
    missing_messages = []
    for idx, row in enumerate(filtered, start=2):
        missing = [
            column for column in REQUIRED if not str(row.get(column, "")).strip()
        ]
        if missing:
            missing_messages.append(f"row {idx} missing: {', '.join(missing)}")
    if missing_messages:
        raise SystemExit("\n".join(missing_messages))
    forbidden = {"derived_from_existing", "legacy", "current_local_bundle"}
    bad = [
        row.get("source_run_id", "")
        for row in filtered
        if row.get("source_run_id", "") in forbidden
    ]
    if bad:
        raise SystemExit(
            "Baseline rows contain non-90pt source_run_id markers: "
            + ", ".join(sorted(set(bad)))
        )
    return [{column: row[column] for column in REQUIRED} for row in filtered]


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", default=".")
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--method", required=True)
    parser.add_argument("--dataset", required=True)
    parser.add_argument(
        "--source", default="results_90pt/raw_trace_manifests/baseline_inputs.tsv"
    )
    parser.add_argument(
        "--out", default="results_90pt/summaries/tifs_baseline_head_to_head.csv"
    )
    args = parser.parse_args()

    root = Path(args.root)
    rows = read_csv_or_tsv(root / args.source)
    validated = validate_rows(rows, args.method, args.dataset)
    out_path = root / args.out
    existing = read_csv_or_tsv(out_path)
    write_csv(out_path, existing + validated)
    print(f"Appended {len(validated)} baseline rows for {args.method} -> {out_path}")


if __name__ == "__main__":
    main()
