# PI Result Lock Coverage For W08 TIFS 90-Point Target

Checked at: `2026-06-23T21:10:43.598596+00:00`

These tables are manuscript/figure sources from PI-provided result locks. They do not replace raw trace, adapter, run-log, or review-archive evidence.

## Imported Rows

- `adaptive`: 32 rows
- `cross_base`: 30 rows
- `open_set`: 4 rows
- `baseline`: 8 rows
- `student_ci`: 3 rows
- `mtcr`: 18 rows
- `review_archive`: 5 rows

## Remaining Hard-Bar Caveats

- **adaptive_attack**: summary-level rows only; no per-trace scored matrix
- **cross_base_task**: AUROC matrix only; no TPR@1%FPR/FPR0/CI columns in result lock
- **open_set_abstention**: abstention/false-attribution/coverage only; no AUROC/TPR columns
- **baseline_head_to_head**: no per-seed CI or TPR@1%FPR in result lock
- **student_level_ci**: usable for manuscript; only three strata in result lock
- **mtcr_task_profiles**: task surplus summary only; not raw per-view scored matrix
- **review_archive**: descriptive patterns and truncated hashes; no local file verification
