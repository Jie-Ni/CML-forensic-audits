from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence

import numpy as np
import pandas as pd

from .schema import AuditColumns, validate_audit_frame


@dataclass(frozen=True)
class DecisionConfig:
    threshold: float | None = None
    margin: float = 0.0


def score_traces(
    frame: pd.DataFrame,
    columns: AuditColumns = AuditColumns(),
    *,
    group_columns: Sequence[str] | None = None,
) -> pd.DataFrame:
    validate_audit_frame(frame, columns, group_columns=group_columns)
    scored = frame.copy()
    scored[columns.suspect_logp] = pd.to_numeric(scored[columns.suspect_logp])
    scored[columns.reference_logp] = pd.to_numeric(scored[columns.reference_logp])
    scored["cml_score"] = scored[columns.suspect_logp] - scored[columns.reference_logp]

    if columns.baseline_logp in scored.columns:
        scored[columns.baseline_logp] = pd.to_numeric(scored[columns.baseline_logp])
        scored["base_relative_score"] = scored[columns.suspect_logp] - scored[columns.baseline_logp]

    if columns.true_lineage in scored.columns and columns.label not in scored.columns:
        scored[columns.label] = (
            scored[columns.true_lineage].astype(str)
            == scored[columns.candidate_teacher].astype(str)
        ).astype(int)

    return scored


def aggregate_candidates(
    scored: pd.DataFrame,
    columns: AuditColumns = AuditColumns(),
    *,
    group_columns: Sequence[str] = ("task", "scenario"),
) -> pd.DataFrame:
    required = [*group_columns, columns.candidate_teacher, "cml_score"]
    missing = sorted(set(required) - set(scored.columns))
    if missing:
        raise ValueError(f"Missing scored columns: {', '.join(missing)}")

    aggregations: dict[str, tuple[str, str]] = {
        "n_traces": ("cml_score", "size"),
        "cml_mean": ("cml_score", "mean"),
        "cml_std": ("cml_score", "std"),
        "cml_median": ("cml_score", "median"),
        "cml_q05": ("cml_score", lambda values: float(np.quantile(values, 0.05))),
        "cml_q95": ("cml_score", lambda values: float(np.quantile(values, 0.95))),
    }
    if "base_relative_score" in scored.columns:
        aggregations["base_relative_mean"] = ("base_relative_score", "mean")
    if columns.label in scored.columns:
        aggregations["label"] = (columns.label, "max")

    grouped = (
        scored.groupby([*group_columns, columns.candidate_teacher], dropna=False)
        .agg(**aggregations)
        .reset_index()
    )
    grouped["cml_std"] = grouped["cml_std"].fillna(0.0)
    return grouped.sort_values(
        [*group_columns, "cml_mean"], ascending=[True] * len(group_columns) + [False]
    )


def decide_lineage(
    candidate_scores: pd.DataFrame,
    columns: AuditColumns = AuditColumns(),
    *,
    group_columns: Sequence[str] = ("task", "scenario"),
    config: DecisionConfig = DecisionConfig(),
) -> pd.DataFrame:
    required = [*group_columns, columns.candidate_teacher, "cml_mean"]
    missing = sorted(set(required) - set(candidate_scores.columns))
    if missing:
        raise ValueError(f"Missing candidate-score columns: {', '.join(missing)}")

    decisions: list[dict[str, object]] = []
    for group_values, group in candidate_scores.groupby(list(group_columns), dropna=False):
        if not isinstance(group_values, tuple):
            group_values = (group_values,)
        ranked = group.sort_values("cml_mean", ascending=False).reset_index(drop=True)
        top = ranked.iloc[0]
        runner_up = ranked.iloc[1] if len(ranked) > 1 else None
        margin = float(top["cml_mean"] - runner_up["cml_mean"]) if runner_up is not None else np.inf
        below_threshold = config.threshold is not None and float(top["cml_mean"]) < config.threshold
        below_margin = margin < config.margin
        abstained = bool(below_threshold or below_margin)

        row: dict[str, object] = dict(zip(group_columns, group_values, strict=True))
        row.update(
            {
                "predicted_teacher": None if abstained else top[columns.candidate_teacher],
                "top_candidate": top[columns.candidate_teacher],
                "top_cml_mean": float(top["cml_mean"]),
                "runner_up_candidate": (
                    None if runner_up is None else runner_up[columns.candidate_teacher]
                ),
                "runner_up_cml_mean": None if runner_up is None else float(runner_up["cml_mean"]),
                "decision_margin": margin,
                "threshold": config.threshold,
                "minimum_margin": config.margin,
                "abstained": abstained,
                "abstention_reason": _abstention_reason(below_threshold, below_margin),
            }
        )
        decisions.append(row)

    return pd.DataFrame(decisions)


def _abstention_reason(below_threshold: bool, below_margin: bool) -> str:
    reasons = []
    if below_threshold:
        reasons.append("below_threshold")
    if below_margin:
        reasons.append("below_margin")
    return ";".join(reasons) if reasons else ""
