#!/usr/bin/env python
"""Import existing W08 cross-architecture summary into the 90-point output contract."""

from __future__ import annotations

import argparse
from pathlib import Path


def require_pandas():
    try:
        import pandas as pd
    except ImportError as exc:
        raise SystemExit("pandas is required for cross-architecture summary import") from exc
    return pd


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", default=".")
    parser.add_argument(
        "--source",
        default=(
            "C:/Users/Jie/Desktop/codex/paper_portfolio_2026/project_roots/"
            "LLM_Distillation_Provenance/"
            "manuscript_new_results_mtcr_20260623_tifs_nature_r_figures_v3_enriched/"
            "figures/source/w08_cross_architecture.csv"
        ),
    )
    parser.add_argument("--dataset", default="GSM8K")
    parser.add_argument("--out", default="results_90pt/summaries/cross_base_student_matrix.csv")
    args = parser.parse_args()

    pd = require_pandas()
    source = Path(args.source)
    if not source.exists():
        raise SystemExit(f"missing source summary: {source}")
    frame = pd.read_csv(source)
    required = {"teacher_family", "student_family", "transfer_type", "method", "auroc", "tpr_at_1pct_fpr", "fpr0", "seed_count"}
    missing = required - set(frame.columns)
    if missing:
        raise SystemExit(f"{source} missing columns: {', '.join(sorted(missing))}")

    out = pd.DataFrame(
        {
            "experiment": "broader_student_matrix",
            "condition": frame["transfer_type"].astype(str) + "__" + frame["method"].astype(str),
            "dataset": args.dataset,
            "student_base": frame["student_family"],
            "student_training": frame["method"],
            "seed": frame["seed_count"].map(lambda value: f"pooled_{value}_seeds"),
            "auroc": frame["auroc"],
            "tpr_at_1pct_fpr": frame["tpr_at_1pct_fpr"],
            "fpr_zero": frame["fpr0"],
            "teacher_family": frame["teacher_family"],
            "transfer_type": frame["transfer_type"],
            "n_traces": frame.get("n_traces", ""),
            "n_students": frame.get("n_students", ""),
            "provenance_note": f"imported_existing_summary:{source.as_posix()}",
        }
    )
    out_path = Path(args.root) / args.out
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out.to_csv(out_path, index=False)
    print(f"Wrote {len(out)} cross-base summary rows -> {out_path}")


if __name__ == "__main__":
    main()
