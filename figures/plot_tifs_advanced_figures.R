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
root_dir <- if (exists("root_dir", inherits = TRUE) && dir.exists(root_dir)) {
  root_dir
} else if (nzchar(script_file)) {
  dirname(normalizePath(script_file))
} else {
  getwd()
}
source_dir <- file.path(root_dir, "source")
derived_dir <- file.path(root_dir, "source_derived")
project_root <- normalizePath(file.path(root_dir, ".."), winslash = "/", mustWork = FALSE)
summary_dir <- file.path(project_root, "results_90pt", "summaries")
dir.create(derived_dir, showWarnings = FALSE, recursive = TRUE)

palette <- c(
  ink = "#111827",
  slate = "#26364D",
  neutral = "#6B7280",
  light = "#DCE3EC",
  pale = "#F7F9FC",
  qwen = "#2563A8",
  qwen_soft = "#D8E6F7",
  llama = "#0E9F78",
  llama_soft = "#D7EFE6",
  cml = "#0E9F78",
  cml_dark = "#047857",
  baseline = "#D95F02",
  baseline_dark = "#A94400",
  baseline_soft = "#F6D7BF",
  risk = "#B8481C",
  purple = "#7C6BB5"
)

pc <- function(name) unname(palette[[name]])

theme_tifs <- function(base_size = 7.4) {
  theme_classic(base_size = base_size, base_family = "Arial") +
    theme(
      plot.background = element_rect(fill = "white", colour = NA),
      panel.background = element_rect(fill = "white", colour = NA),
      axis.line = element_line(colour = pc("slate"), linewidth = 0.32),
      axis.ticks = element_line(colour = pc("slate"), linewidth = 0.28),
      axis.text = element_text(colour = pc("ink"), size = rel(0.90)),
      axis.title = element_text(colour = pc("ink"), size = rel(0.95)),
      plot.title = element_text(face = "bold", size = rel(1.05), colour = pc("ink"), hjust = 0),
      plot.subtitle = element_text(size = rel(0.82), colour = "#536172", hjust = 0),
      legend.title = element_blank(),
      legend.text = element_text(size = rel(0.80), colour = pc("ink")),
      legend.key.height = unit(0.12, "in"),
      legend.key.width = unit(0.22, "in"),
      legend.background = element_blank(),
      panel.grid.major.y = element_line(colour = "#EEF2F7", linewidth = 0.22),
      panel.grid.major.x = element_blank(),
      panel.grid.minor = element_blank(),
      strip.background = element_rect(fill = pc("pale"), colour = "#D8DFEA", linewidth = 0.25),
      strip.text = element_text(face = "bold", size = rel(0.84), colour = pc("ink")),
      plot.margin = margin(4, 5, 4, 5)
    )
}

panel_theme <- theme_tifs() +
  theme(
    plot.tag = element_text(face = "bold", size = 10, colour = pc("ink")),
    plot.tag.position = c(0.01, 0.98)
  )

lineage_cols <- c("Qwen lineage" = pc("qwen"), "Llama lineage" = pc("llama"))
method_cols <- c("base-relative" = pc("baseline"), "CML" = pc("qwen"), "CML+MTCR" = pc("cml"))

save_pub <- function(plot, name, width = 7.2, height = 6.2) {
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

read_required_csv <- function(path) {
  if (!file.exists(path)) {
    stop("Missing required source: ", path, call. = FALSE)
  }
  read_csv(path, show_col_types = FALSE)
}

mtcr_attr <- read_required_csv(file.path(source_dir, "w08_mtcr_attribution.csv"))
shared <- read_required_csv(file.path(source_dir, "w08_shared_ancestor_detection.csv"))
epoch <- read_required_csv(file.path(source_dir, "w08_epoch_sensitivity.csv"))
calib <- read_required_csv(file.path(source_dir, "w08_calibration_tasks_ablation.csv"))
trace_budget <- read_required_csv(file.path(source_dir, "w08_trace_size_sensitivity.csv"))
step_depth <- read_required_csv(file.path(source_dir, "w08_reasoning_step_depth.csv"))
cross_dataset <- read_required_csv(file.path(source_dir, "w08_cross_dataset_generalizability.csv"))
hyper <- read_required_csv(file.path(source_dir, "w08_hyperparameter_robustness.csv"))

mtcr_flow <- mtcr_attr %>%
  select(student_model, standard_cml_accuracy, cml_mtcr_accuracy, gain_pp) %>%
  mutate(lineage = if_else(grepl("Qwen", student_model), "Qwen lineage", "Llama lineage")) %>%
  pivot_longer(
    cols = c(standard_cml_accuracy, cml_mtcr_accuracy),
    names_to = "stage",
    values_to = "accuracy"
  ) %>%
  mutate(
    stage = recode(stage, standard_cml_accuracy = "standard CML", cml_mtcr_accuracy = "CML+MTCR"),
    stage = factor(stage, levels = c("standard CML", "CML+MTCR")),
    stage_x = if_else(stage == "standard CML", 1, 2)
  )

p3a <- ggplot(mtcr_flow, aes(stage_x, accuracy, group = student_model, colour = lineage)) +
  geom_segment(
    data = mtcr_flow %>%
      select(student_model, lineage, stage, accuracy) %>%
      pivot_wider(names_from = stage, values_from = accuracy),
    aes(x = 1, xend = 2, y = `standard CML`, yend = `CML+MTCR`, colour = lineage),
    inherit.aes = FALSE,
    linewidth = 1.0,
    alpha = 0.72
  ) +
  geom_point(size = 2.6) +
  geom_label(
    data = mtcr_flow %>%
      filter(stage == "CML+MTCR") %>%
      mutate(
        label = paste0("+", sprintf("%.1f", gain_pp), " pp"),
        label_x = 2.10,
        label_y = accuracy + if_else(lineage == "Qwen lineage", 0.018, -0.006)
      ),
    aes(x = label_x, y = label_y, label = label),
    linewidth = 0,
    fill = "white",
    hjust = 0,
    size = 2.05,
    show.legend = FALSE
  ) +
  scale_colour_manual(values = lineage_cols) +
  scale_x_continuous(
    breaks = c(1, 2),
    labels = c("standard CML", "CML+MTCR")
  ) +
  scale_y_continuous(limits = c(0.62, 0.955), breaks = c(0.65, 0.75, 0.85, 0.95)) +
  coord_cartesian(xlim = c(0.82, 2.56), clip = "off") +
  labs(
    title = "MTCR repairs sibling attribution",
    subtitle = "Closed-set aggregate accuracy; labels show absolute gain",
    x = NULL,
    y = "accuracy"
  ) +
  panel_theme +
  theme(legend.position = "top")

calib_long <- calib %>%
  pivot_longer(cols = c(qwen_accuracy, llama_accuracy), names_to = "model", values_to = "accuracy") %>%
  mutate(
    lineage = recode(model, qwen_accuracy = "Qwen lineage", llama_accuracy = "Llama lineage"),
    calibration_tasks = as.numeric(calibration_tasks),
    residual_error = 1 - accuracy
  )

p3b <- ggplot(calib_long, aes(calibration_tasks, accuracy, colour = lineage)) +
  geom_line(linewidth = 0.82) +
  geom_point(size = 2.0) +
  geom_hline(yintercept = 0.90, linetype = "dashed", colour = "#C9D3E2", linewidth = 0.36) +
  geom_segment(
    data = calib_long %>%
      group_by(lineage) %>%
      filter(calibration_tasks == max(calibration_tasks)) %>%
      ungroup() %>%
      mutate(label_x = 17.0, label_y = accuracy + if_else(lineage == "Qwen lineage", 0.014, -0.020)),
    aes(x = calibration_tasks, xend = label_x - 0.15, y = accuracy, yend = label_y, colour = lineage),
    linewidth = 0.26,
    show.legend = FALSE
  ) +
  geom_label(
    data = calib_long %>%
      group_by(lineage) %>%
      filter(calibration_tasks == max(calibration_tasks)) %>%
      ungroup() %>%
      mutate(label_x = 17.0, label_y = accuracy + if_else(lineage == "Qwen lineage", 0.014, -0.020)),
    aes(x = label_x, y = label_y, label = lineage, colour = lineage),
    linewidth = 0,
    fill = "white",
    hjust = 0,
    size = 2.05,
    show.legend = FALSE
  ) +
  scale_colour_manual(values = lineage_cols) +
  scale_x_continuous(breaks = calib$calibration_tasks) +
  scale_y_continuous(limits = c(0.64, 0.928), breaks = c(0.70, 0.80, 0.90)) +
  coord_cartesian(xlim = c(1, 19.1), clip = "off") +
  labs(
    title = "Task views add calibration signal",
    subtitle = "More task views move both R1 siblings toward high-confidence attribution",
    x = "calibration task views",
    y = "accuracy"
  ) +
  panel_theme +
  theme(legend.position = "none")

error_df <- mtcr_attr %>%
  transmute(
    lineage = if_else(grepl("Qwen", student_model), "Qwen lineage", "Llama lineage"),
    standard_error = 1 - standard_cml_accuracy,
    mtcr_error = 1 - cml_mtcr_accuracy
  ) %>%
  pivot_longer(cols = c(standard_error, mtcr_error), names_to = "method", values_to = "error_rate") %>%
  mutate(
    method = recode(method, standard_error = "standard CML", mtcr_error = "CML+MTCR"),
    method = factor(method, levels = c("standard CML", "CML+MTCR")),
    lineage = factor(lineage, levels = c("Llama lineage", "Qwen lineage"))
  )

p3c <- ggplot(error_df, aes(error_rate, lineage, colour = method)) +
  geom_line(aes(group = lineage), colour = "#C9D3E2", linewidth = 0.62) +
  geom_point(size = 2.55) +
  geom_text(
    aes(label = percent(error_rate, accuracy = 0.1)),
    vjust = -0.9,
    size = 2.0,
    show.legend = FALSE
  ) +
  scale_colour_manual(values = c("standard CML" = pc("baseline"), "CML+MTCR" = pc("cml"))) +
  scale_x_continuous(labels = percent_format(accuracy = 1), limits = c(0.08, 0.36)) +
  labs(
    title = "Residual attribution error shrinks",
    subtitle = "Error = 1 - closed-set attribution accuracy",
    x = "residual error",
    y = NULL
  ) +
  panel_theme +
  theme(legend.position = "top")

shared_long <- shared %>%
  mutate(lineage = if_else(grepl("Qwen", student_model), "Qwen lineage", "Llama lineage")) %>%
  pivot_longer(
    cols = c(baseline_base_relative, cml_standard, cml_mtcr),
    names_to = "method",
    values_to = "auroc"
  ) %>%
  mutate(
    method = recode(method, baseline_base_relative = "base-relative", cml_standard = "CML", cml_mtcr = "CML+MTCR"),
    method = factor(method, levels = c("base-relative", "CML", "CML+MTCR")),
    lineage = factor(lineage, levels = c("Llama lineage", "Qwen lineage"))
  )

p3d <- ggplot(shared_long, aes(auroc, lineage, colour = method)) +
  geom_segment(aes(x = 0, xend = auroc, yend = lineage), colour = "#E0E6EF", linewidth = 0.38) +
  geom_point(size = 2.35) +
  scale_colour_manual(values = method_cols) +
  scale_x_continuous(limits = c(0, 1.03), breaks = c(0, 0.5, 1.0)) +
  labs(
    title = "Base-relative fails shared-ancestor recovery",
    subtitle = "CML and MTCR restore near-complete binary detection",
    x = "AUROC",
    y = NULL
  ) +
  panel_theme +
  theme(legend.position = "top")

epoch_long <- epoch %>%
  pivot_longer(cols = c(gsm8k_auroc, math_auroc), names_to = "dataset", values_to = "auroc") %>%
  mutate(
    dataset = recode(dataset, gsm8k_auroc = "GSM8K", math_auroc = "MATH"),
    epochs = as.numeric(epochs)
  )

p3e <- ggplot(epoch_long, aes(epochs, auroc, colour = dataset)) +
  geom_line(linewidth = 0.82) +
  geom_point(size = 2.15) +
  geom_text(
    data = epoch_long %>% filter(epochs == max(epochs)),
    aes(y = auroc + if_else(dataset == "GSM8K", 0.009, -0.009), label = sprintf("%.3f", auroc)),
    hjust = -0.18,
    size = 2.0,
    show.legend = FALSE
  ) +
  scale_colour_manual(values = c("GSM8K" = pc("qwen"), "MATH" = pc("llama"))) +
  scale_x_continuous(breaks = epoch$epochs) +
  scale_y_continuous(limits = c(0.76, 1.02), breaks = c(0.80, 0.90, 1.00)) +
  coord_cartesian(xlim = c(1, 5.8), clip = "off") +
  labs(
    title = "Distillation signal strengthens with epochs",
    subtitle = "MATH remains a single-seed stress test",
    x = "distillation epochs",
    y = "AUROC"
  ) +
  panel_theme +
  theme(legend.position = "top")

p3f <- ggplot(epoch, aes(epochs, false_positive_rate)) +
  geom_area(fill = pc("baseline_soft"), alpha = 0.65) +
  geom_line(colour = pc("baseline_dark"), linewidth = 0.78) +
  geom_point(colour = pc("baseline_dark"), size = 2.2) +
  geom_text(aes(label = sprintf("%.3f", false_positive_rate)), vjust = -0.85, size = 2.0) +
  scale_x_continuous(breaks = epoch$epochs) +
  scale_y_continuous(labels = percent_format(accuracy = 0.1), limits = c(0, 0.014)) +
  labs(
    title = "False-positive strip contracts",
    subtitle = "Same checkpoints as panel e",
    x = "distillation epochs",
    y = "FPR0"
  ) +
  panel_theme

write_csv(mtcr_flow, file.path(derived_dir, "figure3_tifs_attr_flow.csv"))
write_csv(calib_long, file.path(derived_dir, "figure3_tifs_calibration_profile.csv"))
write_csv(error_df, file.path(derived_dir, "figure3_tifs_residual_error.csv"))
write_csv(shared_long, file.path(derived_dir, "figure3_tifs_shared_ancestor_lollipop.csv"))
write_csv(epoch_long, file.path(derived_dir, "figure3_tifs_epoch_profile.csv"))

fig3 <- (p3a | p3b) /
  (p3c | p3d) /
  (p3e | p3f) +
  plot_layout(heights = c(1.05, 1, 1), guides = "keep") +
  plot_annotation(tag_levels = "a") &
  theme(plot.tag = element_text(face = "bold", size = 10, colour = pc("ink")))

trace_long <- trace_budget %>%
  pivot_longer(cols = c(qwen_auroc, llama_auroc), names_to = "model", values_to = "auroc") %>%
  mutate(
    lineage = recode(model, qwen_auroc = "Qwen lineage", llama_auroc = "Llama lineage"),
    trace_size = as.numeric(trace_size)
  )

trace_endpoint_labels <- trace_long %>%
  group_by(lineage) %>%
  filter(trace_size == max(trace_size)) %>%
  ungroup() %>%
  mutate(
    label_x = 760,
    label_y = if_else(lineage == "Qwen lineage", auroc + 0.020, auroc - 0.020)
  )

p4a <- ggplot(trace_long, aes(trace_size, auroc, colour = lineage)) +
  geom_hline(yintercept = c(0.95, 0.99), colour = "#D9E0EA", linetype = "dashed", linewidth = 0.34) +
  geom_line(linewidth = 0.88) +
  geom_point(size = 2.3) +
  geom_segment(
    data = trace_endpoint_labels,
    aes(x = trace_size, xend = label_x - 15, y = auroc, yend = label_y),
    inherit.aes = FALSE,
    colour = "#AAB5C4",
    linewidth = 0.28
  ) +
  geom_label(
    data = trace_endpoint_labels,
    aes(x = label_x, y = label_y, label = lineage, colour = lineage),
    inherit.aes = FALSE,
    linewidth = 0,
    fill = "white",
    hjust = 0,
    size = 2.15,
    show.legend = FALSE
  ) +
  scale_x_log10(breaks = trace_budget$trace_size, labels = trace_budget$trace_size) +
  scale_y_continuous(limits = c(0.68, 1.02), breaks = c(0.70, 0.85, 1.00)) +
  scale_colour_manual(values = lineage_cols) +
  coord_cartesian(xlim = c(10, 980), clip = "off") +
  labs(
    title = "Trace budget saturates the detector",
    subtitle = "Operating curve by evaluated suspect traces",
    x = "evaluated traces",
    y = "AUROC"
  ) +
  panel_theme +
  theme(legend.position = "none")

step_long <- step_depth %>%
  pivot_longer(cols = c(qwen_auroc, llama_auroc), names_to = "model", values_to = "auroc") %>%
  mutate(
    lineage = recode(model, qwen_auroc = "Qwen lineage", llama_auroc = "Llama lineage"),
    min_steps = as.numeric(min_steps)
  )

p4b <- ggplot(step_long, aes(min_steps, auroc, colour = lineage)) +
  geom_line(linewidth = 0.82) +
  geom_point(size = 2.2) +
  geom_text(
    data = step_long %>% group_by(lineage) %>% filter(min_steps == max(min_steps)) %>% ungroup(),
    aes(y = auroc + if_else(lineage == "Qwen lineage", 0.004, -0.004), label = sprintf("%.3f", auroc)),
    hjust = -0.18,
    size = 2.0,
    show.legend = FALSE
  ) +
  scale_colour_manual(values = lineage_cols) +
  scale_x_continuous(breaks = step_depth$min_steps) +
  scale_y_continuous(limits = c(0.90, 1.01), breaks = c(0.92, 0.96, 1.00)) +
  coord_cartesian(xlim = c(2, 8.8), clip = "off") +
  labs(
    title = "Longer reasoning chains carry stronger signal",
    x = "minimum reasoning steps",
    y = "AUROC"
  ) +
  panel_theme +
  theme(legend.position = "none")

cross_long <- cross_dataset %>%
  pivot_longer(cols = c(qwen_auroc, llama_auroc), names_to = "model", values_to = "auroc") %>%
  mutate(
    lineage = recode(model, qwen_auroc = "Qwen lineage", llama_auroc = "Llama lineage"),
    dataset = factor(dataset, levels = rev(cross_dataset$dataset))
  )

p4c <- ggplot(cross_long, aes(auroc, dataset, colour = lineage)) +
  geom_line(aes(group = dataset), colour = "#DCE3EC", linewidth = 0.65) +
  geom_point(size = 2.35) +
  geom_text(
    data = cross_long %>%
      filter(dataset == "ARC-Challenge") %>%
      group_by(dataset) %>%
      filter(auroc == min(auroc)) %>%
      ungroup(),
    aes(label = sprintf("%.3f", auroc)),
    hjust = 1.18,
    size = 2.0,
    show.legend = FALSE
  ) +
  scale_colour_manual(values = lineage_cols) +
  scale_x_continuous(limits = c(0.895, 1.005), breaks = c(0.90, 0.95, 1.00)) +
  labs(
    title = "Cross-dataset floor exposes the weak domain",
    subtitle = "ARC-Challenge is the lowest point estimate",
    x = "AUROC",
    y = NULL
  ) +
  panel_theme +
  theme(legend.position = "top")

hyper_long <- hyper %>%
  pivot_longer(cols = c(qwen_auroc, llama_auroc), names_to = "model", values_to = "auroc") %>%
  mutate(
    lineage = recode(model, qwen_auroc = "Qwen lineage", llama_auroc = "Llama lineage"),
    parameter_type = recode(parameter_type, temperature = "teacher temperature", lr = "SFT learning rate"),
    parameter_numeric = suppressWarnings(as.numeric(parameter_value)),
    parameter_order = as.integer(factor(parameter_value, levels = unique(parameter_value)))
  )

p4d <- ggplot(hyper_long, aes(parameter_order, auroc, colour = lineage)) +
  geom_line(linewidth = 0.78) +
  geom_point(size = 2.0) +
  facet_wrap(~parameter_type, scales = "free_x", nrow = 1) +
  scale_x_continuous(
    breaks = sort(unique(hyper_long$parameter_order)),
    labels = function(x) {
      levels(factor(hyper$parameter_value, levels = unique(hyper$parameter_value)))[x]
    }
  ) +
  scale_y_continuous(limits = c(0.978, 1.001), breaks = c(0.98, 0.99, 1.00)) +
  scale_colour_manual(values = lineage_cols) +
  labs(
    title = "Hyperparameter sweep stays high",
    subtitle = "Point estimates; not adversarial laundering",
    x = NULL,
    y = "AUROC"
  ) +
  panel_theme +
  theme(legend.position = "none", axis.text.x = element_text(angle = 25, hjust = 1))

query_threshold_df <- trace_long %>%
  group_by(lineage) %>%
  summarise(
    traces_for_95 = min(trace_size[auroc >= 0.95]),
    traces_for_99 = min(trace_size[auroc >= 0.99]),
    .groups = "drop"
  ) %>%
  pivot_longer(cols = starts_with("traces_for"), names_to = "threshold", values_to = "trace_size") %>%
  mutate(
    threshold = recode(threshold, traces_for_95 = "AUROC >= 0.95", traces_for_99 = "AUROC >= 0.99"),
    threshold = factor(threshold, levels = c("AUROC >= 0.99", "AUROC >= 0.95")),
    lineage = factor(lineage, levels = c("Llama lineage", "Qwen lineage"))
  )

query_threshold_labels <- query_threshold_df %>%
  group_by(threshold, trace_size) %>%
  summarise(
    label = if_else(n() > 1, paste0(first(trace_size), " both"), as.character(first(trace_size))),
    .groups = "drop"
  )

p4e <- ggplot(query_threshold_df, aes(trace_size, threshold, colour = lineage)) +
  geom_segment(aes(x = 50, xend = trace_size, yend = threshold), colour = "#DCE3EC", linewidth = 0.5) +
  geom_point(size = 2.45) +
  geom_label(
    data = query_threshold_labels,
    aes(trace_size, threshold, label = label),
    inherit.aes = FALSE,
    linewidth = 0,
    fill = "white",
    nudge_x = 0.08,
    size = 2.05,
    show.legend = FALSE
  ) +
  scale_x_log10(breaks = c(50, 100, 200, 500), labels = c(50, 100, 200, 500)) +
  scale_colour_manual(values = lineage_cols) +
  coord_cartesian(xlim = c(50, 720), clip = "off") +
  labs(
    title = "Minimum query budget",
    subtitle = "Thresholds are read from the trace-budget sweep",
    x = "evaluated traces",
    y = NULL
  ) +
  panel_theme +
  theme(legend.position = "top")

floor_df <- bind_rows(
  cross_long %>% group_by(lineage) %>% summarise(setting = "cross-dataset", floor_auroc = min(auroc), .groups = "drop"),
  hyper_long %>% group_by(lineage) %>% summarise(setting = "hyperparameter", floor_auroc = min(auroc), .groups = "drop"),
  step_long %>% group_by(lineage) %>% summarise(setting = "reasoning-depth", floor_auroc = min(auroc), .groups = "drop")
) %>%
  mutate(setting = factor(setting, levels = rev(c("cross-dataset", "hyperparameter", "reasoning-depth"))))

p4f <- ggplot(floor_df, aes(floor_auroc, setting, colour = lineage)) +
  geom_segment(aes(x = 0.89, xend = floor_auroc, yend = setting), colour = "#DCE3EC", linewidth = 0.5) +
  geom_point(size = 2.5) +
  geom_label(
    data = floor_df %>%
      group_by(setting) %>%
      filter(floor_auroc == min(floor_auroc)) %>%
      ungroup(),
    aes(label = paste0("floor ", sprintf("%.3f", floor_auroc))),
    hjust = 1.04,
    linewidth = 0,
    fill = "white",
    size = 2.0,
    show.legend = FALSE
  ) +
  scale_colour_manual(values = lineage_cols) +
  scale_x_continuous(limits = c(0.89, 1.01), breaks = c(0.90, 0.95, 1.00)) +
  labs(
    title = "Worst measured operating floors",
    subtitle = "Sensitivity evidence, not adaptive robustness",
    x = "minimum AUROC",
    y = NULL
  ) +
  panel_theme +
  theme(legend.position = "none")

write_csv(trace_long, file.path(derived_dir, "figure4_tifs_trace_budget_profile.csv"))
write_csv(step_long, file.path(derived_dir, "figure4_tifs_reasoning_depth_profile.csv"))
write_csv(cross_long, file.path(derived_dir, "figure4_tifs_cross_dataset_forest.csv"))
write_csv(hyper_long, file.path(derived_dir, "figure4_tifs_hyperparameter_profile.csv"))
write_csv(query_threshold_df, file.path(derived_dir, "figure4_tifs_query_thresholds.csv"))
write_csv(query_threshold_labels, file.path(derived_dir, "figure4_tifs_query_threshold_labels.csv"))
write_csv(floor_df, file.path(derived_dir, "figure4_tifs_operating_floors.csv"))

fig4 <- (p4a | p4e) /
  (p4b | p4c) /
  (p4d | p4f) +
  plot_layout(heights = c(1.02, 1, 1), guides = "keep") +
  plot_annotation(tag_levels = "a") &
  theme(plot.tag = element_text(face = "bold", size = 10, colour = pc("ink")))

base_summary <- read_required_csv(file.path(summary_dir, "base_mismatch_calibration_summary.csv")) %>%
  mutate(
    reference = recode(condition, correct_base_reference = "matched reference", no_runnable_base_fallback = "human fallback", .default = condition),
    teacher = recode(
      candidate_teacher,
      "qwen2.5-14b" = "Qwen2.5-14B",
      "r1-distill-qwen-32b" = "R1-Qwen-32B",
      "r1-distill-llama-8b" = "R1-Llama-8B",
      .default = candidate_teacher
    )
  )

base_long <- base_summary %>%
  select(teacher, reference, auroc, fpr_zero) %>%
  pivot_longer(cols = c(auroc, fpr_zero), names_to = "metric", values_to = "value") %>%
  mutate(
    metric = recode(metric, auroc = "AUROC", fpr_zero = "FPR0"),
    teacher = factor(teacher, levels = c("Qwen2.5-14B", "R1-Qwen-32B", "R1-Llama-8B")),
    reference = factor(reference, levels = c("matched reference", "human fallback"))
  )

p5a <- ggplot(base_long %>% filter(metric == "AUROC"), aes(value, teacher, colour = reference)) +
  geom_line(aes(group = teacher), colour = "#CAD3DF", linewidth = 0.65) +
  geom_point(size = 2.45) +
  geom_text(aes(label = sprintf("%.3f", value)), hjust = -0.14, size = 2.05, show.legend = FALSE) +
  scale_colour_manual(values = c("matched reference" = pc("cml"), "human fallback" = pc("risk"))) +
  scale_x_continuous(limits = c(0.43, 1.04), breaks = c(0.5, 0.75, 1.0)) +
  labs(
    title = "Matched reference is the operating gate",
    subtitle = "AUROC collapses under the fallback reference",
    x = "trace-level AUROC",
    y = NULL
  ) +
  panel_theme +
  theme(legend.position = "top")

p5b <- ggplot(base_long %>% filter(metric == "FPR0"), aes(value, teacher, colour = reference)) +
  geom_line(aes(group = teacher), colour = "#CAD3DF", linewidth = 0.65) +
  geom_point(size = 2.45) +
  geom_text(aes(label = sprintf("%.3f", value)), hjust = ifelse(base_long %>% filter(metric == "FPR0") %>% pull(value) > 0.5, 1.15, -0.15), size = 2.05, show.legend = FALSE) +
  scale_colour_manual(values = c("matched reference" = pc("cml"), "human fallback" = pc("risk"))) +
  scale_x_continuous(limits = c(0, 1.04), breaks = c(0, 0.5, 1.0)) +
  labs(
    title = "Fallback reference creates false alarms",
    x = "FPR at zero threshold",
    y = NULL
  ) +
  panel_theme +
  theme(legend.position = "none")

open_summary <- read_required_csv(file.path(summary_dir, "out_of_set_abstention_summary.csv")) %>%
  mutate(
    student_group = if_else(grepl("^ctrlA|^ctrlC", student_id), "controls", "distilled students"),
    condition_label = recode(
      condition,
      source_teacher_present_closed_set = "source present",
      source_teacher_absent = "source absent",
      sibling_teacher_absent = "sibling absent",
      unrelated_capable_teacher_present = "unrelated present",
      .default = condition
    )
  ) %>%
  group_by(condition_label, student_group) %>%
  summarise(
    abstention = mean(abstention_rate, na.rm = TRUE),
    false_attr = mean(false_attribution_rate, na.rm = TRUE),
    abstention_min = min(abstention_rate, na.rm = TRUE),
    abstention_max = max(abstention_rate, na.rm = TRUE),
    false_attr_min = min(false_attribution_rate, na.rm = TRUE),
    false_attr_max = max(false_attribution_rate, na.rm = TRUE),
    .groups = "drop"
  ) %>%
  mutate(
    condition_label = factor(condition_label, levels = rev(c("source present", "source absent", "sibling absent", "unrelated present"))),
    student_group = factor(student_group, levels = c("distilled students", "controls"))
  )

open_long <- open_summary %>%
  select(condition_label, student_group, abstention, false_attr, abstention_min, abstention_max, false_attr_min, false_attr_max) %>%
  pivot_longer(cols = c(abstention, false_attr), names_to = "metric", values_to = "mean") %>%
  mutate(
    ymin = if_else(metric == "abstention", abstention_min, false_attr_min),
    ymax = if_else(metric == "abstention", abstention_max, false_attr_max),
    metric = recode(metric, abstention = "abstention", false_attr = "false attribution")
  )

p5c <- ggplot(open_long, aes(mean, condition_label, colour = student_group)) +
  geom_linerange(aes(xmin = ymin, xmax = ymax), position = position_dodge(width = 0.42), linewidth = 0.45, alpha = 0.72) +
  geom_point(position = position_dodge(width = 0.42), size = 1.95) +
  facet_wrap(~metric, nrow = 1) +
  scale_colour_manual(values = c("distilled students" = pc("qwen"), "controls" = pc("neutral"))) +
  scale_x_continuous(labels = percent_format(accuracy = 1), limits = c(0, 1.02)) +
  labs(
    title = "Absent-candidate triage",
    subtitle = "Horizontal layout avoids compressed condition labels",
    x = "rate",
    y = NULL
  ) +
  panel_theme +
  theme(legend.position = "top", panel.spacing.x = unit(0.10, "in"))

cross_summary <- read_required_csv(file.path(summary_dir, "cross_base_student_matrix.csv")) %>%
  mutate(
    transfer_label = recode(transfer_type, "within-family" = "within family", "cross-family" = "cross family"),
    method = factor(student_training, levels = c("CML", "CML+MTCR")),
    transfer_label = factor(transfer_label, levels = c("cross family", "within family"))
  ) %>%
  group_by(transfer_label, method) %>%
  summarise(
    auroc_mean = mean(auroc, na.rm = TRUE),
    auroc_min = min(auroc, na.rm = TRUE),
    auroc_max = max(auroc, na.rm = TRUE),
    .groups = "drop"
  )

p5d <- ggplot(cross_summary, aes(auroc_mean, transfer_label, colour = method)) +
  geom_linerange(aes(xmin = auroc_min, xmax = auroc_max), position = position_dodge(width = 0.42), linewidth = 0.48, alpha = 0.72) +
  geom_point(position = position_dodge(width = 0.42), size = 2.35) +
  geom_label(
    data = cross_summary %>% filter(transfer_label == "cross family"),
    aes(label = paste0(method, " ", sprintf("%.3f", auroc_mean))),
    position = position_dodge(width = 0.42),
    linewidth = 0,
    fill = "white",
    size = 2.0,
    show.legend = FALSE
  ) +
  scale_colour_manual(values = c("CML" = pc("qwen"), "CML+MTCR" = pc("cml"))) +
  scale_x_continuous(limits = c(0.90, 1.01), breaks = c(0.90, 0.95, 1.00)) +
  labs(
    title = "Cross-family stress remains lower",
    subtitle = "Ranges span staged family-pair conditions",
    x = "AUROC",
    y = NULL
  ) +
  panel_theme +
  theme(legend.position = "top")

write_csv(base_long, file.path(derived_dir, "forensic_envelope_tifs_reference_gate.csv"))
write_csv(open_long, file.path(derived_dir, "forensic_envelope_tifs_absent_candidate.csv"))
write_csv(cross_summary, file.path(derived_dir, "forensic_envelope_tifs_cross_family.csv"))

fig5 <- (p5a | p5c) /
  (p5b | p5d) +
  plot_layout(widths = c(1.0, 1.26), heights = c(1, 0.94), guides = "keep") +
  plot_annotation(tag_levels = "a") &
  theme(plot.tag = element_text(face = "bold", size = 10, colour = pc("ink")))

save_pub(fig3, "fig_mtcr_attribution_epoch", width = 7.2, height = 6.35)
save_pub(fig4, "fig_robustness_checks", width = 7.2, height = 6.55)
save_pub(fig5, "fig_forensic_envelope", width = 7.2, height = 5.55)

message("Wrote TIFS advanced overrides for Fig. 3, Fig. 4, and Fig. 5 in: ", root_dir)
