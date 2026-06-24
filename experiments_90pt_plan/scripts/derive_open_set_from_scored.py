#!/usr/bin/env python
"""Derive open-set attribution stress tests from existing W08 scored matrices.

This is a scored-matrix reanalysis, not a new inference run. It uses real
candidate-teacher log-likelihood scores that are already staged in figures/source.
"""

from __future__ import annotations

import argparse
import json
import math
import re
from pathlib import Path


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
        raise SystemExit("pandas and pyarrow are required for open-set derivation") from exc
    return pd


def provenance_type(student: str) -> str:
    return re.sub(r"_s\d+$", "", student)


def seed_of(student: str) -> str:
    match = re.search(r"_s(\d+)$", student)
    return match.group(1) if match else "0"


def reference_student(student: str) -> str:
    seed = seed_of(student)
    return "ctrlA_base" if seed == "0" else f"ctrlA_base_s{seed}"


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
                row["source_file"] = path.as_posix()
                rows.append(row)
    if not rows:
        raise SystemExit(f"No scored JSONL files found under {scored_dir}")
    return pd.DataFrame(rows)


def add_cml(frame):
    refs = frame[frame["student"].str.startswith("ctrlA")].copy()
    refs = refs.rename(columns={"student": "reference_student", "mean_lp": "reference_mean_lp"})
    refs = refs[["reference_student", "candidate_teacher", "id", "reference_mean_lp"]]
    data = frame.copy()
    data["reference_student"] = data["student"].map(reference_student)
    merged = data.merge(refs, on=["reference_student", "candidate_teacher", "id"], how="left")
    missing = merged["reference_mean_lp"].isna()
    if missing.any():
        sample = merged.loc[missing, ["student", "reference_student", "candidate_teacher"]].drop_duplicates().head(10)
        raise SystemExit("Missing matched ctrlA reference rows:\n" + sample.to_string(index=False))
    merged["score_cml"] = merged["mean_lp"] - merged["reference_mean_lp"]
    merged["student_id"] = merged["student"]
    merged["seed"] = merged["student"].map(seed_of)
    merged["trace_id"] = merged["id"]
    merged["ptype"] = merged["student"].map(provenance_type)
    merged["true_teacher"] = merged["ptype"].map(TRUE_TEACHER).fillna("none")
    return merged


def candidate_set(condition: str, true_teacher: str) -> list[str]:
    if condition == "source_teacher_present_closed_set":
        return SOURCE_CANDIDATES
    if condition == "source_teacher_absent":
        return [c for c in SOURCE_CANDIDATES if c != true_teacher]
    if condition == "sibling_teacher_absent":
        if true_teacher == "r1-distill-qwen-32b":
            return [c for c in SOURCE_CANDIDATES if c != "r1-distill-llama-8b"]
        if true_teacher == "r1-distill-llama-8b":
            return [c for c in SOURCE_CANDIDATES if c != "r1-distill-qwen-32b"]
        return SOURCE_CANDIDATES
    if condition == "unrelated_capable_teacher_present":
        return EXTENDED_CANDIDATES
    raise ValueError(condition)


def control_threshold(frame, candidates: list[str]) -> float:
    ctrl = frame[(frame["ptype"] == "ctrlC") & frame["candidate_teacher"].isin(candidates)]
    if ctrl.empty:
        return 0.0
    max_scores = ctrl.groupby(["student", "trace_id"], as_index=False)["score_cml"].max()["score_cml"]
    return float(max_scores.quantile(0.99))


def derive_condition(frame, condition: str, dataset: str):
    pd = require_pandas()
    output = []
    for (student, trace_id), group in frame.groupby(["student", "trace_id"], dropna=False):
        ptype = str(group["ptype"].iloc[0])
        true_teacher = str(group["true_teacher"].iloc[0])
        candidates = candidate_set(condition, true_teacher)
        threshold = control_threshold(frame, candidates)
        subset = group[group["candidate_teacher"].isin(candidates)].sort_values("score_cml", ascending=False)
        if subset.empty:
            continue
        top = subset.iloc[0]
        second_score = float(subset.iloc[1]["score_cml"]) if len(subset) > 1 else math.nan
        margin = float(top["score_cml"] - second_score) if not math.isnan(second_score) else math.nan
        pred_teacher = str(top["candidate_teacher"])
        source_absent = true_teacher != "none" and true_teacher not in candidates
        abstained = bool(float(top["score_cml"]) <= threshold)
        output.append(
            {
                "experiment": "out_of_set_candidate",
                "condition": condition,
                "dataset": dataset,
                "student_id": student,
                "seed": str(top["seed"]),
                "trace_id": trace_id,
                "true_teacher": true_teacher,
                "pred_teacher": "" if abstained else pred_teacher,
                "score_margin": margin,
                "abstained": abstained,
                "score_cml": float(top["score_cml"]),
                "candidate_set": ",".join(candidates),
                "source_absent": source_absent,
                "abstention_threshold_ctrlC_99pct": threshold,
                "provenance_note": "derived_from_existing_scored_matrix_without_new_inference",
            }
        )
    return pd.DataFrame(output)


def write_summary(frame, out_path: Path) -> None:
    pd = require_pandas()
    rows = []
    for keys, group in frame.groupby(["condition", "dataset", "student_id", "seed"], dropna=False):
        condition, dataset, student_id, seed = keys
        non_abs = group[~group["abstained"]]
        true_teacher = str(group["true_teacher"].iloc[0])
        if true_teacher == "none":
            false_attribution = len(non_abs) / len(group) if len(group) else math.nan
            closed_acc = math.nan
        else:
            false_attribution = (
                (non_abs["true_teacher"] != non_abs["pred_teacher"]).sum() / len(group)
                if len(group)
                else math.nan
            )
            closed_acc = (
                (non_abs["true_teacher"] == non_abs["pred_teacher"]).mean()
                if len(non_abs)
                else math.nan
            )
        rows.append(
            {
                "experiment": "out_of_set_candidate",
                "condition": condition,
                "dataset": dataset,
                "student_id": student_id,
                "seed": seed,
                "abstention_rate": float(group["abstained"].mean()),
                "false_attribution_rate": float(false_attribution),
                "closed_set_accuracy": float(closed_acc) if not math.isnan(closed_acc) else "",
                "n_traces": len(group),
                "provenance_note": "derived_from_existing_scored_matrix_without_new_inference",
            }
        )
    out_path.parent.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(rows).to_csv(out_path, index=False)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", default=".")
    parser.add_argument("--dataset", default="GSM8K")
    parser.add_argument("--scored-dir", default="figures/source/scored_gsm8k")
    args = parser.parse_args()

    root = Path(args.root)
    scored = load_scored(root / args.scored_dir)
    cml = add_cml(scored)
    conditions = [
        "source_teacher_present_closed_set",
        "source_teacher_absent",
        "sibling_teacher_absent",
        "unrelated_capable_teacher_present",
    ]
    frames = [derive_condition(cml, condition, args.dataset) for condition in conditions]
    pd = require_pandas()
    output = pd.concat(frames, ignore_index=True)
    out_matrix = root / "results_90pt/scored_matrices/out_of_set_candidate_scores.parquet"
    out_matrix.parent.mkdir(parents=True, exist_ok=True)
    output.to_parquet(out_matrix, index=False)
    write_summary(output, root / "results_90pt/summaries/out_of_set_abstention_summary.csv")
    print(f"Wrote {len(output)} open-set rows -> {out_matrix}")


if __name__ == "__main__":
    main()
