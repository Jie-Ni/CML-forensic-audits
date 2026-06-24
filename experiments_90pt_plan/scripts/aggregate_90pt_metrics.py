#!/usr/bin/env python
"""Aggregate W08 90-point experiment tables without fabricating missing data."""

from __future__ import annotations

import argparse
import csv
import math
from pathlib import Path
from typing import Iterable


TRACE_TABLES = {
    "adaptive_laundering": Path("results_90pt/scored_matrices/adaptive_laundering_trace_scores.parquet"),
    "base_mismatch": Path("results_90pt/scored_matrices/base_mismatch_reference_scores.parquet"),
    "out_of_set": Path("results_90pt/scored_matrices/out_of_set_candidate_scores.parquet"),
    "mtcr_profiles": Path("results_90pt/scored_matrices/mtcr_per_task_profiles.parquet"),
}


def read_table(path: Path):
    if path.suffix.lower() == ".parquet":
        try:
            import pandas as pd
        except ImportError as exc:
            raise SystemExit("pandas/pyarrow are required to read parquet result tables") from exc
        return pd.read_parquet(path)
    if path.suffix.lower() in {".csv", ".tsv"}:
        try:
            import pandas as pd
        except ImportError as exc:
            raise SystemExit("pandas is required to read tabular result tables") from exc
        sep = "\t" if path.suffix.lower() == ".tsv" else ","
        return pd.read_csv(path, sep=sep)
    raise SystemExit(f"Unsupported table extension: {path}")


def auroc(labels: Iterable[int], scores: Iterable[float]) -> float:
    pairs = sorted(zip(scores, labels), key=lambda item: item[0])
    pos = sum(1 for _, label in pairs if int(label) == 1)
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
            if int(pairs[k][1]) == 1:
                rank_sum += avg_rank
        i = j
    return (rank_sum - pos * (pos + 1) / 2.0) / (pos * neg)


def threshold_at_fpr(neg_scores, fpr: float) -> float:
    values = sorted(float(v) for v in neg_scores)
    if not values:
        return math.nan
    index = max(0, min(len(values) - 1, math.ceil((1.0 - fpr) * len(values)) - 1))
    return values[index]


def binary_metrics(frame, score_col: str = "score_cml"):
    rows = []
    group_cols = [c for c in ["experiment", "condition", "dataset"] if c in frame.columns]
    if "label" not in frame.columns or score_col not in frame.columns:
        return rows
    for keys, group in frame.groupby(group_cols, dropna=False):
        if not isinstance(keys, tuple):
            keys = (keys,)
        labels = [int(v) for v in group["label"].tolist()]
        scores = [float(v) for v in group[score_col].tolist()]
        neg_scores = [s for s, y in zip(scores, labels) if y == 0]
        pos_scores = [s for s, y in zip(scores, labels) if y == 1]
        threshold = threshold_at_fpr(neg_scores, 0.01)
        row = dict(zip(group_cols, keys))
        row.update(
            score=score_col,
            n=len(group),
            n_pos=len(pos_scores),
            n_neg=len(neg_scores),
            n_students=group["student_id"].nunique() if "student_id" in group.columns else "",
            auroc=auroc(labels, scores),
            threshold_1pct_fpr=threshold,
            tpr_at_1pct_fpr=sum(1 for s in pos_scores if s >= threshold) / len(pos_scores)
            if pos_scores and not math.isnan(threshold)
            else math.nan,
            empirical_fpr_at_threshold=sum(1 for s in neg_scores if s >= threshold) / len(neg_scores)
            if neg_scores and not math.isnan(threshold)
            else math.nan,
            fpr_zero=sum(1 for s in neg_scores if s >= 0.0) / len(neg_scores) if neg_scores else math.nan,
        )
        rows.append(row)
    return rows


def attribution_metrics(frame):
    required = {"true_teacher", "pred_teacher"}
    if not required.issubset(frame.columns):
        return []
    group_cols = [c for c in ["experiment", "condition", "dataset"] if c in frame.columns]
    rows = []
    for keys, group in frame.groupby(group_cols, dropna=False):
        if not isinstance(keys, tuple):
            keys = (keys,)
        abstained = group["abstained"].astype(bool) if "abstained" in group.columns else [False] * len(group)
        non_abs = group.loc[[not bool(v) for v in abstained]]
        correct = (non_abs["true_teacher"] == non_abs["pred_teacher"]).sum() if len(non_abs) else 0
        false_attr = (non_abs["true_teacher"] != non_abs["pred_teacher"]).sum() if len(non_abs) else 0
        row = dict(zip(group_cols, keys))
        row.update(
            n=len(group),
            n_non_abstained=len(non_abs),
            accuracy_non_abstained=correct / len(non_abs) if len(non_abs) else math.nan,
            abstention_rate=sum(bool(v) for v in abstained) / len(group) if len(group) else math.nan,
            false_attribution_rate=false_attr / len(group) if len(group) else math.nan,
        )
        rows.append(row)
    return rows


def write_rows(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if not rows:
        path.write_text("", encoding="utf-8")
        return
    fields = sorted({key for row in rows for key in row})
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", default=".", help="W08 manuscript root")
    parser.add_argument("--out", default="results_90pt/summaries/aggregate_90pt_metrics.csv")
    args = parser.parse_args()

    root = Path(args.root)
    all_rows = []
    missing = []
    for name, rel_path in TRACE_TABLES.items():
        path = root / rel_path
        if not path.exists():
            missing.append(str(rel_path))
            continue
        frame = read_table(path)
        if "score_cml" in frame.columns:
            all_rows.extend(binary_metrics(frame, "score_cml"))
        if "score_mtcr" in frame.columns:
            all_rows.extend(binary_metrics(frame, "score_mtcr"))
        all_rows.extend(attribution_metrics(frame))

    out_path = root / args.out
    write_rows(out_path, all_rows)
    if missing:
        print("Missing result tables:")
        for item in missing:
            print(f"- {item}")
    print(f"Wrote {len(all_rows)} aggregate rows to {out_path}")


if __name__ == "__main__":
    main()
