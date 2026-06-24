#!/usr/bin/env python
"""Run all W08 90-point readiness gates and write a single report."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path


def run_gate(root: Path, name: str, command: list[str]) -> dict:
    completed = subprocess.run(
        command,
        cwd=root,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    return {
        "name": name,
        "command": " ".join(command),
        "returncode": completed.returncode,
        "passed": completed.returncode == 0,
        "stdout": completed.stdout.strip(),
        "stderr": completed.stderr.strip(),
    }


def pdf_status(root: Path) -> dict:
    required = ["main.pdf", "supplementary.pdf", "main_text.txt"]
    files = []
    passed = True
    for rel in required:
        path = root / rel
        exists = path.exists()
        passed = passed and exists and path.stat().st_size > 0 if exists else False
        files.append(
            {
                "path": rel,
                "exists": exists,
                "size_bytes": path.stat().st_size if exists else 0,
                "modified": (
                    datetime.fromtimestamp(
                        path.stat().st_mtime, timezone.utc
                    ).isoformat()
                    if exists
                    else ""
                ),
            }
        )
    return {
        "name": "pdf_artifacts",
        "passed": passed,
        "files": files,
    }


def write_reports(
    root: Path, payload: dict, report_md: Path, report_json: Path
) -> None:
    report_json.parent.mkdir(parents=True, exist_ok=True)
    report_json.write_text(json.dumps(payload, indent=2), encoding="utf-8")

    lines = [
        "# W08 90-Point Master Gate Report",
        "",
        f"Checked at: `{payload['checked_at']}`",
        "",
        f"Overall verdict: **{'PASS' if payload['passed'] else 'FAIL'}**",
        "",
        "## Gates",
        "",
    ]
    for gate in payload["gates"]:
        verdict = "PASS" if gate["passed"] else "FAIL"
        lines.append(f"### {gate['name']}: {verdict}")
        if gate["name"] == "pdf_artifacts":
            for item in gate["files"]:
                status = (
                    "ok" if item["exists"] and item["size_bytes"] > 0 else "missing"
                )
                lines.append(
                    f"- `{item['path']}`: {status}, {item['size_bytes']} bytes"
                )
            lines.append("")
            continue
        lines.append("")
        lines.append("Command:")
        lines.append("")
        lines.append(f"```powershell\n{gate['command']}\n```")
        if gate["stdout"]:
            lines.append("")
            lines.append("Output:")
            lines.append("")
            lines.append(f"```text\n{gate['stdout']}\n```")
        if gate["stderr"]:
            lines.append("")
            lines.append("Stderr:")
            lines.append("")
            lines.append(f"```text\n{gate['stderr']}\n```")
        lines.append("")
    report_md.parent.mkdir(parents=True, exist_ok=True)
    report_md.write_text("\n".join(lines), encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", default=".")
    parser.add_argument("--allow-incomplete", action="store_true")
    parser.add_argument(
        "--report-md", default="results_90pt/90pt_master_gate_report.md"
    )
    parser.add_argument(
        "--report-json", default="results_90pt/90pt_master_gate_report.json"
    )
    args = parser.parse_args()

    root = Path(args.root).resolve()
    py = sys.executable
    gates = [
        run_gate(
            root,
            "claim_evidence",
            [
                py,
                str(root / "experiments_90pt_plan/scripts/validate_claim_evidence.py"),
                "--root",
                str(root),
                "--fail-on-warning",
            ],
        ),
        run_gate(
            root,
            "required_90pt_outputs",
            [
                py,
                str(root / "experiments_90pt_plan/scripts/validate_90pt_package.py"),
                "--root",
                str(root),
            ],
        ),
        run_gate(
            root,
            "review_time_reproducibility",
            [
                py,
                str(
                    root
                    / "experiments_90pt_plan/scripts/validate_reproducibility_gate.py"
                ),
                "--root",
                str(root),
            ],
        ),
        run_gate(
            root,
            "claim_readiness",
            [
                py,
                str(
                    root
                    / "experiments_90pt_plan/scripts/build_claim_readiness_report.py"
                ),
                "--root",
                str(root),
                "--fail-on-blocked",
            ],
        ),
        run_gate(
            root,
            "tifs_90pt_hard_bar",
            [
                py,
                str(
                    root
                    / "experiments_90pt_plan/scripts/validate_tifs_90pt_hard_bar.py"
                ),
                "--root",
                str(root),
            ],
        ),
        run_gate(
            root,
            "tifs_submission_shape",
            [
                py,
                str(
                    root
                    / "experiments_90pt_plan/scripts/validate_tifs_submission_shape.py"
                ),
                "--root",
                str(root),
            ],
        ),
        pdf_status(root),
    ]
    payload = {
        "checked_at": datetime.now(timezone.utc).isoformat(),
        "root": str(root),
        "passed": all(gate["passed"] for gate in gates),
        "gates": gates,
    }
    write_reports(root, payload, root / args.report_md, root / args.report_json)
    print(f"W08 90-point master gate: {'PASS' if payload['passed'] else 'FAIL'}")
    print(f"Markdown report: {root / args.report_md}")
    print(f"JSON report: {root / args.report_json}")
    if not payload["passed"] and not args.allow_incomplete:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
