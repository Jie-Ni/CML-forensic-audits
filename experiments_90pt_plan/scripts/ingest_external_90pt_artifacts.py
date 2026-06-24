#!/usr/bin/env python
"""Ingest externally staged W08 raw artifacts into local reproducibility manifests.

The script expects a staging folder with optional TSV files under:

  datasets/dataset_hashes.tsv
  models/model_revisions.tsv
  models/adapter_index.tsv
  traces/trace_index.tsv
  traces/raw_trace_inputs.tsv
  traces/mtcr_task_views.tsv
  rewrites/external_rewrites.tsv
  run_logs/slurm_jobs.tsv
  results/reproducibility/tifs_review_archive_manifest.tsv

It resolves relative paths against the staging root, computes missing sha256 values
for path-bearing rows, validates file existence, and writes the corresponding local
manifest files. It does not run training, scoring, SSH, or SLURM jobs.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import shutil
from pathlib import Path

COPY_MAP = {
    "datasets/dataset_hashes.tsv": "reproducibility_bundle/DATASETS/dataset_hashes.tsv",
    "models/model_revisions.tsv": "reproducibility_bundle/MODELS/model_revisions.tsv",
    "models/adapter_index.tsv": "reproducibility_bundle/MODELS/adapter_index.tsv",
    "traces/trace_index.tsv": "reproducibility_bundle/TRACES/trace_index.tsv",
    "traces/raw_trace_inputs.tsv": "results_90pt/raw_trace_manifests/raw_trace_inputs.tsv",
    "traces/mtcr_task_views.tsv": "results_90pt/raw_trace_manifests/mtcr_task_views.tsv",
    "rewrites/external_rewrites.tsv": "results_90pt/raw_trace_manifests/external_rewrites.tsv",
    "run_logs/slurm_jobs.tsv": "reproducibility_bundle/RUN_LOGS/slurm_jobs.tsv",
    "results/reproducibility/tifs_review_archive_manifest.tsv": "results_90pt/reproducibility/tifs_review_archive_manifest.tsv",
}

RESULT_COPY_MAP = {
    "results/scored_matrices/adaptive_laundering_trace_scores.parquet": "results_90pt/scored_matrices/adaptive_laundering_trace_scores.parquet",
    "results/summaries/adaptive_laundering_student_summary.csv": "results_90pt/summaries/adaptive_laundering_student_summary.csv",
    "results/scored_matrices/base_mismatch_reference_scores.parquet": "results_90pt/scored_matrices/base_mismatch_reference_scores.parquet",
    "results/summaries/base_mismatch_calibration_summary.csv": "results_90pt/summaries/base_mismatch_calibration_summary.csv",
    "results/scored_matrices/out_of_set_candidate_scores.parquet": "results_90pt/scored_matrices/out_of_set_candidate_scores.parquet",
    "results/summaries/out_of_set_abstention_summary.csv": "results_90pt/summaries/out_of_set_abstention_summary.csv",
    "results/summaries/cross_base_student_matrix.csv": "results_90pt/summaries/cross_base_student_matrix.csv",
    "results/scored_matrices/mtcr_per_task_profiles.parquet": "results_90pt/scored_matrices/mtcr_per_task_profiles.parquet",
    "results/summaries/mtcr_task_ablation_with_ci.csv": "results_90pt/summaries/mtcr_task_ablation_with_ci.csv",
    "results/scored_matrices/tifs_adaptive_attack_trace_scores.parquet": "results_90pt/scored_matrices/tifs_adaptive_attack_trace_scores.parquet",
    "results/summaries/tifs_adaptive_attack_summary.csv": "results_90pt/summaries/tifs_adaptive_attack_summary.csv",
    "results/summaries/tifs_cross_base_task_matrix.csv": "results_90pt/summaries/tifs_cross_base_task_matrix.csv",
    "results/summaries/tifs_open_set_abstention_summary.csv": "results_90pt/summaries/tifs_open_set_abstention_summary.csv",
    "results/summaries/tifs_baseline_head_to_head.csv": "results_90pt/summaries/tifs_baseline_head_to_head.csv",
    "results/summaries/tifs_student_level_ci.csv": "results_90pt/summaries/tifs_student_level_ci.csv",
}

PATH_COLUMNS = {
    "dataset_hashes.tsv": ["path"],
    "adapter_index.tsv": ["path_or_escrow_id"],
    "trace_index.tsv": ["path"],
    "raw_trace_inputs.tsv": ["trace_path"],
    "mtcr_task_views.tsv": ["trace_path", "reference_trace_path"],
    "external_rewrites.tsv": ["external_rewrite_path"],
    "slurm_jobs.tsv": ["stdout_path", "stderr_path"],
}

HASH_COLUMNS = {
    "dataset_hashes.tsv": "sha256",
    "adapter_index.tsv": "sha256",
    "trace_index.tsv": "sha256",
}


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def read_tsv(path: Path) -> tuple[list[str], list[dict[str, str]]]:
    with path.open("r", encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle, delimiter="\t")
        return list(reader.fieldnames or []), list(reader)


def write_tsv(path: Path, fields: list[str], rows: list[dict[str, str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, delimiter="\t")
        writer.writeheader()
        writer.writerows(rows)


def resolve(staging_root: Path, value: str) -> Path:
    path = Path(value)
    return path if path.is_absolute() else staging_root / path


def is_external_reference(value: str) -> bool:
    lowered = value.lower()
    return lowered.startswith(
        ("escrow:", "doi:", "hf:", "s3:", "gs:", "r2:", "zenodo:")
    )


def normalize_paths_and_hashes(
    staging_root: Path, source: Path, fields: list[str], rows: list[dict[str, str]]
) -> tuple[list[dict[str, str]], list[str]]:
    filename = source.name
    path_columns = PATH_COLUMNS.get(filename, [])
    hash_column = HASH_COLUMNS.get(filename, "")
    errors = []
    normalized = []
    for row_index, row in enumerate(rows, start=2):
        row = dict(row)
        existing_paths = []
        for column in path_columns:
            value = row.get(column, "")
            if not value:
                continue
            if is_external_reference(value):
                continue
            resolved = resolve(staging_root, value)
            if not resolved.exists():
                errors.append(
                    f"{source}:{row_index}: missing path in {column}: {value}"
                )
                continue
            row[column] = resolved.as_posix()
            existing_paths.append(resolved)
        if (
            hash_column
            and hash_column in fields
            and not row.get(hash_column)
            and existing_paths
        ):
            row[hash_column] = sha256_file(existing_paths[0])
        if filename == "slurm_jobs.tsv":
            for path_column, hash_column in (
                ("stdout_path", "stdout_sha256"),
                ("stderr_path", "stderr_sha256"),
            ):
                value = row.get(path_column, "")
                if value and hash_column in fields and not row.get(hash_column):
                    resolved = Path(value)
                    if resolved.exists():
                        row[hash_column] = sha256_file(resolved)
        normalized.append(row)
    return normalized, errors


def copy_result_tables(
    root: Path, staging_root: Path, dry_run: bool
) -> tuple[list[str], list[str]]:
    copied = []
    errors = []
    for source_rel, dest_rel in RESULT_COPY_MAP.items():
        source = staging_root / source_rel
        if not source.exists():
            continue
        destination = root / dest_rel
        if source.stat().st_size == 0:
            errors.append(f"{source_rel}: staged result table is empty")
            continue
        if not dry_run:
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, destination)
        copied.append(f"{source_rel} -> {dest_rel} ({source.stat().st_size} bytes)")
    return copied, errors


def ingest(
    root: Path, staging_root: Path, dry_run: bool
) -> tuple[list[str], list[str]]:
    copied = []
    errors = []
    for source_rel, dest_rel in COPY_MAP.items():
        source = staging_root / source_rel
        if not source.exists():
            continue
        fields, rows = read_tsv(source)
        normalized, row_errors = normalize_paths_and_hashes(
            staging_root, source, fields, rows
        )
        errors.extend(row_errors)
        if not dry_run:
            write_tsv(root / dest_rel, fields, normalized)
        copied.append(f"{source_rel} -> {dest_rel} ({len(rows)} rows)")
    result_copied, result_errors = copy_result_tables(root, staging_root, dry_run)
    copied.extend(result_copied)
    errors.extend(result_errors)
    return copied, errors


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", default=".")
    parser.add_argument("--staging-root", required=True)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    root = Path(args.root).resolve()
    staging_root = Path(args.staging_root).resolve()
    if not staging_root.exists():
        raise SystemExit(f"Staging root does not exist: {staging_root}")

    copied, errors = ingest(root, staging_root, args.dry_run)
    if copied:
        print("Ingested manifests:" if not args.dry_run else "Dry-run manifest plan:")
        for item in copied:
            print(f"- {item}")
    else:
        print("No known staging TSV files found.")
    if errors:
        print("Path/hash validation errors:")
        for error in errors:
            print(f"- {error}")
        raise SystemExit(1)


if __name__ == "__main__":
    main()
