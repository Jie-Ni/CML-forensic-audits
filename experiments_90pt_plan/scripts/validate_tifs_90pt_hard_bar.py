#!/usr/bin/env python
"""Validate the TIFS hard-bar evidence contract for the W08 90-point target."""

from __future__ import annotations

import argparse
import csv
import json
from datetime import datetime, timezone
from pathlib import Path


def read_tsv(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle, delimiter="\t"))


def read_table_profile(path: Path) -> tuple[int, set[str], dict[str, set[str]], str]:
    suffix = path.suffix.lower()
    try:
        if suffix == ".parquet":
            import pandas as pd

            frame = pd.read_parquet(path)
            values = {
                column: {str(value) for value in frame[column].dropna().unique()}
                for column in frame.columns
            }
            return len(frame), set(frame.columns), values, ""
        if suffix in {".csv", ".tsv"}:
            delimiter = "\t" if suffix == ".tsv" else ","
            with path.open("r", encoding="utf-8", newline="") as handle:
                reader = csv.DictReader(handle, delimiter=delimiter)
                rows = list(reader)
            columns = set(reader.fieldnames or [])
            values = {
                column: {
                    row.get(column, "") for row in rows if row.get(column, "") != ""
                }
                for column in columns
            }
            return len(rows), columns, values, ""
    except Exception as exc:  # pragma: no cover - reporting path.
        return -1, set(), {}, f"cannot read table: {exc}"
    return -1, set(), {}, f"unsupported artifact type: {path.suffix}"


def parse_value_spec(spec: str) -> dict[str, set[str]]:
    parsed: dict[str, set[str]] = {}
    for clause in spec.split(";"):
        clause = clause.strip()
        if not clause:
            continue
        if "=" not in clause:
            raise SystemExit(f"Malformed value spec clause: {clause}")
        column, raw = clause.split("=", 1)
        parsed[column.strip()] = {
            value.strip() for value in raw.split("|") if value.strip()
        }
    return parsed


def has_forbidden_values(values: dict[str, set[str]], spec: str) -> list[str]:
    blockers = []
    for column, forbidden in parse_value_spec(spec).items():
        observed = values.get(column, set())
        observed_lower = [value.lower() for value in observed]
        for forbidden_value in forbidden:
            needle = forbidden_value.lower()
            if any(needle in value for value in observed_lower):
                blockers.append(
                    f"{column} contains forbidden marker: {forbidden_value}"
                )
    return blockers


def missing_required_values(values: dict[str, set[str]], spec: str) -> list[str]:
    blockers = []
    for column, expected in parse_value_spec(spec).items():
        observed = values.get(column, set())
        if column == "n_students" and len(expected) == 1:
            threshold = int(next(iter(expected)))
            numeric_values = []
            for value in observed:
                try:
                    numeric_values.append(int(float(value)))
                except ValueError:
                    blockers.append(f"{column} has non-numeric value: {value}")
            if numeric_values and min(numeric_values) < threshold:
                blockers.append(f"{column} minimum {min(numeric_values)} < {threshold}")
            if not numeric_values:
                blockers.append(f"{column} has no numeric values")
            continue
        missing = sorted(expected - observed)
        if missing:
            blockers.append(f"missing {column}: " + ", ".join(missing))
    return blockers


def evaluate_record(root: Path, record: dict[str, str]) -> dict[str, str]:
    rel = record["path"]
    path = root / rel
    result = {
        "gate_id": record["gate_id"],
        "pillar": record["pillar"],
        "path": rel,
        "status": "blocked",
        "row_count": "",
        "blocking_reason": "",
        "message": record.get("message", ""),
    }
    if not path.exists():
        result["blocking_reason"] = "missing artifact"
        return result
    if record["kind"] == "file":
        if path.stat().st_size < int(record.get("min_rows") or 1):
            result["blocking_reason"] = "file is empty"
            return result
        text = path.read_text(encoding="utf-8", errors="replace").lower()
        required_terms = ["teacher owner", "suspect deployer", "verifier", "abstain"]
        missing_terms = [term for term in required_terms if term not in text]
        if missing_terms:
            result["blocking_reason"] = "missing threat-model terms: " + ", ".join(
                missing_terms
            )
            return result
        result["status"] = "unlocked"
        result["row_count"] = "file"
        return result

    row_count, columns, values, error = read_table_profile(path)
    result["row_count"] = str(row_count)
    if error:
        result["blocking_reason"] = error
        return result

    blockers = []
    min_rows = int(record.get("min_rows") or 0)
    if row_count < min_rows:
        blockers.append(f"rows {row_count} < {min_rows}")
    required_columns = {
        column.strip()
        for column in record.get("required_columns", "").split(",")
        if column.strip()
    }
    missing_columns = sorted(required_columns - columns)
    if missing_columns:
        blockers.append("missing columns: " + ", ".join(missing_columns))
    blockers.extend(missing_required_values(values, record.get("required_values", "")))
    blockers.extend(has_forbidden_values(values, record.get("forbid_values", "")))

    if blockers:
        result["blocking_reason"] = "; ".join(blockers)
        return result
    result["status"] = "unlocked"
    return result


def write_reports(
    root: Path, rows: list[dict[str, str]], json_out: Path, md_out: Path
) -> None:
    unlocked = [row for row in rows if row["status"] == "unlocked"]
    payload = {
        "checked_at": datetime.now(timezone.utc).isoformat(),
        "root": str(root),
        "passed": len(unlocked) == len(rows),
        "unlocked": len(unlocked),
        "total": len(rows),
        "rows": rows,
    }
    json_out.parent.mkdir(parents=True, exist_ok=True)
    json_out.write_text(json.dumps(payload, indent=2), encoding="utf-8")

    lines = [
        "# W08 TIFS 90-Point Hard-Bar Gate",
        "",
        f"Checked at: `{payload['checked_at']}`",
        "",
        f"Verdict: **{'PASS' if payload['passed'] else 'FAIL'}**",
        "",
        f"Unlocked: **{payload['unlocked']} / {payload['total']}**",
        "",
        "## Blocked",
        "",
    ]
    blocked = [row for row in rows if row["status"] != "unlocked"]
    if blocked:
        for row in blocked:
            lines.append(
                f"- **{row['gate_id']}** ({row['pillar']}): `{row['path']}` - {row['blocking_reason']}"
            )
    else:
        lines.append("No blocked hard-bar gates.")
    lines.extend(["", "## Unlocked", ""])
    if unlocked:
        for row in unlocked:
            lines.append(f"- **{row['gate_id']}** ({row['pillar']}): `{row['path']}`")
    else:
        lines.append("No hard-bar gates unlocked yet.")
    md_out.parent.mkdir(parents=True, exist_ok=True)
    md_out.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", default=".")
    parser.add_argument(
        "--contract",
        default="experiments_90pt_plan/configs/tifs_90pt_hard_bar_outputs.tsv",
    )
    parser.add_argument(
        "--json-out", default="results_90pt/tifs_90pt_hard_bar_report.json"
    )
    parser.add_argument("--md-out", default="results_90pt/tifs_90pt_hard_bar_report.md")
    parser.add_argument("--allow-incomplete", action="store_true")
    args = parser.parse_args()

    root = Path(args.root).resolve()
    records = read_tsv(root / args.contract)
    rows = [evaluate_record(root, record) for record in records]
    write_reports(root, rows, root / args.json_out, root / args.md_out)
    unlocked = sum(1 for row in rows if row["status"] == "unlocked")
    print(f"TIFS 90-point hard-bar: {unlocked}/{len(rows)} gates unlocked")
    print(f"Markdown report: {root / args.md_out}")
    if unlocked != len(rows) and not args.allow_incomplete:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
