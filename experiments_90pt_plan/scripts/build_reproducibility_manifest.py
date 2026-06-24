#!/usr/bin/env python
"""Hash currently staged W08 artifacts into the 90-point reproducibility manifest."""

from __future__ import annotations

import argparse
import csv
import hashlib
from datetime import datetime, timezone
from pathlib import Path


SCAN_TARGETS = [
    "SOURCE_BUNDLE_README.txt",
    "figures/source",
    "figures/source_derived",
    "figures/plot_nature_results.R",
    "figures/plot_tifs_advanced_figures.R",
    "figures/plot_forensic_envelope.R",
    "figures/fig_method_overview.pdf",
    "figures/fig_core_detection.pdf",
    "figures/fig_mtcr_attribution_epoch.pdf",
    "figures/fig_robustness_checks.pdf",
    "figures/fig_forensic_envelope.pdf",
    "FIGURE_PANEL_TRACEABILITY.tsv",
    "artifact_manifest.tsv",
    "artifact_manifest.yaml",
    "main.tex",
    "supplementary.tex",
    "references.bib",
    "sections",
    "experiments_90pt_plan",
    "reproducibility_bundle",
    "results_90pt/summaries",
    "results_90pt/scored_matrices",
    "results_90pt/raw_trace_manifests",
]


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def artifact_type(path: Path) -> str:
    suffix = path.suffix.lower()
    if suffix in {".jsonl", ".parquet", ".csv", ".tsv", ".json"}:
        return "data"
    if suffix in {".py", ".r", ".sh", ".slurm"}:
        return "code"
    if suffix in {".md", ".txt", ".tex", ".bib"}:
        return "documentation"
    if suffix in {".pdf", ".png", ".svg", ".tiff"}:
        return "rendered_artifact"
    return "other"


def iter_files(root: Path):
    seen: set[Path] = set()
    for target in SCAN_TARGETS:
        path = root / target
        if not path.exists():
            continue
        if path.is_file():
            files = [path]
        else:
            files = [p for p in path.rglob("*") if p.is_file()]
        for file_path in files:
            if "__pycache__" in file_path.parts:
                continue
            if file_path in seen:
                continue
            seen.add(file_path)
            yield file_path


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", default=".")
    parser.add_argument(
        "--out",
        default="results_90pt/reproducibility/reproducibility_manifest.tsv",
    )
    args = parser.parse_args()

    root = Path(args.root).resolve()
    out = root / args.out
    out.parent.mkdir(parents=True, exist_ok=True)
    fields = [
        "artifact_id",
        "artifact_type",
        "path",
        "sha256",
        "size_bytes",
        "created_at",
        "source_run_id",
        "public_release_status",
    ]
    now = datetime.now(timezone.utc).isoformat()
    rows = []
    for index, path in enumerate(sorted(iter_files(root)), start=1):
        rel = path.relative_to(root).as_posix()
        rows.append(
            {
                "artifact_id": f"w08-artifact-{index:05d}",
                "artifact_type": artifact_type(path),
                "path": rel,
                "sha256": sha256_file(path),
                "size_bytes": path.stat().st_size,
                "created_at": now,
                "source_run_id": "current_local_bundle",
                "public_release_status": "local_staged_not_public",
            }
        )

    with out.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, delimiter="\t")
        writer.writeheader()
        writer.writerows(rows)
    print(f"Wrote {len(rows)} reproducibility manifest rows -> {out}")


if __name__ == "__main__":
    main()
