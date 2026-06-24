#!/usr/bin/env python
"""Select real low-score trace IDs for the selective-training stress test."""

from __future__ import annotations

import argparse
import json
from pathlib import Path


def require_pandas():
    try:
        import pandas as pd
    except ImportError as exc:
        raise SystemExit(
            "pandas and pyarrow are required for low-score selection"
        ) from exc
    return pd


def load_jsonl(path: Path) -> list[dict]:
    rows = []
    with path.open("r", encoding="utf-8") as handle:
        for line_no, line in enumerate(handle, start=1):
            if not line.strip():
                continue
            try:
                rows.append(json.loads(line))
            except json.JSONDecodeError as exc:
                raise SystemExit(f"{path}:{line_no} is not valid JSONL") from exc
    return rows


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", default=".")
    parser.add_argument("--dataset", required=True)
    parser.add_argument(
        "--scores",
        default="results_90pt/scored_matrices/tifs_adaptive_attack_trace_scores.parquet",
    )
    parser.add_argument(
        "--source-traces",
        default="results_90pt/raw_trace_manifests/raw_trace_inputs.tsv",
    )
    parser.add_argument("--fraction", type=float, default=0.25)
    parser.add_argument("--out", required=True)
    args = parser.parse_args()

    if args.fraction <= 0 or args.fraction >= 1:
        raise SystemExit("--fraction must be in (0, 1)")
    root = Path(args.root)
    pd = require_pandas()
    scores = pd.read_parquet(root / args.scores)
    required = {"dataset", "attack_type", "trace_id", "score_cml"}
    missing = required - set(scores.columns)
    if missing:
        raise SystemExit("score table missing columns: " + ", ".join(sorted(missing)))
    identity = scores.loc[
        (scores["dataset"].astype(str).str.lower() == args.dataset.lower())
        & (scores["attack_type"].astype(str) == "identity_control")
    ].copy()
    if identity.empty:
        raise SystemExit("No identity_control rows available for low-score selection")
    cutoff = identity["score_cml"].astype(float).quantile(args.fraction)
    selected_ids = set(
        identity.loc[identity["score_cml"].astype(float) <= cutoff, "trace_id"].astype(
            str
        )
    )
    if not selected_ids:
        raise SystemExit("Low-score selection produced no trace IDs")

    manifests = pd.read_csv(root / args.source_traces, sep="\t")
    manifests = manifests.loc[
        manifests["dataset"].astype(str).str.lower() == args.dataset.lower()
    ]
    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    written = 0
    with out_path.open("w", encoding="utf-8", newline="\n") as handle:
        for _, row in manifests.iterrows():
            trace_path = Path(str(row.get("trace_path", "")))
            if not trace_path.exists():
                continue
            for record in load_jsonl(trace_path):
                trace_id = str(record.get("id") or record.get("trace_id") or "")
                if trace_id not in selected_ids:
                    continue
                output = dict(record)
                output["laundering_condition"] = "selective_low_score_traces"
                output["selection_fraction"] = args.fraction
                output["selection_score_cutoff"] = float(cutoff)
                handle.write(json.dumps(output, ensure_ascii=True) + "\n")
                written += 1
    if written == 0:
        raise SystemExit("No selected trace records were found in source trace files")
    print(f"Wrote {written} selected low-score traces -> {out_path}")


if __name__ == "__main__":
    main()
