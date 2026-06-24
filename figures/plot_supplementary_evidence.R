#!/usr/bin/env Rscript

suppressPackageStartupMessages({
  library(dplyr)
  library(ggrepel)
  library(ggplot2)
  library(patchwork)
  library(readr)
  library(scales)
  library(tidyr)
})

`%||%` <- function(x, y) {
  if (is.null(x) || length(x) == 0 || is.na(x)) y else x
}

script_file <- sub("^--file=", "", grep("^--file=", commandArgs(FALSE), value = TRUE)[1] %||% "")
root_dir <- if (nzchar(script_file)) {
  dirname(normalizePath(script_file, winslash = "/", mustWork = TRUE))
} else {
  normalizePath(getwd(), winslash = "/", mustWork = TRUE)
}
project_root <- normalizePath(file.path(root_dir, ".."), winslash = "/", mustWork = TRUE)
source_dir <- file.path(root_dir, "source")
derived_dir <- file.path(root_dir, "source_derived")
table_dir <- file.path(project_root, "tables")
dir.create(derived_dir, showWarnings = FALSE, recursive = TRUE)
dir.create(table_dir, showWarnings = FALSE, recursive = TRUE)

palette <- c(
  ink = "#111827",
  slate = "#26364D",
  neutral = "#6B7280",
  light = "#DCE3EC",
  pale = "#F7F9FC",
  cml = "#0E9F78",
  cml_dark = "#047857",
  baseline = "#B8481C",
  baseline_soft = "#F6D7BF",
  blue = "#2563A8",
  blue_soft = "#D8E6F7",
  purple = "#7C6BB5",
  orange = "#D95F02"
)

pc <- function(name) unname(palette[[name]])

theme_supp <- function(base_size = 7.2) {
  theme_classic(base_size = base_size, base_family = "Arial") +
    theme(
      plot.background = element_rect(fill = "white", colour = NA),
      panel.background = element_rect(fill = "white", colour = NA),
      axis.line = element_line(colour = pc("slate"), linewidth = 0.32),
      axis.ticks = element_line(colour = pc("slate"), linewidth = 0.28),
      axis.text = element_text(colour = pc("ink"), size = rel(0.88)),
      axis.title = element_text(colour = pc("ink"), size = rel(0.95)),
      plot.title = element_text(face = "bold", size = rel(1.05), colour = pc("ink"), hjust = 0),
      plot.subtitle = element_text(size = rel(0.82), colour = "#536172", hjust = 0),
      legend.title = element_blank(),
      legend.text = element_text(size = rel(0.78), colour = pc("ink")),
      legend.key.height = unit(0.12, "in"),
      legend.key.width = unit(0.22, "in"),
      legend.background = element_blank(),
      panel.grid.major.y = element_line(colour = "#EEF2F7", linewidth = 0.22),
      panel.grid.major.x = element_blank(),
      panel.grid.minor = element_blank(),
      strip.background = element_rect(fill = pc("pale"), colour = "#D8DFEA", linewidth = 0.25),
      strip.text = element_text(face = "bold", size = rel(0.82), colour = pc("ink")),
      plot.margin = margin(4, 5, 4, 5),
      plot.tag = element_text(face = "bold", size = 10, colour = pc("ink")),
      plot.tag.position = c(0.01, 0.98)
    )
}

save_pub <- function(plot, name, width = 7.2, height = 6.0) {
  ggsave(file.path(root_dir, paste0(name, ".pdf")), plot,
    width = width, height = height, units = "in", device = cairo_pdf
  )
  svglite::svglite(file.path(root_dir, paste0(name, ".svg")), width = width, height = height)
  print(plot)
  dev.off()
  ragg::agg_png(file.path(root_dir, paste0(name, ".png")),
    width = width, height = height, units = "in", res = 450, background = "white"
  )
  print(plot)
  dev.off()
  ragg::agg_tiff(file.path(root_dir, paste0(name, ".tiff")),
    width = width, height = height, units = "in", res = 600,
    compression = "lzw", background = "white"
  )
  print(plot)
  dev.off()
}

read_required_csv <- function(path) {
  if (!file.exists(path)) {
    stop("Missing required source: ", path, call. = FALSE)
  }
  read_csv(path, show_col_types = FALSE)
}

latex_escape <- function(x) {
  x <- gsub("\\\\", "\\\\textbackslash{}", x)
  x <- gsub("([#$%&_{}])", "\\\\\\1", x, perl = TRUE)
  x
}

write_latex_table <- function(path, caption, label, header, rows) {
  lines <- c(
    "\\begin{table}[!htbp]\\centering\\footnotesize",
    paste0("\\caption{", caption, "}"),
    paste0("\\label{", label, "}"),
    "\\begin{tabular}{lrrrr}",
    "\\toprule",
    header,
    "\\midrule",
    rows,
    "\\bottomrule",
    "\\end{tabular}",
    "\\end{table}"
  )
  writeLines(lines, path, useBytes = TRUE)
}

baseline <- read_required_csv(file.path(source_dir, "w08_tifs_baseline_head_to_head.csv"))
adaptive <- read_required_csv(file.path(source_dir, "w08_tifs_adaptive_attack_summary.csv"))
open_set <- read_required_csv(file.path(source_dir, "w08_tifs_open_set_abstention_summary.csv"))
cross_base <- read_required_csv(file.path(source_dir, "w08_tifs_cross_base_task_matrix.csv"))
mtcr_profile <- read_required_csv(file.path(source_dir, "w08_tifs_mtcr_task_profile_summary.csv"))
student_ci <- read_required_csv(file.path(source_dir, "w08_tifs_student_level_ci.csv"))

method_levels <- c(
  "Base-Relative Surplus",
  "Perplexity/Logprob Shift",
  "Embedding MMD",
  "Style Classifier (SVM/TF-IDF)",
  "Teacher Classifier (Logit-SFT)",
  "Model Provenance Testing (MPT)",
  "CML (Standard ours)",
  "CML+MTCR (Refined ours)"
)

baseline_summary <- baseline %>%
  group_by(original_method) %>%
  summarise(
    detection_auroc = mean(auroc, na.rm = TRUE),
    same_family_auroc = mean(same_family_auroc, na.rm = TRUE),
    sibling_attribution = mean(sibling_attribution_accuracy, na.rm = TRUE),
    fpr_zero = mean(fpr_zero, na.rm = TRUE),
    n_students = max(n_students, na.rm = TRUE),
    .groups = "drop"
  ) %>%
  mutate(
    original_method = factor(original_method, levels = method_levels),
    method_family = if_else(grepl("^CML", as.character(original_method)), "CML family", "comparison baseline")
  ) %>%
  arrange(original_method)

write_csv(baseline_summary, file.path(derived_dir, "supp_baseline_summary.csv"))

baseline_long <- baseline_summary %>%
  select(original_method, method_family, detection_auroc, same_family_auroc, sibling_attribution) %>%
  pivot_longer(
    cols = c(detection_auroc, same_family_auroc, sibling_attribution),
    names_to = "metric",
    values_to = "value"
  ) %>%
  mutate(
    metric = recode(
      metric,
      detection_auroc = "detection AUROC",
      same_family_auroc = "same-family AUROC",
      sibling_attribution = "sibling attribution"
    ),
    metric = factor(metric, levels = c("detection AUROC", "same-family AUROC", "sibling attribution"))
  )

p_s2a <- ggplot(baseline_long, aes(metric, original_method, fill = value)) +
  geom_tile(colour = "white", linewidth = 0.42) +
  geom_text(aes(label = sprintf("%.3f", value)), size = 2.05, colour = pc("ink")) +
  scale_fill_gradient(low = "#F8E6D8", high = pc("cml"), limits = c(0.1, 1.0), oob = squish) +
  labs(
    title = "Baseline metrics",
    subtitle = "Mean score over staged student rows",
    x = NULL,
    y = NULL
  ) +
  theme_supp() +
  theme(
    legend.position = "right",
    axis.text.x = element_text(angle = 20, hjust = 1)
  )

p_s2b <- ggplot(baseline_summary, aes(fpr_zero, original_method, colour = method_family)) +
  geom_segment(aes(x = 0, xend = fpr_zero, yend = original_method),
    colour = "#D8DFEA", linewidth = 0.35
  ) +
  geom_point(size = 2.0) +
  geom_text(aes(label = sprintf("%.3f", fpr_zero)),
    hjust = -0.15, size = 2.1, colour = pc("ink")
  ) +
  scale_colour_manual(values = c("CML family" = pc("cml"), "comparison baseline" = pc("baseline"))) +
  scale_x_continuous(limits = c(0, 0.90), breaks = c(0, 0.25, 0.5, 0.75)) +
  labs(
    title = "Zero-threshold false alarms",
    subtitle = "Lower is better",
    x = "FPR at zero threshold",
    y = NULL
  ) +
  theme_supp() +
  theme(legend.position = "none")

open_summary <- open_set %>%
  group_by(scenario) %>%
  summarise(
    abstention_rate = mean(abstention_rate, na.rm = TRUE),
    false_attribution_rate = mean(false_attribution_rate, na.rm = TRUE),
    coverage = mean(coverage, na.rm = TRUE),
    .groups = "drop"
  ) %>%
  arrange(abstention_rate) %>%
  mutate(scenario = factor(scenario, levels = scenario))

write_csv(open_summary, file.path(derived_dir, "supp_open_set_summary.csv"))

open_long <- open_summary %>%
  pivot_longer(
    cols = c(abstention_rate, false_attribution_rate, coverage),
    names_to = "metric",
    values_to = "value"
  ) %>%
  mutate(
    metric = recode(
      metric,
      abstention_rate = "abstention",
      false_attribution_rate = "false attribution",
      coverage = "coverage"
    ),
    metric = factor(metric, levels = c("abstention", "false attribution", "coverage"))
  )

p_s2c <- ggplot(open_long, aes(value, scenario, colour = metric)) +
  geom_point(size = 2.0, position = position_dodge(width = 0.55)) +
  geom_segment(aes(x = 0, xend = value, yend = scenario, colour = metric),
    linewidth = 0.25, alpha = 0.55, position = position_dodge(width = 0.55)
  ) +
  scale_colour_manual(values = c("abstention" = pc("blue"), "false attribution" = pc("baseline"), "coverage" = pc("cml"))) +
  scale_x_continuous(limits = c(0, 1.02), labels = percent_format(accuracy = 1)) +
  labs(
    title = "Absent-candidate triage",
    subtitle = "High abstention with low false attribution",
    x = "rate",
    y = NULL
  ) +
  theme_supp() +
  theme(legend.position = "top")

ci_summary <- student_ci %>%
  filter(metric == "effect_size_margin", condition == "all_distilled_vs_ctrlc") %>%
  mutate(
    display = paste(dataset, if_else(grepl("Qwen", student_base), "Qwen", "Llama"), sep = " / "),
    display = factor(display, levels = rev(unique(display)))
  )

write_csv(ci_summary, file.path(derived_dir, "supp_student_effect_size_ci.csv"))

p_s2d <- ggplot(ci_summary, aes(estimate, display, colour = student_base)) +
  geom_vline(xintercept = 0, linewidth = 0.28, linetype = "dashed", colour = pc("neutral")) +
  geom_segment(aes(x = ci_low, xend = ci_high, yend = display), linewidth = 0.65) +
  geom_point(size = 1.8) +
  scale_colour_manual(values = c("Qwen2.5-7B" = pc("blue"), "Llama-3.1-8B" = pc("cml"))) +
  labs(
    title = "Student-level separation",
    subtitle = "Effect-size margin with reported interval",
    x = "distilled-control margin",
    y = NULL
  ) +
  theme_supp() +
  theme(legend.position = "top")

fig_s2 <- (p_s2a | p_s2b) / (p_s2c | p_s2d)
fig_s2 <- fig_s2 +
  plot_layout(widths = c(1.10, 1.0), heights = c(1.0, 1.0), guides = "keep") +
  plot_annotation(tag_levels = "a") &
  theme(plot.tag = element_text(face = "bold", size = 10, colour = pc("ink")))

save_pub(fig_s2, "fig_supp_baseline_and_abstention", width = 7.25, height = 6.95)

adaptive_summary <- adaptive %>%
  group_by(evasion_attack, method) %>%
  summarise(
    auroc = mean(auroc, na.rm = TRUE),
    tpr_at_1pct_fpr = mean(tpr_at_1pct_fpr, na.rm = TRUE),
    fpr_zero = mean(fpr_zero, na.rm = TRUE),
    .groups = "drop"
  ) %>%
  mutate(
    method = factor(method, levels = c("Base-relative", "CML+MTCR")),
    evasion_attack = factor(evasion_attack, levels = rev(unique(evasion_attack[order(auroc)])))
  )

write_csv(adaptive_summary, file.path(derived_dir, "supp_adaptive_attack_summary.csv"))

p_s3a <- ggplot(adaptive_summary, aes(method, evasion_attack, fill = auroc)) +
  geom_tile(colour = "white", linewidth = 0.45) +
  geom_text(aes(label = sprintf("%.3f", auroc)), size = 2.15, colour = pc("ink")) +
  scale_fill_gradient(low = "#F8E6D8", high = pc("cml"), limits = c(0.5, 1.0), oob = squish) +
  labs(
    title = "Adaptive stress AUROC",
    subtitle = "Uncalibrated surplus fails under transformations",
    x = NULL,
    y = NULL
  ) +
  theme_supp() +
  theme(legend.position = "none")

adaptive_cml <- adaptive_summary %>% filter(method == "CML+MTCR")

p_s3b <- ggplot(adaptive_cml, aes(fpr_zero, tpr_at_1pct_fpr, label = evasion_attack)) +
  geom_point(aes(size = auroc), colour = pc("cml"), alpha = 0.88) +
  ggrepel::geom_text_repel(
    size = 2.0, colour = pc("ink"), min.segment.length = 0,
    box.padding = 0.18, point.padding = 0.12, seed = 11, max.overlaps = Inf
  ) +
  scale_x_continuous(limits = c(0, max(adaptive_cml$fpr_zero) + 0.01), labels = percent_format(accuracy = 0.1)) +
  scale_y_continuous(limits = c(0.88, 1.01), labels = percent_format(accuracy = 1)) +
  scale_size_continuous(range = c(1.8, 4.2)) +
  labs(
    title = "Low-FPR operating points",
    subtitle = "CML+MTCR; point size encodes AUROC",
    x = "FPR at zero threshold",
    y = "TPR at 1% FPR"
  ) +
  theme_supp() +
  theme(legend.position = "none")

cross_plot <- cross_base %>%
  mutate(
    dataset = factor(dataset, levels = c("GSM8K", "MATH", "BBH", "ARC-Challenge", "MBPP")),
    training_label = if_else(student_training == "same_base", "same-base", "cross-base"),
    condition = paste(training_label, gsub("-v0.3", "", student_base), sep = "\n")
  ) %>%
  group_by(condition, dataset) %>%
  summarise(auroc = mean(auroc, na.rm = TRUE), .groups = "drop")

write_csv(cross_plot, file.path(derived_dir, "supp_cross_base_task_heatmap.csv"))

p_s3c <- ggplot(cross_plot, aes(dataset, condition, fill = auroc)) +
  geom_tile(colour = "white", linewidth = 0.45) +
  geom_text(aes(label = sprintf("%.3f", auroc)), size = 2.15, colour = pc("ink")) +
  scale_fill_gradient(low = "#EDF2FB", high = pc("blue"), limits = c(0.90, 1.0), oob = squish) +
  labs(
    title = "Cross-task AUROC",
    subtitle = "Cross-base rows remain below same-base rows but above chance",
    x = NULL,
    y = NULL
  ) +
  theme_supp() +
  theme(
    legend.position = "none",
    axis.text.x = element_text(angle = 30, hjust = 1)
  )

task_levels <- c("GSM8K", "MATH", "BBH", "ARC", "MBPP", "MMLU")
mtcr_plot <- mtcr_profile %>%
  mutate(
    task_view = factor(task_view, levels = task_levels),
    profile = case_when(
      grepl("True", candidate_teacher) ~ "true teacher",
      grepl("Sibling", candidate_teacher) ~ "sibling teacher",
      TRUE ~ "surplus margin"
    ),
    profile = factor(profile, levels = c("true teacher", "sibling teacher", "surplus margin"))
  )

write_csv(mtcr_plot, file.path(derived_dir, "supp_mtcr_task_profile.csv"))

p_s3d <- ggplot(mtcr_plot, aes(task_view, score_mtcr, group = profile, colour = profile)) +
  geom_line(linewidth = 0.75) +
  geom_point(size = 1.8) +
  geom_text(
    data = mtcr_plot %>% filter(task_view == "MMLU"),
    aes(label = profile),
    nudge_x = 0.35,
    hjust = 0,
    size = 2.05,
    show.legend = FALSE
  ) +
  scale_colour_manual(values = c("true teacher" = pc("cml"), "sibling teacher" = pc("purple"), "surplus margin" = pc("orange"))) +
  scale_x_discrete(expand = expansion(add = c(0.25, 1.25))) +
  scale_y_continuous(limits = c(0.1, 0.42)) +
  coord_cartesian(clip = "off") +
  labs(
    title = "MTCR task profile",
    subtitle = "Aggregate separation used for sibling triage",
    x = NULL,
    y = "MTCR score"
  ) +
  theme_supp() +
  theme(
    legend.position = "none",
    axis.text.x = element_text(angle = 30, hjust = 1)
  )

fig_s3 <- (p_s3a | p_s3b) / (p_s3c | p_s3d)
fig_s3 <- fig_s3 +
  plot_layout(guides = "keep") +
  plot_annotation(tag_levels = "a") &
  theme(plot.tag = element_text(face = "bold", size = 10, colour = pc("ink")))

save_pub(fig_s3, "fig_supp_operating_stress", width = 7.25, height = 6.95)

baseline_rows <- baseline_summary %>%
  arrange(desc(detection_auroc)) %>%
  transmute(
    row = sprintf(
      "%s & %.3f & %.3f & %.3f & %.3f \\\\",
      latex_escape(as.character(original_method)),
      detection_auroc,
      same_family_auroc,
      sibling_attribution,
      fpr_zero
    )
  ) %>%
  pull(row)

write_latex_table(
  file.path(table_dir, "supp_baseline_head_to_head.tex"),
  "Aggregate head-to-head comparison against alternative provenance baselines. Values are means over the staged student rows in the packaged source table.",
  "tab:supp_baseline_head_to_head",
  "Method & Detection AUROC & Same-family AUROC & Sibling attribution & FPR$_0$ \\\\",
  baseline_rows
)

open_rows <- open_summary %>%
  arrange(desc(abstention_rate)) %>%
  transmute(
    row = sprintf(
      "%s & %.3f & %.3f & %.3f & %.3f \\\\",
      latex_escape(as.character(scenario)),
      abstention_rate,
      false_attribution_rate,
      coverage,
      NA_real_
    )
  ) %>%
  pull(row) %>%
  gsub(" & NA \\\\", " & -- \\\\", ., fixed = TRUE)

write_latex_table(
  file.path(table_dir, "supp_open_set_triage.tex"),
  "Open-set and absent-candidate triage summary. Coverage denotes the non-false-attribution operating coverage reported in the source table.",
  "tab:supp_open_set_triage",
  "Scenario & Abstention & False attribution & Coverage & Closed-set acc. \\\\",
  open_rows
)

adaptive_rows <- adaptive_summary %>%
  filter(method == "CML+MTCR") %>%
  arrange(desc(auroc)) %>%
  transmute(
    row = sprintf(
      "%s & %.3f & %.3f & %.3f & -- \\\\",
      latex_escape(as.character(evasion_attack)),
      auroc,
      tpr_at_1pct_fpr,
      fpr_zero
    )
  ) %>%
  pull(row)

write_latex_table(
  file.path(table_dir, "supp_adaptive_stress.tex"),
  "Adaptive trace-transformation stress tests for CML+MTCR. Values are aggregate operating summaries over the staged student rows.",
  "tab:supp_adaptive_stress",
  "Stress condition & AUROC & TPR at 1\\% FPR & FPR$_0$ & Notes \\\\",
  adaptive_rows
)

message("Wrote supplementary figures and tables.")
