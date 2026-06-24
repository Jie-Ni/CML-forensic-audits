#!/usr/bin/env python
"""Assemble vLLM scored JSONL outputs into W08 90-point result tables.

The assembler is intentionally strict. It writes tables only from real scored JSONL
files and manifest metadata. It does not simulate missing rows or fill in scores.
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
        raise SystemExit("pandas and pyarrow are required for 90-point table assembly") from exc
    return pd


def read_tsv(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        return []
    with path.open("r", encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle, delimiter="\t"))


def load_scored(scored_dir: Path):
    pd = require_pandas()
    rows = []
    for path in sorted(scored_dir.rglob("*.jsonl")):
        with path.open("r", encoding="utf-8") as handle:
            for line_no, line in enumerate(handle, start=1):
                if not line.strip():
                    continue
                try:
                    row = json.loads(line)
                except Exception as exc:
                    raise SystemExit(f"{path}:{line_no} is not valid JSONL") from exc
                row["source_file"] = path.as_posix()
                rows.append(row)
    if not rows:
        raise SystemExit(f"No scored JSONL rows found under {scored_dir}")
    return pd.DataFrame(rows)


def manifest_frame(root: Path, dataset: str):
    pd = require_pandas()
    rows = read_tsv(root / "results_90pt/raw_trace_manifests/raw_trace_inputs.tsv")
    rows = [row for row in rows if row.get("dataset", "").lower() == dataset.lower()]
    if not rows:
        raise SystemExit(f"raw_trace_inputs.tsv has no rows for dataset={dataset}")
    return pd.DataFrame(rows)


def label_to_int(value: str, true_teacher: str = "") -> int | None:
    lowered = str(value or "").strip().lower()
    if lowered in {"1", "positive", "distilled", "suspect", "source"}:
        return 1
    if lowered in {"0", "negative", "control", "human_reference", "human-ref", "ctrlc"}:
        return 0
    if lowered in {"reference", "base_reference", "ctrla", "ctrla_base"}:
        return None
    if true_teacher and true_teacher.lower() not in {"none", "na", "reference"}:
        return 1
    return 0


def auroc(labels, scores) -> float:
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


def append_or_write_table(frame, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        pd = require_pandas()
        old = pd.read_parquet(path)
        frame = pd.concat([old, frame], ignore_index=True)
        frame = frame.drop_duplicates()
    frame.to_parquet(path, index=False)


def write_csv(frame, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    frame.to_csv(path, index=False)


def add_manifest(scored, manifest):
    pd = require_pandas()
    manifest = manifest.copy()
    manifest["student"] = manifest["student_id"]
    merged = scored.merge(manifest, on="student", how="left", suffixes=("", "_manifest"))
    if merged["student_id"].isna().any():
        missing = sorted(set(merged.loc[merged["student_id"].isna(), "student"].astype(str)))
        raise SystemExit("scored rows lack raw_trace_inputs metadata for: " + ", ".join(missing[:20]))
    merged["trace_id"] = merged["id"].astype(str)
    merged["label"] = [
        label_to_int(label, teacher) for label, teacher in zip(merged["label"], merged["true_teacher"])
    ]
    return merged


def compute_cml(frame):
    pd = require_pandas()
    data = frame.copy()
    reference_mask = data["label"].isna() | data["student_id"].astype(str).str.lower().str.startswith("ctrla")
    refs = data.loc[reference_mask, ["trace_id", "candidate_teacher", "mean_lp"]]
    if refs.empty:
        raise SystemExit("No base-reference scored rows found; cannot compute CML")
    refs = refs.groupby(["trace_id", "candidate_teacher"], as_index=False)["mean_lp"].mean()
    refs = refs.rename(columns={"mean_lp": "reference_mean_lp"})
    test = data.loc[~reference_mask].merge(refs, on=["trace_id", "candidate_teacher"], how="left")
    test = test.dropna(subset=["reference_mean_lp"])
    if test.empty:
        raise SystemExit("No scored rows overlap with base-reference rows; cannot compute CML")
    test["score_cml"] = test["mean_lp"] - test["reference_mean_lp"]
    return test


def binary_summary(frame, experiment: str, condition: str, dataset: str):
    pd = require_pandas()
    rows = []
    group_cols = ["student_id", "seed"]
    for keys, group in frame.groupby(group_cols, dropna=False):
        if not isinstance(keys, tuple):
            keys = (keys,)
        labels = [int(v) for v in group["label"].tolist()]
        scores = [float(v) for v in group["score_cml"].tolist()]
        neg_scores = [s for s, y in zip(scores, labels) if y == 0]
        pos_scores = [s for s, y in zip(scores, labels) if y == 1]
        threshold = threshold_at_fpr(neg_scores, 0.01)
        rows.append(
            {
                "experiment": experiment,
                "condition": condition,
                "dataset": dataset,
                "student_id": keys[0],
                "seed": keys[1],
                "auroc": auroc(labels, scores),
                "tpr_at_1pct_fpr": sum(1 for s in pos_scores if s >= threshold) / len(pos_scores)
                if pos_scores and not math.isnan(threshold)
                else math.nan,
                "fpr_zero": sum(1 for s in neg_scores if s >= 0.0) / len(neg_scores)
                if neg_scores
                else math.nan,
            }
        )
    return pd.DataFrame(rows)


def assemble_binary(args, output_path: Path, summary_path: Path | None = None) -> None:
    scored = load_scored(Path(args.scored_dir))
    manifest = manifest_frame(Path(args.root), args.dataset)
    merged = add_manifest(scored, manifest)
    table = compute_cml(merged)
    table["experiment"] = args.experiment
    table["condition"] = args.condition
    table["dataset"] = args.dataset
    if args.reference_model:
        table["reference_model"] = args.reference_model
    keep = [
        "experiment",
        "condition",
        "dataset",
        "student_id",
        "seed",
        "trace_id",
        "label",
        "score_cml",
        "candidate_teacher",
        "true_teacher",
        "reference_model",
        "source_file",
    ]
    keep = [column for column in keep if column in table.columns]
    append_or_write_table(table[keep], output_path)
    if summary_path:
        write_csv(binary_summary(table, args.experiment, args.condition, args.dataset), summary_path)


def assemble_open_set(args) -> None:
    pd = require_pandas()
    scored = load_scored(Path(args.scored_dir))
    manifest = manifest_frame(Path(args.root), args.dataset)
    merged = add_manifest(scored, manifest)
    table = compute_cml(merged)
    grouped = []
    for keys, group in table.groupby(["student_id", "seed", "trace_id"], dropna=False):
        ranked = group.sort_values("score_cml", ascending=False)
        top = ranked.iloc[0]
        second = ranked.iloc[1] if len(ranked) > 1 else None
        margin = float(top["score_cml"] - second["score_cml"]) if second is not None else math.nan
        abstained = bool(math.isnan(margin) or margin < 0.0)
        grouped.append(
            {
                "experiment": args.experiment,
                "condition": args.condition,
                "dataset": args.dataset,
                "student_id": top["student_id"],
                "seed": top["seed"],
                "trace_id": top["trace_id"],
                "true_teacher": top.get("true_teacher", ""),
                "pred_teacher": "" if abstained else top["candidate_teacher"],
                "score_margin": margin,
                "abstained": abstained,
                "score_cml": top["score_cml"],
            }
        )
    out = pd.DataFrame(grouped)
    append_or_write_table(out, Path(args.root) / "results_90pt/scored_matrices/out_of_set_candidate_scores.parquet")
    summary_rows = []
    for keys, group in out.groupby(["student_id", "seed"], dropna=False):
        if not isinstance(keys, tuple):
            keys = (keys,)
        non_abs = group.loc[~group["abstained"]]
        false_attr = (
            (non_abs["true_teacher"] != non_abs["pred_teacher"]).sum() / len(group)
            if len(group)
            else math.nan
        )
        summary_rows.append(
            {
                "experiment": args.experiment,
                "condition": args.condition,
                "dataset": args.dataset,
                "student_id": keys[0],
                "seed": keys[1],
                "abstention_rate": group["abstained"].mean(),
                "false_attribution_rate": false_attr,
                "closed_set_accuracy": (non_abs["true_teacher"] == non_abs["pred_teacher"]).mean()
                if len(non_abs)
                else math.nan,
            }
        )
    write_csv(
        pd.DataFrame(summary_rows),
        Path(args.root) / "results_90pt/summaries/out_of_set_abstention_summary.csv",
    )


def assemble_mtcr(args) -> None:
    pd = require_pandas()
    scored = load_scored(Path(args.scored_dir)) if args.scored_dir else pd.DataFrame()
    if scored.empty:
        raise SystemExit("MTCR assembly requires scored JSONL rows")
    scored["experiment"] = args.experiment
    scored["condition"] = args.condition
    scored["dataset"] = args.dataset
    scored["task_view"] = scored.get("task_view", "unknown_task")
    scored["reference_model"] = args.reference_model or ""
    scored["student_id"] = scored["student"]
    scored["seed"] = ""
    scored["score_mtcr"] = scored["mean_lp"]
    keep = [
        "experiment",
        "condition",
        "task_view",
        "candidate_teacher",
        "reference_model",
        "student_id",
        "seed",
        "score_mtcr",
    ]
    append_or_write_table(
        scored[keep],
        Path(args.root) / "results_90pt/scored_matrices/mtcr_per_task_profiles.parquet",
    )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", default=".")
    parser.add_argument("--experiment", required=True)
    parser.add_argument("--condition", required=True)
    parser.add_argument("--dataset", required=True)
    parser.add_argument("--scored-dir", default="")
    parser.add_argument("--reference-model", default="")
    args = parser.parse_args()

    root = Path(args.root)
    if args.experiment == "adaptive_laundering":
        assemble_binary(
            args,
            root / "results_90pt/scored_matrices/adaptive_laundering_trace_scores.parquet",
            root / "results_90pt/summaries/adaptive_laundering_student_summary.csv",
        )
    elif args.experiment == "base_mismatch":
        assemble_binary(
            args,
            root / "results_90pt/scored_matrices/base_mismatch_reference_scores.parquet",
            root / "results_90pt/summaries/base_mismatch_calibration_summary.csv",
        )
    elif args.experiment == "out_of_set_candidate":
        assemble_open_set(args)
    elif args.experiment == "mtcr_raw_profiles":
        assemble_mtcr(args)
    elif args.experiment == "broader_student_matrix":
        raise SystemExit("broader_student_matrix assembly requires completed trained-student score matrices")
    else:
        raise SystemExit(f"Unsupported experiment assembly: {args.experiment}")


if __name__ == "__main__":
    main()
