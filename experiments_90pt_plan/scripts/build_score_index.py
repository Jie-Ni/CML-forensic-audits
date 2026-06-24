#!/usr/bin/env python
"""Build a reproducibility index for W08 scored matrices and derived score tables."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
from pathlib import Path


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def count_jsonl(path: Path) -> int:
    count = 0
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            if line.strip():
                count += 1
    return count


def first_jsonl(path: Path) -> dict:
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            if line.strip():
                return json.loads(line)
    return {}


def count_table(path: Path) -> int:
    if path.suffix.lower() == ".parquet":
        try:
            import pandas as pd
        except ImportError as exc:
            raise SystemExit("pandas/pyarrow are required to index parquet outputs") from exc
        return len(pd.read_parquet(path))
    if path.suffix.lower() in {".csv", ".tsv"}:
        delimiter = "\t" if path.suffix.lower() == ".tsv" else ","
        with path.open("r", encoding="utf-8", newline="") as handle:
            reader = csv.DictReader(handle, delimiter=delimiter)
            return sum(1 for _ in reader)
    return 0


def dataset_from_path(path: Path) -> str:
    text = path.as_posix().lower()
    if "gsm8k" in text:
        return "GSM8K"
    if "math" in text:
        return "MATH"
    return "derived"


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", default=".")
    parser.add_argument("--out", default="reproducibility_bundle/SCORES/scored_matrix_index.tsv")
    args = parser.parse_args()

    root = Path(args.root)
    rows = []
    for path in sorted((root / "figures/source").rglob("*.jsonl")):
        row = first_jsonl(path)
        rows.append(
            {
                "matrix_id": path.stem,
                "dataset": dataset_from_path(path),
                "split": "test",
                "student_id": row.get("student", ""),
                "seed": "",
                "candidate_teacher": row.get("candidate_teacher", ""),
                "path": path.relative_to(root).as_posix(),
                "sha256": sha256_file(path),
                "expected_rows": 200,
                "actual_rows": count_jsonl(path),
                "scoring_command_hash": "",
                "scorer_env_id": "legacy_vllm_scoring_unstaged",
                "validation_status": "pass" if count_jsonl(path) == 200 else "review",
            }
        )
    for rel in [
        "results_90pt/scored_matrices/out_of_set_candidate_scores.parquet",
        "results_90pt/summaries/out_of_set_abstention_summary.csv",
        "results_90pt/summaries/cross_base_student_matrix.csv",
        "results_90pt/scored_matrices/base_mismatch_reference_scores.parquet",
        "results_90pt/summaries/base_mismatch_calibration_summary.csv",
    ]:
        path = root / rel
        if not path.exists():
            continue
        rows.append(
            {
                "matrix_id": path.stem,
                "dataset": "derived",
                "split": "derived",
                "student_id": "multiple",
                "seed": "multiple",
                "candidate_teacher": "multiple",
                "path": rel,
                "sha256": sha256_file(path),
                "expected_rows": "",
                "actual_rows": count_table(path),
                "scoring_command_hash": "",
                "scorer_env_id": "local_derived_reanalysis",
                "validation_status": "derived",
            }
        )

    out = root / args.out
    out.parent.mkdir(parents=True, exist_ok=True)
    fields = [
        "matrix_id",
        "dataset",
        "split",
        "student_id",
        "seed",
        "candidate_teacher",
        "path",
        "sha256",
        "expected_rows",
        "actual_rows",
        "scoring_command_hash",
        "scorer_env_id",
        "validation_status",
    ]
    with out.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, delimiter="\t")
        writer.writeheader()
        writer.writerows(rows)
    print(f"Wrote {len(rows)} scored-matrix index rows -> {out}")


if __name__ == "__main__":
    main()
