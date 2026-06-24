#!/usr/bin/env python
"""Report which W08 90-point claims are currently unlocked by staged evidence."""

from __future__ import annotations

import argparse
import csv
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path


def read_tsv(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle, delimiter="\t"))


def parse_required_values(spec: str) -> dict[str, set[str]]:
    clauses: dict[str, set[str]] = {}
    for clause in spec.split(";"):
        clause = clause.strip()
        if not clause:
            continue
        column, raw = clause.split("=", 1)
        clauses[column.strip()] = {value.strip() for value in raw.split("|") if value.strip()}
    return clauses


def read_profile(path: Path) -> tuple[int, set[str], dict[str, set[str]], str]:
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
        delimiter = "\t" if suffix == ".tsv" else ","
        with path.open("r", encoding="utf-8", newline="") as handle:
            reader = csv.DictReader(handle, delimiter=delimiter)
            rows = list(reader)
        columns = set(reader.fieldnames or [])
        values = {
            column: {row.get(column, "") for row in rows if row.get(column, "") != ""}
            for column in columns
        }
        return len(rows), columns, values, ""
    except Exception as exc:  # pragma: no cover - report generator should not hide bad tables.
        return -1, set(), {}, f"cannot read table: {exc}"


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


def reproducibility_gate_status(root: Path) -> str:
    completed = subprocess.run(
        [
            sys.executable,
            str(root / "experiments_90pt_plan/scripts/validate_reproducibility_gate.py"),
            "--root",
            str(root),
        ],
        cwd=root,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    if completed.returncode == 0:
        return ""
    output = "\n".join(part for part in [completed.stdout.strip(), completed.stderr.strip()] if part)
    first_lines = [line.strip() for line in output.splitlines() if line.strip()][:4]
    detail = "; ".join(first_lines) if first_lines else "validate_reproducibility_gate.py failed"
    return f"full reproducibility gate failed: {detail}"


def evaluate_record(root: Path, record: dict[str, str]) -> dict[str, str]:
    rel_path = record["path"]
    path = root / rel_path
    required_columns = {
        column.strip()
        for column in record.get("required_columns", "").split(",")
        if column.strip()
    }
    min_rows = int(record.get("min_rows") or 0)
    result = {
        "path": rel_path,
        "claim_gate": record.get("claim_gate", ""),
        "status": "blocked",
        "row_count": "",
        "blocking_reason": "",
    }
    if not path.exists():
        result["blocking_reason"] = "missing table"
        return result
    row_count, columns, values, error = read_profile(path)
    result["row_count"] = str(row_count)
    if error:
        result["blocking_reason"] = error
        return result
    blockers = []
    if row_count < min_rows:
        blockers.append(f"rows {row_count} < {min_rows}")
    missing_columns = sorted(required_columns - columns)
    if missing_columns:
        blockers.append("missing columns: " + ", ".join(missing_columns))
    for column, expected in parse_required_values(record.get("required_values", "")).items():
        observed = values.get(column, set())
        missing_values = sorted(expected - observed)
        if missing_values:
            blockers.append(f"missing {column}: " + ", ".join(missing_values))
    if rel_path == "results_90pt/reproducibility/reproducibility_manifest.tsv":
        repro_blocker = reproducibility_gate_status(root)
        if repro_blocker:
            blockers.append(repro_blocker)
    if has_derived_only_provenance(values):
        blockers.append("derived/legacy provenance; real raw/HPC lineage required")
    if blockers:
        result["blocking_reason"] = "; ".join(blockers)
        return result
    result["status"] = "unlocked"
    result["blocking_reason"] = ""
    return result


def write_tsv(path: Path, rows: list[dict[str, str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fields = ["status", "claim_gate", "path", "row_count", "blocking_reason"]
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, delimiter="\t")
        writer.writeheader()
        writer.writerows(rows)


def write_md(path: Path, rows: list[dict[str, str]]) -> None:
    unlocked = [row for row in rows if row["status"] == "unlocked"]
    blocked = [row for row in rows if row["status"] != "unlocked"]
    lines = [
        "# W08 90-Point Claim Readiness",
        "",
        f"Checked at: `{datetime.now(timezone.utc).isoformat(timespec='seconds')}`",
        "",
        f"Unlocked claim gates: **{len(unlocked)} / {len(rows)}**",
        "",
        "## Blocked Claims",
        "",
    ]
    if blocked:
        lines.extend(
            f"- **{row['claim_gate']}**: `{row['path']}` - {row['blocking_reason']}"
            for row in blocked
        )
    else:
        lines.append("No blocked claim gates.")
    lines.extend(["", "## Unlocked Claims", ""])
    if unlocked:
        lines.extend(
            f"- **{row['claim_gate']}**: `{row['path']}` ({row['row_count']} rows)"
            for row in unlocked
        )
    else:
        lines.append("No claim gates are fully unlocked yet.")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", default=".")
    parser.add_argument(
        "--contract",
        default="experiments_90pt_plan/source_tables_expected.tsv",
    )
    parser.add_argument(
        "--tsv-out",
        default="results_90pt/claim_readiness.tsv",
    )
    parser.add_argument(
        "--md-out",
        default="results_90pt/claim_readiness_report.md",
    )
    parser.add_argument("--fail-on-blocked", action="store_true")
    args = parser.parse_args()

    root = Path(args.root)
    records = read_tsv(root / args.contract)
    rows = [evaluate_record(root, record) for record in records]
    write_tsv(root / args.tsv_out, rows)
    write_md(root / args.md_out, rows)

    unlocked_count = sum(1 for row in rows if row["status"] == "unlocked")
    print(f"Claim readiness: {unlocked_count}/{len(rows)} claim gates unlocked")
    print(f"Markdown report: {root / args.md_out}")
    if args.fail_on_blocked and unlocked_count != len(rows):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
