from __future__ import annotations

import argparse
from pathlib import Path

import pandas as pd

from .schema import AuditColumns, parse_group_columns
from .scoring import DecisionConfig, aggregate_candidates, decide_lineage, score_traces


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run capability-matched likelihood audits.")
    parser.add_argument("--input", required=True, type=Path, help="CSV of scored traces.")
    parser.add_argument("--output", required=True, type=Path, help="Output summary CSV.")
    parser.add_argument(
        "--group",
        default="task,scenario",
        help="Comma-separated grouping columns for candidate aggregation.",
    )
    parser.add_argument(
        "--threshold",
        type=float,
        default=None,
        help="Optional minimum top CML mean for a non-abstaining decision.",
    )
    parser.add_argument(
        "--margin",
        type=float,
        default=0.0,
        help="Optional minimum gap between top and runner-up candidate.",
    )
    parser.add_argument(
        "--write-decisions",
        type=Path,
        default=None,
        help="Optional path for one decision row per audit group.",
    )
    return parser


def main() -> None:
    args = build_parser().parse_args()
    columns = AuditColumns()
    group_columns = parse_group_columns(args.group)
    frame = pd.read_csv(args.input)
    scored = score_traces(frame, columns, group_columns=group_columns)
    candidate_scores = aggregate_candidates(scored, columns, group_columns=group_columns)

    args.output.parent.mkdir(parents=True, exist_ok=True)
    candidate_scores.to_csv(args.output, index=False)

    if args.write_decisions is not None:
        config = DecisionConfig(threshold=args.threshold, margin=args.margin)
        decisions = decide_lineage(
            candidate_scores,
            columns,
            group_columns=group_columns,
            config=config,
        )
        args.write_decisions.parent.mkdir(parents=True, exist_ok=True)
        decisions.to_csv(args.write_decisions, index=False)


if __name__ == "__main__":
    main()
