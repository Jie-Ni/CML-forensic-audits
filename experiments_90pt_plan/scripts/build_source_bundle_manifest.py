#!/usr/bin/env python
"""Build the review-safe source bundle manifest for W08."""

from __future__ import annotations

import argparse
import csv
import hashlib
from pathlib import Path


TARGETS = [
    "SOURCE_BUNDLE_README.txt",
    "FIGURE_PANEL_TRACEABILITY.tsv",
    "main.tex",
    "supplementary.tex",
    "references.bib",
    "sections",
    "tables",
    "figures",
    "results_90pt/summaries",
]

ALLOWED_SUFFIXES = {
    ".bib",
    ".csv",
    ".json",
    ".jsonl",
    ".parquet",
    ".pdf",
    ".png",
    ".r",
    ".svg",
    ".tex",
    ".tiff",
    ".tsv",
    ".txt",
}

EXCLUDED_SUFFIXES = {".aux", ".bbl", ".blg", ".log", ".out"}
EXCLUDED_PARTS = {
    "__pycache__",
    "archive",
    "gate_verdicts",
    "paper_run_latest.json",
    "paper_operator_consume_latest.json",
    "paper_operator_next_latest.json",
    "run_commands",
}


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def is_allowed(path: Path) -> bool:
    if any(part in EXCLUDED_PARTS for part in path.parts):
        return False
    suffix = path.suffix.lower()
    if suffix in EXCLUDED_SUFFIXES:
        return False
    return suffix in ALLOWED_SUFFIXES


def iter_bundle_files(root: Path):
    seen: set[Path] = set()
    for target in TARGETS:
        path = root / target
        if not path.exists():
            continue
        candidates = [path] if path.is_file() else [p for p in path.rglob("*") if p.is_file()]
        for candidate in candidates:
            if not is_allowed(candidate):
                continue
            if candidate in seen:
                continue
            seen.add(candidate)
            yield candidate


def yaml_quote(value: str) -> str:
    return '"' + value.replace("\\", "\\\\").replace('"', '\\"') + '"'


def write_yaml(rows: list[dict[str, str]], out: Path) -> None:
    with out.open("w", encoding="utf-8", newline="\n") as handle:
        handle.write("files:\n")
        for row in rows:
            handle.write(f"  - path: {yaml_quote(row['path'])}\n")
            handle.write(f"    size: {row['size']}\n")
            handle.write(f"    sha256: {yaml_quote(row['sha256'])}\n")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", default=".")
    parser.add_argument("--tsv", default="artifact_manifest.tsv")
    parser.add_argument("--yaml", default="artifact_manifest.yaml")
    args = parser.parse_args()

    root = Path(args.root).resolve()
    rows = []
    for path in sorted(iter_bundle_files(root)):
        rel = path.relative_to(root).as_posix()
        rows.append(
            {
                "path": rel,
                "size": str(path.stat().st_size),
                "sha256": sha256_file(path),
            }
        )

    tsv_out = root / args.tsv
    with tsv_out.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=["path", "size", "sha256"], delimiter="\t")
        writer.writeheader()
        writer.writerows(rows)

    write_yaml(rows, root / args.yaml)
    print(f"Wrote {len(rows)} source-bundle manifest rows -> {tsv_out}")


if __name__ == "__main__":
    main()
