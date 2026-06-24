#!/usr/bin/env python
"""Validate review-safe W08 source-bundle hygiene."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import re
from datetime import datetime, timezone
from pathlib import Path


REQUIRED_FILES = [
    "SOURCE_BUNDLE_README.txt",
    "FIGURE_PANEL_TRACEABILITY.tsv",
    "artifact_manifest.tsv",
    "artifact_manifest.yaml",
    "main.tex",
    "supplementary.tex",
    "references.bib",
    "figures/plot_nature_results.R",
    "figures/plot_tifs_advanced_figures.R",
    "figures/plot_forensic_envelope.R",
]

REQUIRED_FIGURES = [
    "fig_method_overview",
    "fig_core_detection",
    "fig_mtcr_attribution_epoch",
    "fig_robustness_checks",
    "fig_forensic_envelope",
]

FIGURE_SUFFIXES = [".pdf", ".svg", ".png", ".tiff"]

TEXT_SUFFIXES = {".bib", ".csv", ".json", ".jsonl", ".md", ".r", ".tex", ".tsv", ".txt"}

FORBIDDEN_TEXT_PATTERNS = {
    "local_windows_path": re.compile(r"(?:[A-Za-z]:\\Users\\|C:/Users/)"),
    "todo_marker": re.compile(r"\b(?:TODO|TBD)\b", re.IGNORECASE),
    "draft_placeholder": re.compile(r"\b(?:draft confirmation|placeholder)\b", re.IGNORECASE),
    "ai_author_disclosure": re.compile(
        r"\b(?:ChatGPT|Claude|Codex|AI assistance|AI-assisted author)\b",
        re.IGNORECASE,
    ),
}

PLOTTING_RISK_PATTERNS = {
    "random_generation": re.compile(r"\b(?:rnorm|runif|rexp|rpois|sample\s*\()\b"),
    "simulated_density": re.compile(r"\b(?:simulate|simulation|bootstrap|KDE|kernel density|violin)\b", re.IGNORECASE),
}


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def read_tsv(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle, delimiter="\t"))


def scan_text_file(path: Path, rel: str, patterns: dict[str, re.Pattern[str]], issues: list[dict[str, str]]) -> None:
    try:
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError as exc:
        issues.append({"severity": "fail", "kind": "read_error", "path": rel, "detail": str(exc)})
        return
    for lineno, line in enumerate(lines, start=1):
        for kind, pattern in patterns.items():
            if pattern.search(line):
                issues.append(
                    {
                        "severity": "fail",
                        "kind": kind,
                        "path": rel,
                        "line": str(lineno),
                        "detail": line[:240],
                    }
                )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", default=".")
    parser.add_argument("--json-out", default="results_90pt/source_bundle_hygiene_report.json")
    parser.add_argument("--md-out", default="results_90pt/source_bundle_hygiene_report.md")
    args = parser.parse_args()

    root = Path(args.root).resolve()
    issues: list[dict[str, str]] = []

    for rel in REQUIRED_FILES:
        path = root / rel
        if not path.exists() or path.stat().st_size == 0:
            issues.append({"severity": "fail", "kind": "missing_required_file", "path": rel, "detail": "missing or empty"})

    for figure in REQUIRED_FIGURES:
        for suffix in FIGURE_SUFFIXES:
            rel = f"figures/{figure}{suffix}"
            path = root / rel
            if not path.exists() or path.stat().st_size == 0:
                issues.append({"severity": "fail", "kind": "missing_figure_artifact", "path": rel, "detail": "missing or empty"})

    manifest_path = root / "artifact_manifest.tsv"
    manifest_rows: list[dict[str, str]] = []
    if manifest_path.exists():
        manifest_rows = read_tsv(manifest_path)
        seen: set[str] = set()
        for row in manifest_rows:
            rel = row.get("path", "")
            if rel in seen:
                issues.append({"severity": "fail", "kind": "duplicate_manifest_path", "path": rel, "detail": "duplicate row"})
            seen.add(rel)
            path = root / rel
            if not path.exists():
                issues.append({"severity": "fail", "kind": "manifest_missing_file", "path": rel, "detail": "listed file is absent"})
                continue
            size = str(path.stat().st_size)
            digest = sha256_file(path)
            if row.get("size") != size:
                issues.append({"severity": "fail", "kind": "manifest_stale_size", "path": rel, "detail": f"{row.get('size')} != {size}"})
            if row.get("sha256") != digest:
                issues.append({"severity": "fail", "kind": "manifest_stale_hash", "path": rel, "detail": "sha256 mismatch"})

    readme_path = root / "SOURCE_BUNDLE_README.txt"
    readme_text = readme_path.read_text(encoding="utf-8", errors="replace") if readme_path.exists() else ""
    for figure in REQUIRED_FIGURES:
        if figure not in readme_text:
            issues.append({"severity": "fail", "kind": "readme_missing_figure", "path": "SOURCE_BUNDLE_README.txt", "detail": figure})
    for script in ["plot_nature_results.R", "plot_tifs_advanced_figures.R", "plot_forensic_envelope.R"]:
        if script not in readme_text:
            issues.append({"severity": "fail", "kind": "readme_missing_script", "path": "SOURCE_BUNDLE_README.txt", "detail": script})

    trace_path = root / "FIGURE_PANEL_TRACEABILITY.tsv"
    if trace_path.exists():
        rows = read_tsv(trace_path)
        figures = {row.get("figure", "") for row in rows}
        for fig_no in [f"Figure {i}" for i in range(1, 6)]:
            if fig_no not in figures:
                issues.append({"severity": "fail", "kind": "traceability_missing_figure", "path": "FIGURE_PANEL_TRACEABILITY.tsv", "detail": fig_no})
        for row in rows:
            for field in ["primary_source", "derived_source"]:
                values = [item.strip() for item in row.get(field, "").split(";") if item.strip()]
                for value in values:
                    if "*" in value:
                        parent = value.split("*", 1)[0]
                        if not (root / parent).parent.exists():
                            issues.append({"severity": "fail", "kind": "traceability_missing_glob_parent", "path": value, "detail": field})
                        continue
                    if not (root / value).exists():
                        issues.append({"severity": "fail", "kind": "traceability_missing_source", "path": value, "detail": field})

    scan_candidates = set(REQUIRED_FILES + ["SOURCE_BUNDLE_README.txt", "FIGURE_PANEL_TRACEABILITY.tsv"])
    scan_candidates.update(row.get("path", "") for row in manifest_rows)
    for rel in sorted(scan_candidates):
        if not rel:
            continue
        path = root / rel
        if not path.exists() or path.suffix.lower() not in TEXT_SUFFIXES:
            continue
        scan_text_file(path, rel, FORBIDDEN_TEXT_PATTERNS, issues)
        if rel.startswith("figures/") and rel.endswith(".R"):
            scan_text_file(path, rel, PLOTTING_RISK_PATTERNS, issues)

    verdict = "PASS" if not any(issue["severity"] == "fail" for issue in issues) else "FAIL"
    report = {
        "checked_at": datetime.now(timezone.utc).isoformat(),
        "root": str(root),
        "verdict": verdict,
        "manifest_rows": len(manifest_rows),
        "issues": issues,
    }

    json_out = root / args.json_out
    json_out.parent.mkdir(parents=True, exist_ok=True)
    json_out.write_text(json.dumps(report, indent=2), encoding="utf-8")

    md_out = root / args.md_out
    with md_out.open("w", encoding="utf-8", newline="\n") as handle:
        handle.write("# Source Bundle Hygiene Report\n\n")
        handle.write(f"Checked at: `{report['checked_at']}`\n\n")
        handle.write(f"Verdict: **{verdict}**\n\n")
        handle.write(f"Manifest rows: {len(manifest_rows)}\n\n")
        if issues:
            handle.write("## Issues\n\n")
            for issue in issues:
                line = issue.get("line")
                where = f"{issue['path']}:{line}" if line else issue["path"]
                handle.write(f"- `{issue['kind']}` at `{where}`: {issue.get('detail', '')}\n")
        else:
            handle.write("No hygiene issues detected in the review-safe source bundle.\n")

    print(f"Source-bundle hygiene: {verdict}")
    print(f"Markdown report: {md_out}")
    print(f"JSON report: {json_out}")
    return 0 if verdict == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
