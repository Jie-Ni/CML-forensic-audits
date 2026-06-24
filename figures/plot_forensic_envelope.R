#!/usr/bin/env Rscript

suppressPackageStartupMessages({
  library(dplyr)
  library(ggplot2)
  library(ggrepel)
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
project_root <- normalizePath(file.path(root_dir, ".."))
summary_dir <- file.path(project_root, "results_90pt", "summaries")
derived_dir <- file.path(root_dir, "source_derived")
dir.create(derived_dir, showWarnings = FALSE, recursive = TRUE)

required <- file.path(
  summary_dir,
  c(
    "base_mismatch_calibration_summary.csv",
    "out_of_set_abstention_summary.csv",
    "cross_base_student_matrix.csv"
  )
)
missing <- required[!file.exists(required)]
if (length(missing) > 0) {
  stop("Missing required summary source(s): ", paste(missing, collapse = ", "), call. = FALSE)
}

palette <- c(
  ink = "#111827",
  slate = "#26364D",
  neutral = "#6B7280",
  light = "#E6EBF2",
  pale = "#F7F9FC",
  cml = "#0E9F78",
  cml_dark = "#047857",
  baseline = "#D95F02",
  qwen = "#2563A8",
  llama = "#0E9F78",
  risk = "#B8481C",
  caution = "#C89211",
  purple = "#7C6BB5",
  blue_soft = "#D8E6F7",
  teal_soft = "#D7EFE6",
  orange_soft = "#F6D7BF"
)

pc <- function(name) unname(palette[[name]])

theme_envelope <- function(base_size = 6.8) {
  theme_classic(base_size = base_size, base_family = "Arial") +
    theme(
      plot.background = element_rect(fill = "white", colour = NA),
      panel.background = element_rect(fill = "white", colour = NA),
      axis.line = element_line(colour = pc("slate"), linewidth = 0.30),
      axis.ticks = element_line(colour = pc("slate"), linewidth = 0.25),
      axis.text = element_text(colour = pc("ink"), size = rel(0.88)),
      axis.title = element_text(colour = pc("ink"), size = rel(0.94)),
      plot.title = element_text(face = "bold", size = rel(1.04), colour = pc("ink"), hjust = 0),
      plot.subtitle = element_text(size = rel(0.81), colour = "#536172", hjust = 0),
      strip.background = element_rect(fill = pc("pale"), colour = "#D8DFEA", linewidth = 0.25),
      strip.text = element_text(face = "bold", colour = pc("ink"), size = rel(0.82)),
      legend.title = element_blank(),
      legend.text = element_text(size = rel(0.78), colour = pc("ink")),
      legend.key.height = unit(0.13, "in"),
      legend.key.width = unit(0.24, "in"),
      legend.background = element_blank(),
      legend.box.background = element_blank(),
      panel.grid.major.y = element_line(colour = "#EEF2F7", linewidth = 0.20),
      panel.grid.major.x = element_blank(),
      panel.grid.minor = element_blank(),
      plot.margin = margin(4, 5, 4, 5)
    )
}

theme_set(theme_envelope())

panel_theme <- theme_envelope() +
  theme(
    plot.tag = element_text(face = "bold", size = 9.5, colour = pc("ink")),
    plot.tag.position = c(0.01, 0.98)
  )

save_pub <- function(plot, name, width = 7.2, height = 6.1) {
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
  ragg::agg_tiff(
    tiff_path,
    width = width,
    height = height,
    units = "in",
    res = 600,
    compression = "lzw",
    background = "white"
  )
  print(plot)
  dev.off()
}

short_teacher <- function(x) {
  recode(
    x,
    "r1-distill-qwen-32b" = "R1-Qwen-32B",
    "qwen2.5-14b" = "Qwen2.5-14B",
    "r1-distill-llama-8b" = "R1-Llama-8B",
    .default = x
  )
}

base_summary <- read_csv(file.path(summary_dir, "base_mismatch_calibration_summary.csv"), show_col_types = FALSE) %>%
  mutate(
    reference = recode(
      condition,
      "correct_base_reference" = "matched reference",
      "no_runnable_base_fallback" = "human fallback",
      .default = condition
    ),
    teacher = short_teacher(candidate_teacher)
  )

base_auroc <- base_summary %>%
  select(teacher, reference, auroc) %>%
  mutate(metric = "AUROC", value = auroc)

base_fpr <- base_summary %>%
  select(teacher, reference, fpr_zero) %>%
  mutate(metric = "FPR at zero threshold", value = fpr_zero)

base_long <- bind_rows(base_auroc, base_fpr) %>%
  mutate(
    teacher = factor(teacher, levels = c("Qwen2.5-14B", "R1-Qwen-32B", "R1-Llama-8B")),
    reference = factor(reference, levels = c("matched reference", "human fallback")),
    metric = factor(metric, levels = c("AUROC", "FPR at zero threshold")),
    label_hjust = if_else(value > 0.92, 1.10, -0.10)
  )

write_csv(base_long, file.path(derived_dir, "forensic_envelope_base_reference.csv"))

open_summary <- read_csv(file.path(summary_dir, "out_of_set_abstention_summary.csv"), show_col_types = FALSE) %>%
  mutate(
    student_group = if_else(grepl("^ctrlA|^ctrlC", student_id), "controls", "distilled students"),
    condition_label = recode(
      condition,
      "source_teacher_present_closed_set" = "present\nclosed",
      "source_teacher_absent" = "source\nabsent",
      "sibling_teacher_absent" = "sibling\nabsent",
      "unrelated_capable_teacher_present" = "unrelated\npresent",
      .default = condition
    )
  ) %>%
  group_by(condition, condition_label, student_group) %>%
  summarise(
    abstention_mean = mean(abstention_rate, na.rm = TRUE),
    abstention_min = min(abstention_rate, na.rm = TRUE),
    abstention_max = max(abstention_rate, na.rm = TRUE),
    false_attr_mean = mean(false_attribution_rate, na.rm = TRUE),
    false_attr_min = min(false_attribution_rate, na.rm = TRUE),
    false_attr_max = max(false_attribution_rate, na.rm = TRUE),
    closed_set_accuracy = mean(closed_set_accuracy, na.rm = TRUE),
    n_students = n(),
    .groups = "drop"
  ) %>%
  mutate(
    condition_label = factor(
      condition_label,
      levels = c(
        "present\nclosed",
        "source\nabsent",
        "sibling\nabsent",
        "unrelated\npresent"
      )
    ),
    student_group = factor(student_group, levels = c("distilled students", "controls"))
  )

write_csv(open_summary, file.path(derived_dir, "forensic_envelope_open_set_summary.csv"))

open_long <- open_summary %>%
  select(
    condition_label,
    student_group,
    n_students,
    abstention_mean,
    abstention_min,
    abstention_max,
    false_attr_mean,
    false_attr_min,
    false_attr_max
  ) %>%
  pivot_longer(
    cols = c(abstention_mean, false_attr_mean),
    names_to = "metric",
    values_to = "mean"
  ) %>%
  mutate(
    ymin = if_else(metric == "abstention_mean", abstention_min, false_attr_min),
    ymax = if_else(metric == "abstention_mean", abstention_max, false_attr_max),
    metric_label = recode(
      metric,
      "abstention_mean" = "abstention",
      "false_attr_mean" = "false attribution"
    ),
    metric_label = factor(metric_label, levels = c("abstention", "false attribution"))
  )

cross_summary <- read_csv(file.path(summary_dir, "cross_base_student_matrix.csv"), show_col_types = FALSE) %>%
  mutate(
    transfer_label = recode(
      transfer_type,
      "within-family" = "within family",
      "cross-family" = "cross family",
      .default = transfer_type
    ),
    method = student_training,
    family_pair = paste0(student_base, "\nvs ", teacher_family)
  ) %>%
  group_by(transfer_label, method) %>%
  summarise(
    auroc_mean = mean(auroc, na.rm = TRUE),
    auroc_min = min(auroc, na.rm = TRUE),
    auroc_max = max(auroc, na.rm = TRUE),
    tpr_mean = mean(tpr_at_1pct_fpr, na.rm = TRUE),
    fpr_mean = mean(fpr_zero, na.rm = TRUE),
    n_conditions = n(),
    .groups = "drop"
  ) %>%
  mutate(
    transfer_label = factor(transfer_label, levels = c("within family", "cross family")),
    method = factor(method, levels = c("CML", "CML+MTCR"))
  )

write_csv(cross_summary, file.path(derived_dir, "forensic_envelope_cross_family_summary.csv"))

p_a <- ggplot(base_long %>% filter(metric == "AUROC"), aes(x = value, y = teacher, colour = reference)) +
  geom_path(aes(group = teacher), colour = "#CAD3DF", linewidth = 0.65) +
  geom_point(size = 2.35) +
  geom_text(
    aes(label = number(value, accuracy = 0.001)),
    size = 2.05,
    hjust = -0.10,
    show.legend = FALSE
  ) +
  scale_colour_manual(values = c("matched reference" = pc("cml"), "human fallback" = pc("risk"))) +
  scale_x_continuous(limits = c(0.42, 1.04), breaks = c(0.5, 0.75, 1.0)) +
  labs(
    title = "Reference choice sets the boundary",
    subtitle = "AUROC collapses when the matched reference is unavailable",
    x = "trace-level AUROC",
    y = NULL
  ) +
  panel_theme +
  theme(legend.position = "top")

p_b <- ggplot(base_long %>% filter(metric == "FPR at zero threshold"), aes(x = value, y = teacher, colour = reference)) +
  geom_path(aes(group = teacher), colour = "#CAD3DF", linewidth = 0.65) +
  geom_point(size = 2.35) +
  geom_text(
    aes(label = number(value, accuracy = 0.001), hjust = label_hjust),
    size = 2.05,
    show.legend = FALSE
  ) +
  scale_colour_manual(values = c("matched reference" = pc("cml"), "human fallback" = pc("risk"))) +
  scale_x_continuous(limits = c(0, 1.03), breaks = c(0, 0.5, 1.0)) +
  labs(
    title = "Fallback reference creates false alarms",
    subtitle = "Same scored matrices; only the reference changes",
    x = "FPR at zero threshold",
    y = NULL
  ) +
  panel_theme +
  theme(legend.position = "none")

p_c <- ggplot(
  open_long,
  aes(x = condition_label, y = mean, ymin = ymin, ymax = ymax, colour = student_group)
) +
  geom_linerange(
    position = position_dodge(width = 0.46),
    linewidth = 0.42,
    alpha = 0.82
  ) +
  geom_point(
    position = position_dodge(width = 0.46),
    size = 1.75
  ) +
  facet_wrap(~metric_label, nrow = 1) +
  scale_colour_manual(values = c("distilled students" = pc("qwen"), "controls" = pc("neutral"))) +
  scale_y_continuous(labels = percent_format(accuracy = 1), limits = c(0, 1.02)) +
  labs(
    title = "Absent-candidate triage",
    subtitle = "Group means with min-max ranges across staged student rows",
    x = NULL,
    y = "rate"
  ) +
  panel_theme +
  theme(
    legend.position = "top",
    axis.text.x = element_text(size = 4.8, lineheight = 0.86),
    panel.spacing.x = unit(0.08, "in")
  )

p_d <- ggplot(cross_summary, aes(x = auroc_mean, y = transfer_label, colour = method)) +
  geom_segment(
    aes(x = auroc_min, xend = auroc_max, yend = transfer_label),
    linewidth = 0.52,
    alpha = 0.48
  ) +
  geom_point(size = 2.35) +
  geom_text_repel(
    aes(label = paste0(method, " ", number(auroc_mean, accuracy = 0.001))),
    size = 2.0,
    min.segment.length = 0,
    box.padding = 0.18,
    point.padding = 0.12,
    seed = 8,
    show.legend = FALSE
  ) +
  scale_colour_manual(values = c("CML" = pc("qwen"), "CML+MTCR" = pc("cml"))) +
  scale_x_continuous(limits = c(0.90, 1.005), breaks = c(0.90, 0.95, 1.00)) +
  labs(
    title = "Cross-family stress is lower than within-family",
    subtitle = "Imported summary; ranges span the staged family-pair conditions",
    x = "AUROC",
    y = NULL
  ) +
  panel_theme +
  theme(legend.position = "none")

fig <- (p_a | p_c) / (p_b | p_d) +
  plot_layout(widths = c(1.0, 1.22), heights = c(1, 1), guides = "keep") +
  plot_annotation(tag_levels = "a") &
  theme(
    plot.tag = element_text(face = "bold", size = 9.5, colour = pc("ink"))
  )

save_pub(fig, "fig_forensic_envelope", width = 7.2, height = 6.05)

message("Wrote fig_forensic_envelope.{pdf,svg,png,tiff} and source_derived/forensic_envelope_*.csv")
