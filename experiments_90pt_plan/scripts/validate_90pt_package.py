#!/usr/bin/env python
"""Validate whether W08 has the raw outputs needed for a 90-point package."""

from __future__ import annotations

import argparse
import csv
from pathlib import Path


def read_tsv(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle, delimiter="\t"))


def read_table_profile(path: Path) -> tuple[int, set[str], dict[str, set[str]]]:
    suffix = path.suffix.lower()
    if suffix == ".parquet":
        try:
            import pandas as pd
        except ImportError:
            return -1, set(), {}
        frame = pd.read_parquet(path)
        values = {
            column: {str(value) for value in frame[column].dropna().unique()}
            for column in frame.columns
        }
        return len(frame), set(frame.columns), values
    if suffix in {".csv", ".tsv"}:
        delimiter = "\t" if suffix == ".tsv" else ","
        with path.open("r", encoding="utf-8", newline="") as handle:
            reader = csv.DictReader(handle, delimiter=delimiter)
            count = 0
            values: dict[str, set[str]] = {field: set() for field in reader.fieldnames or []}
            for _ in reader:
                for field in values:
                    value = _.get(field, "")
                    if value != "":
                        values[field].add(str(value))
                count += 1
            return count, set(reader.fieldnames or []), values
    return -1, set(), {}


def parse_required_values(spec: str) -> dict[str, set[str]]:
    clauses: dict[str, set[str]] = {}
    for clause in spec.split(";"):
        clause = clause.strip()
        if not clause:
            continue
        if "=" not in clause:
            raise SystemExit(f"Malformed required_values clause: {clause}")
        column, raw_values = clause.split("=", 1)
        values = {value.strip() for value in raw_values.split("|") if value.strip()}
        clauses[column.strip()] = values
    return clauses


def has_derived_only_provenance(values: dict[str, set[str]]) -> bool:
    provenance_values = set()
    for column in ("provenance_note", "source_run_id", "lineage_status"):
        provenance_values.update(values.get(column, set()))
    lowered = " ".join(sorted(provenance_values)).lower()
    return any(
        marker in lowered
        for marker in (
            "derived_from_existing",
            "legacy",
            "unstaged",
            "summary_import",
        )
    )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", default=".", help="W08 manuscript root")
    parser.add_argument(
        "--contract",
        default="experiments_90pt_plan/configs/90pt_required_outputs.tsv",
        help="Required output contract TSV",
    )
    parser.add_argument("--allow-missing", action="store_true", help="Return zero even when required outputs are missing")
    args = parser.parse_args()

    root = Path(args.root)
    contract = root / args.contract
    records = read_tsv(contract)
    failures: list[str] = []
    for record in records:
        rel = Path(record["path"])
        path = root / rel
        required = record.get("required", "true").lower() == "true"
        min_rows = int(record.get("min_rows") or 0)
        required_columns = {c.strip() for c in record.get("required_columns", "").split(",") if c.strip()}
        if not path.exists():
            if required:
                failures.append(f"missing required output: {rel}")
            continue
        row_count, columns, table_values = read_table_profile(path)
        if row_count >= 0 and row_count < min_rows:
            failures.append(f"{rel} has {row_count} rows, expected at least {min_rows}")
        missing_columns = sorted(required_columns - columns)
        if missing_columns:
            failures.append(f"{rel} missing columns: {', '.join(missing_columns)}")
        for column, expected_values in parse_required_values(record.get("required_values", "")).items():
            if column not in columns:
                failures.append(f"{rel} missing required-values column: {column}")
                continue
            observed = table_values.get(column, set())
            missing_values = sorted(expected_values - observed)
            if missing_values:
                failures.append(
                    f"{rel} missing required {column} values: {', '.join(missing_values)}"
                )
        if record.get("required_for_90pt", record.get("required", "true")).lower() in {"true", "yes"}:
            if has_derived_only_provenance(table_values):
                failures.append(
                    f"{rel} contains derived/legacy provenance markers; real raw/HPC lineage is required for 90-point claims"
                )

    if failures:
        print("90-point package validation failed:")
        for failure in failures:
            print(f"- {failure}")
        if not args.allow_missing:
            raise SystemExit(1)
    else:
        print("90-point package validation passed.")


if __name__ == "__main__":
    main()
