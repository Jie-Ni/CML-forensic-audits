#!/usr/bin/env python
"""Compute student-level CI rows from real per-student summary tables."""

from __future__ import annotations

import argparse
import csv
import math
from pathlib import Path

INPUTS = [
    "results_90pt/summaries/tifs_adaptive_attack_summary.csv",
    "results_90pt/summaries/tifs_open_set_abstention_summary.csv",
    "results_90pt/summaries/tifs_cross_base_task_matrix.csv",
    "results_90pt/summaries/tifs_baseline_head_to_head.csv",
]

METRIC_COLUMNS = [
    "auroc",
    "tpr_at_1pct_fpr",
    "fpr_zero",
    "abstention_rate",
    "false_attribution_rate",
    "closed_set_accuracy",
]


def read_csv(path: Path) -> list[dict[str, str]]:
    if not path.exists() or path.stat().st_size == 0:
        return []
    with path.open("r", encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def write_csv(path: Path, rows: list[dict[str, str]]) -> None:
    fields = [
        "experiment",
        "dataset",
        "student_base",
        "teacher_family",
        "condition",
        "n_students",
        "student_unit",
        "metric",
        "estimate",
        "ci_low",
        "ci_high",
        "permutation_p",
        "threshold_split",
        "heldout_fpr",
        "source_run_id",
    ]
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def as_float(value: str) -> float | None:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    if math.isnan(parsed):
        return None
    return parsed


def mean_ci(values: list[float]) -> tuple[float, float, float]:
    n = len(values)
    mean = sum(values) / n
    if n == 1:
        return mean, mean, mean
    var = sum((value - mean) ** 2 for value in values) / (n - 1)
    se = math.sqrt(var / n)
    return mean, mean - 1.96 * se, mean + 1.96 * se


def grouped_rows(
    rows: list[dict[str, str]], condition: str, dataset: str
) -> list[dict[str, str]]:
    filtered = [
        row
        for row in rows
        if row.get("condition", "") == condition and row.get("dataset", "") == dataset
    ]
    groups: dict[tuple[str, str, str, str], list[dict[str, str]]] = {}
    for row in filtered:
        key = (
            row.get("experiment", ""),
            row.get("student_base", ""),
            row.get("teacher_family", ""),
            row.get("condition", ""),
        )
        groups.setdefault(key, []).append(row)

    out = []
    for (
        experiment,
        student_base,
        teacher_family,
        group_condition,
    ), group in groups.items():
        students = {
            row.get("student_id") or row.get("seed") or f"row-{idx}"
            for idx, row in enumerate(group)
        }
        if len(students) < 5:
            continue
        for metric in METRIC_COLUMNS:
            values = [as_float(row.get(metric, "")) for row in group]
            values = [value for value in values if value is not None]
            if len(values) < 5:
                continue
            estimate, ci_low, ci_high = mean_ci(values)
            permutation_values = [
                as_float(row.get("permutation_p", "")) for row in group
            ]
            permutation_values = [
                value for value in permutation_values if value is not None
            ]
            out.append(
                {
                    "experiment": experiment,
                    "dataset": dataset,
                    "student_base": student_base,
                    "teacher_family": teacher_family,
                    "condition": group_condition,
                    "n_students": str(len(students)),
                    "student_unit": "student_seed",
                    "metric": metric,
                    "estimate": f"{estimate:.6g}",
                    "ci_low": f"{ci_low:.6g}",
                    "ci_high": f"{ci_high:.6g}",
                    "permutation_p": (
                        f"{min(permutation_values):.6g}" if permutation_values else ""
                    ),
                    "threshold_split": group[0].get(
                        "threshold_split", "calibration_controls_to_heldout_controls"
                    ),
                    "heldout_fpr": group[0].get("heldout_fpr", "0.01"),
                    "source_run_id": group[0].get("source_run_id", ""),
                }
            )
    return out


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", default=".")
    parser.add_argument("--condition", required=True)
    parser.add_argument("--dataset", required=True)
    parser.add_argument(
        "--out", default="results_90pt/summaries/tifs_student_level_ci.csv"
    )
    args = parser.parse_args()

    root = Path(args.root)
    all_rows = []
    for rel in INPUTS:
        all_rows.extend(read_csv(root / rel))
    output = grouped_rows(all_rows, args.condition, args.dataset)
    if not output:
        raise SystemExit(
            "No student-level CI rows could be computed; need at least five "
            "student-level rows with real metrics for the requested condition."
        )

    out_path = root / args.out
    existing = read_csv(out_path)
    merged = existing + output
    write_csv(out_path, merged)
    print(f"Wrote {len(output)} student-level CI rows -> {out_path}")


if __name__ == "__main__":
    main()
