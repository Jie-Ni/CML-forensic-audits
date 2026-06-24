# Capability-Matched Likelihood for Forensic Audits of Reasoning-LLM Distillation

This repository contains the manuscript source, figure-generation scripts, aggregate source tables, and review-time reproducibility assets for:

**Capability-Matched Likelihood for Forensic Audits of Reasoning-LLM Distillation**

Authors: Jie Ni, Chenning Zhang, and Xinting Zhang.

The paper studies a closed-candidate forensic audit for reasoning-LLM distillation. The core method compares suspect traces and same-base reference traces under the same candidate teacher, yielding a capability-matched likelihood statistic for calibrated detection and attribution.

## Repository Contents

- `main.tex`, `supplementary.tex`, `sections/`, `tables/`, `references.bib`: LaTeX manuscript source.
- `main.pdf`, `supplementary.pdf`: compiled manuscript and supplementary material.
- `figures/*.R`: R scripts used to regenerate the manuscript figures.
- `figures/source/`: primary source tables and scored JSONL summaries used by the plotting scripts.
- `figures/source_derived/`: derived figure-panel source tables exported by the plotting scripts.
- `figures/source_external/`: source bitmap for the selected Fig. 1 workflow schematic.
- `results_90pt/summaries/`: aggregate result tables used in the manuscript.
- `results_90pt/pi_result_locks/`: locked aggregate tables imported from the final result files.
- `results_90pt/scored_matrices/`: compact scored-matrix artifacts used by the reanalysis scripts.
- `experiments_90pt_plan/scripts/`: aggregation, validation, and figure-source preparation scripts.
- `FIGURE_PANEL_TRACEABILITY.tsv`: panel-to-source traceability map.
- `SOURCE_BUNDLE_README.txt`: review-source bundle notes.

## Regenerating Figures

Install the R packages listed in `requirements-r.txt`, then run:

```bash
Rscript figures/plot_nature_results.R
Rscript figures/plot_tifs_advanced_figures.R
Rscript figures/plot_pi_result_lock_tifs_suite.R
Rscript figures/plot_forensic_envelope.R
Rscript figures/plot_supplementary_evidence.R
Rscript figures/import_external_fig1.R
```

`figures/import_external_fig1.R` restores the selected Fig. 1 schematic after the R figure-regeneration pass.

## Rebuilding The Manuscript

```bash
pdflatex main.tex
bibtex main
pdflatex main.tex
pdflatex main.tex

pdflatex supplementary.tex
pdflatex supplementary.tex
```

## Python Environment

The Python scripts use the packages listed in `experiments_90pt_plan/requirements.txt`.
The plotting and source-table validation scripts are intended to be run from the repository root.

## Data Scope

This repository releases aggregate source tables, compact scored summaries, manuscript figures, and scripts needed to rebuild the reported manuscript figures and source-bundle checks. It does not publish trained model adapters or full training/inference logs.

## License

No reuse license has been selected yet. Public visibility is provided for review and transparency; reuse permissions should be confirmed with the corresponding author.
