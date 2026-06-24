#!/usr/bin/env Rscript

suppressPackageStartupMessages({
  library(dplyr)
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
root_dir <- if (nzchar(script_file)) dirname(normalizePath(script_file)) else getwd()
source_dir <- file.path(root_dir, "source")
derived_dir <- file.path(root_dir, "source_derived")
dir.create(derived_dir, showWarnings = FALSE, recursive = TRUE)

palette <- c(
  ink = "#111827",
  slate = "#253244",
  neutral = "#73808F",
  grid = "#E8EDF3",
  cml = "#0E9F78",
  cml_dark = "#047857",
  baseline = "#C65A1E",
  blue = "#2764A5",
  purple = "#7767B0",
  amber = "#D89A27",
  risk = "#B53F2F",
  pale = "#F7F9FC"
)

pc <- function(name) unname(palette[[name]])

theme_tifs <- function(base_size = 8.0) {
  theme_classic(base_size = base_size, base_family = "Arial") +
    theme(
      plot.background = element_rect(fill = "white", colour = NA),
      panel.background = element_rect(fill = "white", colour = NA),
      axis.line = element_line(colour = pc("slate"), linewidth = 0.3),
      axis.ticks = element_line(colour = pc("slate"), linewidth = 0.25),
      axis.text = element_text(colour = pc("ink"), size = rel(0.86)),
      axis.title = element_text(colour = pc("ink"), size = rel(0.93)),
      plot.title = element_text(face = "bold", size = rel(1.02), colour = pc("ink"), hjust = 0),
      plot.subtitle = element_text(size = rel(0.78), colour = "#566274", hjust = 0),
      panel.grid.major.y = element_line(colour = pc("grid"), linewidth = 0.22),
      panel.grid.major.x = element_blank(),
      panel.grid.minor = element_blank(),
      legend.title = element_blank(),
      legend.text = element_text(size = rel(0.78), colour = pc("ink")),
      strip.background = element_rect(fill = pc("pale"), colour = "#D7DEE8", linewidth = 0.25),
      strip.text = element_text(face = "bold", size = rel(0.82), colour = pc("ink")),
      plot.margin = margin(4, 5, 4, 5)
    )
}

theme_set(theme_tifs())

save_pub <- function(plot, name, width = 7.2, height = 11.3) {
  pdf_path <- file.path(root_dir, paste0(name, ".pdf"))
  svg_path <- file.path(root_dir, paste0(name, ".svg"))
  png_path <- file.path(root_dir, paste0(name, ".png"))
  tiff_path <- file.path(root_dir, paste0(name, ".tiff"))

  ggsave(pdf_path, plot, width = width, height = height, units = "in", device = cairo_pdf)
  svglite::svglite(svg_path, width = width, height = height)
  print(plot)
  dev.off()
  ragg::agg_png(png_path, width = width, height = height, units = "in", res = 450, background = "white")
  print(plot)
  dev.off()
  ragg::agg_tiff(tiff_path, width = width, height = height, units = "in", res = 600, compression = "lzw", background = "white")
  print(plot)
  dev.off()
}

read_required <- function(name) {
  path <- file.path(source_dir, name)
  if (!file.exists(path)) stop("Missing figure source: ", path, call. = FALSE)
  read_csv(path, show_col_types = FALSE)
}

label_attack <- function(x) {
  recode(
    x,
    identity_control = "Identity",
    paraphrase_second_model = "Paraphrase",
    answer_only_compression = "Answer-only",
    cot_compression = "CoT comp.",
    style_rewrite = "Style",
    temperature_top_p = "Temp/top-p",
    mixed_human_teacher = "Mixed 50%",
    mixed_human_teacher_50pct = "Mixed 50%",
    selective_low_score_traces = "Low-score",
    .default = x
  )
}

task_levels <- c("GSM8K", "MATH", "BBH", "ARC-Challenge", "MBPP", "MMLU")
task_axis_labels <- c(
  "GSM8K" = "GSM8K",
  "MATH" = "MATH",
  "BBH" = "BBH",
  "ARC-Challenge" = "ARC",
  "MBPP" = "MBPP",
  "MMLU" = "MMLU"
)

adaptive <- read_required("w08_tifs_adaptive_attack_summary.csv") %>%
  mutate(
    attack_label = label_attack(attack_type),
    method = if_else(detection_method == "CML+MTCR", "CML+MTCR", "Base-relative"),
    auroc = as.numeric(auroc),
    ci_low = as.numeric(ci_low),
    ci_high = as.numeric(ci_high),
    tpr_at_1pct_fpr = as.numeric(tpr_at_1pct_fpr),
    fpr_zero = as.numeric(fpr_zero),
    attack_label = factor(
      attack_label,
      levels = c("Identity", "Paraphrase", "Answer-only", "CoT comp.", "Style", "Temp/top-p", "Mixed 50%", "Low-score")
    ),
    dataset = factor(dataset, levels = task_levels)
  )

write_csv(adaptive, file.path(derived_dir, "pi_lock_adaptive_for_plot.csv"))

adaptive_cml <- adaptive %>%
  filter(method == "CML+MTCR") %>%
  group_by(dataset, attack_label) %>%
  summarise(
    auroc = mean(auroc, na.rm = TRUE),
    ci_low = min(ci_low, na.rm = TRUE),
    ci_high = max(ci_high, na.rm = TRUE),
    tpr_at_1pct_fpr = mean(tpr_at_1pct_fpr, na.rm = TRUE),
    fpr_zero = max(fpr_zero, na.rm = TRUE),
    .groups = "drop"
  )

adaptive_base <- adaptive %>%
  filter(method == "Base-relative") %>%
  group_by(dataset, attack_label) %>%
  summarise(base_auroc = mean(auroc, na.rm = TRUE), .groups = "drop")

write_csv(adaptive_cml, file.path(derived_dir, "pi_lock_adaptive_cml_heatmap.csv"))
write_csv(adaptive_base, file.path(derived_dir, "pi_lock_adaptive_base_points.csv"))

p_adaptive <- adaptive_cml %>%
  ggplot(aes(x = dataset, y = attack_label, fill = auroc)) +
  geom_tile(colour = "white", linewidth = 0.35) +
  geom_point(
    data = adaptive_base,
    aes(x = dataset, y = attack_label, size = base_auroc),
    inherit.aes = FALSE,
    shape = 21,
    colour = pc("baseline"),
    fill = "white",
    stroke = 0.35,
    alpha = 0.95
  ) +
  scale_fill_gradientn(
    colours = c("#F4D6C5", "#F6E7A7", "#DDEDC8", "#A8D9C7", pc("cml_dark")),
    limits = c(0.90, 1.00),
    oob = squish
  ) +
  scale_x_discrete(labels = task_axis_labels) +
  scale_size_continuous(range = c(0.55, 1.75), limits = c(0.49, 0.53), breaks = c(0.50, 0.53)) +
  labs(title = "Adaptive evasion stress", subtitle = "CML+MTCR AUROC heatmap; open circles show base-relative AUROC", x = NULL, y = NULL) +
  theme(
    legend.position = "right",
    axis.text.x = element_text(angle = 35, hjust = 1),
    axis.text.y = element_text(size = 6.3)
  )

cross_base <- read_required("w08_tifs_cross_base_task_matrix.csv") %>%
  mutate(
    access = if_else(grepl("same", student_training), "same-base", "cross-base"),
    teacher_short = recode(
      teacher_model,
      "Qwen2.5-32B" = "Qwen teacher",
      "Llama-3.1-70B" = "Llama teacher",
      .default = teacher_model
    ),
    student_short = recode(
      student_base,
      "Qwen2.5-7B" = "Qwen student",
      "Llama-3.1-8B" = "Llama student",
      "Mistral-v0.3-7B" = "Mistral student",
      .default = student_base
    ),
    row_id = paste(teacher_short, student_short, access, sep = " / "),
    dataset = factor(dataset, levels = c("GSM8K", "MATH", "BBH", "ARC-Challenge", "MBPP"))
  )

write_csv(cross_base, file.path(derived_dir, "pi_lock_cross_base_for_plot.csv"))

p_cross <- cross_base %>%
  ggplot(aes(x = dataset, y = reorder(row_id, auroc), fill = auroc)) +
  geom_tile(colour = "white", linewidth = 0.35) +
  scale_fill_gradientn(colours = c("#F4D6C5", "#F6E7A7", "#DDEDC8", "#A8D9C7", "#65B8A0"), limits = c(0.90, 1.00), oob = squish) +
  scale_x_discrete(labels = task_axis_labels) +
  labs(title = "Cross-base and cross-task transfer", subtitle = "Aggregate AUROC matrix", x = NULL, y = NULL) +
  theme(
    legend.position = "right",
    axis.text.x = element_text(angle = 35, hjust = 1),
    axis.text.y = element_text(size = 6.3)
  )

open_set <- read_required("w08_tifs_open_set_abstention_summary.csv") %>%
  mutate(
    abstention_rate = as.numeric(abstention_rate),
    false_attribution_rate = as.numeric(false_attribution_rate),
    coverage = as.numeric(coverage)
  ) %>%
  group_by(condition) %>%
  summarise(
    abstention_rate = mean(abstention_rate, na.rm = TRUE),
    false_attribution_rate = mean(false_attribution_rate, na.rm = TRUE),
    coverage = mean(coverage, na.rm = TRUE),
    false_attribution_max = max(false_attribution_rate, na.rm = TRUE),
    .groups = "drop"
  ) %>%
  mutate(
    scenario = recode(
      condition,
      source_teacher_absent = "Source absent",
      sibling_teacher_absent = "Sibling absent",
      unrelated_teacher = "Unrelated teacher",
      unrelated_capable_teacher_present = "Unrelated teacher",
      public_decoy_present = "Public decoy",
      public_model_decoy = "Public decoy",
      .default = condition
    )
  ) %>%
  select(scenario, abstention_rate, false_attribution_rate, coverage, false_attribution_max) %>%
  pivot_longer(-scenario, names_to = "metric", values_to = "value") %>%
  mutate(
    metric = recode(
      metric,
      abstention_rate = "abstention",
      false_attribution_rate = "false attribution",
      false_attribution_max = "max false attribution",
      coverage = "coverage"
    )
  )

write_csv(open_set, file.path(derived_dir, "pi_lock_open_set_for_plot.csv"))

p_open <- open_set %>%
  filter(metric != "max false attribution") %>%
  ggplot(aes(x = value, y = reorder(scenario, value), fill = metric)) +
  geom_col(position = position_dodge2(width = 0.78), width = 0.66) +
  scale_fill_manual(values = c("abstention" = pc("blue"), "coverage" = pc("cml"), "false attribution" = pc("risk"))) +
  scale_x_continuous(labels = percent_format(accuracy = 1), limits = c(0, 1)) +
  labs(title = "Open-set abstention", subtitle = "Mean across five tasks and two reported lineages", x = NULL, y = NULL) +
  guides(fill = guide_legend(nrow = 3, byrow = TRUE)) +
  theme(
    legend.position = "right",
    legend.key.size = grid::unit(3.2, "mm"),
    legend.spacing.y = grid::unit(0.5, "mm")
  )

baseline <- read_required("w08_tifs_baseline_head_to_head.csv") %>%
  mutate(
    method_label = recode(
      method,
      base_relative = "BaseRel",
      perplexity_logprob = "PPL",
      embedding_mmd = "MMD",
      style_classifier = "Style",
      wadhwa_classifier = "Teacher",
      model_provenance_testing = "MPT",
      `CML+MTCR` = "MTCR",
      .default = method
    ),
    auroc = as.numeric(auroc),
    same_family_auroc = as.numeric(same_family_auroc),
    sibling_attribution_accuracy = as.numeric(sibling_attribution_accuracy),
    fpr_zero = as.numeric(fpr_zero),
    method = factor(
      method,
      levels = c("base_relative", "perplexity_logprob", "embedding_mmd", "style_classifier", "wadhwa_classifier", "model_provenance_testing", "CML", "CML+MTCR")
    )
  ) %>%
  group_by(method, method_label) %>%
  summarise(
    auroc = min(auroc, na.rm = TRUE),
    same_family_auroc = min(same_family_auroc, na.rm = TRUE),
    sibling_attribution_accuracy = min(sibling_attribution_accuracy, na.rm = TRUE),
    fpr_zero = max(fpr_zero, na.rm = TRUE),
    .groups = "drop"
  ) %>%
  select(method, method_label, auroc, same_family_auroc, sibling_attribution_accuracy, fpr_zero) %>%
  pivot_longer(c(auroc, same_family_auroc, sibling_attribution_accuracy, fpr_zero), names_to = "metric", values_to = "value") %>%
  mutate(
    metric = recode(
      metric,
      auroc = "detection AUROC",
      same_family_auroc = "same-family AUROC",
      sibling_attribution_accuracy = "sibling attribution",
      fpr_zero = "FPR0"
    ),
    is_ours = method %in% c("CML", "CML+MTCR")
  )

write_csv(baseline, file.path(derived_dir, "pi_lock_baseline_for_plot.csv"))

p_baseline <- baseline %>%
  mutate(
    metric = factor(metric, levels = c("detection AUROC", "same-family AUROC", "sibling attribution", "FPR0")),
    method_label = factor(method_label, levels = c("BaseRel", "PPL", "MMD", "Style", "Teacher", "MPT", "CML", "MTCR")),
    value_label = sprintf("%.2f", value),
    label_colour = if_else(value > 0.62, "white", pc("ink"))
  ) %>%
  ggplot(aes(x = method_label, y = metric, fill = value)) +
  geom_tile(colour = "white", linewidth = 0.35) +
  geom_text(aes(label = value_label, colour = label_colour), size = 2.05, fontface = "bold") +
  scale_fill_gradientn(colours = c("#F3DDC8", "#F5EBAF", "#D6EBC6", "#88CEB8", pc("cml_dark")), limits = c(0, 1), oob = squish) +
  scale_colour_identity() +
  labs(title = "Unified-calibration baselines", subtitle = "Worst-case metric matrix across tasks and lineages", x = NULL, y = NULL) +
  theme(
    legend.position = "none",
    axis.text.x = element_text(angle = 35, hjust = 1, size = 5.8),
    axis.text.y = element_text(size = 6.5)
  )

student_ci <- read_required("w08_tifs_student_level_ci.csv") %>%
  mutate(
    estimate = as.numeric(estimate),
    ci_low = as.numeric(ci_low),
    ci_high = as.numeric(ci_high),
    condition_label = recode(
      condition,
      all_distilled_vs_ctrlc = "All distilled",
      cross_style_vs_ctrlc = "Cross-style",
      `cross-style_vs_ctrlc` = "Cross-style",
      same_family_vs_ctrlc = "Same-family",
      `same-family_vs_ctrlc` = "Same-family",
      .default = condition
    )
  ) %>%
  group_by(condition_label) %>%
  summarise(
    estimate = mean(estimate, na.rm = TRUE),
    ci_low = min(ci_low, na.rm = TRUE),
    ci_high = max(ci_high, na.rm = TRUE),
    .groups = "drop"
  )

write_csv(student_ci, file.path(derived_dir, "pi_lock_student_ci_for_plot.csv"))

p_ci <- student_ci %>%
  ggplot(aes(x = estimate, y = reorder(condition_label, estimate))) +
  geom_errorbar(aes(xmin = ci_low, xmax = ci_high), orientation = "y", width = 0.18, linewidth = 0.45, colour = pc("blue")) +
  geom_point(size = 1.8, colour = pc("blue")) +
  scale_x_continuous(limits = c(0.90, 1.12)) +
  labs(title = "Student-level significance", subtitle = "Mean margin with full reported CI envelope", x = "margin", y = NULL)

mtcr <- read_required("w08_tifs_mtcr_task_profile_summary.csv") %>%
  mutate(
    candidate_label = case_when(
      grepl("True", candidate_teacher) ~ "true teacher",
      grepl("Sibling", candidate_teacher) ~ "sibling",
      grepl("Surplus", candidate_teacher) ~ "surplus margin",
      TRUE ~ candidate_teacher
    ),
    task_view = factor(task_view, levels = c("GSM8K", "MATH", "BBH", "ARC", "MBPP", "MMLU"))
  )

write_csv(mtcr, file.path(derived_dir, "pi_lock_mtcr_for_plot.csv"))

p_mtcr <- mtcr %>%
  ggplot(aes(x = task_view, y = candidate_label, fill = score_mtcr)) +
  geom_tile(colour = "white", linewidth = 0.35) +
  scale_fill_gradient(low = "#F5E8BF", high = pc("purple")) +
  labs(title = "MTCR task profile", subtitle = "Sibling surplus remains stable across task views", x = NULL, y = NULL) +
  theme(legend.position = "right", axis.text.x = element_text(angle = 35, hjust = 1))

fig <- p_adaptive / (p_cross | p_open) / (p_baseline | p_ci) / p_mtcr +
  plot_layout(heights = c(1.22, 1.02, 1.02, 0.92)) +
  plot_annotation(tag_levels = "a") &
  theme(plot.tag = element_text(face = "bold", size = 9.5, colour = pc("ink")))

save_pub(fig, "fig_tifs_pi_result_lock_suite", width = 7.2, height = 8.55)

message("Wrote fig_tifs_pi_result_lock_suite.{pdf,svg,png,tiff}")
