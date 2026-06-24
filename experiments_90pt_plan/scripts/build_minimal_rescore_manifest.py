#!/usr/bin/env python
"""Build the minimal rescoring manifest for unresolved short scored matrices."""

from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path
from typing import Any


REQUIRED_PATCH_COLUMNS = ["id", "student", "candidate_teacher", "mean_lp", "sum_lp", "n_assistant_tokens"]


def read_tsv(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle, delimiter="\t"))


def write_tsv(path: Path, rows: list[dict[str, Any]], fields: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, delimiter="\t")
        writer.writeheader()
        writer.writerows(rows)


def jsonl_rows(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    if not path.exists():
        return rows
    with path.open("r", encoding="utf-8") as handle:
        for line_no, line in enumerate(handle, start=1):
            if not line.strip():
                continue
            try:
                rows.append(json.loads(line))
            except json.JSONDecodeError as exc:
                raise SystemExit(f"{path}:{line_no} is invalid JSONL") from exc
    return rows


def find_neighbor_scores(root: Path, target_rel: str, student: str, trace_id: str) -> str:
    target = root / target_rel
    group_dir = target.parent
    neighbors = []
    for path in sorted(group_dir.glob("*.jsonl")):
        for row in jsonl_rows(path):
            if str(row.get("id")) == trace_id and str(row.get("student")) == student:
                neighbors.append(path.relative_to(root).as_posix())
                break
    return "|".join(neighbors)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", default=".")
    parser.add_argument(
        "--missing",
        default="results_90pt/scored_matrix_repairs/short_row_missing_trace_ids.tsv",
    )
    parser.add_argument(
        "--out",
        default="results_90pt/scored_matrix_repairs/minimal_rescore_manifest.tsv",
    )
    parser.add_argument(
        "--md",
        default="results_90pt/scored_matrix_repairs/minimal_rescore_manifest.md",
    )
    args = parser.parse_args()

    root = Path(args.root)
    missing_rows = read_tsv(root / args.missing)
    patch_path = "results_90pt/scored_matrix_repairs/incoming/minimal_rescore_rows.jsonl"
    output_rows = []

    for index, row in enumerate(missing_rows, start=1):
        target_rel = row["path"]
        student = row["student_id"]
        candidate = row["candidate_teacher"]
        trace_id = row["missing_trace_id"]
        repair_id = f"score_patch_{index:03d}_{row['dataset'].lower()}_{student}__{candidate}__{trace_id}"
        output_rows.append(
            {
                "repair_id": repair_id,
                "dataset": row["dataset"],
                "target_path": target_rel,
                "student_id": student,
                "candidate_teacher": candidate,
                "trace_id": trace_id,
                "required_action": "rescore_trace_under_candidate_teacher",
                "required_patch_columns": ",".join(REQUIRED_PATCH_COLUMNS),
                "expected_patch_jsonl": patch_path,
                "raw_trace_status": "not_staged_locally",
                "candidate_model_status": "model_revision_not_staged_locally",
                "neighbor_score_paths": find_neighbor_scores(root, target_rel, student, trace_id),
                "validation_rule": "patch_row_must_match_id_student_candidate_and_complete_required_columns",
            }
        )

    fields = [
        "repair_id",
        "dataset",
        "target_path",
        "student_id",
        "candidate_teacher",
        "trace_id",
        "required_action",
        "required_patch_columns",
        "expected_patch_jsonl",
        "raw_trace_status",
        "candidate_model_status",
        "neighbor_score_paths",
        "validation_rule",
    ]
    write_tsv(root / args.out, output_rows, fields)

    lines = [
        "# Minimal Rescore Manifest",
        "",
        f"Rows to rescore: **{len(output_rows)}**.",
        "",
        "The current local package does not contain the raw trace text or candidate-model",
        "revision metadata needed to score these rows locally. This manifest narrows the",
        "remaining scored-matrix repair from broad reruns to the exact trace/candidate",
        "pairs that must be recovered from the original machine or rerun on an approved",
        "HPC environment.",
        "",
        "Expected patch file:",
        "",
        f"- `{patch_path}`",
        "",
        "Each patch row must be JSONL with columns: `id`, `student`,",
        "`candidate_teacher`, `mean_lp`, `sum_lp`, and `n_assistant_tokens`.",
        "",
        "After the patch file exists, run the merge script in dry-run mode first:",
        "",
        "```powershell",
        "python experiments_90pt_plan/scripts/apply_scored_jsonl_patch.py --root . --patch-jsonl results_90pt/scored_matrix_repairs/incoming/minimal_rescore_rows.jsonl",
        "```",
        "",
        "Only if the dry run reports all expected rows valid, run the same command with",
        "`--apply`.",
    ]
    (root / args.md).write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"Wrote {len(output_rows)} minimal rescore rows -> {root / args.out}")
    print(f"Wrote summary -> {root / args.md}")


if __name__ == "__main__":
    main()
