# CML Forensic Audit Code

This repository contains only the core experiment code for capability-matched
likelihood (CML) forensic audits.

It intentionally excludes manuscripts, figures, plotting scripts, result
tables, scored traces, model outputs, and submission material.

## Install

```bash
python -m pip install -r requirements.txt
```

## Input Table

The audit CLI expects a CSV where each row is one trace scored under one
candidate teacher.

Required columns:

- `task`
- `scenario`
- `trace_id`
- `candidate_teacher`
- `suspect_logp`
- `reference_logp`

Optional columns:

- `true_lineage`
- `label`
- `baseline_logp`

The CML trace score is:

```text
suspect_logp - reference_logp
```

Candidate-level scores are aggregated by the requested grouping columns and
`candidate_teacher`.

## Run

```bash
python -m cml_audit.run_audit \
  --input path/to/scored_traces.csv \
  --output path/to/audit_summary.csv \
  --group task,scenario \
  --threshold 0.0
```

Use `examples/audit_config.example.json` as a compact reference for the accepted
column names and CLI options.
