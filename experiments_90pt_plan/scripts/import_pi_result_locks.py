#!/usr/bin/env python
"""Convert PI-provided W08 result-lock Markdown files into structured CSV sources.

The imported files are manuscript/figure sources. They are not a substitute for raw
trace, adapter, run-log, or full review-archive evidence.
"""

from __future__ import annotations

import argparse
import csv
import json
import re
from datetime import datetime, timezone
from pathlib import Path

SOURCE_RUN_ID = "pi_locked_result_summary_20260623"


ATTACK_MAP = {
    "Identity SFT (Naive)": "identity_control",
    "Paraphrase Rewrite": "paraphrase_second_model",
    "Answer-Only SFT": "answer_only_compression",
    "CoT Compression": "cot_compression",
    "Style Rewrite": "style_rewrite",
    "Temperature/Top-p": "temperature_top_p",
    "Mixed Traces (50%)": "mixed_human_teacher_50pct",
    "Low-Score Selection": "selective_low_score_traces",
}

BASELINE_MAP = {
    "Base-Relative Surplus": "base_relative",
    "Teacher Classifier (Logit-SFT)": "wadhwa_classifier",
    "Model Provenance Testing (MPT)": "model_provenance_testing",
    "Embedding MMD": "embedding_mmd",
    "Style Classifier (SVM/TF-IDF)": "style_classifier",
    "Perplexity/Logprob Shift": "perplexity_logprob",
    "CML (Standard ours)": "CML",
    "CML+MTCR (Refined ours)": "CML+MTCR",
}


def clean_cell(value: str) -> str:
    value = value.strip()
    value = re.sub(r"^\*\*|\*\*$", "", value)
    value = value.replace("**", "")
    value = value.replace("$", "")
    return value.strip()


def parse_float(value: str) -> str:
    value = clean_cell(value)
    value = value.replace("<", "")
    match = re.search(r"-?\d+(?:\.\d+)?", value)
    return match.group(0) if match else ""


def parse_estimate_ci(value: str) -> tuple[str, str, str]:
    value = clean_cell(value)
    match = re.search(
        r"(-?\d+(?:\.\d+)?)\s*\[\s*(-?\d+(?:\.\d+)?)\s*,\s*(-?\d+(?:\.\d+)?)\s*\]",
        value,
    )
    if match:
        return match.group(1), match.group(2), match.group(3)
    estimate = parse_float(value)
    return estimate, "", ""


def markdown_rows(text: str, table_title: str) -> list[list[str]]:
    start = text.find(table_title)
    if start < 0:
        return []
    next_table = text.find("### Table", start + len(table_title))
    block = text[start:] if next_table < 0 else text[start:next_table]
    rows = []
    for line in block.splitlines():
        if not line.strip().startswith("|"):
            continue
        cells = [clean_cell(cell) for cell in line.strip().strip("|").split("|")]
        if (
            not cells
            or cells[0].startswith(":---")
            or cells[0] in {"Evasion Attack", "Teacher Base"}
        ):
            continue
        if cells[0] in {
            "Open-Set Scenario",
            "Provenance Detection Method",
            "Strata",
            "Asset Type",
            "Candidate Teacher",
        }:
            continue
        rows.append(cells)
    return rows


def write_csv(path: Path, fieldnames: list[str], rows: list[dict[str, str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def adaptive_rows(text: str) -> list[dict[str, str]]:
    output = []
    for title, dataset in [
        ("Table 1.1: GSM8K Adaptive Attack Results", "GSM8K"),
        ("Table 1.2: MATH Adaptive Attack Results", "MATH"),
    ]:
        current_attack = ""
        for cells in markdown_rows(text, title):
            if len(cells) < 5:
                continue
            attack, method, auroc_ci, tpr, fpr0 = cells[:5]
            if attack:
                current_attack = attack
            if method not in {"Base-Relative", "CML+MTCR"}:
                continue
            auroc, ci_low, ci_high = parse_estimate_ci(auroc_ci)
            output.append(
                {
                    "experiment": "adaptive_attack",
                    "attack_type": ATTACK_MAP.get(current_attack, current_attack),
                    "attack_label": current_attack,
                    "detection_method": method,
                    "attack_strength": (
                        "50pct" if "Mixed" in current_attack else "standard"
                    ),
                    "dataset": dataset,
                    "student_base": "Qwen2.5-7B",
                    "teacher_family": "R1-Qwen",
                    "seed": "aggregate_5_student_seeds",
                    "auroc": auroc,
                    "tpr_at_1pct_fpr": parse_float(tpr),
                    "fpr_zero": parse_float(fpr0),
                    "ci_low": ci_low,
                    "ci_high": ci_high,
                    "n_students": "5",
                    "threshold_source": "calibration_controls_to_heldout_controls",
                    "source_run_id": SOURCE_RUN_ID,
                }
            )
    return output


def cross_base_rows(text: str) -> list[dict[str, str]]:
    rows = []
    current_teacher = ""
    tasks = ["GSM8K", "MATH", "BBH", "ARC-Challenge", "MBPP"]
    for cells in markdown_rows(text, "Table 2: Generalization AUROC Matrix"):
        if len(cells) < 7:
            continue
        teacher, student, *scores = cells[:7]
        if teacher:
            current_teacher = teacher
        student_clean = re.sub(r"\s*\((Same|Cross)\)", "", student).strip()
        regime = "same_base" if "(Same)" in student else "cross_base"
        for task, score in zip(tasks, scores):
            rows.append(
                {
                    "experiment": "cross_base_task",
                    "dataset": task,
                    "student_base": student_clean,
                    "teacher_family": current_teacher,
                    "teacher_model": current_teacher,
                    "student_training": regime,
                    "seed": "aggregate_5_student_seeds",
                    "auroc": parse_float(score),
                    "tpr_at_1pct_fpr": "",
                    "fpr_zero": "",
                    "ci_low": "",
                    "ci_high": "",
                    "n_students": "5",
                    "source_run_id": SOURCE_RUN_ID,
                }
            )
    return rows


def open_set_rows(text: str) -> list[dict[str, str]]:
    rows = []
    for cells in markdown_rows(text, "Table 3: Open-Set Attribution Metrics"):
        if len(cells) < 5:
            continue
        scenario, true_lineage, abstention, false_attr, coverage = cells[:5]
        condition = scenario.lower().replace(" ", "_").replace("-", "_")
        rows.append(
            {
                "experiment": "open_set",
                "condition": condition,
                "dataset": "GSM8K",
                "student_base": "Qwen2.5-7B",
                "true_teacher": true_lineage,
                "candidate_set": "closed_set_with_absent_or_decoy_candidate",
                "pred_teacher": "ABSTAIN_OR_TOP_CANDIDATE",
                "abstention_rate": parse_float(abstention),
                "false_attribution_rate": parse_float(false_attr),
                "closed_set_accuracy": "",
                "coverage": parse_float(coverage),
                "auroc": "",
                "tpr_at_1pct_fpr": "",
                "source_run_id": SOURCE_RUN_ID,
            }
        )
    return rows


def baseline_rows(text: str) -> list[dict[str, str]]:
    rows = []
    for cells in markdown_rows(text, "Table 4: Baseline Comparison Matrix"):
        if len(cells) < 5:
            continue
        method, detection, same_family, sibling_acc, fpr0 = cells[:5]
        rows.append(
            {
                "experiment": "baseline_head_to_head",
                "method": BASELINE_MAP.get(method, method),
                "dataset": "GSM8K",
                "student_base": "Qwen2.5-7B",
                "teacher_family": "R1-Qwen",
                "condition": "unified_calibration",
                "seed": "aggregate_5_student_seeds",
                "auroc": parse_float(detection),
                "same_family_auroc": parse_float(same_family),
                "sibling_attribution_accuracy": parse_float(sibling_acc),
                "tpr_at_1pct_fpr": "",
                "fpr_zero": parse_float(fpr0),
                "ci_low": "",
                "ci_high": "",
                "n_students": "5",
                "access_tier": "black_box_scoring_with_candidate_access",
                "source_run_id": SOURCE_RUN_ID,
            }
        )
    return rows


def student_ci_rows(text: str) -> list[dict[str, str]]:
    rows = []
    for cells in markdown_rows(text, "Table 5: Student-Level Significance"):
        if len(cells) < 6:
            continue
        strata, student_mean, control_mean, margin, pvalue, ci = cells[:6]
        _, ci_low, ci_high = parse_estimate_ci(f"0 {ci}")
        rows.append(
            {
                "experiment": "student_level_ci",
                "dataset": "GSM8K",
                "student_base": "Qwen2.5-7B",
                "teacher_family": "R1-Qwen",
                "condition": strata.lower().replace(" ", "_").replace(".", ""),
                "n_students": "5",
                "student_unit": "student_seed",
                "metric": "effect_size_margin",
                "student_mean_max_statistic": parse_float(student_mean),
                "control_mean_max_statistic": parse_float(control_mean),
                "estimate": parse_float(margin),
                "ci_low": ci_low,
                "ci_high": ci_high,
                "permutation_p": parse_float(pvalue),
                "threshold_split": "calibration_controls_to_heldout_controls",
                "heldout_fpr": "0.01",
                "source_run_id": SOURCE_RUN_ID,
            }
        )
    return rows


def mtcr_rows(text: str) -> list[dict[str, str]]:
    rows = []
    tasks = ["GSM8K", "MATH", "BBH", "ARC", "MBPP", "MMLU"]
    for cells in markdown_rows(text, "Table 7: Sibling Logprob Surplus"):
        if len(cells) < 7:
            continue
        candidate, *scores = cells[:7]
        for task, score in zip(tasks, scores):
            rows.append(
                {
                    "experiment": "mtcr_raw_profile_result_lock",
                    "condition": "per_task_reference_profile",
                    "task_view": task,
                    "candidate_teacher": candidate,
                    "reference_model": "multi_task_calibration_reference",
                    "student_id": "aggregate_5_student_seeds",
                    "seed": "aggregate",
                    "score_cml": "",
                    "score_mtcr": parse_float(score),
                    "source_run_id": SOURCE_RUN_ID,
                }
            )
    return rows


def review_archive_rows(text: str) -> list[dict[str, str]]:
    mapping = {
        "Raw Traces": "raw_trace",
        "Adapter Checkpoints": "adapter_checkpoint",
        "Scored Likelihood Matrices": "scored_matrix",
        "Environment Lock": "environment_lock",
        "Analysis Code": "analysis_code",
    }
    rows = []
    for index, cells in enumerate(
        markdown_rows(text, "Table 6: Review Archive Manifest"), start=1
    ):
        if len(cells) < 5:
            continue
        asset_type, pattern, summary, revision_hash, size = cells[:5]
        rows.append(
            {
                "artifact_id": f"pi-lock-review-{index:02d}",
                "asset_type": asset_type,
                "file_or_path_pattern": pattern,
                "content_summary": summary,
                "revision_hash": revision_hash,
                "size": size,
                "artifact_class": mapping.get(asset_type, ""),
                "source_run_id": SOURCE_RUN_ID,
                "validation_status": "result_lock_descriptive_not_file_verified",
            }
        )
    return rows


def coverage_report(rows_by_name: dict[str, list[dict[str, str]]]) -> tuple[dict, str]:
    hard_bar = {
        "adaptive_attack": bool(rows_by_name["adaptive"]),
        "cross_base_task": bool(rows_by_name["cross_base"]),
        "open_set_abstention": bool(rows_by_name["open_set"]),
        "baseline_head_to_head": bool(rows_by_name["baseline"]),
        "student_level_ci": bool(rows_by_name["student_ci"]),
        "mtcr_task_profiles": bool(rows_by_name["mtcr"]),
        "review_archive_descriptive_only": bool(rows_by_name["review_archive"]),
    }
    blocking = {
        "adaptive_attack": "summary-level rows only; no per-trace scored matrix",
        "cross_base_task": "AUROC matrix only; no TPR@1%FPR/FPR0/CI columns in result lock",
        "open_set_abstention": "abstention/false-attribution/coverage only; no AUROC/TPR columns",
        "baseline_head_to_head": "no per-seed CI or TPR@1%FPR in result lock",
        "student_level_ci": "usable for manuscript; only three strata in result lock",
        "mtcr_task_profiles": "task surplus summary only; not raw per-view scored matrix",
        "review_archive": "descriptive patterns and truncated hashes; no local file verification",
    }
    payload = {
        "checked_at": datetime.now(timezone.utc).isoformat(),
        "source_run_id": SOURCE_RUN_ID,
        "coverage": hard_bar,
        "row_counts": {name: len(rows) for name, rows in rows_by_name.items()},
        "blocking_notes": blocking,
    }
    lines = [
        "# PI Result Lock Coverage For W08 TIFS 90-Point Target",
        "",
        f"Checked at: `{payload['checked_at']}`",
        "",
        "These tables are manuscript/figure sources from PI-provided result locks. They do not replace raw trace, adapter, run-log, or review-archive evidence.",
        "",
        "## Imported Rows",
        "",
    ]
    for name, rows in rows_by_name.items():
        lines.append(f"- `{name}`: {len(rows)} rows")
    lines.extend(["", "## Remaining Hard-Bar Caveats", ""])
    for name, note in blocking.items():
        lines.append(f"- **{name}**: {note}")
    return payload, "\n".join(lines) + "\n"


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", default=".")
    parser.add_argument("--ideal-results", required=True)
    parser.add_argument("--out-dir", default="results_90pt/pi_result_locks")
    args = parser.parse_args()

    root = Path(args.root)
    text = Path(args.ideal_results).read_text(encoding="utf-8")
    out_dir = root / args.out_dir

    rows_by_name = {
        "adaptive": adaptive_rows(text),
        "cross_base": cross_base_rows(text),
        "open_set": open_set_rows(text),
        "baseline": baseline_rows(text),
        "student_ci": student_ci_rows(text),
        "mtcr": mtcr_rows(text),
        "review_archive": review_archive_rows(text),
    }

    write_csv(
        out_dir / "tifs_adaptive_attack_summary.csv",
        list(rows_by_name["adaptive"][0].keys()) if rows_by_name["adaptive"] else [],
        rows_by_name["adaptive"],
    )
    write_csv(
        out_dir / "tifs_cross_base_task_matrix.csv",
        (
            list(rows_by_name["cross_base"][0].keys())
            if rows_by_name["cross_base"]
            else []
        ),
        rows_by_name["cross_base"],
    )
    write_csv(
        out_dir / "tifs_open_set_abstention_summary.csv",
        list(rows_by_name["open_set"][0].keys()) if rows_by_name["open_set"] else [],
        rows_by_name["open_set"],
    )
    write_csv(
        out_dir / "tifs_baseline_head_to_head.csv",
        list(rows_by_name["baseline"][0].keys()) if rows_by_name["baseline"] else [],
        rows_by_name["baseline"],
    )
    write_csv(
        out_dir / "tifs_student_level_ci.csv",
        (
            list(rows_by_name["student_ci"][0].keys())
            if rows_by_name["student_ci"]
            else []
        ),
        rows_by_name["student_ci"],
    )
    write_csv(
        out_dir / "tifs_mtcr_task_profile_summary.csv",
        list(rows_by_name["mtcr"][0].keys()) if rows_by_name["mtcr"] else [],
        rows_by_name["mtcr"],
    )
    write_csv(
        out_dir / "tifs_review_archive_descriptive_manifest.csv",
        (
            list(rows_by_name["review_archive"][0].keys())
            if rows_by_name["review_archive"]
            else []
        ),
        rows_by_name["review_archive"],
    )

    payload, markdown = coverage_report(rows_by_name)
    (out_dir / "pi_result_lock_coverage_report.json").write_text(
        json.dumps(payload, indent=2), encoding="utf-8"
    )
    (out_dir / "pi_result_lock_coverage_report.md").write_text(
        markdown, encoding="utf-8"
    )
    print(f"Imported PI result locks into {out_dir}")
    print(markdown)


if __name__ == "__main__":
    main()
