#!/usr/bin/env python
"""Derive the locally supportable base-mismatch checks from scored matrices.

This script is a reanalysis of existing scored likelihood rows. It does not create
neighboring-base or different-family evidence, because those require real reference
traces from the corresponding base models.
"""

from __future__ import annotations

import argparse
import json
import math
import re
from pathlib import Path


TEACHER_BY_TYPE = {
    "suspect": "r1-distill-qwen-32b",
    "ctrlInst_qwen": "qwen2.5-14b",
    "ctrlLlama_r1": "r1-distill-llama-8b",
}

SOURCE_CANDIDATES = ["r1-distill-qwen-32b", "r1-distill-llama-8b", "qwen2.5-14b"]

REFERENCE_POLICY = {
    "correct_base_reference": {
        "reference_model": "qwen2.5-7b",
        "reference_prefix": "ctrlA_base",
        "note": "same-base reference rows derived from existing ctrlA scored outputs",
    },
    "no_runnable_base_fallback": {
        "reference_model": "human_reference_fallback",
        "reference_prefix": "ctrlC_ref",
        "note": "fallback reference rows derived from existing ctrlC human-reference outputs",
    },
}


def require_pandas():
    try:
        import pandas as pd
    except ImportError as exc:
        raise SystemExit("pandas and pyarrow are required for base-mismatch derivation") from exc
    return pd


def provenance_type(student: str) -> str:
    return re.sub(r"_s\d+$", "", student)


def seed_of(student: str) -> str:
    match = re.search(r"_s(\d+)$", student)
    return match.group(1) if match else "0"


def reference_student(prefix: str, seed: str) -> str:
    return prefix if seed == "0" else f"{prefix}_s{seed}"


def load_scored(scored_dir: Path):
    pd = require_pandas()
    rows = []
    for path in sorted(scored_dir.glob("*.jsonl")):
        with path.open("r", encoding="utf-8") as handle:
            for line_no, line in enumerate(handle, start=1):
                if not line.strip():
                    continue
                try:
                    row = json.loads(line)
                except json.JSONDecodeError as exc:
                    raise SystemExit(f"{path}:{line_no} is not valid JSONL") from exc
                row["source_file"] = path.relative_to(scored_dir).as_posix()
                rows.append(row)
    if not rows:
        raise SystemExit(f"No scored JSONL files found under {scored_dir}")
    frame = pd.DataFrame(rows)
    frame["ptype"] = frame["student"].map(provenance_type)
    frame["seed"] = frame["student"].map(seed_of)
    return frame


def add_reference_scores(frame, condition: str):
    policy = REFERENCE_POLICY[condition]
    candidates = SOURCE_CANDIDATES
    refs = frame[
        (frame["ptype"] == policy["reference_prefix"])
        & (frame["candidate_teacher"].isin(candidates))
    ].copy()
    refs = refs.rename(columns={"mean_lp": "reference_mean_lp", "student": "reference_student"})
    refs = refs[["reference_student", "candidate_teacher", "id", "reference_mean_lp"]]

    data = frame[frame["candidate_teacher"].isin(candidates)].copy()
    data["reference_student"] = data["seed"].map(
        lambda seed: reference_student(policy["reference_prefix"], str(seed))
    )
    merged = data.merge(refs, on=["reference_student", "candidate_teacher", "id"], how="left")
    missing = merged["reference_mean_lp"].isna()
    if missing.any():
        sample = merged.loc[
            missing, ["student", "reference_student", "candidate_teacher", "id"]
        ].head(12)
        raise SystemExit(
            f"Missing reference rows for {condition}:\n" + sample.to_string(index=False)
        )
    merged["score_cml"] = merged["mean_lp"] - merged["reference_mean_lp"]
    merged["condition"] = condition
    merged["reference_model"] = policy["reference_model"]
    merged["reference_policy"] = policy["note"]
    return merged


def auroc(pos, neg) -> float:
    values = [(float(x), 1) for x in pos] + [(float(x), 0) for x in neg]
    if not pos or not neg:
        return math.nan
    values.sort(key=lambda item: item[0])
    ranks = {}
    i = 0
    while i < len(values):
        j = i
        while j + 1 < len(values) and values[j + 1][0] == values[i][0]:
            j += 1
        rank = (i + 1 + j + 1) / 2
        for k in range(i, j + 1):
            ranks[k] = rank
        i = j + 1
    pos_rank_sum = sum(ranks[index] for index, (_, label) in enumerate(values) if label == 1)
    return (pos_rank_sum - len(pos) * (len(pos) + 1) / 2) / (len(pos) * len(neg))


def tpr_at_fpr(pos, neg, fpr: float = 0.01) -> float:
    if not pos or not neg:
        return math.nan
    threshold = sorted(float(x) for x in neg)[max(0, math.ceil((1 - fpr) * len(neg)) - 1)]
    return sum(float(x) >= threshold for x in pos) / len(pos)


def fpr_zero(neg) -> float:
    if not neg:
        return math.nan
    return sum(float(x) >= 0 for x in neg) / len(neg)


def build_trace_scores(frame, dataset: str):
    pd = require_pandas()
    outputs = []
    for condition in REFERENCE_POLICY:
        reference_prefix = REFERENCE_POLICY[condition]["reference_prefix"]
        derived = add_reference_scores(frame, condition)
        for _, row in derived.iterrows():
            ptype = row["ptype"]
            if ptype == reference_prefix:
                continue
            if ptype in TEACHER_BY_TYPE:
                label = 1
                true_teacher = TEACHER_BY_TYPE[ptype]
            else:
                label = 0
                true_teacher = "none"
            outputs.append(
                {
                    "experiment": "base_mismatch",
                    "condition": condition,
                    "dataset": dataset,
                    "student_id": row["student"],
                    "seed": str(row["seed"]),
                    "trace_id": row["id"],
                    "label": label,
                    "score_cml": float(row["score_cml"]),
                    "reference_model": row["reference_model"],
                    "candidate_teacher": row["candidate_teacher"],
                    "true_teacher": true_teacher,
                    "reference_student": row["reference_student"],
                    "reference_policy": row["reference_policy"],
                    "provenance_note": "derived_from_existing_scored_matrix_without_new_inference",
                }
            )
    return pd.DataFrame(outputs)


def build_summary(trace_scores):
    rows = []
    group_cols = ["condition", "dataset", "reference_model", "candidate_teacher"]
    for keys, group in trace_scores.groupby(group_cols, dropna=False):
        condition, dataset, reference_model, candidate_teacher = keys
        pos = group[(group["label"] == 1) & (group["true_teacher"] == candidate_teacher)]["score_cml"].tolist()
        neg = group[group["label"] == 0]["score_cml"].tolist()
        rows.append(
            {
                "experiment": "base_mismatch",
                "condition": condition,
                "dataset": dataset,
                "reference_model": reference_model,
                "candidate_teacher": candidate_teacher,
                "auroc": auroc(pos, neg),
                "tpr_at_1pct_fpr": tpr_at_fpr(pos, neg),
                "fpr_zero": fpr_zero(neg),
                "calibration_bias": (
                    float(sum(pos) / len(pos) - sum(neg) / len(neg))
                    if pos and neg
                    else math.nan
                ),
                "n_positive_traces": len(pos),
                "n_negative_traces": len(neg),
                "provenance_note": "derived_from_existing_scored_matrix_without_new_inference",
            }
        )
    pd = require_pandas()
    return pd.DataFrame(rows)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", default=".")
    parser.add_argument("--dataset", default="GSM8K")
    parser.add_argument("--scored-dir", default="figures/source/scored_gsm8k")
    args = parser.parse_args()

    root = Path(args.root)
    frame = load_scored(root / args.scored_dir)
    trace_scores = build_trace_scores(frame, args.dataset)
    out_matrix = root / "results_90pt/scored_matrices/base_mismatch_reference_scores.parquet"
    out_matrix.parent.mkdir(parents=True, exist_ok=True)
    trace_scores.to_parquet(out_matrix, index=False)

    summary = build_summary(trace_scores)
    out_summary = root / "results_90pt/summaries/base_mismatch_calibration_summary.csv"
    out_summary.parent.mkdir(parents=True, exist_ok=True)
    summary.to_csv(out_summary, index=False)

    print(f"Wrote {len(trace_scores)} base-mismatch rows -> {out_matrix}")
    print(f"Wrote {len(summary)} base-mismatch summary rows -> {out_summary}")


if __name__ == "__main__":
    main()
