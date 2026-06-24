#!/usr/bin/env python
"""Validate hard TIFS/SPS submission-shape constraints for the current manuscript."""

from __future__ import annotations

import argparse
import json
import re
from datetime import datetime, timezone
from pathlib import Path


FORBIDDEN_PATTERNS = [
    r"\bTODO\b",
    r"\bTBD\b",
    r"\bPLACEHOLDER\b",
    r"\bdraft confirmation\b",
]


def pdf_page_count(path: Path) -> int:
    try:
        from pypdf import PdfReader
    except ImportError:
        try:
            from PyPDF2 import PdfReader
        except ImportError as exc:
            raise SystemExit("pypdf or PyPDF2 is required for PDF page counting") from exc
    return len(PdfReader(str(path)).pages)


def strip_latex(text: str) -> str:
    text = re.sub(r"%.*", " ", text)
    text = re.sub(r"\\[a-zA-Z]+\*?(?:\[[^\]]*\])?(?:\{([^{}]*)\})?", r" \1 ", text)
    text = re.sub(r"[{}$\\]", " ", text)
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def word_count(path: Path) -> int:
    if not path.exists():
        return 0
    text = strip_latex(path.read_text(encoding="utf-8"))
    return len(re.findall(r"[A-Za-z0-9][A-Za-z0-9+\-.]*", text))


def keyword_count(main_tex: Path) -> int:
    text = main_tex.read_text(encoding="utf-8")
    match = re.search(r"\\begin\{IEEEkeywords\}(.*?)\\end\{IEEEkeywords\}", text, re.S)
    if not match:
        return 0
    raw = strip_latex(match.group(1))
    return len([item.strip() for item in raw.split(",") if item.strip()])


def scan_forbidden(paths: list[Path]) -> list[str]:
    findings: list[str] = []
    for path in paths:
        if not path.exists():
            continue
        text = path.read_text(encoding="utf-8", errors="ignore")
        for pattern in FORBIDDEN_PATTERNS:
            if re.search(pattern, text, flags=re.I):
                findings.append(f"{path.name}: matched {pattern}")
    return findings


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", default=".")
    parser.add_argument("--max-pages", type=int, default=13)
    parser.add_argument("--abstract-min-words", type=int, default=150)
    parser.add_argument("--abstract-max-words", type=int, default=250)
    parser.add_argument("--report-md", default="results_90pt/tifs_submission_shape_report.md")
    parser.add_argument("--report-json", default="results_90pt/tifs_submission_shape_report.json")
    args = parser.parse_args()

    root = Path(args.root)
    main_pdf = root / "main.pdf"
    main_tex = root / "main.tex"
    abstract_tex = root / "sections/abstract_body.tex"
    section_files = sorted((root / "sections").glob("*.tex"))
    scan_files = [main_tex, abstract_tex, *section_files]
    failures: list[str] = []
    warnings: list[str] = []

    pages = pdf_page_count(main_pdf) if main_pdf.exists() else 0
    if not main_pdf.exists():
        failures.append("main.pdf is missing")
    elif pages > args.max_pages:
        failures.append(f"main.pdf has {pages} pages; initial TIFS/SPS limit is {args.max_pages}")

    abstract_words = word_count(abstract_tex)
    if abstract_words < args.abstract_min_words or abstract_words > args.abstract_max_words:
        failures.append(
            f"abstract has {abstract_words} words; expected "
            f"{args.abstract_min_words}-{args.abstract_max_words}"
        )

    keywords = keyword_count(main_tex) if main_tex.exists() else 0
    if keywords == 0:
        failures.append("IEEEkeywords block is missing or empty")
    elif keywords > 6:
        warnings.append(f"keyword count is {keywords}; consider reducing to 5-6")

    forbidden = scan_forbidden(scan_files)
    if forbidden:
        failures.extend(f"forbidden placeholder marker: {item}" for item in forbidden)

    payload = {
        "checked_at": datetime.now(timezone.utc).isoformat(),
        "root": str(root.resolve()),
        "passed": not failures,
        "page_count": pages,
        "max_pages": args.max_pages,
        "abstract_words": abstract_words,
        "keyword_count": keywords,
        "failures": failures,
        "warnings": warnings,
    }
    report_json = root / args.report_json
    report_json.parent.mkdir(parents=True, exist_ok=True)
    report_json.write_text(json.dumps(payload, indent=2), encoding="utf-8")

    lines = [
        "# TIFS Submission Shape Report",
        "",
        f"Checked at: `{payload['checked_at']}`",
        "",
        f"Verdict: **{'PASS' if payload['passed'] else 'FAIL'}**",
        "",
        f"- page count: {pages}/{args.max_pages}",
        f"- abstract words: {abstract_words}/{args.abstract_min_words}-{args.abstract_max_words}",
        f"- keyword count: {keywords}",
        "",
    ]
    if failures:
        lines.append("## Failures")
        lines.extend(f"- {failure}" for failure in failures)
        lines.append("")
    if warnings:
        lines.append("## Warnings")
        lines.extend(f"- {warning}" for warning in warnings)
        lines.append("")
    (root / args.report_md).write_text("\n".join(lines), encoding="utf-8")

    if failures:
        print("TIFS submission-shape validation failed:")
        for failure in failures:
            print(f"- {failure}")
        raise SystemExit(1)
    if warnings:
        print("TIFS submission-shape validation passed with warnings:")
        for warning in warnings:
            print(f"- {warning}")
    else:
        print("TIFS submission-shape validation passed.")


if __name__ == "__main__":
    main()
