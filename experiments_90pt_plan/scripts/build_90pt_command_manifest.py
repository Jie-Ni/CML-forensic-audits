#!/usr/bin/env python
"""Build a TSV command manifest for the W08 90-point run matrix."""

from __future__ import annotations

import argparse
import csv
import hashlib
import sys
from pathlib import Path


def read_tsv(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle, delimiter="\t"))


def sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", default=".")
    parser.add_argument("--out", default="results_90pt/run_commands/command_manifest.tsv")
    args = parser.parse_args()

    root = Path(args.root).resolve()
    rows = read_tsv(root / "experiments_90pt_plan/run_matrix.tsv")
    executor = root / "experiments_90pt_plan/scripts/execute_90pt_run.py"
    executor_hash = sha256_file(executor)
    out = root / args.out
    out.parent.mkdir(parents=True, exist_ok=True)
    fields = [
        "array_index",
        "run_id",
        "source_run_id",
        "priority",
        "experiment",
        "condition",
        "dataset",
        "command",
        "command_hash",
        "script_sha256",
        "expected_env_id",
        "hpc_profile",
        "expected_primary_output",
        "required_for_90pt",
    ]
    with out.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, delimiter="\t")
        writer.writeheader()
        for index, row in enumerate(rows, start=1):
            command = (
                f'"{sys.executable}" '
                f'"{executor}" '
                f'--root "{root}" --array-index {index} --execute'
            )
            writer.writerow(
                {
                    "array_index": index,
                    "run_id": row["run_id"],
                    "source_run_id": row["run_id"],
                    "priority": row["priority"],
                    "experiment": row["experiment"],
                    "condition": row["condition"],
                    "dataset": row["dataset"],
                    "command": command,
                    "command_hash": sha256_text(command),
                    "script_sha256": executor_hash,
                    "expected_env_id": "w08_90pt_env_pending",
                    "hpc_profile": "musica_90pt_array_local_plan_pi_only",
                    "expected_primary_output": row["expected_primary_output"],
                    "required_for_90pt": row["required_for_90pt"],
                }
            )
    print(f"Wrote {len(rows)} commands -> {out}")


if __name__ == "__main__":
    main()
