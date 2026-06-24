#!/usr/bin/env python
"""Audit impact of short scored JSONL matrices without imputing missing rows."""

from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path
from typing import Any


TRUE_TEACHER = {
    "suspect": "r1-distill-qwen-32b",
    "ctrlInst_qwen": "qwen2.5-14b",
    "ctrlLlama_r1": "r1-distill-llama-8b",
}

SOURCE_CANDIDATES = ["r1-distill-qwen-32b", "r1-distill-llama-8b", "qwen2.5-14b"]
EXTENDED_CANDIDATES = [
    "r1-distill-qwen-32b",
    "r1-distill-llama-8b",
    "qwen2.5-14b",
    "qwen2.5-7b",
    "qwen2.5-3b",
    "qwen2.5-1.5b",
]


def require_pandas():
    try:
        import pandas as pd
    except ImportError as exc:
        raise SystemExit("pandas/pyarrow are required for impact audit") from exc
    return pd


def read_tsv(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle, delimiter="\t"))


def write_tsv(path: Path, rows: list[dict[str, Any]], fields: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, delimiter="\t")
        writer.writeheader()
        writer.writerows(rows)


def jsonl_ids(path: Path) -> list[str]:
    ids: list[str] = []
    with path.open("r", encoding="utf-8") as handle:
        for line_no, line in enumerate(handle, start=1):
            if not line.strip():
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError as exc:
                raise SystemExit(f"{path}:{line_no} is invalid JSONL") from exc
            ids.append(str(row.get("id", "")))
    return ids


def prompt_universe(group_dir: Path, expected_rows: int) -> list[str]:
    candidates = []
    for path in sorted(group_dir.glob("*.jsonl")):
        ids = jsonl_ids(path)
        if len(ids) == expected_rows:
            candidates.append(ids)
    if not candidates:
        return sorted({trace_id for path in group_dir.glob("*.jsonl") for trace_id in jsonl_ids(path)})
    universe = set(candidates[0])
    for ids in candidates[1:]:
        universe &= set(ids)
    if len(universe) < expected_rows:
        universe = set().union(*(set(ids) for ids in candidates))
    return sorted(universe, key=lambda value: (len(value), value))


def provenance_type(student: str) -> str:
    import re

    return re.sub(r"_s\d+$", "", student)


def candidate_set(condition: str, true_teacher: str) -> list[str]:
    if condition == "source_teacher_present_closed_set":
        return SOURCE_CANDIDATES
    if condition == "source_teacher_absent":
        return [candidate for candidate in SOURCE_CANDIDATES if candidate != true_teacher]
    if condition == "sibling_teacher_absent":
        if true_teacher == "r1-distill-qwen-32b":
            return [candidate for candidate in SOURCE_CANDIDATES if candidate != "r1-distill-llama-8b"]
        if true_teacher == "r1-distill-llama-8b":
            return [candidate for candidate in SOURCE_CANDIDATES if candidate != "r1-distill-qwen-32b"]
        return SOURCE_CANDIDATES
    if condition == "unrelated_capable_teacher_present":
        return EXTENDED_CANDIDATES
    return []


def open_set_affected_rows(root: Path, student: str, candidate: str, missing_ids: set[str]) -> int:
    path = root / "results_90pt/scored_matrices/out_of_set_candidate_scores.parquet"
    if not path.exists():
        return 0
    pd = require_pandas()
    frame = pd.read_parquet(path)
    subset = frame[(frame["student_id"] == student) & (frame["trace_id"].astype(str).isin(missing_ids))]
    if subset.empty:
        return 0
    ptype = provenance_type(student)
    true_teacher = TRUE_TEACHER.get(ptype, "none")
    affected = 0
    for _, row in subset.iterrows():
        if candidate in candidate_set(str(row["condition"]), true_teacher):
            affected += 1
    return affected


def base_mismatch_missing_output_rows(root: Path, student: str, candidate: str, missing_ids: set[str]) -> int:
    if candidate not in SOURCE_CANDIDATES:
        return 0
    path = root / "results_90pt/scored_matrices/base_mismatch_reference_scores.parquet"
    if not path.exists():
        return 0
    pd = require_pandas()
    frame = pd.read_parquet(path)
    conditions = set(frame["condition"].astype(str).unique())
    present = frame[
        (frame["student_id"] == student)
        & (frame["candidate_teacher"] == candidate)
        & (frame["trace_id"].astype(str).isin(missing_ids))
    ]
    expected = len(missing_ids) * len(conditions)
    return max(0, expected - len(present))


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", default=".")
    parser.add_argument(
        "--score-index",
        default="reproducibility_bundle/SCORES/scored_matrix_index.tsv",
    )
    parser.add_argument(
        "--out",
        default="results_90pt/scored_matrix_repairs/short_row_impact_report.tsv",
    )
    parser.add_argument(
        "--missing-out",
        default="results_90pt/scored_matrix_repairs/short_row_missing_trace_ids.tsv",
    )
    parser.add_argument(
        "--md",
        default="results_90pt/scored_matrix_repairs/short_row_impact_summary.md",
    )
    args = parser.parse_args()

    root = Path(args.root)
    index_rows = read_tsv(root / args.score_index)
    review_rows = [row for row in index_rows if row.get("validation_status") == "review"]

    report_rows: list[dict[str, Any]] = []
    missing_rows: list[dict[str, Any]] = []

    for row in review_rows:
        rel = row["path"]
        path = root / rel
        expected_rows = int(row.get("expected_rows") or 0)
        actual_rows = int(row.get("actual_rows") or 0)
        observed_ids = set(jsonl_ids(path))
        universe = set(prompt_universe(path.parent, expected_rows))
        missing_ids = sorted(universe - observed_ids, key=lambda value: (len(value), value))
        student = row.get("student_id", "")
        candidate = row.get("candidate_teacher", "")
        dataset = row.get("dataset", "")

        affected: list[str] = []
        risk = "source_bundle_completeness"
        if "scored_gsm8k" in rel.replace("\\", "/"):
            affected.append("fig_core_detection_scored_panels_potential")
            base_missing = base_mismatch_missing_output_rows(root, student, candidate, set(missing_ids))
            open_affected = open_set_affected_rows(root, student, candidate, set(missing_ids))
            if base_missing:
                affected.append(f"base_mismatch_missing_output_rows={base_missing}")
            if open_affected:
                affected.append(f"open_set_candidate_decision_rows_potentially_affected={open_affected}")
            risk = "main_gsm8k_reanalysis_potentially_affected"
        elif "scored_math" in rel.replace("\\", "/"):
            affected.append("math_scored_matrix_reproducibility")
            affected.append("current_main_math_metrics_read_from_results_full_math_json")
            risk = "source_bundle_completeness_for_math_reanalysis"

        report_rows.append(
            {
                "path": rel,
                "dataset": dataset,
                "student_id": student,
                "candidate_teacher": candidate,
                "expected_rows": expected_rows,
                "actual_rows": actual_rows,
                "missing_row_count": max(0, expected_rows - actual_rows),
                "missing_trace_ids_found": ",".join(missing_ids),
                "affected_outputs": ";".join(affected),
                "risk_class": risk,
                "resolution": "retrieve_complete_matrix_or_rerun_scoring_no_imputation_applied",
            }
        )
        for trace_id in missing_ids:
            missing_rows.append(
                {
                    "path": rel,
                    "dataset": dataset,
                    "student_id": student,
                    "candidate_teacher": candidate,
                    "missing_trace_id": trace_id,
                }
            )

    fields = [
        "path",
        "dataset",
        "student_id",
        "candidate_teacher",
        "expected_rows",
        "actual_rows",
        "missing_row_count",
        "missing_trace_ids_found",
        "affected_outputs",
        "risk_class",
        "resolution",
    ]
    write_tsv(root / args.out, report_rows, fields)
    write_tsv(
        root / args.missing_out,
        missing_rows,
        ["path", "dataset", "student_id", "candidate_teacher", "missing_trace_id"],
    )

    total_missing = sum(int(row["missing_row_count"]) for row in report_rows)
    gsm8k_missing = sum(
        int(row["missing_row_count"]) for row in report_rows if row["dataset"] == "GSM8K"
    )
    math_missing = sum(
        int(row["missing_row_count"]) for row in report_rows if row["dataset"] == "MATH"
    )
    lines = [
        "# Short Scored-Matrix Impact Summary",
        "",
        f"Reviewed short matrices: **{len(report_rows)}**.",
        f"Missing scored rows: **{total_missing}** total "
        f"({gsm8k_missing} GSM8K, {math_missing} MATH).",
        "",
        "No missing rows were imputed and no scored JSONL file was modified.",
        "",
        "## Interpretation",
        "",
        "- The two GSM8K short files belong to `ctrlLlama_r1_s1` under the two R1 candidate teachers. They can affect scored-matrix-derived GSM8K diagnostics, including the core scored panels and local open-set/base-mismatch reanalyses.",
        "- The two MATH short files belong to `suspect` under the two R1 candidate teachers. The current main MATH stress-test text and Figure 2 slope panel read from `results_full_math.json`, but these JSONL files are still incomplete source matrices for any review-time reanalysis.",
        "- Because no compatible complete local donor was found, the only clean resolution is to retrieve the complete original matrices or rerun the corresponding scoring jobs.",
        "",
        "## Gate Consequence",
        "",
        "The review-time reproducibility gate should remain failed while these rows are unresolved. This report documents impact; it is not a pass condition.",
    ]
    (root / args.md).parent.mkdir(parents=True, exist_ok=True)
    (root / args.md).write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"Wrote {len(report_rows)} short-matrix impact rows -> {root / args.out}")
    print(f"Wrote {len(missing_rows)} missing-trace rows -> {root / args.missing_out}")
    print(f"Wrote summary -> {root / args.md}")


if __name__ == "__main__":
    main()
