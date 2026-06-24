#!/usr/bin/env python
"""Promote PI result-lock CSVs to figure source tables."""

from __future__ import annotations

import argparse
import shutil
from pathlib import Path


COPY_MAP = {
    "tifs_adaptive_attack_summary.csv": "w08_tifs_adaptive_attack_summary.csv",
    "tifs_cross_base_task_matrix.csv": "w08_tifs_cross_base_task_matrix.csv",
    "tifs_open_set_abstention_summary.csv": "w08_tifs_open_set_abstention_summary.csv",
    "tifs_baseline_head_to_head.csv": "w08_tifs_baseline_head_to_head.csv",
    "tifs_student_level_ci.csv": "w08_tifs_student_level_ci.csv",
    "tifs_mtcr_task_profile_summary.csv": "w08_tifs_mtcr_task_profile_summary.csv",
    "tifs_review_archive_descriptive_manifest.csv": "w08_tifs_review_archive_descriptive_manifest.csv",
}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", default=".")
    parser.add_argument("--source-dir", default="results_90pt/pi_result_locks")
    parser.add_argument("--figure-source-dir", default="figures/source")
    args = parser.parse_args()

    root = Path(args.root)
    source_dir = root / args.source_dir
    figure_source_dir = root / args.figure_source_dir
    figure_source_dir.mkdir(parents=True, exist_ok=True)
    copied = []
    for src_name, dest_name in COPY_MAP.items():
        src = source_dir / src_name
        if not src.exists():
            raise SystemExit(f"Missing PI result-lock source: {src}")
        dest = figure_source_dir / dest_name
        shutil.copy2(src, dest)
        copied.append(f"{src} -> {dest}")
    print("Promoted PI result-lock sources:")
    for item in copied:
        print(f"- {item}")


if __name__ == "__main__":
    main()
