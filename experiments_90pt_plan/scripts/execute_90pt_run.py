#!/usr/bin/env python
"""Execute or dry-run one W08 90-point run-matrix row.

The default mode is dry-run. Use --execute only inside a PI-approved HPC job.
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

BASE_REFERENCE_BY_CONDITION = {
    "correct_base_reference": "qwen2.5-7b",
    "neighboring_same_family_reference": "qwen2.5-14b",
    "different_family_reference": "llama-3.1-8b",
    "no_runnable_base_fallback": "",
}


def read_tsv(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        return []
    with path.open("r", encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle, delimiter="\t"))


def load_run(root: Path, run_id: str | None, array_index: int | None) -> dict[str, str]:
    rows = read_tsv(root / "experiments_90pt_plan/run_matrix.tsv")
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


def py(root: Path, relative: str) -> str:
    return f'"{sys.executable}" "{root / relative}"'


def legacy_script(name: str) -> str:
    default = (
        "C:/Users/Jie/Desktop/codex/paper_portfolio_2026/project_roots/"
        "LLM_Distillation_Provenance/scripts"
    )
    base = Path(os.environ.get("W08_LEGACY_SCRIPTS", default))
    return str(base / name)


def quote(value: str | Path) -> str:
    return '"' + str(value).replace('"', '\\"') + '"'


def candidate_teachers(root: Path) -> list[str]:
    path = root / "results_90pt/raw_trace_manifests/candidate_teachers.tsv"
    rows = read_tsv(path)
    values = [r["candidate_teacher"] for r in rows if r.get("candidate_teacher")]
    return values or DEFAULT_CANDIDATES


def raw_trace_inputs(root: Path, dataset: str) -> list[dict[str, str]]:
    path = root / "results_90pt/raw_trace_manifests/raw_trace_inputs.tsv"
    rows = read_tsv(path)
    wanted = dataset.lower()
    return [r for r in rows if r.get("dataset", "").lower() == wanted]


def external_rewrites(root: Path, run: dict[str, str]) -> dict[tuple[str, str, str], str]:
    path = root / "results_90pt/raw_trace_manifests/external_rewrites.tsv"
    rows = read_tsv(path)
    out = {}
    for row in rows:
        if row.get("run_id") != run["run_id"]:
            continue
        key = (row.get("student_id", ""), row.get("seed", ""), row.get("dataset", ""))
        out[key] = row.get("external_rewrite_path", "")
    return out


def laundering_commands(root: Path, run: dict[str, str]) -> tuple[list[str], list[str]]:
    dataset = run["dataset"]
    condition = run["condition"]
    traces = raw_trace_inputs(root, dataset)
    if not traces:
        return [], [f"missing raw trace input rows for dataset={dataset}"]

    rewrites = external_rewrites(root, run)
    laundered_paths = []
    commands = []
    missing = []
    for row in traces:
        trace_path = row.get("trace_path", "")
        if not trace_path:
            missing.append(f"raw_trace_inputs row lacks trace_path for {row}")
            continue
        student = row.get("student_id", "student")
        seed = row.get("seed", "0")
        out = (
            root
            / "results_90pt/traces_laundered"
            / condition
            / dataset.lower()
            / f"{student}_s{seed}.jsonl"
        )
        cmd = [
            py(root, "experiments_90pt_plan/scripts/make_laundered_traces.py"),
            "--input",
            quote(trace_path),
            "--out",
            quote(out),
            "--condition",
            condition,
        ]
        key = (student, seed, dataset)
        if condition in {"paraphrase_second_model", "self_rewrite_with_non_candidate_llm"}:
            rewrite_path = rewrites.get(key, "")
            if not rewrite_path:
                missing.append(f"missing external rewrite for {run['run_id']} {key}")
            else:
                cmd.extend(["--external-rewrite-jsonl", quote(rewrite_path)])
        commands.append(" ".join(cmd))
        laundered_paths.append(out)

    for candidate in candidate_teachers(root):
        if not laundered_paths:
            continue
        outdir = root / "results_90pt/scored_laundering" / condition / dataset.lower()
        score_cmd = [
            quote(sys.executable),
            quote(legacy_script("score_traces.py")),
            "--candidate",
            candidate,
            "--outdir",
            quote(outdir),
            "--traces",
            *[quote(path) for path in laundered_paths],
        ]
        commands.append(" ".join(score_cmd))
    if laundered_paths:
        assemble = [
            py(root, "experiments_90pt_plan/scripts/assemble_90pt_tables.py"),
            "--root",
            quote(root),
            "--experiment",
            "adaptive_laundering",
            "--condition",
            condition,
            "--dataset",
            dataset,
            "--scored-dir",
            quote(root / "results_90pt/scored_laundering" / condition / dataset.lower()),
        ]
        commands.append(" ".join(assemble))
    return commands, missing


def score_raw_traces_commands(
    root: Path,
    traces: list[dict[str, str]],
    candidates: list[str],
    outdir: Path,
) -> tuple[list[str], list[str]]:
    trace_paths = [row.get("trace_path", "") for row in traces if row.get("trace_path")]
    missing = []
    if len(trace_paths) != len(traces):
        missing.append("one or more raw_trace_inputs rows lack trace_path")
    if not trace_paths:
        return [], missing
    commands = []
    for candidate in candidates:
        command = [
            quote(sys.executable),
            quote(legacy_script("score_traces.py")),
            "--candidate",
            candidate,
            "--outdir",
            quote(outdir / candidate),
            "--traces",
            *[quote(path) for path in trace_paths],
        ]
        commands.append(" ".join(command))
    return commands, missing


def base_mismatch_commands(root: Path, run: dict[str, str], allow_derived_local_reanalysis: bool) -> tuple[list[str], list[str]]:
    traces = raw_trace_inputs(root, run["dataset"])
    if not traces:
        scored_dir = root / "figures/source/scored_gsm8k"
        derivable = {"correct_base_reference", "no_runnable_base_fallback"}
        if (
            run["dataset"].lower() == "gsm8k"
            and run["condition"] in derivable
            and scored_dir.exists()
        ):
            if not allow_derived_local_reanalysis:
                return [], [
                    f"missing raw trace input rows for dataset={run['dataset']}; "
                    "derived local base-mismatch reanalysis is available only with "
                    "--allow-derived-local-reanalysis and cannot unlock 90-point claims"
                ]
            return [
                " ".join(
                    [
                        py(root, "experiments_90pt_plan/scripts/derive_base_mismatch_from_scored.py"),
                        "--root",
                        quote(root),
                        "--dataset",
                        run["dataset"],
                        "--scored-dir",
                        quote(scored_dir),
                    ]
                )
            ], []
        return [], [f"missing raw trace input rows for dataset={run['dataset']}"]
    reference_model = BASE_REFERENCE_BY_CONDITION.get(run["condition"], "")
    candidates = candidate_teachers(root)
    if reference_model:
        candidates = sorted(set(candidates + [reference_model]))
    outdir = root / "results_90pt/scored_base_mismatch" / run["condition"] / run["dataset"].lower()
    commands, missing = score_raw_traces_commands(root, traces, candidates, outdir)
    assemble = [
        py(root, "experiments_90pt_plan/scripts/assemble_90pt_tables.py"),
        "--root",
        quote(root),
        "--experiment",
        "base_mismatch",
        "--condition",
        run["condition"],
        "--dataset",
        run["dataset"],
        "--scored-dir",
        quote(outdir),
        "--reference-model",
        reference_model or "none",
    ]
    commands.append(" ".join(assemble))
    return commands, missing


def open_set_commands(root: Path, run: dict[str, str], allow_derived_local_reanalysis: bool) -> tuple[list[str], list[str]]:
    traces = raw_trace_inputs(root, run["dataset"])
    if not traces:
        scored_dir = root / "figures/source/scored_gsm8k"
        if run["dataset"].lower() == "gsm8k" and scored_dir.exists():
            if not allow_derived_local_reanalysis:
                return [], [
                    f"missing raw trace input rows for dataset={run['dataset']}; "
                    "derived local open-set reanalysis is available only with "
                    "--allow-derived-local-reanalysis and cannot unlock 90-point claims"
                ]
            return [
                " ".join(
                    [
                        py(root, "experiments_90pt_plan/scripts/derive_open_set_from_scored.py"),
                        "--root",
                        quote(root),
                        "--dataset",
                        run["dataset"],
                        "--scored-dir",
                        quote(scored_dir),
                    ]
                )
            ], []
        return [], [f"missing raw trace input rows for dataset={run['dataset']}"]
    candidates = candidate_teachers(root)
    outdir = root / "results_90pt/scored_open_set" / run["condition"] / run["dataset"].lower()
    commands, missing = score_raw_traces_commands(root, traces, candidates, outdir)
    assemble = [
        py(root, "experiments_90pt_plan/scripts/assemble_90pt_tables.py"),
        "--root",
        quote(root),
        "--experiment",
        "out_of_set_candidate",
        "--condition",
        run["condition"],
        "--dataset",
        run["dataset"],
        "--scored-dir",
        quote(outdir),
    ]
    commands.append(" ".join(assemble))
    return commands, missing


def xbase_commands(root: Path, run: dict[str, str], allow_derived_local_reanalysis: bool) -> tuple[list[str], list[str]]:
    inputs = read_tsv(root / "results_90pt/raw_trace_manifests/student_training_inputs.tsv")
    rows = [row for row in inputs if row.get("run_id") == run["run_id"]]
    if not rows:
        source = Path(
            "C:/Users/Jie/Desktop/codex/paper_portfolio_2026/project_roots/"
            "LLM_Distillation_Provenance/"
            "manuscript_new_results_mtcr_20260623_tifs_nature_r_figures_v3_enriched/"
            "figures/source/w08_cross_architecture.csv"
        )
        if source.exists():
            if not allow_derived_local_reanalysis:
                return [], [
                    f"missing student_training_inputs rows for run_id={run['run_id']}; "
                    "derived local cross-architecture import is available only with "
                    "--allow-derived-local-reanalysis and cannot unlock 90-point claims"
                ]
            return [
                " ".join(
                    [
                        py(root, "experiments_90pt_plan/scripts/import_cross_architecture_summary.py"),
                        "--root",
                        quote(root),
                        "--source",
                        quote(source),
                    ]
                )
            ], []
        return [], [f"missing student_training_inputs rows for run_id={run['run_id']}"]
    commands = []
    missing = []
    for row in rows:
        required = ["student_base", "sft_jsonl", "adapter_out_dir", "trace_out_path"]
        absent = [key for key in required if not row.get(key)]
        if absent:
            missing.append(f"{run['run_id']} training row missing: {', '.join(absent)}")
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
    if commands:
        assemble = [
            py(root, "experiments_90pt_plan/scripts/assemble_90pt_tables.py"),
            "--root",
            quote(root),
            "--experiment",
            "broader_student_matrix",
            "--condition",
            run["condition"],
            "--dataset",
            run["dataset"],
        ]
        commands.append(" ".join(assemble))
    return commands, missing


def mtcr_commands(root: Path, run: dict[str, str]) -> tuple[list[str], list[str]]:
    rows = read_tsv(root / "results_90pt/raw_trace_manifests/mtcr_task_views.tsv")
    rows = [row for row in rows if row.get("dataset", "").lower() == run["dataset"].lower()]
    if not rows:
        return [], [f"missing mtcr_task_views rows for dataset={run['dataset']}"]
    commands = []
    missing = []
    for row in rows:
        if not row.get("trace_path") or not row.get("candidate_teacher"):
            missing.append(f"mtcr_task_views row missing trace_path/candidate_teacher: {row}")
            continue
        outdir = root / "results_90pt/scored_mtcr" / row.get("task_view", "task")
        command = [
            quote(sys.executable),
            quote(legacy_script("score_traces.py")),
            "--candidate",
            row["candidate_teacher"],
            "--outdir",
            quote(outdir),
            "--traces",
            quote(row["trace_path"]),
        ]
        if row.get("reference_trace_path"):
            command.append(quote(row["reference_trace_path"]))
        commands.append(" ".join(command))
    if commands:
        assemble = [
            py(root, "experiments_90pt_plan/scripts/assemble_90pt_tables.py"),
            "--root",
            quote(root),
            "--experiment",
            "mtcr_raw_profiles",
            "--condition",
            run["condition"],
            "--dataset",
            run["dataset"],
        ]
        commands.append(" ".join(assemble))
    return commands, missing


def generic_blocked_commands(root: Path, run: dict[str, str]) -> tuple[list[str], list[str]]:
    experiment = run["experiment"]
    if experiment == "reproducibility":
        command = " ".join(
            [
                py(root, "experiments_90pt_plan/scripts/build_reproducibility_manifest.py"),
                "--root",
                quote(root),
            ]
        )
        return [command], []

    return [], [f"{experiment}/{run['condition']} has no command adapter yet"]


def build_commands(root: Path, run: dict[str, str]) -> tuple[list[str], list[str]]:
    return build_commands_with_options(root, run, allow_derived_local_reanalysis=False)


def write_plan(root: Path, run: dict[str, str], commands: list[str], blockers: list[str]) -> Path:
    out = root / "results_90pt/run_commands" / f"{run['run_id']}.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    diagnostic_markers = (
        "derive_base_mismatch_from_scored.py",
        "derive_open_set_from_scored.py",
        "import_cross_architecture_summary.py",
    )
    if blockers or not commands:
        status = "blocked"
    elif any(marker in command for command in commands for marker in diagnostic_markers):
        status = "ready_local_diagnostic"
    else:
        status = "ready_hpc_raw"
    payload = {
        "run_id": run["run_id"],
        "experiment": run["experiment"],
        "condition": run["condition"],
        "dataset": run["dataset"],
        "commands": commands,
        "blockers": blockers,
        "status": status,
    }
    out.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return out


def build_commands_with_options(
    root: Path,
    run: dict[str, str],
    allow_derived_local_reanalysis: bool,
) -> tuple[list[str], list[str]]:
    if run["experiment"] == "adaptive_laundering":
        return laundering_commands(root, run)
    if run["experiment"] == "base_mismatch":
        return base_mismatch_commands(root, run, allow_derived_local_reanalysis)
    if run["experiment"] == "out_of_set_candidate":
        return open_set_commands(root, run, allow_derived_local_reanalysis)
    if run["experiment"] == "broader_student_matrix":
        return xbase_commands(root, run, allow_derived_local_reanalysis)
    if run["experiment"] == "mtcr_raw_profiles":
        return mtcr_commands(root, run)
    return generic_blocked_commands(root, run)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", default=".")
    parser.add_argument("--run-id")
    parser.add_argument("--array-index", type=int)
    parser.add_argument("--execute", action="store_true", help="Run commands; otherwise dry-run")
    parser.add_argument(
        "--allow-derived-local-reanalysis",
        action="store_true",
        help="Permit diagnostic local reanalysis from old scored files; never valid for 90-point claim unlocks.",
    )
    args = parser.parse_args()

    root = Path(args.root).resolve()
    run = load_run(root, args.run_id, args.array_index)
    commands, blockers = build_commands_with_options(root, run, args.allow_derived_local_reanalysis)
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
    elif blockers:
        raise SystemExit(0)


if __name__ == "__main__":
    main()
