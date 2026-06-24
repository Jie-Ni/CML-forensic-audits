from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence

import pandas as pd


@dataclass(frozen=True)
class AuditColumns:
    task: str = "task"
    scenario: str = "scenario"
    trace_id: str = "trace_id"
    candidate_teacher: str = "candidate_teacher"
    suspect_logp: str = "suspect_logp"
    reference_logp: str = "reference_logp"
    true_lineage: str = "true_lineage"
    label: str = "label"
    baseline_logp: str = "baseline_logp"

    @property
    def required(self) -> tuple[str, ...]:
        return (
            self.task,
            self.scenario,
            self.trace_id,
            self.candidate_teacher,
            self.suspect_logp,
            self.reference_logp,
        )

    @property
    def optional(self) -> tuple[str, ...]:
        return (self.true_lineage, self.label, self.baseline_logp)


def parse_group_columns(value: str | Sequence[str] | None) -> list[str]:
    if value is None:
        return ["task", "scenario"]
    if isinstance(value, str):
        columns = [part.strip() for part in value.split(",") if part.strip()]
    else:
        columns = [str(part).strip() for part in value if str(part).strip()]
    if not columns:
        raise ValueError("At least one grouping column is required.")
    return columns


def validate_audit_frame(
    frame: pd.DataFrame,
    columns: AuditColumns = AuditColumns(),
    *,
    group_columns: Sequence[str] | None = None,
    require_label: bool = False,
) -> None:
    required = list(columns.required)
    if require_label:
        required.append(columns.label)
    if group_columns:
        required.extend(group_columns)

    missing = sorted(set(required) - set(frame.columns))
    if missing:
        raise ValueError(f"Missing required columns: {', '.join(missing)}")

    numeric_columns = [columns.suspect_logp, columns.reference_logp]
    if columns.baseline_logp in frame.columns:
        numeric_columns.append(columns.baseline_logp)
    for name in numeric_columns:
        values = pd.to_numeric(frame[name], errors="coerce")
        if values.isna().any():
            bad = int(values.isna().sum())
            raise ValueError(f"Column {name!r} contains {bad} non-numeric values.")

    key_columns = [columns.trace_id, columns.candidate_teacher]
    if group_columns:
        key_columns.extend(group_columns)
    if frame[key_columns].isna().any().any():
        raise ValueError("Trace, candidate, and grouping columns must not be empty.")
