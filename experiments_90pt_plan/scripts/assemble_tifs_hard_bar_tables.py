#!/usr/bin/env python
"""Assemble fully scored rows into TIFS hard-bar output tables.

This assembler expects upstream scoring to provide real per-trace score columns. It
does not impute CML, MTCR, baseline scores, confidence intervals, or missing labels.
"""

from __future__ import annotations

import argparse
import csv
import json
import math
from pathlib import Path


def require_pandas():
    try:
        import pandas as pd
    except ImportError as exc:
        raise SystemExit(
            "pandas and pyarrow are required for TIFS table assembly"
        ) from exc
    return pd


def read_jsonl_dir(path: Path):
    pd = require_pandas()
    rows = []
    for item in sorted(path.rglob("*.jsonl")):
        with item.open("r", encoding="utf-8") as handle:
            for line_no, line in enumerate(handle, start=1):
                if not line.strip():
                    continue
                try:
                    row = json.loads(line)
                except json.JSONDecodeError as exc:
                    raise SystemExit(f"{item}:{line_no} is not valid JSONL") from exc
                row["source_file"] = item.as_posix()
                rows.append(row)
    if not rows:
        raise SystemExit(f"No scored JSONL rows found under {path}")
    return pd.DataFrame(rows)


def read_tsv(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        return []
    with path.open("r", encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle, delimiter="\t"))


def append_csv(frame, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists() and path.stat().st_size:
        pd = require_pandas()
        existing = pd.read_csv(path)
        frame = pd.concat([existing, frame], ignore_index=True).drop_duplicates()
    frame.to_csv(path, index=False)


def append_parquet(frame, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        pd = require_pandas()
        existing = pd.read_parquet(path)
        frame = pd.concat([existing, frame], ignore_index=True).drop_duplicates()
    frame.to_parquet(path, index=False)


def require_columns(frame, columns: list[str], context: str) -> None:
    missing = [column for column in columns if column not in frame.columns]
    if missing:
        raise SystemExit(f"{context} missing required columns: {', '.join(missing)}")
    empty = []
    for column in columns:
        values = frame[column].astype(str).str.strip()
        if values.eq("").any() or values.eq("nan").any():
            empty.append(column)
    if empty:
        raise SystemExit(
            f"{context} contains empty required columns: {', '.join(empty)}"
        )


def auroc(labels: list[int], scores: list[float]) -> float:
    pairs = sorted(zip(scores, labels), key=lambda item: item[0])
    pos = sum(1 for _, label in pairs if label == 1)
    neg = len(pairs) - pos
    if pos == 0 or neg == 0:
        return math.nan
    rank_sum = 0.0
    i = 0
    while i < len(pairs):
        j = i + 1
        while j < len(pairs) and pairs[j][0] == pairs[i][0]:
            j += 1
        avg_rank = (i + 1 + j) / 2.0
        for k in range(i, j):
            if pairs[k][1] == 1:
                rank_sum += avg_rank
        i = j
    return (rank_sum - pos * (pos + 1) / 2.0) / (pos * neg)


def threshold_at_fpr(neg_scores: list[float], fpr: float) -> float:
    if not neg_scores:
        return math.nan
    values = sorted(neg_scores)
    index = max(0, min(len(values) - 1, math.ceil((1.0 - fpr) * len(values)) - 1))
    return values[index]


def normalize_scored(frame, run_id: str, args):
    pd = require_pandas()
    required = [
        "student_id",
        "seed",
        "trace_id",
        "label",
        "score_cml",
        "score_mtcr",
        "score_baseline",
    ]
    aliases = {
        "student": "student_id",
        "id": "trace_id",
        "mean_lp": "score_baseline",
    }
    frame = frame.rename(
        columns={old: new for old, new in aliases.items() if old in frame.columns}
    )
    require_columns(frame, required, "scored rows")
    out = frame.copy()
    out["experiment"] = args.experiment
    out["dataset"] = args.dataset
    out["student_base"] = args.student_base or ""
    out["teacher_family"] = args.teacher_family or ""
    out["source_run_id"] = run_id
    return out


def adaptive_attack(args) -> None:
    pd = require_pandas()
    scored = normalize_scored(read_jsonl_dir(Path(args.scored_dir)), args.run_id, args)
    scored["attack_type"] = args.condition
    scored["attack_strength"] = args.attack_strength or args.condition
    scored["threshold_source"] = args.threshold_source
    keep = [
        "experiment",
        "attack_type",
        "attack_strength",
        "dataset",
        "student_base",
        "teacher_family",
        "student_id",
        "seed",
        "trace_id",
        "label",
        "score_cml",
        "score_mtcr",
        "score_baseline",
        "threshold_source",
        "source_run_id",
    ]
    append_parquet(
        scored[keep],
        Path(args.root)
        / "results_90pt/scored_matrices/tifs_adaptive_attack_trace_scores.parquet",
    )
    summary = summarize_binary(
        scored,
        [
            "experiment",
            "attack_type",
            "attack_strength",
            "dataset",
            "student_base",
            "teacher_family",
            "seed",
        ],
    )
    append_csv(
        summary,
        Path(args.root) / "results_90pt/summaries/tifs_adaptive_attack_summary.csv",
    )


def open_set(args) -> None:
    scored = normalize_scored(read_jsonl_dir(Path(args.scored_dir)), args.run_id, args)
    required = [
        "true_teacher",
        "candidate_set",
        "pred_teacher",
        "abstained",
        "auroc",
        "tpr_at_1pct_fpr",
    ]
    require_columns(scored, required, "open-set scored rows")
    grouped = []
    for keys, group in scored.groupby(["student_id", "seed"], dropna=False):
        if not isinstance(keys, tuple):
            keys = (keys,)
        abstained = (
            group["abstained"].astype(str).str.lower().isin({"1", "true", "yes"})
        )
        non_abs = group.loc[~abstained]
        false_attr = (
            (non_abs["true_teacher"] != non_abs["pred_teacher"]).sum() / len(group)
            if len(group)
            else float("nan")
        )
        grouped.append(
            {
                "experiment": args.experiment,
                "condition": args.condition,
                "dataset": args.dataset,
                "student_base": args.student_base or "",
                "true_teacher": group["true_teacher"].iloc[0],
                "candidate_set": group["candidate_set"].iloc[0],
                "pred_teacher": (
                    non_abs["pred_teacher"].mode().iloc[0]
                    if len(non_abs)
                    else "ABSTAIN"
                ),
                "abstention_rate": abstained.mean(),
                "false_attribution_rate": false_attr,
                "closed_set_accuracy": (
                    (non_abs["true_teacher"] == non_abs["pred_teacher"]).mean()
                    if len(non_abs)
                    else float("nan")
                ),
                "coverage": 1.0 - abstained.mean(),
                "auroc": group["auroc"].astype(float).mean(),
                "tpr_at_1pct_fpr": group["tpr_at_1pct_fpr"].astype(float).mean(),
                "source_run_id": args.run_id,
            }
        )
    pd = require_pandas()
    append_csv(
        pd.DataFrame(grouped),
        Path(args.root) / "results_90pt/summaries/tifs_open_set_abstention_summary.csv",
    )


def summarize_binary(frame, group_cols: list[str]):
    pd = require_pandas()
    if "ci_low" not in frame.columns or "ci_high" not in frame.columns:
        raise SystemExit(
            "student-level uncertainty columns ci_low/ci_high are required; "
            "this assembler will not invent confidence intervals from point estimates"
        )
    rows = []
    for keys, group in frame.groupby(group_cols, dropna=False):
        if not isinstance(keys, tuple):
            keys = (keys,)
        labels = group["label"].astype(int).tolist()
        scores = group["score_cml"].astype(float).tolist()
        pos = [score for score, label in zip(scores, labels) if label == 1]
        neg = [score for score, label in zip(scores, labels) if label == 0]
        threshold = threshold_at_fpr(neg, 0.01)
        row = dict(zip(group_cols, keys))
        row.update(
            auroc=auroc(labels, scores),
            tpr_at_1pct_fpr=(
                sum(score >= threshold for score in pos) / len(pos)
                if pos and neg
                else float("nan")
            ),
            fpr_zero=(
                sum(score >= 0 for score in neg) / len(neg) if neg else float("nan")
            ),
            ci_low=group["ci_low"].astype(float).min(),
            ci_high=group["ci_high"].astype(float).max(),
            n_students=group["student_id"].nunique(),
            threshold_source=(
                frame["threshold_source"].iloc[0]
                if "threshold_source" in frame.columns
                else ""
            ),
            source_run_id=(
                frame["source_run_id"].iloc[0]
                if "source_run_id" in frame.columns
                else ""
            ),
        )
        rows.append(row)
    return pd.DataFrame(rows)


def cross_base_task(args) -> None:
    path = Path(args.root) / "results_90pt/summaries/cross_base_student_matrix.csv"
    if not path.exists():
        raise SystemExit(
            "cross_base_task assembly requires externally staged cross_base_student_matrix.csv"
        )
    pd = require_pandas()
    frame = pd.read_csv(path)
    required = [
        "experiment",
        "dataset",
        "student_base",
        "teacher_family",
        "teacher_model",
        "student_training",
        "seed",
        "auroc",
        "tpr_at_1pct_fpr",
        "fpr_zero",
        "ci_low",
        "ci_high",
        "n_students",
        "source_run_id",
    ]
    require_columns(frame, required, "cross-base summary")
    append_csv(
        frame[required],
        Path(args.root) / "results_90pt/summaries/tifs_cross_base_task_matrix.csv",
    )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", default=".")
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--experiment", required=True)
    parser.add_argument("--condition", required=True)
    parser.add_argument("--dataset", required=True)
    parser.add_argument("--scored-dir", default="")
    parser.add_argument("--student-base", default="")
    parser.add_argument("--teacher-family", default="")
    parser.add_argument("--attack-strength", default="")
    parser.add_argument(
        "--threshold-source", default="calibration_controls_to_heldout_controls"
    )
    args = parser.parse_args()

    if args.experiment == "adaptive_attack":
        adaptive_attack(args)
    elif args.experiment == "open_set":
        open_set(args)
    elif args.experiment == "cross_base_task":
        cross_base_task(args)
    else:
        raise SystemExit(f"Unsupported TIFS hard-bar assembly: {args.experiment}")


if __name__ == "__main__":
    main()
