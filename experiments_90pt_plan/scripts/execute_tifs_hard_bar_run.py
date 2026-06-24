#!/usr/bin/env python
"""Plan or execute one TIFS hard-bar run-matrix row.

Default behavior is a dry-run plan. Use --execute only inside a PI-approved HPC job.
The script never fabricates missing data and never substitutes local diagnostic
derivations for 90-point evidence.
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import subprocess
import sys
from pathlib import Path

DEFAULT_CANDIDATES = [
    "r1-distill-qwen-32b",
    "r1-distill-llama-8b",
    "qwen2.5-14b",
    "qwen2.5-7b",
]

LOCAL_ATTACK_RECIPES = {
    "identity_control": ["--condition", "identity_control"],
    "answer_only_compression": ["--condition", "answer_only_compression"],
    "cot_compression": ["--condition", "cot_compression", "--keep-sentences", "3"],
}

EXTERNAL_ATTACK_RECIPES = {
    "paraphrase_second_model": ["--condition", "paraphrase_second_model"],
    "style_rewrite": ["--condition", "style_rewrite"],
}


def read_tsv(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        return []
    with path.open("r", encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle, delimiter="\t"))


def quote(value: str | Path) -> str:
    return '"' + str(value).replace('"', '\\"') + '"'


def py(root: Path, relative: str) -> str:
    return f"{quote(sys.executable)} {quote(root / relative)}"


def legacy_script(name: str) -> str:
    default = (
        "C:/Users/Jie/Desktop/codex/paper_portfolio_2026/project_roots/"
        "LLM_Distillation_Provenance/scripts"
    )
    base = Path(os.environ.get("W08_LEGACY_SCRIPTS", default))
    return str(base / name)


def load_run(root: Path, run_id: str | None, array_index: int | None) -> dict[str, str]:
    rows = read_tsv(root / "experiments_90pt_plan/tifs_hard_bar_run_matrix.tsv")
    if array_index is not None:
        if array_index < 1 or array_index > len(rows):
            raise SystemExit(f"array index {array_index} outside 1..{len(rows)}")
        return rows[array_index - 1]
    if not run_id:
        raise SystemExit("Provide --run-id or --array-index")
    for row in rows:
        if row["run_id"] == run_id:
            return row
    raise SystemExit(f"Unknown run_id: {run_id}")


def candidate_teachers(root: Path) -> list[str]:
    rows = read_tsv(root / "results_90pt/raw_trace_manifests/candidate_teachers.tsv")
    values = [
        row["candidate_teacher"]
        for row in rows
        if row.get("candidate_teacher")
        and row.get("include_in_closed_set", "yes") != "no"
    ]
    return values or DEFAULT_CANDIDATES


def raw_trace_inputs(root: Path, run: dict[str, str]) -> list[dict[str, str]]:
    rows = read_tsv(root / "results_90pt/raw_trace_manifests/raw_trace_inputs.tsv")
    wanted = run["dataset"].lower()
    filtered = [row for row in rows if row.get("dataset", "").lower() == wanted]
    if run.get("student_base") not in {"", "all"} and filtered:
        with_base = [
            row
            for row in filtered
            if row.get("student_base", run["student_base"]) == run["student_base"]
        ]
        if with_base:
            filtered = with_base
    return filtered


def external_rewrite_map(
    root: Path, run: dict[str, str]
) -> dict[tuple[str, str, str], str]:
    rows = read_tsv(root / "results_90pt/raw_trace_manifests/external_rewrites.tsv")
    out = {}
    for row in rows:
        if row.get("dataset", "").lower() != run["dataset"].lower():
            continue
        if row.get("run_id") not in {"", run["run_id"]}:
            continue
        if row.get("condition") not in {"", run["condition"]}:
            continue
        key = (row.get("student_id", ""), row.get("seed", ""), row.get("dataset", ""))
        out[key] = row.get("external_rewrite_path", "")
    return out


def append_score_commands(
    root: Path, commands: list[str], trace_paths: list[Path], outdir: Path
) -> None:
    if not trace_paths:
        return
    for candidate in candidate_teachers(root):
        commands.append(
            " ".join(
                [
                    quote(sys.executable),
                    quote(legacy_script("score_traces.py")),
                    "--candidate",
                    candidate,
                    "--outdir",
                    quote(outdir / candidate),
                    "--traces",
                    *[quote(path) for path in trace_paths],
                ]
            )
        )


def adaptive_attack_commands(
    root: Path, run: dict[str, str]
) -> tuple[list[str], list[str]]:
    commands: list[str] = []
    blockers: list[str] = []
    condition = run["condition"]
    traces = raw_trace_inputs(root, run)
    if not traces:
        return [], [f"missing raw_trace_inputs rows for dataset={run['dataset']}"]

    mixed_manifest = root / "results_90pt/raw_trace_manifests/mixed_trace_inputs.tsv"
    if condition.startswith("mixed_human_teacher_"):
        rows = read_tsv(mixed_manifest)
        if not rows:
            return [], [f"missing mixed trace manifest: {mixed_manifest}"]
        trace_paths = [
            Path(row["mixed_trace_path"])
            for row in rows
            if row.get("condition") == condition and row.get("mixed_trace_path")
        ]
        if not trace_paths:
            return [], [f"mixed_trace_inputs.tsv has no rows for condition={condition}"]
        append_score_commands(
            root,
            commands,
            trace_paths,
            root
            / "results_90pt/scored_tifs_adaptive"
            / condition
            / run["dataset"].lower(),
        )
    elif condition == "temperature_top_p":
        return [], [
            "temperature_top_p requires regenerated suspect traces with decoding "
            "metadata staged in raw_trace_inputs.tsv; no local rewrite is valid"
        ]
    elif condition == "selective_low_score_traces":
        selector_source = (
            root
            / "results_90pt/scored_matrices/tifs_adaptive_attack_trace_scores.parquet"
        )
        if not selector_source.exists():
            return [], [
                "selective_low_score_traces requires completed identity/control "
                f"scores first: {selector_source}"
            ]
        commands.append(
            " ".join(
                [
                    py(
                        root,
                        "experiments_90pt_plan/scripts/select_tifs_low_score_traces.py",
                    ),
                    "--root",
                    quote(root),
                    "--dataset",
                    run["dataset"],
                    "--out",
                    quote(
                        root
                        / "results_90pt/traces_laundered/selective_low_score_traces"
                        / f"{run['dataset'].lower()}.jsonl"
                    ),
                ]
            )
        )
    else:
        if (
            condition not in LOCAL_ATTACK_RECIPES
            and condition not in EXTERNAL_ATTACK_RECIPES
        ):
            return [], [f"unsupported adaptive attack condition: {condition}"]
        rewrites = external_rewrite_map(root, run)
        trace_paths = []
        for row in traces:
            trace_path = row.get("trace_path", "")
            if not trace_path:
                blockers.append(f"raw_trace_inputs row lacks trace_path: {row}")
                continue
            student = row.get("student_id", "student")
            seed = row.get("seed", "0")
            out = (
                root
                / "results_90pt/traces_laundered"
                / condition
                / run["dataset"].lower()
                / f"{student}_s{seed}.jsonl"
            )
            recipe = (
                LOCAL_ATTACK_RECIPES.get(condition)
                or EXTERNAL_ATTACK_RECIPES[condition]
            )
            command = [
                py(root, "experiments_90pt_plan/scripts/make_laundered_traces.py"),
                "--input",
                quote(trace_path),
                "--out",
                quote(out),
                *recipe,
            ]
            if condition in EXTERNAL_ATTACK_RECIPES:
                key = (student, seed, run["dataset"])
                rewrite_path = rewrites.get(key, "")
                if not rewrite_path:
                    blockers.append(f"missing external rewrite for {condition} {key}")
                    continue
                command.extend(["--external-rewrite-jsonl", quote(rewrite_path)])
            commands.append(" ".join(command))
            trace_paths.append(out)
        append_score_commands(
            root,
            commands,
            trace_paths,
            root
            / "results_90pt/scored_tifs_adaptive"
            / condition
            / run["dataset"].lower(),
        )

    if commands and not blockers:
        commands.append(
            " ".join(
                [
                    py(
                        root,
                        "experiments_90pt_plan/scripts/assemble_tifs_hard_bar_tables.py",
                    ),
                    "--root",
                    quote(root),
                    "--run-id",
                    run["run_id"],
                    "--experiment",
                    "adaptive_attack",
                    "--condition",
                    condition,
                    "--dataset",
                    run["dataset"],
                    "--scored-dir",
                    quote(
                        root
                        / "results_90pt/scored_tifs_adaptive"
                        / condition
                        / run["dataset"].lower()
                    ),
                ]
            )
        )
    return commands, blockers


def generic_scored_run(
    root: Path, run: dict[str, str], experiment: str
) -> tuple[list[str], list[str]]:
    traces = raw_trace_inputs(root, run)
    if not traces:
        return [], [f"missing raw_trace_inputs rows for dataset={run['dataset']}"]
    trace_paths = [Path(row["trace_path"]) for row in traces if row.get("trace_path")]
    if not trace_paths:
        return [], ["raw_trace_inputs rows exist but no trace_path values are present"]
    outdir = (
        root
        / "results_90pt"
        / f"scored_tifs_{experiment}"
        / run["condition"]
        / run["dataset"].lower()
    )
    commands: list[str] = []
    append_score_commands(root, commands, trace_paths, outdir)
    commands.append(
        " ".join(
            [
                py(
                    root,
                    "experiments_90pt_plan/scripts/assemble_tifs_hard_bar_tables.py",
                ),
                "--root",
                quote(root),
                "--run-id",
                run["run_id"],
                "--experiment",
                experiment,
                "--condition",
                run["condition"],
                "--dataset",
                run["dataset"],
                "--scored-dir",
                quote(outdir),
            ]
        )
    )
    return commands, []


def cross_base_task_commands(
    root: Path, run: dict[str, str]
) -> tuple[list[str], list[str]]:
    rows = read_tsv(
        root / "results_90pt/raw_trace_manifests/student_training_inputs.tsv"
    )
    rows = [row for row in rows if row.get("run_id") == run["run_id"]]
    if not rows:
        return [], [f"missing student_training_inputs rows for run_id={run['run_id']}"]
    commands: list[str] = []
    blockers: list[str] = []
    for row in rows:
        missing = [
            key
            for key in [
                "student_base",
                "sft_jsonl",
                "adapter_out_dir",
                "trace_out_path",
            ]
            if not row.get(key)
        ]
        if missing:
            blockers.append(f"{run['run_id']} row missing: {', '.join(missing)}")
            continue
        commands.append(
            " ".join(
                [
                    quote(sys.executable),
                    quote(legacy_script("train_student.py")),
                    "--base",
                    row["student_base"],
                    "--sft_jsonl",
                    quote(row["sft_jsonl"]),
                    "--out_dir",
                    quote(row["adapter_out_dir"]),
                    "--seed",
                    row.get("seed", "0"),
                ]
            )
        )
        commands.append(
            " ".join(
                [
                    quote(sys.executable),
                    quote(legacy_script("gen_traces.py")),
                    "--teacher",
                    row["student_base"],
                    "--adapter",
                    quote(row["adapter_out_dir"]),
                    "--label",
                    f"{run['condition']}_s{row.get('seed', '0')}",
                    "--task",
                    run["dataset"].lower(),
                    "--n",
                    run.get("trace_budget", "200"),
                    "--out",
                    quote(row["trace_out_path"]),
                    "--seed",
                    row.get("seed", "0"),
                ]
            )
        )
    if commands and not blockers:
        commands.append(
            " ".join(
                [
                    py(
                        root,
                        "experiments_90pt_plan/scripts/assemble_tifs_hard_bar_tables.py",
                    ),
                    "--root",
                    quote(root),
                    "--run-id",
                    run["run_id"],
                    "--experiment",
                    "cross_base_task",
                    "--condition",
                    run["condition"],
                    "--dataset",
                    run["dataset"],
                ]
            )
        )
    return commands, blockers


def baseline_commands(root: Path, run: dict[str, str]) -> tuple[list[str], list[str]]:
    rows = read_tsv(root / "results_90pt/raw_trace_manifests/baseline_inputs.tsv")
    rows = [
        row
        for row in rows
        if row.get("method", "").lower() == run["condition"].lower()
        and row.get("dataset", "").lower() == run["dataset"].lower()
    ]
    if not rows:
        return [], [f"missing baseline_inputs rows for method={run['condition']}"]
    out = root / "results_90pt/summaries/tifs_baseline_head_to_head.csv"
    return [
        " ".join(
            [
                py(
                    root,
                    "experiments_90pt_plan/scripts/run_tifs_baseline_from_manifest.py",
                ),
                "--root",
                quote(root),
                "--run-id",
                run["run_id"],
                "--method",
                run["condition"],
                "--dataset",
                run["dataset"],
                "--out",
                quote(out),
            ]
        )
    ], []


def student_ci_commands(root: Path, run: dict[str, str]) -> tuple[list[str], list[str]]:
    inputs = [
        root / "results_90pt/summaries/tifs_adaptive_attack_summary.csv",
        root / "results_90pt/summaries/tifs_open_set_abstention_summary.csv",
        root / "results_90pt/summaries/tifs_cross_base_task_matrix.csv",
    ]
    missing = [str(path) for path in inputs if not path.exists()]
    if missing:
        return [], [
            "student-level CI requires summary tables first: " + ", ".join(missing)
        ]
    return [
        " ".join(
            [
                py(
                    root,
                    "experiments_90pt_plan/scripts/compute_tifs_student_level_ci.py",
                ),
                "--root",
                quote(root),
                "--condition",
                run["condition"],
                "--dataset",
                run["dataset"],
            ]
        )
    ], []


def review_archive_commands(
    root: Path, run: dict[str, str]
) -> tuple[list[str], list[str]]:
    return [
        " ".join(
            [
                py(
                    root,
                    "experiments_90pt_plan/scripts/build_tifs_review_archive_manifest.py",
                ),
                "--root",
                quote(root),
            ]
        )
    ], []


def build_commands(root: Path, run: dict[str, str]) -> tuple[list[str], list[str]]:
    experiment = run["experiment"]
    if experiment == "documentation":
        return [], []
    if experiment == "adaptive_attack":
        return adaptive_attack_commands(root, run)
    if experiment == "open_set":
        return generic_scored_run(root, run, "open_set")
    if experiment == "cross_base_task":
        return cross_base_task_commands(root, run)
    if experiment == "baseline_head_to_head":
        return baseline_commands(root, run)
    if experiment == "student_level_ci":
        return student_ci_commands(root, run)
    if experiment == "review_archive":
        return review_archive_commands(root, run)
    return [], [f"no executor for experiment={experiment}"]


def write_plan(
    root: Path, run: dict[str, str], commands: list[str], blockers: list[str]
) -> Path:
    out = root / "results_90pt/run_commands/tifs_hard_bar" / f"{run['run_id']}.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    required_output = root / run["required_output"]
    if blockers:
        status = "blocked"
    elif run["experiment"] == "documentation" and required_output.exists():
        status = "unlocked_existing"
    elif not commands and required_output.exists():
        status = "unlocked_existing"
    elif commands:
        status = "ready_hpc_raw_or_local_assembly"
    else:
        status = "blocked"
        blockers = [
            f"no commands produced and output missing: {run['required_output']}"
        ]
    payload = {
        "run_id": run["run_id"],
        "priority": run["priority"],
        "pillar": run["pillar"],
        "experiment": run["experiment"],
        "condition": run["condition"],
        "dataset": run["dataset"],
        "student_base": run["student_base"],
        "teacher_family": run["teacher_family"],
        "required_output": run["required_output"],
        "claim_gate": run["claim_gate"],
        "status": status,
        "commands": commands,
        "blockers": blockers,
    }
    out.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return out


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", default=".")
    parser.add_argument("--run-id")
    parser.add_argument("--array-index", type=int)
    parser.add_argument("--execute", action="store_true")
    args = parser.parse_args()

    root = Path(args.root).resolve()
    run = load_run(root, args.run_id, args.array_index)
    commands, blockers = build_commands(root, run)
    plan_path = write_plan(root, run, commands, blockers)

    print(f"Run {run['run_id']} {run['experiment']}/{run['condition']} -> {plan_path}")
    if blockers:
        print("Blockers:")
        for blocker in blockers:
            print(f"- {blocker}")
    if commands:
        print("Commands:")
        for command in commands:
            print(command)

    if args.execute:
        if blockers:
            raise SystemExit(2)
        for command in commands:
            subprocess.run(command, shell=True, check=True, cwd=root)


if __name__ == "__main__":
    main()
