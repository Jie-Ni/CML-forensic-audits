Source bundle for the IEEE TIFS review submission.

Review-safe contents:
- artifact_manifest.tsv and artifact_manifest.yaml: relative-path file manifests
  with SHA256 hashes for the review-safe source bundle.
- FIGURE_PANEL_TRACEABILITY.tsv: panel-level map from each submitted main figure
  panel to its source and derived data files.
- main.tex, supplementary.tex, sections/*.tex, and references.bib: manuscript
  source.
- figures/fig_method_overview.{pdf,svg,png,tiff}
- figures/fig_core_detection.{pdf,svg,png,tiff}
- figures/fig_mtcr_attribution_epoch.{pdf,svg,png,tiff}
- figures/fig_robustness_checks.{pdf,svg,png,tiff}
- figures/fig_tifs_pi_result_lock_suite.{pdf,svg,png,tiff}
- figures/fig_forensic_envelope.{pdf,svg,png,tiff}
- figures/plot_nature_results.R: canonical R rebuild entry point.
- figures/import_external_fig1.R: restores the PI-selected external workflow
  schematic as Fig. 1 after any R regeneration pass.
- figures/plot_tifs_advanced_figures.R: R override script for the TIFS-style
  Fig. 3, Fig. 4, and Fig. 5 layouts.
- figures/plot_forensic_envelope.R: standalone R script for the forensic-envelope
  diagnostic figure.
- figures/plot_pi_result_lock_tifs_suite.R: standalone R script for the adaptive,
  open-set, cross-base, baseline, student-level, and MTCR stress-summary figure.
- figures/source/*.csv and figures/source/results_full_*.json: source result
  tables used by the figure scripts.
- figures/source_external/fig1_cml_protocol_external_source_20260624_155038.png:
  source bitmap for the PI-selected Fig. 1 workflow schematic.
- figures/source/scored_gsm8k/*.jsonl and figures/source/scored_math/*.jsonl:
  scored log-probability source summaries used to derive the core detection
  figure.
- figures/source_derived/*.csv: derived figure-source tables exported by the R
  scripts.
- results_90pt/summaries/*.csv: staged summary artifacts used for the current
  operating diagnostics.

To regenerate the figures:
Rscript figures/plot_nature_results.R
Rscript figures/plot_pi_result_lock_tifs_suite.R
Rscript figures/import_external_fig1.R

To rebuild the manuscript:
pdflatex main.tex
bibtex main
pdflatex main.tex
pdflatex main.tex

This bundle contains manuscript, figure, plotting-script, and staged source-data
files for review.

Public repository:
https://github.com/Jie-Ni/CML-forensic-audits
