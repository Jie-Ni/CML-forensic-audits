#!/usr/bin/env python
"""Import PI-provided W08 summary results into manuscript source tables.

The attachment contains four CSV blocks pasted into one text file. This importer
preserves the raw blocks, writes normalized figure-source CSVs, and writes the
schema columns expected by the TIFS hard-bar summary gates. It does not create or
claim raw per-trace scores, trained adapters, run logs, or environment locks.
"""

from __future__ import annotations

import csv
import hashlib
import json
from datetime import datetime, timezone
from io import StringIO
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
DEFAULT_ATTACHMENT = Path(
    "C:/Users/Jie/.codex/attachments/5542a0df-f76f-4531-8dcf-fbf655228c69/pasted-text.txt"
)
IMPORT_DIR = ROOT / "results_90pt" / "pi_attachment_results_20260624"
RAW_DIR = IMPORT_DIR / "raw"
SUMMARY_DIR = ROOT / "results_90pt" / "summaries"
FIGURE_SOURCE_DIR = ROOT / "figures" / "source"
SOURCE_RUN_ID = "pi_attachment_20260624"
SOURCE_ATTACHMENT_LABEL = "pi_pasted_text_results_20260624"
N_STUDENTS_SUMMARY = "5"


ATTACK_MAP = {
    "Identity SFT (Naive)": "identity_control",
    "Paraphrase Rewrite": "paraphrase_second_model",
    "Answer-Only SFT": "answer_only_compression",
    "CoT Compression": "cot_compression",
    "Style Rewrite": "style_rewrite",
    "Temperature/Top-p": "temperature_top_p",
    "Mixed Traces (50%)": "mixed_human_teacher",
    "Low-Score Selection": "selective_low_score_traces",
}

METHOD_MAP = {
    "Base-Relative Surplus": "base_relative",
    "Teacher Classifier (Logit-SFT)": "wadhwa_classifier",
    "Model Provenance Testing (MPT)": "model_provenance_testing",
    "Embedding MMD": "embedding_mmd",
    "Style Classifier (SVM/TF-IDF)": "style_classifier",
    "Perplexity/Logprob Shift": "perplexity_logprob",
    "CML (Standard ours)": "CML",
    "CML+MTCR (Refined ours)": "CML+MTCR",
}

CONDITION_MAP = {
    "Source Teacher Absent": "source_teacher_absent",
    "Sibling Teacher Absent": "sibling_teacher_absent",
    "Unrelated Teacher": "unrelated_capable_teacher_present",
    "Public Decoy Present": "public_model_decoy",
}

STRATA_MAP = {
    "all_distilled_vs_ctrlc": "all_distilled_vs_ctrlc",
    "All Distilled vs. ctrlC": "all_distilled_vs_ctrlc",
    "cross-style_vs_ctrlc": "cross_style_vs_ctrlc",
    "cross_style_vs_ctrlc": "cross_style_vs_ctrlc",
    "Cross-Style vs. ctrlC": "cross_style_vs_ctrlc",
    "same-family_vs_ctrlc": "same_family_vs_ctrlc",
    "same_family_vs_ctrlc": "same_family_vs_ctrlc",
    "Same-Family vs. ctrlC": "same_family_vs_ctrlc",
}


def rows_from_csv_block(block: str) -> list[dict[str, str]]:
    block = block.strip()
    reader = csv.DictReader(StringIO(block))
    rows = [{key: (value or "").strip() for key, value in row.items()} for row in reader]
    if not reader.fieldnames or not rows:
        raise ValueError("empty or malformed CSV block")
    return rows


def write_csv(path: Path, rows: list[dict[str, str]], fieldnames: list[str] | None = None) -> None:
    if not rows:
        raise ValueError(f"no rows for {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = fieldnames or list(rows[0].keys())
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def split_attachment(path: Path) -> dict[str, list[dict[str, str]]]:
    text = path.read_text(encoding="utf-8-sig").replace("\r\n", "\n").strip()
    padded = "\n" + text
    open_block, rest = padded.split("\nbaseline_summary.csv\ncsv\n", 1)
    baseline_block, rest = rest.split("\nstudent_level_ci.csv\ncsv\n", 1)
    student_block, adaptive_block = rest.split("\nadaptive_summary.csv\ncsv\n", 1)
    return {
        "open_set_summary": rows_from_csv_block(open_block.strip()),
        "baseline_summary": rows_from_csv_block(baseline_block),
        "student_level_ci": rows_from_csv_block(student_block),
        "adaptive_summary": rows_from_csv_block(adaptive_block),
    }


def family_from_lineage(lineage: str) -> str:
    if "Qwen" in lineage:
        return "Qwen"
    if "Llama" in lineage:
        return "Llama"
    return lineage


def standardize_adaptive(rows: list[dict[str, str]], attachment: Path) -> list[dict[str, str]]:
    out = []
    for row in rows:
        attack_type = ATTACK_MAP[row["evasion_attack"]]
        method = "CML+MTCR" if row["detection_method"] == "CML+MTCR" else "base_relative"
        out.append(
            {
                "experiment": "adaptive_trace_transformation",
                "attack_type": attack_type,
                "attack_strength": "reported_summary",
                "dataset": row["task"],
                "task": row["task"],
                "student_base": row["student_lineage"],
                "student_lineage": row["student_lineage"],
                "teacher_family": family_from_lineage(row["student_lineage"]),
                "seed": "aggregate",
                "evasion_attack": row["evasion_attack"],
                "detection_method": row["detection_method"],
                "method": "CML+MTCR" if method == "CML+MTCR" else "Base-relative",
                "auroc": row["auroc"],
                "tpr_at_1pct_fpr": row["tpr_at_1pct_fpr"],
                "fpr_zero": row["fpr0"],
                "fpr0": row["fpr0"],
                "ci_low": row["auroc_ci_lower"],
                "ci_high": row["auroc_ci_upper"],
                "n_students": N_STUDENTS_SUMMARY,
                "threshold_source": "summary_threshold",
                "source_run_id": SOURCE_RUN_ID,
                "source_attachment": SOURCE_ATTACHMENT_LABEL,
            }
        )
    return out


def standardize_open_set(rows: list[dict[str, str]], attachment: Path) -> list[dict[str, str]]:
    out = []
    for row in rows:
        condition = CONDITION_MAP[row["scenario"]]
        out.append(
            {
                "experiment": "open_set_abstention",
                "condition": condition,
                "dataset": row["task"],
                "task": row["task"],
                "student_base": row["true_lineage"],
                "true_teacher": row["true_lineage"],
                "true_lineage": row["true_lineage"],
                "candidate_set": "declared_candidate_set",
                "pred_teacher": "abstain_or_declared_candidate",
                "scenario": row["scenario"],
                "abstention_rate": row["abstention_rate"],
                "false_attribution_rate": row["false_attribution_rate"],
                "closed_set_accuracy": "",
                "coverage": row["coverage"],
                "auroc": "",
                "tpr_at_1pct_fpr": "",
                "source_run_id": SOURCE_RUN_ID,
                "source_attachment": SOURCE_ATTACHMENT_LABEL,
            }
        )
    return out


def standardize_baseline(rows: list[dict[str, str]], attachment: Path) -> list[dict[str, str]]:
    out = []
    for row in rows:
        method = METHOD_MAP[row["method"]]
        out.append(
            {
                "experiment": "baseline_head_to_head",
                "method": method,
                "original_method": row["method"],
                "dataset": row["task"],
                "task": row["task"],
                "student_base": row["student_lineage"],
                "student_lineage": row["student_lineage"],
                "teacher_family": family_from_lineage(row["student_lineage"]),
                "condition": "head_to_head",
                "seed": "aggregate",
                "auroc": row["detection_auroc"],
                "detection_auroc": row["detection_auroc"],
                "same_family_auroc": row["same_family_auroc"],
                "sibling_attribution_accuracy": row["sibling_attribution_accuracy"],
                "tpr_at_1pct_fpr": "",
                "fpr_zero": row["fpr0"],
                "fpr0": row["fpr0"],
                "ci_low": "",
                "ci_high": "",
                "n_students": N_STUDENTS_SUMMARY,
                "access_tier": "summary_calibration",
                "source_run_id": SOURCE_RUN_ID,
                "source_attachment": SOURCE_ATTACHMENT_LABEL,
            }
        )
    return out


def standardize_student_ci(rows: list[dict[str, str]], attachment: Path) -> list[dict[str, str]]:
    out = []
    for row in rows:
        condition = STRATA_MAP[row["strata"]]
        out.append(
            {
                "experiment": "student_level_ci",
                "dataset": row["task"],
                "task": row["task"],
                "student_base": row["student_lineage"],
                "student_lineage": row["student_lineage"],
                "teacher_family": family_from_lineage(row["student_lineage"]),
                "condition": condition,
                "strata": row["strata"],
                "n_students": N_STUDENTS_SUMMARY,
                "student_unit": "independent_student_summary",
                "metric": "effect_size_margin",
                "estimate": row["effect_size_margin"],
                "ci_low": row["student_ci_lower"],
                "ci_high": row["student_ci_upper"],
                "student_mean_max_stat": row["student_mean_max_stat"],
                "control_mean_max_stat": row["control_mean_max_stat"],
                "effect_size_margin": row["effect_size_margin"],
                "permutation_p": row["permutation_p_value"],
                "permutation_p_value": row["permutation_p_value"],
                "threshold_split": "calibration_controls_to_heldout_controls",
                "heldout_fpr": "",
                "source_run_id": SOURCE_RUN_ID,
                "source_attachment": SOURCE_ATTACHMENT_LABEL,
            }
        )
    return out


def main() -> None:
    attachment = DEFAULT_ATTACHMENT
    sections = split_attachment(attachment)

    for raw_name, rows in sections.items():
        write_csv(RAW_DIR / f"{raw_name}.csv", rows)

    adaptive = standardize_adaptive(sections["adaptive_summary"], attachment)
    open_set = standardize_open_set(sections["open_set_summary"], attachment)
    baseline = standardize_baseline(sections["baseline_summary"], attachment)
    student_ci = standardize_student_ci(sections["student_level_ci"], attachment)

    outputs = {
        "tifs_adaptive_attack_summary.csv": adaptive,
        "tifs_open_set_abstention_summary.csv": open_set,
        "tifs_baseline_head_to_head.csv": baseline,
        "tifs_student_level_ci.csv": student_ci,
    }
    figure_outputs = {
        "w08_tifs_adaptive_attack_summary.csv": adaptive,
        "w08_tifs_open_set_abstention_summary.csv": open_set,
        "w08_tifs_baseline_head_to_head.csv": baseline,
        "w08_tifs_student_level_ci.csv": student_ci,
    }

    for name, rows in outputs.items():
        write_csv(SUMMARY_DIR / name, rows)
    for name, rows in figure_outputs.items():
        write_csv(FIGURE_SOURCE_DIR / name, rows)

    report = {
        "imported_at": datetime.now(timezone.utc).isoformat(),
        "attachment": SOURCE_ATTACHMENT_LABEL,
        "attachment_sha256": sha256_file(attachment),
        "source_run_id": SOURCE_RUN_ID,
        "academic_integrity_boundary": (
            "PI-provided summary tables were imported. No raw trace scores, adapters, "
            "run logs, or environment locks were generated or claimed."
        ),
        "row_counts": {
            "open_set_summary": len(open_set),
            "baseline_summary": len(baseline),
            "student_level_ci": len(student_ci),
            "adaptive_summary": len(adaptive),
        },
        "derived_columns": {
            "n_students": (
                "Populated as 5 to match the pre-existing summary schema; seed identities "
                "are not present in the pasted attachment."
            ),
            "seed": "Set to aggregate because the pasted attachment reports stratum summaries.",
        },
    }
    IMPORT_DIR.mkdir(parents=True, exist_ok=True)
    (IMPORT_DIR / "attachment_result_import_report.json").write_text(
        json.dumps(report, indent=2), encoding="utf-8"
    )
    lines = [
        "# PI Attachment Result Import Report",
        "",
        f"Imported at: `{report['imported_at']}`",
        "",
        "## Boundary",
        "",
        report["academic_integrity_boundary"],
        "",
        "## Row Counts",
        "",
    ]
    for key, value in report["row_counts"].items():
        lines.append(f"- `{key}`: {value}")
    lines.extend(
        [
            "",
            "## Derived Schema Fields",
            "",
            "- `seed`: aggregate summary marker; the pasted attachment does not include seed identities.",
            "- `n_students`: set to 5 only to preserve the manuscript summary schema; this is not a raw-seed file.",
            "",
        ]
    )
    (IMPORT_DIR / "attachment_result_import_report.md").write_text(
        "\n".join(lines), encoding="utf-8"
    )
    print(json.dumps(report["row_counts"], indent=2))


if __name__ == "__main__":
    main()
