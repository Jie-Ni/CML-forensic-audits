#!/usr/bin/env python
"""Check manuscript claims against staged evidence gates."""

from __future__ import annotations

import argparse
import csv
import re
from pathlib import Path


DEFAULT_FILES = [
    "main.tex",
    "supplementary.tex",
    "sections/abstract_body.tex",
    "sections/introduction.tex",
    "sections/experimental_setup.tex",
    "sections/method.tex",
    "sections/results.tex",
    "sections/discussion.tex",
    "sections/conclusion.tex",
    "sections/appendix.tex",
]


def read_tsv(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle, delimiter="\t"))


def parse_required_values(spec: str) -> dict[str, set[str]]:
    clauses: dict[str, set[str]] = {}
    for clause in spec.split(";"):
        clause = clause.strip()
        if not clause:
            continue
        if "=" not in clause:
            raise SystemExit(f"Malformed required_values clause: {clause}")
        column, raw_values = clause.split("=", 1)
        clauses[column.strip()] = {
            value.strip() for value in raw_values.split("|") if value.strip()
        }
    return clauses


def read_table_profile(path: Path) -> tuple[int, set[str], dict[str, set[str]]]:
    suffix = path.suffix.lower()
    if suffix == ".parquet":
        try:
            import pandas as pd
        except ImportError as exc:
            raise SystemExit("pandas/pyarrow are required to read parquet evidence") from exc
        frame = pd.read_parquet(path)
        values = {
            column: {str(value) for value in frame[column].dropna().unique()}
            for column in frame.columns
        }
        return len(frame), set(frame.columns), values
    if suffix in {".csv", ".tsv"}:
        delimiter = "\t" if suffix == ".tsv" else ","
        with path.open("r", encoding="utf-8", newline="") as handle:
            reader = csv.DictReader(handle, delimiter=delimiter)
            values: dict[str, set[str]] = {field: set() for field in reader.fieldnames or []}
            count = 0
            for row in reader:
                count += 1
                for field in values:
                    value = row.get(field, "")
                    if value != "":
                        values[field].add(str(value))
            return count, set(reader.fieldnames or []), values
    return -1, set(), {}


def manuscript_text(root: Path, files: list[str]) -> str:
    chunks = []
    for rel in files:
        path = root / rel
        if path.exists():
            chunks.append(f"\n\n%% FILE: {rel}\n" + path.read_text(encoding="utf-8"))
    return "\n".join(chunks)


def snippet(text: str, match: re.Match[str], width: int = 120) -> str:
    start = max(0, match.start() - width // 2)
    end = min(len(text), match.end() + width // 2)
    return " ".join(text[start:end].split())


def check_evidence(root: Path, record: dict[str, str]) -> list[str]:
    failures = []
    required_paths = [p for p in record.get("required_paths", "").split("|") if p]
    required_values = parse_required_values(record.get("required_values", ""))
    for rel in required_paths:
        path = root / rel
        if not path.exists():
            failures.append(f"missing evidence file: {rel}")
            continue
        _, columns, values = read_table_profile(path)
        for column, expected in required_values.items():
            if column not in columns:
                failures.append(f"{rel} missing evidence column: {column}")
                continue
            missing = sorted(expected - values.get(column, set()))
            if missing:
                failures.append(
                    f"{rel} missing {column} values: {', '.join(missing)}"
                )
    return failures


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", default=".")
    parser.add_argument(
        "--contract",
        default="experiments_90pt_plan/configs/claim_evidence_contract.tsv",
    )
    parser.add_argument("--fail-on-warning", action="store_true")
    parser.add_argument("--report", default="results_90pt/claim_evidence_gate_report.md")
    args = parser.parse_args()

    root = Path(args.root)
    contract = read_tsv(root / args.contract)
    text = manuscript_text(root, DEFAULT_FILES)
    blockers: list[str] = []
    warnings: list[str] = []
    report_lines = ["# Claim-Evidence Gate Report", ""]

    for record in contract:
        pattern = record["search_regex"]
        match = re.search(pattern, text, flags=re.MULTILINE | re.DOTALL)
        if not match:
            continue
        claim_id = record["claim_id"]
        message = record.get("message", "")
        evidence_failures = check_evidence(root, record)
        finding = f"{claim_id}: {message}\n  snippet: {snippet(text, match)}"
        if record.get("severity", "block").lower() == "warn":
            warnings.append(finding)
            continue
        if evidence_failures:
            blockers.append(finding + "\n  evidence: " + "; ".join(evidence_failures))

    if blockers:
        report_lines.append("## Blocking Claim Problems")
        report_lines.extend(f"- {item}" for item in blockers)
        report_lines.append("")
    if warnings:
        report_lines.append("## Warnings")
        report_lines.extend(f"- {item}" for item in warnings)
        report_lines.append("")
    if not blockers and not warnings:
        report_lines.append("No blocked claims or warning phrases detected.")

    report = root / args.report
    report.parent.mkdir(parents=True, exist_ok=True)
    report.write_text("\n".join(report_lines) + "\n", encoding="utf-8")

    if blockers:
        print("Claim-evidence gate failed:")
        for item in blockers:
            print(f"- {item}")
        raise SystemExit(1)
    if warnings:
        print("Claim-evidence gate warnings:")
        for item in warnings:
            print(f"- {item}")
        if args.fail_on_warning:
            raise SystemExit(2)
    else:
        print("Claim-evidence gate passed.")


if __name__ == "__main__":
    main()
