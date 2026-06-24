#!/usr/bin/env python
"""Repair short scored JSONL matrices from complete local donor copies.

This script is intentionally conservative. A donor is usable only when it has the
same scored_* group and basename, contains the expected number of rows, has the
same student and candidate_teacher metadata, has no duplicate ids, and exactly
matches the current target on every shared id. With --apply it replaces the short
target with the donor file and writes a backup plus a provenance report.
"""

from __future__ import annotations

import argparse
import csv
import json
import shutil
import subprocess
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


REQUIRED_COLUMNS = {"id", "student", "candidate_teacher", "mean_lp", "sum_lp", "n_assistant_tokens"}
EXPECTED_ROWS = 200


@dataclass
class Matrix:
    path: Path
    rows: list[dict[str, Any]]
    by_id: dict[str, dict[str, Any]]
    duplicate_ids: int
    malformed: int
    columns: set[str]


def load_jsonl(path: Path) -> Matrix:
    rows: list[dict[str, Any]] = []
    by_id: dict[str, dict[str, Any]] = {}
    duplicate_ids = 0
    malformed = 0
    columns: set[str] = set()
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            if not line.strip():
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                malformed += 1
                continue
            rows.append(row)
            columns.update(row.keys())
            row_id = str(row.get("id", ""))
            if row_id in by_id:
                duplicate_ids += 1
            by_id[row_id] = row
    return Matrix(path=path, rows=rows, by_id=by_id, duplicate_ids=duplicate_ids, malformed=malformed, columns=columns)


def first_meta(matrix: Matrix, key: str) -> str:
    for row in matrix.rows:
        value = row.get(key)
        if value is not None:
            return str(value)
    return ""


def compatible(target: Matrix, donor: Matrix) -> tuple[bool, str, str]:
    if donor.malformed:
        return False, "donor_malformed_json", ""
    if donor.duplicate_ids:
        return False, "donor_duplicate_ids", ""
    if len(donor.rows) != EXPECTED_ROWS:
        return False, f"donor_row_count_{len(donor.rows)}", ""
    missing_cols = sorted(REQUIRED_COLUMNS - donor.columns)
    if missing_cols:
        return False, "donor_missing_columns", ",".join(missing_cols)
    if first_meta(target, "student") != first_meta(donor, "student"):
        return False, "student_mismatch", f"{first_meta(target, 'student')} != {first_meta(donor, 'student')}"
    if first_meta(target, "candidate_teacher") != first_meta(donor, "candidate_teacher"):
        return (
            False,
            "candidate_teacher_mismatch",
            f"{first_meta(target, 'candidate_teacher')} != {first_meta(donor, 'candidate_teacher')}",
        )
    missing_ids = sorted(set(donor.by_id) - set(target.by_id))
    if len(target.rows) + len(missing_ids) != EXPECTED_ROWS:
        return False, "target_not_subset_of_donor_ids", f"missing_ids={len(missing_ids)}"
    for row_id, target_row in target.by_id.items():
        donor_row = donor.by_id.get(row_id)
        if donor_row is None:
            return False, "target_id_absent_from_donor", row_id
        if donor_row != target_row:
            return False, "shared_row_value_mismatch", row_id
    return True, "compatible", ",".join(missing_ids)


def scored_group_tail(path: Path) -> Path | None:
    parts = path.parts
    lowered = [part.lower() for part in parts]
    for idx, part in enumerate(lowered):
        if part.startswith("scored_") and idx + 1 < len(parts):
            return Path(*parts[idx:])
    return None


def scan_candidate_paths(search_root: Path, target: Path, current_root: Path) -> list[Path]:
    target_tail = scored_group_tail(target)
    if target_tail is None:
        return []
    rg_paths: list[Path] = []
    try:
        result = subprocess.run(
            ["rg", "--files", str(search_root), "-g", target.name],
            check=False,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
        if result.returncode in {0, 1}:
            rg_paths = [Path(line.strip()) for line in result.stdout.splitlines() if line.strip()]
    except FileNotFoundError:
        rg_paths = []
    source_paths = rg_paths if rg_paths else list(search_root.rglob(target.name))
    candidates: list[Path] = []
    for path in source_paths:
        if not path.is_file():
            continue
        try:
            path.resolve().relative_to(current_root.resolve())
            continue
        except ValueError:
            pass
        if scored_group_tail(path) == target_tail:
            candidates.append(path)
    return sorted(candidates)


def short_targets(root: Path) -> list[Path]:
    targets: list[Path] = []
    for path in sorted((root / "figures" / "source").rglob("*.jsonl")):
        matrix = load_jsonl(path)
        if len(matrix.rows) != EXPECTED_ROWS or matrix.malformed or matrix.duplicate_ids:
            targets.append(path)
    return targets


def write_tsv(path: Path, rows: list[dict[str, Any]], fields: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, delimiter="\t")
        writer.writeheader()
        writer.writerows(rows)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", default=".")
    parser.add_argument("--search-root", default="C:/Users/Jie/Desktop/codex")
    parser.add_argument("--apply", action="store_true")
    parser.add_argument(
        "--report",
        default="results_90pt/scored_matrix_repairs/repair_candidate_report.tsv",
    )
    args = parser.parse_args()

    root = Path(args.root).resolve()
    search_root = Path(args.search_root).resolve()
    report_rows: list[dict[str, Any]] = []
    repair_rows: list[dict[str, Any]] = []
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    backup_dir = root / "results_90pt" / "scored_matrix_repairs" / f"backups_{timestamp}"

    for target_path in short_targets(root):
        target = load_jsonl(target_path)
        target_rel = target_path.relative_to(root).as_posix()
        candidates = scan_candidate_paths(search_root, target_path, root)
        chosen: tuple[Path, str] | None = None
        for donor_path in candidates:
            donor = load_jsonl(donor_path)
            ok, status, detail = compatible(target, donor)
            report_rows.append(
                {
                    "target_path": target_rel,
                    "target_rows": len(target.rows),
                    "donor_path": str(donor_path),
                    "donor_rows": len(donor.rows),
                    "status": status,
                    "detail": detail,
                }
            )
            if ok and chosen is None:
                chosen = (donor_path, detail)
        if args.apply and chosen is not None:
            donor_path, missing_ids = chosen
            backup_path = backup_dir / target_rel
            backup_path.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(target_path, backup_path)
            shutil.copy2(donor_path, target_path)
            repair_rows.append(
                {
                    "target_path": target_rel,
                    "backup_path": str(backup_path),
                    "donor_path": str(donor_path),
                    "target_rows_before": len(target.rows),
                    "target_rows_after": EXPECTED_ROWS,
                    "missing_ids_filled": missing_ids,
                    "repair_status": "replaced_with_verified_complete_donor",
                }
            )
        elif args.apply:
            repair_rows.append(
                {
                    "target_path": target_rel,
                    "backup_path": "",
                    "donor_path": "",
                    "target_rows_before": len(target.rows),
                    "target_rows_after": len(target.rows),
                    "missing_ids_filled": "",
                    "repair_status": "no_compatible_donor",
                }
            )

    report_fields = ["target_path", "target_rows", "donor_path", "donor_rows", "status", "detail"]
    report_path = root / args.report
    write_tsv(report_path, report_rows, report_fields)
    print(f"Wrote donor candidate report with {len(report_rows)} rows -> {report_path}")

    if args.apply:
        repair_path = root / "results_90pt" / "scored_matrix_repairs" / "repair_report.tsv"
        repair_fields = [
            "target_path",
            "backup_path",
            "donor_path",
            "target_rows_before",
            "target_rows_after",
            "missing_ids_filled",
            "repair_status",
        ]
        write_tsv(repair_path, repair_rows, repair_fields)
        print(f"Wrote repair report with {len(repair_rows)} rows -> {repair_path}")
        repaired = sum(1 for row in repair_rows if row["repair_status"] == "replaced_with_verified_complete_donor")
        print(f"Applied {repaired} verified donor repairs.")


if __name__ == "__main__":
    main()
