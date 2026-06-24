#!/usr/bin/env python
"""Validate and merge real rescored rows into short scored JSONL matrices."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import re
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


REQUIRED_PATCH_COLUMNS = {
    "id",
    "student",
    "candidate_teacher",
    "mean_lp",
    "sum_lp",
    "n_assistant_tokens",
}
REPORT_FIELDS = [
    "repair_id",
    "target_path",
    "trace_id",
    "student_id",
    "candidate_teacher",
    "status",
    "message",
]


def read_tsv(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle, delimiter="\t"))


def write_tsv(path: Path, rows: list[dict[str, Any]], fields: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, delimiter="\t")
        writer.writeheader()
        writer.writerows(rows)


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as handle:
        for line_no, line in enumerate(handle, start=1):
            if not line.strip():
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError as exc:
                raise SystemExit(f"{path}:{line_no} is invalid JSONL") from exc
            if not isinstance(row, dict):
                raise SystemExit(f"{path}:{line_no} is not a JSON object")
            rows.append(row)
    return rows


def write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    with path.open("w", encoding="utf-8", newline="\n") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False, sort_keys=False) + "\n")


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def row_key(row: dict[str, Any]) -> tuple[str, str, str]:
    return (
        str(row.get("id", "")),
        str(row.get("student", "")),
        str(row.get("candidate_teacher", "")),
    )


def manifest_key(row: dict[str, str]) -> tuple[str, str, str]:
    return (row["trace_id"], row["student_id"], row["candidate_teacher"])


def natural_id_key(row: dict[str, Any]) -> list[Any]:
    raw_id = str(row.get("id", ""))
    parts: list[Any] = []
    for part in re.split(r"(\d+)", raw_id):
        if part.isdigit():
            parts.append(int(part))
        else:
            parts.append(part)
    return parts


def validate_patch_row(row: dict[str, Any]) -> list[str]:
    failures: list[str] = []
    missing_columns = sorted(REQUIRED_PATCH_COLUMNS - set(row))
    if missing_columns:
        failures.append(f"missing required columns: {', '.join(missing_columns)}")
    for numeric_column in ["mean_lp", "sum_lp"]:
        if numeric_column in row and not isinstance(row[numeric_column], (int, float)):
            failures.append(f"{numeric_column} must be numeric")
    if "n_assistant_tokens" in row:
        value = row["n_assistant_tokens"]
        if not isinstance(value, int) or value <= 0:
            failures.append("n_assistant_tokens must be a positive integer")
    return failures


def update_score_index(root: Path, target_rel: str) -> None:
    index_path = root / "reproducibility_bundle/SCORES/scored_matrix_index.tsv"
    if not index_path.exists():
        return
    rows = read_tsv(index_path)
    fields = list(rows[0].keys()) if rows else []
    changed = False
    target_norm = target_rel.replace("\\", "/")
    for row in rows:
        if row.get("path", "").replace("\\", "/") != target_norm:
            continue
        matrix_path = root / row["path"]
        actual_rows = len(read_jsonl(matrix_path))
        expected_rows = int(row.get("expected_rows") or 0)
        row["actual_rows"] = str(actual_rows)
        row["sha256"] = sha256_file(matrix_path)
        row["validation_status"] = "pass" if actual_rows == expected_rows else "review"
        changed = True
    if changed and fields:
        write_tsv(index_path, rows, fields)


def build_patch_index(patch_rows: list[dict[str, Any]]) -> tuple[dict[tuple[str, str, str], dict[str, Any]], list[str]]:
    patch_index: dict[tuple[str, str, str], dict[str, Any]] = {}
    failures: list[str] = []
    for row in patch_rows:
        key = row_key(row)
        row_failures = validate_patch_row(row)
        if "" in key:
            row_failures.append("id/student/candidate_teacher key fields must be non-empty")
        if key in patch_index:
            row_failures.append(f"duplicate patch key: {key}")
        if row_failures:
            failures.append(f"{key}: {'; '.join(row_failures)}")
            continue
        patch_index[key] = row
    return patch_index, failures


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", default=".")
    parser.add_argument(
        "--manifest",
        default="results_90pt/scored_matrix_repairs/minimal_rescore_manifest.tsv",
    )
    parser.add_argument(
        "--patch-jsonl",
        default="results_90pt/scored_matrix_repairs/incoming/minimal_rescore_rows.jsonl",
    )
    parser.add_argument(
        "--report",
        default="results_90pt/scored_matrix_repairs/minimal_rescore_patch_report.tsv",
    )
    parser.add_argument("--allow-partial", action="store_true")
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()

    root = Path(args.root)
    manifest_path = root / args.manifest
    patch_path = root / args.patch_jsonl
    report_path = root / args.report

    if not manifest_path.exists():
        raise SystemExit(f"Missing manifest: {manifest_path}")
    if not patch_path.exists():
        raise SystemExit(f"Missing patch JSONL: {patch_path}")

    manifest_rows = read_tsv(manifest_path)
    patch_rows = read_jsonl(patch_path)
    patch_index, failures = build_patch_index(patch_rows)
    manifest_keys = {manifest_key(row) for row in manifest_rows}
    patch_keys = set(patch_index)
    extra_keys = sorted(patch_keys - manifest_keys)
    missing_keys = sorted(manifest_keys - patch_keys)

    for key in extra_keys:
        failures.append(f"{key}: patch row is not requested by the manifest")
    if missing_keys and not args.allow_partial:
        for key in missing_keys:
            failures.append(f"{key}: expected patch row is missing")

    report_rows: list[dict[str, Any]] = []
    rows_by_target: dict[str, list[dict[str, Any]]] = {}
    for manifest_row in manifest_rows:
        key = manifest_key(manifest_row)
        target_rel = manifest_row["target_path"]
        target_path = root / target_rel
        patch_row = patch_index.get(key)
        if not target_path.exists():
            failures.append(f"{key}: missing target file {target_rel}")
            report_rows.append(
                {
                    "repair_id": manifest_row["repair_id"],
                    "target_path": target_rel,
                    "trace_id": manifest_row["trace_id"],
                    "student_id": manifest_row["student_id"],
                    "candidate_teacher": manifest_row["candidate_teacher"],
                    "status": "invalid",
                    "message": "target file missing",
                }
            )
            continue
        existing_rows = read_jsonl(target_path)
        existing_ids = {str(row.get("id", "")) for row in existing_rows}
        if manifest_row["trace_id"] in existing_ids:
            failures.append(f"{key}: target already contains trace id")
            report_rows.append(
                {
                    "repair_id": manifest_row["repair_id"],
                    "target_path": target_rel,
                    "trace_id": manifest_row["trace_id"],
                    "student_id": manifest_row["student_id"],
                    "candidate_teacher": manifest_row["candidate_teacher"],
                    "status": "invalid",
                    "message": "target already contains trace id",
                }
            )
            continue
        if patch_row is None:
            status = "missing_allowed" if args.allow_partial else "missing"
            report_rows.append(
                {
                    "repair_id": manifest_row["repair_id"],
                    "target_path": target_rel,
                    "trace_id": manifest_row["trace_id"],
                    "student_id": manifest_row["student_id"],
                    "candidate_teacher": manifest_row["candidate_teacher"],
                    "status": status,
                    "message": "no patch row supplied",
                }
            )
            continue
        rows_by_target.setdefault(target_rel, []).append(patch_row)
        report_rows.append(
            {
                "repair_id": manifest_row["repair_id"],
                "target_path": target_rel,
                "trace_id": manifest_row["trace_id"],
                "student_id": manifest_row["student_id"],
                "candidate_teacher": manifest_row["candidate_teacher"],
                "status": "valid",
                "message": "ready to merge" if not args.apply else "merged",
            }
        )

    if failures:
        write_tsv(report_path, report_rows, REPORT_FIELDS)
        print("Patch validation failed:")
        for failure in failures:
            print(f"- {failure}")
        print(f"Report: {report_path}")
        raise SystemExit(1)

    write_tsv(report_path, report_rows, REPORT_FIELDS)
    if not args.apply:
        print(f"Patch dry-run passed for {sum(len(rows) for rows in rows_by_target.values())} rows.")
        print(f"Report: {report_path}")
        return

    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    backup_root = root / f"results_90pt/scored_matrix_repairs/backups_patch_{timestamp}"
    backup_root.mkdir(parents=True, exist_ok=True)
    touched_targets: list[str] = []

    for target_rel, new_rows in rows_by_target.items():
        target_path = root / target_rel
        backup_path = backup_root / target_rel
        backup_path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(target_path, backup_path)
        merged_rows = read_jsonl(target_path) + new_rows
        merged_rows.sort(key=natural_id_key)
        write_jsonl(target_path, merged_rows)
        update_score_index(root, target_rel)
        touched_targets.append(target_rel)

    print(f"Applied {sum(len(rows) for rows in rows_by_target.values())} patch rows.")
    print(f"Backups: {backup_root}")
    print(f"Updated targets: {', '.join(touched_targets)}")
    print(f"Report: {report_path}")


if __name__ == "__main__":
    main()
