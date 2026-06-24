#!/usr/bin/env python
"""Build the TIFS review-archive manifest from real review-ready artifacts."""

from __future__ import annotations

import argparse
import csv
from pathlib import Path

REQUIRED_CLASSES = {
    "raw_trace",
    "adapter_checkpoint",
    "model_revision",
    "scored_matrix",
    "run_log",
    "environment_lock",
    "analysis_code",
}


def read_tsv(path: Path) -> list[dict[str, str]]:
    if not path.exists() or path.stat().st_size == 0:
        return []
    with path.open("r", encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle, delimiter="\t"))


def write_tsv(path: Path, rows: list[dict[str, str]]) -> None:
    fields = [
        "artifact_id",
        "artifact_type",
        "path",
        "sha256",
        "size_bytes",
        "source_run_id",
        "public_release_status",
        "artifact_class",
        "validation_status",
    ]
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, delimiter="\t")
        writer.writeheader()
        writer.writerows(rows)


def infer_class(row: dict[str, str]) -> str:
    path = row.get("path", "").lower()
    artifact_type = row.get("artifact_type", "").lower()
    if "raw_trace" in path or "/traces/" in path or "\\traces\\" in path:
        return "raw_trace"
    if "adapter" in path or "checkpoint" in path:
        return "adapter_checkpoint"
    if "model_revisions" in path or "model_revision" in path:
        return "model_revision"
    if "scored_matrices" in path or path.endswith(".parquet"):
        return "scored_matrix"
    if "run_logs" in path or "/logs/" in path or "\\logs\\" in path:
        return "run_log"
    if "environment" in path or "requirements" in path or path.endswith(".lock"):
        return "environment_lock"
    if artifact_type in {"code", "script"} or path.endswith((".py", ".r", ".R")):
        return "analysis_code"
    return ""


def normalize_source_rows(
    rows: list[dict[str, str]],
) -> tuple[list[dict[str, str]], list[str]]:
    output = []
    blockers = []
    for row in rows:
        artifact_class = row.get("artifact_class") or infer_class(row)
        if not artifact_class:
            continue
        validation_status = row.get("validation_status", "")
        if validation_status != "review_ready":
            continue
        source_run_id = row.get("source_run_id", "")
        if source_run_id in {
            "",
            "current_local_bundle",
            "derived_from_existing",
            "legacy",
        }:
            blockers.append(
                f"{row.get('path', '<unknown>')} has non-review source_run_id={source_run_id}"
            )
            continue
        output.append(
            {
                "artifact_id": row.get("artifact_id", ""),
                "artifact_type": row.get("artifact_type", ""),
                "path": row.get("path", ""),
                "sha256": row.get("sha256", ""),
                "size_bytes": row.get("size_bytes", ""),
                "source_run_id": source_run_id,
                "public_release_status": row.get("public_release_status", ""),
                "artifact_class": artifact_class,
                "validation_status": validation_status,
            }
        )
    present = {row["artifact_class"] for row in output}
    missing = sorted(REQUIRED_CLASSES - present)
    if missing:
        blockers.append("missing review-ready artifact classes: " + ", ".join(missing))
    return output, blockers


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", default=".")
    parser.add_argument(
        "--source",
        default="reproducibility_bundle/REVIEW_ARCHIVE/review_archive_source.tsv",
        help="Preferred external review-ready manifest.",
    )
    parser.add_argument(
        "--fallback",
        default="results_90pt/reproducibility/reproducibility_manifest.tsv",
        help="Fallback manifest, usually local and expected to fail review-ready checks.",
    )
    parser.add_argument(
        "--out",
        default="results_90pt/reproducibility/tifs_review_archive_manifest.tsv",
    )
    args = parser.parse_args()

    root = Path(args.root)
    source_path = root / args.source
    fallback_path = root / args.fallback
    rows = read_tsv(source_path) or read_tsv(fallback_path)
    if not rows:
        raise SystemExit("No review archive source rows found")
    output, blockers = normalize_source_rows(rows)
    if blockers:
        for blocker in blockers:
            print(f"- {blocker}")
        raise SystemExit(1)
    out_path = root / args.out
    write_tsv(out_path, output)
    print(f"Wrote {len(output)} review archive rows -> {out_path}")


if __name__ == "__main__":
    main()
