#!/usr/bin/env python
"""Validate whether the W08 review-time reproducibility package is complete."""

from __future__ import annotations

import argparse
import csv
from pathlib import Path


def read_tsv(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle, delimiter="\t"))


def parse_values(spec: str) -> dict[str, set[str]]:
    clauses: dict[str, set[str]] = {}
    for clause in spec.split(";"):
        clause = clause.strip()
        if not clause:
            continue
        if "=" not in clause:
            raise SystemExit(f"Malformed value clause: {clause}")
        column, raw_values = clause.split("=", 1)
        clauses[column.strip()] = {
            value.strip() for value in raw_values.split("|") if value.strip()
        }
    return clauses


def read_table(path: Path) -> tuple[list[dict[str, str]], set[str]]:
    if not path.exists():
        return [], set()
    suffix = path.suffix.lower()
    if suffix == ".parquet":
        try:
            import pandas as pd
        except ImportError as exc:
            raise SystemExit("pandas/pyarrow are required to read parquet evidence") from exc
        frame = pd.read_parquet(path)
        return frame.astype(str).to_dict(orient="records"), set(frame.columns)
    delimiter = "\t" if suffix == ".tsv" else ","
    with path.open("r", encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle, delimiter=delimiter)
        return list(reader), set(reader.fieldnames or [])


def resolve_path(root: Path, value: str) -> Path:
    path = Path(value)
    return path if path.is_absolute() else root / path


def check_record(root: Path, record: dict[str, str]) -> list[str]:
    failures: list[str] = []
    rel = record["path"]
    path = root / rel
    kind = record.get("kind", "table")
    min_rows = int(record.get("min_rows") or 0)
    if kind == "file":
        if not path.exists():
            return [f"{record['gate_id']}: missing file {rel}"]
        if min_rows > 0 and path.stat().st_size == 0:
            failures.append(f"{record['gate_id']}: file is empty: {rel}")
        return failures

    if not path.exists():
        return [f"{record['gate_id']}: missing table {rel}"]
    rows, columns = read_table(path)
    if len(rows) < min_rows:
        failures.append(
            f"{record['gate_id']}: {rel} has {len(rows)} rows, expected at least {min_rows}"
        )

    required_columns = {
        column.strip()
        for column in record.get("required_columns", "").split(",")
        if column.strip()
    }
    missing_columns = sorted(required_columns - columns)
    if missing_columns:
        failures.append(
            f"{record['gate_id']}: {rel} missing columns: {', '.join(missing_columns)}"
        )

    values_by_column = {
        column: {row.get(column, "") for row in rows if row.get(column, "") != ""}
        for column in columns
    }
    for column, expected_values in parse_values(record.get("required_values", "")).items():
        observed = values_by_column.get(column, set())
        missing = sorted(expected_values - observed)
        if missing:
            failures.append(
                f"{record['gate_id']}: {rel} missing {column} values: {', '.join(missing)}"
            )
    for column, forbidden_values in parse_values(record.get("forbid_values", "")).items():
        observed_forbidden = sorted(values_by_column.get(column, set()) & forbidden_values)
        if observed_forbidden:
            failures.append(
                f"{record['gate_id']}: {rel} contains forbidden {column} values: {', '.join(observed_forbidden)}"
            )

    for column in [c for c in record.get("check_path_columns", "").split("|") if c]:
        if column not in columns:
            failures.append(f"{record['gate_id']}: cannot path-check missing column {column}")
            continue
        missing_paths = []
        for row in rows:
            value = row.get(column, "")
            if not value:
                continue
            if not resolve_path(root, value).exists():
                missing_paths.append(value)
        if missing_paths:
            sample = ", ".join(missing_paths[:5])
            suffix = " ..." if len(missing_paths) > 5 else ""
            failures.append(
                f"{record['gate_id']}: {rel} has missing paths in {column}: {sample}{suffix}"
            )
    return failures


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", default=".")
    parser.add_argument(
        "--contract",
        default="experiments_90pt_plan/configs/reproducibility_gate_contract.tsv",
    )
    parser.add_argument("--allow-incomplete", action="store_true")
    parser.add_argument("--report", default="results_90pt/reproducibility_gate_report.md")
    args = parser.parse_args()

    root = Path(args.root)
    failures: list[str] = []
    for record in read_tsv(root / args.contract):
        failures.extend(check_record(root, record))

    report = root / args.report
    report.parent.mkdir(parents=True, exist_ok=True)
    lines = ["# Reproducibility Gate Report", ""]
    if failures:
        lines.append("## Failures")
        lines.extend(f"- {failure}" for failure in failures)
    else:
        lines.append("Reproducibility gate passed.")
    report.write_text("\n".join(lines) + "\n", encoding="utf-8")

    if failures:
        print("Reproducibility gate failed:")
        for failure in failures:
            print(f"- {failure}")
        if not args.allow_incomplete:
            raise SystemExit(1)
    else:
        print("Reproducibility gate passed.")


if __name__ == "__main__":
    main()
