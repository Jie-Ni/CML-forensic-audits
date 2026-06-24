#!/usr/bin/env Rscript

suppressPackageStartupMessages({
  library(dplyr)
  library(ggplot2)
  library(jsonlite)
  library(patchwork)
  library(readr)
  library(scales)
  library(stringr)
  library(tidyr)
  library(grid)
})

`%||%` <- function(x, y) {
  if (is.null(x) || length(x) == 0 || is.na(x)) y else x
}

script_file <- sub("^--file=", "", grep("^--file=", commandArgs(FALSE), value = TRUE)[1] %||% "")
root_dir <- if (nzchar(script_file)) dirname(normalizePath(script_file)) else getwd()
if (!dir.exists(file.path(root_dir, "source"))) {
  stop("Cannot find figures/source next to plot_nature_results.R: ", root_dir, call. = FALSE)
}
source_dir <- file.path(root_dir, "source")
derived_dir <- file.path(root_dir, "source_derived")
dir.create(derived_dir, showWarnings = FALSE, recursive = TRUE)
unlink(list.files(derived_dir, pattern = "^figure[0-9].*\\.csv$", full.names = TRUE))

palette <- c(
  cml = "#0E9F78",
  cml_dark = "#047857",
  cml_soft = "#CDEFE4",
  baseline = "#D95F02",
  baseline_dark = "#A94400",
  baseline_soft = "#F6D7BF",
  qwen = "#2563A8",
  qwen_soft = "#D8E6F7",
  llama = "#0E9F78",
  llama_soft = "#D7EFE6",
  neutral = "#6B7280",
  slate = "#223047",
  light = "#E7ECF3",
  pale = "#F7F9FC",
  ink = "#111827",
  gold = "#C89211",
  purple = "#7C6BB5"
)

pc <- function(name) unname(palette[[name]])

theme_nature <- function(base_size = 6.8) {
  theme_classic(base_size = base_size, base_family = "Arial") +
    theme(
      plot.background = element_rect(fill = "white", colour = NA),
      panel.background = element_rect(fill = "white", colour = NA),
      panel.border = element_blank(),
      axis.line = element_line(colour = pc("slate"), linewidth = 0.30),
      axis.ticks = element_line(colour = pc("slate"), linewidth = 0.25),
      axis.text = element_text(colour = pc("ink"), size = rel(0.88)),
      axis.title = element_text(colour = pc("ink"), size = rel(0.95)),
      plot.title = element_text(face = "bold", size = rel(1.05), colour = pc("ink"), hjust = 0),
      plot.subtitle = element_text(size = rel(0.82), colour = "#536172", hjust = 0),
      strip.background = element_rect(fill = pc("pale"), colour = "#D8DFEA", linewidth = 0.25),
      strip.text = element_text(face = "bold", colour = pc("ink"), size = rel(0.84)),
      legend.title = element_blank(),
      legend.text = element_text(size = rel(0.80), colour = pc("ink")),
      legend.key.height = unit(0.12, "in"),
      legend.key.width = unit(0.23, "in"),
      legend.background = element_blank(),
      legend.box.background = element_blank(),
      panel.grid.major.y = element_line(colour = "#EEF2F7", linewidth = 0.20),
      panel.grid.major.x = element_blank(),
      panel.grid.minor = element_blank(),
      plot.margin = margin(4, 5, 4, 5)
    )
}

panel_theme <- theme_nature() +
  theme(
    plot.tag = element_text(face = "bold", size = 9.5, colour = pc("ink")),
    plot.tag.position = c(0.01, 0.98)
  )

tile_text_colour <- function(values, midpoint = 0.82) {
  if_else(values >= midpoint, "white", pc("ink"))
}

lighten_hex <- function(hex, alpha = "33") {
  paste0(hex, alpha)
}

method_cols <- c("base-relative" = pc("baseline"), "CML" = pc("cml"), "CML+MTCR" = pc("cml_dark"))
lineage_cols <- c("Qwen lineage" = pc("qwen"), "Llama lineage" = pc("llama"))

save_pub <- function(plot, name, width = 7.2, height = 5.0) {
  pdf_path <- file.path(root_dir, paste0(name, ".pdf"))
  svg_path <- file.path(root_dir, paste0(name, ".svg"))
  png_path <- file.path(root_dir, paste0(name, ".png"))
  tiff_path <- file.path(root_dir, paste0(name, ".tiff"))

  ggsave(pdf_path, plot, width = width, height = height, units = "in", device = cairo_pdf, limitsize = FALSE)
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

short_teacher <- function(x) {
  recode(
    x,
    "r1-distill-qwen-32b" = "R1-Qwen-32B",
    "qwen2.5-14b" = "Qwen2.5-14B",
    "r1-distill-llama-8b" = "R1-Llama-8B",
    "qwen2.5-7b" = "Base Qwen-7B",
    .default = x
  )
}

ptype <- function(x) sub("_s[0-9]+$", "", x)

display_type <- function(x) {
  recode(
    x,
    "suspect" = "R1-Qwen student",
    "ctrlInst_qwen" = "Qwen14B student",
    "ctrlLlama_r1" = "R1-Llama student",
    "ctrlC_ref" = "Human-ref control",
    "ctrlA_base" = "Base reference",
    .default = x
  )
}

read_jsonl_dir <- function(dir_path) {
  files <- list.files(dir_path, pattern = "\\.jsonl$", full.names = TRUE)
  bind_rows(lapply(files, function(path) {
    con <- file(path, open = "r", encoding = "UTF-8")
    on.exit(close(con), add = TRUE)
    stream_in(con, verbose = FALSE) %>% mutate(source_file = basename(path))
  }))
}

read_json_lenient <- function(path) {
  txt <- paste(readLines(path, warn = FALSE, encoding = "UTF-8"), collapse = "\n")
  txt <- gsub("\\bNaN\\b", "null", txt)
  fromJSON(txt, simplifyVector = FALSE)
}

roc_curve <- function(pos, neg) {
  thresholds <- sort(unique(c(pos, neg)), decreasing = TRUE)
  tibble(
    threshold = c(Inf, thresholds, -Inf),
    fpr = c(0, vapply(thresholds, function(t) mean(neg >= t), numeric(1)), 1),
    tpr = c(0, vapply(thresholds, function(t) mean(pos >= t), numeric(1)), 1)
  )
}

load_core_data <- function(task = "gsm8k") {
  result <- read_json_lenient(file.path(source_dir, paste0("results_full_", task, ".json")))
  scored <- read_jsonl_dir(file.path(source_dir, paste0("scored_", task)))
  teachers <- unlist(result$teachers)
  base <- result$reference

  keep <- c(teachers, base)
  scored <- scored %>%
    filter(candidate_teacher %in% keep) %>%
    mutate(type = ptype(student))

  reference <- scored %>%
    filter(type == "ctrlA_base", candidate_teacher %in% teachers) %>%
    group_by(candidate_teacher, id) %>%
    summarise(ref_lp = mean(mean_lp), .groups = "drop")

  matched <- scored %>%
    filter(candidate_teacher %in% teachers) %>%
    left_join(reference, by = c("candidate_teacher", "id")) %>%
    mutate(r_c = mean_lp - ref_lp)

  base_lp <- scored %>%
    filter(candidate_teacher == base) %>%
    select(student, id, base_lp = mean_lp)

  surplus <- scored %>%
    filter(candidate_teacher %in% teachers) %>%
    left_join(base_lp, by = c("student", "id")) %>%
    mutate(s_c = mean_lp - base_lp)

  list(result = result, scored = scored, matched = matched, surplus = surplus, teachers = teachers)
}

max_stat <- function(df, value_col) {
  value_col <- enquo(value_col)
  df %>%
    group_by(student, type, id) %>%
    summarise(value = max(!!value_col, na.rm = TRUE), .groups = "drop")
}

strata_def <- tibble(
  stratum = c("all distilled", "cross-style", "same-family"),
  key = c("all_distilled", "crossstyle", "samefamily"),
  positive_types = list(
    c("suspect", "ctrlInst_qwen", "ctrlLlama_r1"),
    c("suspect", "ctrlLlama_r1"),
    c("ctrlInst_qwen")
  )
)

core <- load_core_data("gsm8k")
math_result <- read_json_lenient(file.path(source_dir, "results_full_math.json"))

matched_max <- max_stat(core$matched, r_c)
baseline_max <- max_stat(core$surplus, s_c)

roc_df <- bind_rows(lapply(seq_len(nrow(strata_def)), function(i) {
  st <- strata_def[i, ]
  bind_rows(
    roc_curve(
      matched_max$value[matched_max$type %in% st$positive_types[[1]]],
      matched_max$value[matched_max$type == "ctrlC_ref"]
    ) %>% mutate(stratum = st$stratum, method = "CML"),
    roc_curve(
      baseline_max$value[baseline_max$type %in% st$positive_types[[1]]],
      baseline_max$value[baseline_max$type == "ctrlC_ref"]
    ) %>% mutate(stratum = st$stratum, method = "base-relative")
  )
}))

auroc_df <- bind_rows(lapply(seq_len(nrow(strata_def)), function(i) {
  key <- strata_def$key[[i]]
  tibble(
    stratum = strata_def$stratum[[i]],
    method = c("base-relative", "CML"),
    auroc = c(
      core$result$matched_method$baseline_strata_vs_ctrlC[[key]]$auroc,
      core$result$matched_method$detection_strata[[key]]$auroc
    ),
    fpr0 = c(
      core$result$matched_method$baseline_strata_vs_ctrlC[[key]]$empirical_fpr_zero_threshold,
      core$result$matched_method$detection_strata[[key]]$empirical_fpr_zero_threshold
    )
  )
}))

core_metric_df <- bind_rows(lapply(seq_len(nrow(strata_def)), function(i) {
  key <- strata_def$key[[i]]
  tibble(
    stratum = strata_def$stratum[[i]],
    method = c("base-relative", "CML"),
    auroc = c(
      core$result$matched_method$baseline_strata_vs_ctrlC[[key]]$auroc,
      core$result$matched_method$detection_strata[[key]]$auroc
    ),
    tpr1 = c(
      core$result$matched_method$baseline_strata_vs_ctrlC[[key]]$tpr_at_1pct_fpr,
      core$result$matched_method$detection_strata[[key]]$tpr_at_1pct_fpr
    ),
    fpr0 = c(
      core$result$matched_method$baseline_strata_vs_ctrlC[[key]]$empirical_fpr_zero_threshold,
      core$result$matched_method$detection_strata[[key]]$empirical_fpr_zero_threshold
    )
  )
})) %>%
  mutate(
    stratum = factor(stratum, levels = rev(c("all distilled", "cross-style", "same-family"))),
    method = factor(method, levels = c("base-relative", "CML"))
  )

math_metric_df <- bind_rows(lapply(seq_len(nrow(strata_def)), function(i) {
  key <- strata_def$key[[i]]
  tibble(
    stratum = strata_def$stratum[[i]],
    method = c("base-relative", "CML"),
    auroc = c(
      math_result$matched_method$baseline_strata_vs_ctrlC[[key]]$auroc,
      math_result$matched_method$detection_strata[[key]]$auroc
    ),
    tpr1 = c(
      math_result$matched_method$baseline_strata_vs_ctrlC[[key]]$tpr_at_1pct_fpr,
      math_result$matched_method$detection_strata[[key]]$tpr_at_1pct_fpr
    ),
    fpr0 = c(
      math_result$matched_method$baseline_strata_vs_ctrlC[[key]]$empirical_fpr_zero_threshold,
      math_result$matched_method$detection_strata[[key]]$empirical_fpr_zero_threshold
    )
  )
})) %>%
  mutate(
    stratum = factor(stratum, levels = levels(core_metric_df$stratum)),
    method = factor(method, levels = levels(core_metric_df$method)),
    task = "MATH"
  )

task_metric_df <- bind_rows(
  core_metric_df %>% mutate(task = "GSM8K"),
  math_metric_df
) %>%
  mutate(task = factor(task, levels = c("GSM8K", "MATH")))

student_df <- matched_max %>%
  filter(type %in% c("suspect", "ctrlInst_qwen", "ctrlLlama_r1", "ctrlC_ref")) %>%
  group_by(student, type) %>%
  summarise(mean_max_r = mean(value), .groups = "drop") %>%
  mutate(
    group = if_else(type == "ctrlC_ref", "non-distilled control", "distilled"),
    label = display_type(type),
    label = factor(label, levels = rev(c("R1-Qwen student", "Qwen14B student", "R1-Llama student", "Human-ref control"))),
    seed_offset = case_when(
      str_detect(student, "_s1$") ~ -0.12,
      str_detect(student, "_s2$") ~ 0.12,
      TRUE ~ 0
    ),
    y_pos = as.numeric(label) + seed_offset
  )

trace_distribution_df <- matched_max %>%
  filter(type %in% c("suspect", "ctrlInst_qwen", "ctrlLlama_r1", "ctrlC_ref")) %>%
  mutate(
    group = if_else(type == "ctrlC_ref", "non-distilled control", "distilled"),
    label = display_type(type),
    label = factor(label, levels = rev(c("R1-Qwen student", "Qwen14B student", "R1-Llama student", "Human-ref control")))
  )

set.seed(20260623)
trace_distribution_points <- trace_distribution_df %>%
  group_by(label) %>%
  slice_sample(n = 180) %>%
  ungroup()

trace_distribution_summary <- trace_distribution_df %>%
  group_by(label, group) %>%
  summarise(
    n = n(),
    mean = mean(value),
    median = median(value),
    q25 = quantile(value, 0.25),
    q75 = quantile(value, 0.75),
    min = min(value),
    max = max(value),
    .groups = "drop"
  )

heatmap_df <- core$matched %>%
  filter(type %in% c("suspect", "ctrlInst_qwen", "ctrlLlama_r1", "ctrlC_ref")) %>%
  group_by(type, candidate_teacher) %>%
  summarise(mean_r = mean(r_c, na.rm = TRUE), .groups = "drop") %>%
  mutate(
    student_type = factor(display_type(type), levels = rev(c(
      "R1-Qwen student", "Qwen14B student", "R1-Llama student", "Human-ref control"
    ))),
    teacher = factor(short_teacher(candidate_teacher), levels = short_teacher(core$teachers))
  )

write_csv(roc_df, file.path(derived_dir, "figure2_roc_points.csv"))
write_csv(auroc_df, file.path(derived_dir, "figure2_auroc_summary.csv"))
write_csv(core_metric_df, file.path(derived_dir, "figure2_core_metrics.csv"))
write_csv(task_metric_df, file.path(derived_dir, "figure2_task_replication_metrics.csv"))
write_csv(student_df, file.path(derived_dir, "figure2_student_level_scores.csv"))
write_csv(trace_distribution_df, file.path(derived_dir, "figure2_trace_level_distribution.csv"))
write_csv(trace_distribution_summary, file.path(derived_dir, "figure2_trace_distribution_summary.csv"))
write_csv(heatmap_df, file.path(derived_dir, "figure2_matched_heatmap.csv"))

mtcr_attr <- read_csv(file.path(source_dir, "w08_mtcr_attribution.csv"), show_col_types = FALSE)
shared <- read_csv(file.path(source_dir, "w08_shared_ancestor_detection.csv"), show_col_types = FALSE)
epoch <- read_csv(file.path(source_dir, "w08_epoch_sensitivity.csv"), show_col_types = FALSE)
calib <- read_csv(file.path(source_dir, "w08_calibration_tasks_ablation.csv"), show_col_types = FALSE)
trace_budget <- read_csv(file.path(source_dir, "w08_trace_size_sensitivity.csv"), show_col_types = FALSE)
step_depth <- read_csv(file.path(source_dir, "w08_reasoning_step_depth.csv"), show_col_types = FALSE)
cross_dataset <- read_csv(file.path(source_dir, "w08_cross_dataset_generalizability.csv"), show_col_types = FALSE)
hyper <- read_csv(file.path(source_dir, "w08_hyperparameter_robustness.csv"), show_col_types = FALSE)

write_csv(mtcr_attr, file.path(derived_dir, "figure3_mtcr_attribution.csv"))
write_csv(shared, file.path(derived_dir, "figure3_shared_ancestor.csv"))
write_csv(epoch, file.path(derived_dir, "figure3_epoch_sensitivity.csv"))
write_csv(calib, file.path(derived_dir, "figure3_calibration_tasks.csv"))
write_csv(trace_budget, file.path(derived_dir, "figure4_trace_budget.csv"))
write_csv(step_depth, file.path(derived_dir, "figure4_reasoning_depth.csv"))
write_csv(cross_dataset, file.path(derived_dir, "figure4_cross_dataset.csv"))
write_csv(hyper, file.path(derived_dir, "figure4_hyperparameters.csv"))

arrow_spec <- arrow(length = unit(0.08, "inches"), type = "closed")

chain_nodes <- tibble(
  step = 1:6,
  x = seq(0.85, 9.15, length.out = 6),
  y = 0.82,
  fill = c("#EFF6FF", "#EFF6FF", "#F8FAFC", "#EEF2FF", "#ECFDF5", "#F8FAFC"),
  stroke = c(pc("qwen"), pc("qwen"), "#334155", pc("purple"), pc("cml_dark"), "#334155"),
  title = c(
    "Suspect API",
    "Same-base ref.",
    "Candidate scoring",
    "Matched statistic",
    "Null threshold",
    "Forensic report"
  ),
  detail = c(
    "black-box traces only",
    "base outputs on audit pool",
    "authorized teacher likelihoods",
    "r = log p(S) - log p(R)",
    "empirical FPR control",
    "detect / attribute / abstain"
  )
) %>%
  mutate(
    title = str_wrap(title, 14),
    detail = str_wrap(detail, 19)
  )

chain_edges <- tibble(
  x = head(chain_nodes$x, -1) + 0.62,
  xend = tail(chain_nodes$x, -1) - 0.62,
  y = 0.82,
  yend = 0.82
)

p1a <- ggplot() +
  geom_segment(
    data = chain_edges,
    aes(x = x, xend = xend, y = y, yend = yend),
    arrow = arrow_spec, linewidth = 0.38, colour = "#475569",
    lineend = "round"
  ) +
  geom_rect(
    data = chain_nodes,
    aes(xmin = x - 0.64, xmax = x + 0.64, ymin = y - 0.46, ymax = y + 0.46, fill = fill, colour = stroke),
    linewidth = 0.32
  ) +
  geom_text(
    data = chain_nodes,
    aes(x = x, y = y + 0.18, label = title),
    size = 2.18, fontface = "bold", lineheight = 0.86, colour = pc("ink")
  ) +
  geom_text(
    data = chain_nodes,
    aes(x = x, y = y - 0.25, label = detail),
    size = 1.96, lineheight = 0.86, colour = "#475569"
  ) +
  annotate("text", x = 0.10, y = 1.55, label = "forensic evidence chain", hjust = 0, fontface = "bold", size = 2.65, colour = pc("ink")) +
  annotate("text", x = 0.10, y = 1.37, label = "CML is black-box for the suspect but scorer-assisted for candidate teachers.", hjust = 0, size = 2.05, colour = "#536172") +
  scale_fill_identity() +
  scale_colour_identity() +
  coord_cartesian(xlim = c(0, 10), ylim = c(0.26, 1.70), expand = FALSE, clip = "off") +
  theme_void(base_family = "Arial") +
  theme(plot.margin = margin(4, 6, 2, 6))

fig1_density_input <- trace_distribution_df %>%
  mutate(decision_group = if_else(group == "distilled", "distilled suspects", "human-reference null"))

fig1_density <- bind_rows(lapply(split(fig1_density_input, fig1_density_input$decision_group), function(df) {
  dens <- density(df$value, n = 260, adjust = 1.05)
  tibble(decision_group = df$decision_group[[1]], x = dens$x, y = dens$y / max(dens$y))
}))

fig1_threshold <- quantile(fig1_density_input$value[fig1_density_input$decision_group == "human-reference null"], 0.99, na.rm = TRUE)

p1b <- ggplot(fig1_density, aes(x, y, fill = decision_group, colour = decision_group)) +
  geom_area(alpha = 0.34, linewidth = 0.28) +
  geom_vline(xintercept = fig1_threshold, linetype = "dashed", linewidth = 0.36, colour = pc("slate")) +
  annotate("text", x = fig1_threshold + 0.03, y = 0.72, label = "1% null\nthreshold", hjust = 0, size = 2.08, lineheight = 0.86, colour = pc("slate")) +
  annotate("text", x = -0.72, y = 0.98, label = "human-reference null", hjust = 0.5, size = 2.12, colour = pc("baseline_dark")) +
  annotate("text", x = 0.13, y = 0.98, label = "distilled suspects", hjust = 0.5, size = 2.12, colour = pc("cml_dark")) +
  scale_fill_manual(values = c("distilled suspects" = pc("cml"), "human-reference null" = pc("baseline"))) +
  scale_colour_manual(values = c("distilled suspects" = pc("cml_dark"), "human-reference null" = pc("baseline_dark"))) +
  labs(title = "Null-threshold decision", subtitle = "Trace-level max r distribution; threshold set on the null", x = "max matched surplus r", y = "scaled density") +
  theme_nature(base_size = 6.9) +
  theme(
    legend.position = "none",
    axis.title.y = element_blank(),
    plot.margin = margin(3, 5, 3, 5)
  )

claim_ladder <- tibble(
  y = factor(
    c("Decision output", "Decision output", "Attribution", "Audit input", "Audit input"),
    levels = rev(c("Decision output", "Attribution", "Audit input"))
  ),
  x = c(1, 2, 1, 1, 2),
  label = c(
    "distillation flag",
    "same-base recovery",
    "R1 sibling attribution via MTCR",
    "suspect traces",
    "candidate scoring"
  ),
  fill = c(pc("cml_soft"), pc("cml_soft"), "#EEF2FF", "#F8FAFC", "#F8FAFC"),
  stroke = c(pc("cml_dark"), pc("cml_dark"), pc("purple"), "#94A3B8", "#94A3B8")
) %>%
  mutate(label = str_wrap(label, 22))

p1c <- ggplot(claim_ladder, aes(x, y)) +
  geom_tile(aes(fill = fill, colour = stroke), width = 0.92, height = 0.70, linewidth = 0.30) +
  geom_text(aes(label = label), size = 2.12, lineheight = 0.88, colour = pc("ink")) +
  scale_fill_identity() +
  scale_colour_identity() +
  scale_x_continuous(limits = c(0.45, 2.55), breaks = NULL) +
  labs(title = "Decision summary", subtitle = "Inputs and reported outputs", x = NULL, y = NULL) +
  theme_nature(base_size = 6.9) +
  theme(
    axis.text.x = element_blank(),
    axis.ticks = element_blank(),
    axis.line = element_blank(),
    panel.grid = element_blank(),
    plot.margin = margin(3, 5, 3, 5)
  )

headline_rows <- tibble(
  metric = c("False accusation FPR0", "False accusation FPR0", "Same-family AUROC", "Same-family AUROC", "MATH AUROC", "MATH AUROC"),
  method = c("base-relative", "CML", "base-relative", "CML", "base-relative", "CML"),
  value = c(
    core_metric_df %>% filter(stratum == "all distilled", method == "base-relative") %>% pull(fpr0),
    core_metric_df %>% filter(stratum == "all distilled", method == "CML") %>% pull(fpr0),
    core_metric_df %>% filter(stratum == "same-family", method == "base-relative") %>% pull(auroc),
    core_metric_df %>% filter(stratum == "same-family", method == "CML") %>% pull(auroc),
    math_metric_df %>% filter(stratum == "all distilled", method == "base-relative") %>% pull(auroc),
    math_metric_df %>% filter(stratum == "all distilled", method == "CML") %>% pull(auroc)
  )
) %>%
  mutate(
    metric = factor(metric, levels = rev(c("False accusation FPR0", "Same-family AUROC", "MATH AUROC"))),
    method = factor(method, levels = c("base-relative", "CML")),
    label = sprintf("%.3f", value)
  )

headline_segments <- headline_rows %>%
  select(metric, method, value) %>%
  pivot_wider(names_from = method, values_from = value) %>%
  rename(base_relative = `base-relative`, cml = CML)

p1d <- ggplot(headline_rows, aes(value, metric, colour = method)) +
  geom_segment(
    data = headline_segments,
    aes(x = base_relative, xend = cml, y = metric, yend = metric),
    inherit.aes = FALSE, linewidth = 0.72, colour = "#CBD5E1"
  ) +
  geom_point(size = 2.15) +
  geom_text(
    aes(label = label, hjust = if_else(method == "CML", 1.10, -0.10)),
    nudge_y = 0.17, size = 2.08, show.legend = FALSE
  ) +
  scale_colour_manual(values = method_cols) +
  scale_x_continuous(limits = c(0, 1.02), breaks = c(0, 0.5, 1.0), labels = label_number(accuracy = 0.1)) +
  labs(title = "Operating points reviewers will check", subtitle = "Same data as the result panels, reframed as forensic evidence", x = "metric value", y = NULL) +
  theme_nature(base_size = 6.9) +
  theme(
    legend.position = c(0.73, 1.08),
    legend.direction = "horizontal",
    legend.text = element_text(size = 5.7),
    plot.margin = margin(3, 5, 3, 5)
  )

write_csv(chain_nodes, file.path(derived_dir, "figure1_evidence_chain_nodes.csv"))
write_csv(chain_edges, file.path(derived_dir, "figure1_evidence_chain_edges.csv"))
write_csv(fig1_density_input, file.path(derived_dir, "figure1_null_threshold_trace_scores.csv"))
write_csv(tibble(threshold_1pct_fpr = fig1_threshold), file.path(derived_dir, "figure1_null_threshold.csv"))
write_csv(claim_ladder, file.path(derived_dir, "figure1_claim_ladder.csv"))
write_csv(headline_rows, file.path(derived_dir, "figure1_headline_operating_points.csv"))

fig1 <- p1a / (p1b | p1c) / p1d +
  plot_layout(heights = c(0.88, 1.15, 0.88)) +
  plot_annotation(tag_levels = "a") &
  theme(plot.tag = element_text(face = "bold", size = 9.5, colour = "#0F172A"))

core_metric_long <- core_metric_df %>%
  mutate(
    stratum = factor(as.character(stratum), levels = levels(core_metric_df$stratum)),
    method = factor(method, levels = c("base-relative", "CML"))
  ) %>%
  select(stratum, method, AUROC = auroc, `TPR at 1% FPR` = tpr1) %>%
  pivot_longer(cols = c(AUROC, `TPR at 1% FPR`), names_to = "metric", values_to = "value")

metric_span <- core_metric_long %>%
  select(stratum, method, metric, value) %>%
  pivot_wider(names_from = method, values_from = value) %>%
  rename(base_relative = `base-relative`, cml = CML)

metric_gain_matrix <- metric_span %>%
  mutate(
    metric = recode(metric, `TPR at 1% FPR` = "TPR@1% FPR"),
    metric = factor(metric, levels = c("AUROC", "TPR@1% FPR")),
    delta = cml - base_relative,
    label = sprintf("CML %.3f\nΔ %+0.3f", cml, delta),
    text_colour = if_else(delta > 0.38, "white", pc("ink"))
  )

metric_gain_matrix <- metric_gain_matrix %>%
  mutate(label = sprintf("CML %.3f\ndelta %+0.3f", cml, delta))

decision_boundary_df <- matched_max %>%
  rename(cml_max_r = value) %>%
  inner_join(
    baseline_max %>% rename(base_relative_max = value) %>% select(student, type, id, base_relative_max),
    by = c("student", "type", "id")
  ) %>%
  filter(type %in% c("suspect", "ctrlInst_qwen", "ctrlLlama_r1", "ctrlC_ref")) %>%
  mutate(
    group = if_else(type == "ctrlC_ref", "human-reference null", "distilled suspects"),
    group = factor(group, levels = c("human-reference null", "distilled suspects")),
    type_label = display_type(type)
  )

p2a <- ggplot(decision_boundary_df, aes(base_relative_max, cml_max_r, colour = group, fill = group)) +
  annotate("rect", xmin = 0, xmax = Inf, ymin = -Inf, ymax = 0, fill = pc("baseline_soft"), alpha = 0.25) +
  annotate("rect", xmin = -Inf, xmax = Inf, ymin = 0, ymax = Inf, fill = pc("cml_soft"), alpha = 0.18) +
  geom_hline(yintercept = 0, colour = pc("cml_dark"), linetype = "dashed", linewidth = 0.36) +
  geom_vline(xintercept = 0, colour = pc("baseline_dark"), linetype = "dashed", linewidth = 0.36) +
  geom_point(shape = 21, size = 1.05, stroke = 0.18, alpha = 0.42) +
  annotate("label", x = -1.04, y = 0.36, label = "CML-positive\nregion", size = 2.35, lineheight = 0.86, colour = pc("cml_dark"), fill = "white", linewidth = 0, hjust = 0) +
  scale_colour_manual(values = c("human-reference null" = pc("baseline_dark"), "distilled suspects" = pc("cml_dark"))) +
  scale_fill_manual(values = c("human-reference null" = pc("baseline"), "distilled suspects" = pc("cml"))) +
  coord_cartesian(xlim = c(-1.45, 0.86), ylim = c(-1.45, 0.52), clip = "on") +
  labs(title = "Decision boundary", subtitle = "CML separates where the base-relative statistic false-alarms", x = "base-relative max surplus", y = "CML max matched surplus") +
  panel_theme +
  theme(legend.position = "none")

stress_slope <- task_metric_df %>%
  filter(method == "CML") %>%
  mutate(
    label = sprintf("%.3f", auroc),
    stratum = factor(as.character(stratum), levels = c("same-family", "cross-style", "all distilled"))
  )

p2b <- ggplot(stress_slope, aes(task, auroc, group = stratum, colour = stratum)) +
  geom_line(linewidth = 0.62, alpha = 0.82) +
  geom_point(size = 2.05) +
  geom_text(
    data = stress_slope %>%
      filter(task == "MATH") %>%
      mutate(
        label = recode(as.character(stratum), `same-family` = "same-family", `cross-style` = "cross-style", `all distilled` = "all distilled"),
        label_y = auroc + recode(as.character(stratum), `same-family` = 0.0017, `cross-style` = -0.0017, `all distilled` = 0)
      ),
    aes(x = task, y = label_y, label = label),
    hjust = -0.12,
    size = 2.45,
    show.legend = FALSE
  ) +
  scale_colour_manual(values = c("same-family" = pc("qwen"), "cross-style" = pc("llama"), "all distilled" = pc("cml_dark"))) +
  scale_y_continuous(breaks = c(0.99, 0.995, 1.00), labels = label_number(accuracy = 0.001)) +
  coord_cartesian(ylim = c(0.985, 1.01), clip = "on") +
  labs(title = "GSM8K to MATH stress test", subtitle = "CML trace-level AUROC by stratum; MATH is single-seed", x = NULL, y = "AUROC") +
  panel_theme +
  theme(legend.position = "none")

fpr_gauge_df <- core_metric_df %>%
  select(stratum, method, fpr0) %>%
  mutate(
    stratum = factor(as.character(stratum), levels = levels(core_metric_df$stratum)),
    y_base = as.numeric(stratum),
    y_pos = y_base + if_else(method == "base-relative", 0.16, -0.16),
    label = sprintf("%.3f", fpr0),
    label_x = if_else(fpr0 < 0.05, 0.06, pmin(fpr0 - 0.035, 0.80)),
    label_hjust = if_else(fpr0 < 0.05, 0, 1)
  )

fpr_collapse_df <- core_metric_df %>%
  select(stratum, method, fpr0) %>%
  pivot_wider(names_from = method, values_from = fpr0) %>%
  rename(base_relative = `base-relative`, cml = CML) %>%
  mutate(
    drop = base_relative - cml,
    label = paste0("−", sprintf("%.1f", drop * 100), " pp")
  )

fpr_collapse_df <- fpr_collapse_df %>%
  mutate(label = paste0(sprintf("%.1f", drop * 100), " pp drop"))

p2c <- ggplot(fpr_collapse_df) +
  annotate("rect", xmin = 0, xmax = 0.01, ymin = -Inf, ymax = Inf, fill = pc("cml_soft"), alpha = 0.55) +
  geom_segment(
    aes(x = base_relative, xend = cml, y = stratum, yend = stratum),
    arrow = arrow(length = unit(0.08, "in"), type = "closed"),
    colour = "#8997AA",
    linewidth = 1.1,
    lineend = "round"
  ) +
  geom_point(aes(base_relative, stratum), colour = pc("baseline"), size = 2.6) +
  geom_point(aes(cml, stratum), colour = pc("cml_dark"), size = 2.8) +
  annotate("text", x = 0.045, y = 3.36, label = "0.808 -> 0.002", size = 2.55, fontface = "bold", colour = pc("ink"), hjust = 0) +
  scale_x_continuous(limits = c(0, 0.86), breaks = c(0.4, 0.8), labels = c("40%", "80%")) +
  labs(title = "FPR collapse trajectory", subtitle = "All strata move into the 1% operating band", x = "Empirical FPR at zero threshold", y = NULL) +
  panel_theme +
  theme(legend.position = "none")

trace_ridge_df <- bind_rows(lapply(split(trace_distribution_df, list(trace_distribution_df$label, trace_distribution_df$group), drop = TRUE), function(df) {
  dens <- density(df$value, from = -1.55, to = 0.50, n = 260, adjust = 1.05)
  y0 <- as.numeric(df$label[1])
  tibble(
    label = df$label[1],
    group = df$group[1],
    y = y0,
    value = dens$x,
    density = dens$y / max(dens$y),
    y_top = y0 + (dens$y / max(dens$y)) * 0.58
  )
}))

p2d <- ggplot() +
  geom_vline(xintercept = 0, colour = "#A7B2C3", linetype = "dotted", linewidth = 0.32) +
  geom_ribbon(
    data = trace_ridge_df,
    aes(x = value, ymin = y, ymax = y_top, fill = group, colour = group, group = interaction(label, group)),
    linewidth = 0.34,
    alpha = 0.30
  ) +
  geom_segment(
    data = trace_distribution_summary %>% mutate(y = as.numeric(label)),
    aes(x = q25, xend = q75, y = y + 0.045, yend = y + 0.045, colour = group),
    linewidth = 1.20,
    lineend = "round"
  ) +
  geom_point(
    data = trace_distribution_summary %>% mutate(y = as.numeric(label)),
    aes(x = median, y = y + 0.045, colour = group),
    size = 1.45
  ) +
  geom_point(
    data = trace_distribution_points,
    aes(x = value, y = as.numeric(label) - 0.06, colour = group),
    position = position_jitter(width = 0, height = 0.095, seed = 20260623),
    size = 0.34,
    alpha = 0.22,
    stroke = 0,
    show.legend = FALSE
  ) +
  scale_fill_manual(values = c("distilled" = pc("cml"), "non-distilled control" = pc("baseline"))) +
  scale_colour_manual(values = c("distilled" = pc("cml"), "non-distilled control" = pc("baseline"))) +
  scale_y_continuous(
    breaks = seq_along(levels(trace_distribution_df$label)),
    labels = levels(trace_distribution_df$label),
    limits = c(0.72, length(levels(trace_distribution_df$label)) + 0.72)
  ) +
  scale_x_continuous(breaks = c(-1.5, -1.0, -0.5, 0.0, 0.5)) +
  coord_cartesian(xlim = c(-1.55, 0.50), clip = "on") +
  labs(
    title = "Trace-level matched-statistic ridges",
    subtitle = "Density ridges, quartile bars and sampled trace points",
    x = "max r per trace",
    y = NULL
  ) +
  panel_theme +
  theme(
    legend.position = "none",
    plot.title = element_text(face = "bold", size = rel(1.10))
  )

p2e_heat <- heatmap_df %>%
  mutate(
    label = sprintf("%+.2f", mean_r),
    text_colour = if_else(abs(mean_r) > 0.55, "white", pc("ink"))
  )

p2e <- ggplot(p2e_heat, aes(teacher, student_type, fill = mean_r)) +
  geom_tile(colour = "white", linewidth = 0.68) +
  geom_text(aes(label = label, colour = text_colour), size = 2.05, show.legend = FALSE) +
  scale_colour_identity() +
  scale_fill_gradient2(low = pc("baseline"), mid = "#F8FAFC", high = pc("cml_dark"), midpoint = 0) +
  labs(title = "Teacher–student evidence matrix", subtitle = "Mean matched surplus by candidate teacher", x = NULL, y = NULL) +
  panel_theme +
  theme(axis.text.x = element_text(angle = 20, hjust = 1), legend.position = "none")

roc_plot_df <- roc_df %>%
  filter(stratum == "all distilled") %>%
  mutate(method = factor(method, levels = c("base-relative", "CML")))

p2f <- ggplot(roc_plot_df, aes(fpr, tpr, colour = method)) +
  geom_abline(slope = 1, intercept = 0, colour = "#C9D3E2", linetype = "dotted", linewidth = 0.36) +
  geom_line(linewidth = 0.70) +
  annotate("text", x = 0.10, y = 0.98, label = "CML", colour = pc("cml_dark"), size = 2.45, hjust = 0) +
  annotate("text", x = 0.70, y = 0.67, label = "base-relative", colour = pc("baseline_dark"), size = 2.25, hjust = 0) +
  scale_colour_manual(values = method_cols[c("base-relative", "CML")]) +
  scale_x_continuous(limits = c(0, 1), breaks = c(0, 0.5, 1)) +
  scale_y_continuous(limits = c(0, 1), breaks = c(0, 0.5, 1)) +
  labs(title = "ROC shape on GSM8K", x = "False-positive rate", y = "True-positive rate") +
  panel_theme +
  theme(legend.position = "none")

design2 <- "
AABB
CCDD
EEDD
FFDD
"

fig2 <- p2a + p2b + p2c + p2d + p2e + p2f +
  plot_layout(design = design2, heights = c(0.88, 0.88, 0.86, 0.86)) +
  plot_annotation(tag_levels = "a") &
  theme(plot.tag = element_text(face = "bold", size = 9.5, colour = pc("ink")))

# Refined Fig. 1 and Fig. 2 overrides after visual review.
# The manuscript-facing versions below keep the same source data, but improve
# the evidence hierarchy: Fig. 1 is method-only; Fig. 2 uses one hero result
# and compact supporting evidence panels.

protocol_nodes_refined <- tibble(
  x = c(0.90, 2.45, 4.00, 5.65, 7.28, 8.82),
  y = 0.76,
  w = c(0.66, 0.68, 0.70, 0.72, 0.68, 0.68),
  h = 0.40,
  fill = c("#EFF6FF", "#EFF6FF", "#F8FAFC", "#EEF2FF", "#ECFDF5", "#F8FAFC"),
  stroke = c(pc("qwen"), pc("qwen"), pc("slate"), pc("purple"), pc("cml_dark"), pc("slate")),
  title = c("Suspect traces", "Same-base reference", "Candidate teachers", "CML statistic", "Null calibration", "Audit decision"),
  detail = c(
    "black-box outputs",
    "non-distilled base outputs",
    "authorized likelihood scoring",
    "score S and R under same T_c",
    "threshold on negative controls",
    "detect, attribute, or abstain"
  )
) %>%
  mutate(
    title = str_wrap(title, 15),
    detail = str_wrap(detail, 22)
  )

protocol_edges_refined <- protocol_nodes_refined %>%
  arrange(x) %>%
  transmute(x = x + w, xend = lead(x - w), y = y, yend = lead(y)) %>%
  filter(!is.na(xend))

p1a <- ggplot() +
  geom_segment(
    data = protocol_edges_refined,
    aes(x = x, xend = xend, y = y, yend = yend),
    arrow = arrow(length = unit(0.075, "in"), type = "closed"),
    linewidth = 0.38,
    colour = "#475569",
    lineend = "round"
  ) +
  geom_rect(
    data = protocol_nodes_refined,
    aes(xmin = x - w, xmax = x + w, ymin = y - h, ymax = y + h, fill = fill, colour = stroke),
    linewidth = 0.34
  ) +
  geom_text(
    data = protocol_nodes_refined,
    aes(x = x, y = y + 0.13, label = title),
    size = 2.18,
    fontface = "bold",
    lineheight = 0.86,
    colour = pc("ink")
  ) +
  geom_text(
    data = protocol_nodes_refined,
    aes(x = x, y = y - 0.18, label = detail),
    size = 2.00,
    lineheight = 0.88,
    colour = "#475569"
  ) +
  annotate("text", x = 0.08, y = 1.43, label = "CML audit protocol", hjust = 0, fontface = "bold", size = 2.75, colour = pc("ink")) +
  annotate("text", x = 0.08, y = 1.22, label = "Black-box for the suspect; scorer-assisted for candidate teachers; calibrated against a same-base null.", hjust = 0, size = 2.05, colour = "#536172") +
  scale_fill_identity() +
  scale_colour_identity() +
  coord_cartesian(xlim = c(0, 9.55), ylim = c(0.22, 1.55), expand = FALSE, clip = "off") +
  theme_void(base_family = "Arial") +
  theme(plot.margin = margin(4, 6, 2, 6))

stat_cards <- tibble(
  x = c(0.92, 2.62, 4.10),
  y = c(0.64, 0.64, 0.64),
  w = c(0.62, 0.62, 0.72),
  title = c("Suspect S", "Reference R", "Matched evidence"),
  detail = c("score under T_c", "score under T_c", "r_c = mean[log p_c(S) - log p_c(R)]"),
  fill = c("#ECFDF5", "#EFF6FF", "#EEF2FF"),
  stroke = c(pc("cml_dark"), pc("qwen"), pc("purple"))
)

stat_edges <- tibble(
  x = c(1.55, 3.25),
  xend = c(2.00, 3.58),
  y = c(0.64, 0.64),
  yend = c(0.64, 0.64),
  label = c("minus", "")
)

p1b <- ggplot() +
  geom_segment(
    data = stat_edges,
    aes(x = x, xend = xend, y = y, yend = yend),
    arrow = arrow(length = unit(0.06, "in"), type = "closed"),
    linewidth = 0.34,
    colour = "#64748B"
  ) +
  geom_text(data = stat_edges, aes(x = (x + xend) / 2, y = y + 0.17, label = label), size = 2.00, colour = "#64748B") +
  geom_rect(
    data = stat_cards,
    aes(xmin = x - w, xmax = x + w, ymin = y - 0.36, ymax = y + 0.36, fill = fill, colour = stroke),
    linewidth = 0.32
  ) +
  geom_text(data = stat_cards, aes(x = x, y = y + 0.12, label = title), size = 2.10, fontface = "bold", colour = pc("ink")) +
  geom_text(data = stat_cards, aes(x = x, y = y - 0.14, label = str_wrap(detail, 22)), size = 2.00, lineheight = 0.88, colour = "#475569") +
  annotate("text", x = 0.10, y = 1.40, label = "Capability matching", hjust = 0, fontface = "bold", size = 2.35, colour = pc("ink")) +
  annotate("text", x = 0.10, y = 1.20, label = "The same candidate scores both traces, so candidate capability shifts both terms.", hjust = 0, size = 2.00, colour = "#536172") +
  scale_fill_identity() +
  scale_colour_identity() +
  coord_cartesian(xlim = c(0, 5.00), ylim = c(0.12, 1.50), expand = FALSE, clip = "off") +
  theme_void(base_family = "Arial") +
  theme(plot.margin = margin(3, 5, 3, 5))

p1c <- ggplot(fig1_density, aes(x, y, fill = decision_group, colour = decision_group)) +
  geom_area(alpha = 0.34, linewidth = 0.28) +
  geom_vline(xintercept = fig1_threshold, linetype = "dashed", linewidth = 0.36, colour = pc("slate")) +
  annotate("label", x = fig1_threshold + 0.03, y = 0.54, label = "1% null\nthreshold", hjust = 0, size = 2.00, lineheight = 0.86, colour = pc("slate"), fill = "white", linewidth = 0) +
  annotate("text", x = -0.76, y = 0.98, label = "negative-control null", hjust = 0.5, size = 2.03, colour = pc("baseline_dark")) +
  annotate("text", x = 0.15, y = 0.98, label = "distilled suspects", hjust = 0.5, size = 2.03, colour = pc("cml_dark")) +
  scale_fill_manual(values = c("distilled suspects" = pc("cml"), "human-reference null" = pc("baseline"))) +
  scale_colour_manual(values = c("distilled suspects" = pc("cml_dark"), "human-reference null" = pc("baseline_dark"))) +
  labs(title = "Decision threshold", subtitle = "Calibrated on the null rather than on absolute likelihood", x = "max matched surplus r", y = NULL) +
  theme_nature(base_size = 6.8) +
  theme(
    legend.position = "none",
    axis.title.y = element_blank(),
    plot.margin = margin(3, 5, 3, 5)
  )

claim_boundary_refined <- tibble(
  column = factor(c(rep("Decision output", 3), rep("Audit input", 3)), levels = c("Decision output", "Audit input")),
  row = factor(rep(c("Detection", "Attribution", "Threshold"), 2), levels = rev(c("Detection", "Attribution", "Threshold"))),
  label = c(
    "distillation flag",
    "candidate teacher",
    "score and threshold",
    "suspect traces",
    "same-base reference",
    "candidate likelihood scoring"
  ),
  fill = c(pc("cml_soft"), "#EEF2FF", "#ECFDF5", "#F8FAFC", "#F8FAFC", "#F8FAFC"),
  stroke = c(pc("cml_dark"), pc("purple"), pc("cml_dark"), "#94A3B8", "#94A3B8", "#94A3B8")
) %>%
  mutate(label = str_wrap(label, 30))

p1d <- ggplot(claim_boundary_refined, aes(column, row)) +
  geom_tile(aes(fill = fill, colour = stroke), width = 0.93, height = 0.72, linewidth = 0.32) +
  geom_text(aes(label = label), size = 2.05, lineheight = 0.88, colour = pc("ink")) +
  scale_fill_identity() +
  scale_colour_identity() +
  labs(title = "Decision summary", subtitle = "Inputs and reported outputs", x = NULL, y = NULL) +
  theme_nature(base_size = 6.8) +
  theme(
    axis.text.x = element_text(face = "bold", size = 6.4),
    axis.ticks = element_blank(),
    axis.line = element_blank(),
    panel.grid = element_blank(),
    plot.margin = margin(3, 5, 3, 5)
  )

fig1 <- p1a / (p1b | p1c) / p1d +
  plot_layout(heights = c(0.86, 1.02, 1.08)) +
  plot_annotation(tag_levels = "a") &
  theme(plot.tag = element_text(face = "bold", size = 9.5, colour = "#0F172A"))

p2a <- ggplot(decision_boundary_df, aes(base_relative_max, cml_max_r, colour = group, fill = group)) +
  annotate("rect", xmin = 0, xmax = Inf, ymin = -Inf, ymax = 0, fill = pc("baseline_soft"), alpha = 0.22) +
  annotate("rect", xmin = -Inf, xmax = Inf, ymin = 0, ymax = Inf, fill = pc("cml_soft"), alpha = 0.18) +
  geom_hline(yintercept = 0, colour = pc("cml_dark"), linetype = "dashed", linewidth = 0.34) +
  geom_vline(xintercept = 0, colour = pc("baseline_dark"), linetype = "dashed", linewidth = 0.34) +
  geom_point(shape = 21, size = 1.00, stroke = 0.16, alpha = 0.36) +
  annotate("label", x = -1.16, y = 0.35, label = "CML-positive\nregion", size = 2.15, lineheight = 0.86, colour = pc("cml_dark"), fill = "white", linewidth = 0, hjust = 0) +
  scale_colour_manual(values = c("human-reference null" = pc("baseline_dark"), "distilled suspects" = pc("cml_dark"))) +
  scale_fill_manual(values = c("human-reference null" = pc("baseline"), "distilled suspects" = pc("cml"))) +
  coord_cartesian(xlim = c(-1.45, 0.86), ylim = c(-1.45, 0.52), clip = "on") +
  labs(title = "Decision boundary", subtitle = "CML separates distilled suspects while the base-relative statistic fires on null traces", x = "base-relative max surplus", y = "CML max matched surplus") +
  panel_theme +
  theme(legend.position = "none")

p2b <- ggplot(roc_plot_df, aes(fpr, tpr, colour = method)) +
  annotate("segment", x = 0, xend = 1, y = 0, yend = 1, colour = "#C9D3E2", linetype = "dotted", linewidth = 0.34) +
  geom_line(linewidth = 0.78) +
  annotate("label", x = 0.11, y = 0.96, label = "CML\nAUROC 0.997", colour = pc("cml_dark"), fill = "white", linewidth = 0, size = 2.12, hjust = 0) +
  annotate("label", x = 0.63, y = 0.61, label = "base-relative", colour = pc("baseline_dark"), fill = "white", linewidth = 0, size = 2.00, hjust = 0) +
  scale_colour_manual(values = method_cols[c("base-relative", "CML")]) +
  scale_x_continuous(limits = c(0, 1), breaks = c(0, 0.5, 1)) +
  scale_y_continuous(limits = c(0, 1), breaks = c(0, 0.5, 1)) +
  labs(title = "Full ROC shift", x = "False-positive rate", y = "True-positive rate") +
  panel_theme +
  theme(legend.position = "none")

metric_dashboard <- core_metric_df %>%
  mutate(
    stratum_short = recode(as.character(stratum), `all distilled` = "all", `cross-style` = "cross", `same-family` = "same"),
    method_short = recode(as.character(method), `base-relative` = "base-rel", CML = "CML")
  ) %>%
  select(stratum_short, method_short, AUROC = auroc, `TPR@1%FPR` = tpr1, `1-FPR0` = fpr0) %>%
  mutate(`1-FPR0` = 1 - `1-FPR0`) %>%
  pivot_longer(cols = c(AUROC, `TPR@1%FPR`, `1-FPR0`), names_to = "metric", values_to = "value") %>%
  mutate(
    metric = factor(metric, levels = c("AUROC", "TPR@1%FPR", "1-FPR0")),
    stratum_short = factor(stratum_short, levels = c("all", "cross", "same")),
    method_short = factor(method_short, levels = c("base-rel", "CML")),
    label = sprintf("%.3f", value),
    text_colour = if_else(value > 0.72, "white", pc("ink"))
  )

p2c <- ggplot(metric_dashboard, aes(stratum_short, method_short, fill = value)) +
  geom_tile(colour = "white", linewidth = 0.58) +
  geom_text(aes(label = label, colour = text_colour), size = 2.05, show.legend = FALSE) +
  facet_wrap(~metric, nrow = 1) +
  scale_colour_identity() +
  scale_fill_gradientn(colours = c("#F6E7D7", "#DCE9F7", pc("cml_dark")), limits = c(0, 1), oob = squish) +
  labs(title = "GSM8K operating dashboard", subtitle = "All metrics oriented as higher is better", x = "stratum", y = NULL) +
  panel_theme +
  theme(
    legend.position = "none",
    axis.text.x = element_text(size = 6.0),
    axis.text.y = element_text(size = 6.0),
    strip.text = element_text(size = 6.0, face = "bold"),
    panel.spacing.x = unit(0.04, "in")
  )

fpr_collapse_levels <- levels(fpr_collapse_df$stratum)
if (is.null(fpr_collapse_levels)) {
  fpr_collapse_levels <- unique(as.character(fpr_collapse_df$stratum))
}

fpr_collapse_plot_df <- fpr_collapse_df %>%
  mutate(
    stratum_label = as.character(stratum),
    y_pos = as.numeric(factor(stratum_label, levels = fpr_collapse_levels)),
    label_y = y_pos + 0.18,
    label_x = pmin(base_relative - 0.06, 0.70),
    value_label = paste0(sprintf("%.3f", base_relative), " -> ", sprintf("%.3f", cml))
  )

p2d <- ggplot(fpr_collapse_plot_df) +
  annotate("rect", xmin = 0, xmax = 0.01, ymin = -Inf, ymax = Inf, fill = pc("cml_soft"), alpha = 0.55) +
  geom_segment(
    aes(x = base_relative, xend = cml, y = y_pos, yend = y_pos),
    arrow = arrow(length = unit(0.08, "in"), type = "closed"),
    colour = "#8997AA",
    linewidth = 1.05,
    lineend = "round"
  ) +
  geom_point(aes(base_relative, y_pos), colour = pc("baseline"), size = 2.45) +
  geom_point(aes(cml, y_pos), colour = pc("cml_dark"), size = 2.55) +
  geom_label(
    aes(x = label_x, y = label_y, label = value_label),
    hjust = 1,
    linewidth = 0,
    fill = "white",
    size = 1.95,
    colour = pc("ink")
  ) +
  annotate("text", x = 0.014, y = length(fpr_collapse_levels) + 0.42, label = "1% band", hjust = 0, size = 1.95, colour = pc("cml_dark")) +
  scale_x_continuous(limits = c(0, 0.86), breaks = c(0.4, 0.8), labels = c("40%", "80%")) +
  scale_y_continuous(
    breaks = seq_along(fpr_collapse_levels),
    labels = fpr_collapse_levels,
    limits = c(0.68, length(fpr_collapse_levels) + 0.55)
  ) +
  labs(title = "False-accusation collapse", subtitle = "Lower FPR0 is better", x = "Empirical FPR at zero threshold", y = NULL) +
  panel_theme +
  theme(legend.position = "none")

task_heatmap <- task_metric_df %>%
  mutate(
    stratum_short = recode(as.character(stratum), `all distilled` = "all distilled", `cross-style` = "cross-style", `same-family` = "same-family"),
    method = factor(as.character(method), levels = c("base-relative", "CML")),
    stratum_short = factor(stratum_short, levels = rev(c("all distilled", "cross-style", "same-family"))),
    task = factor(as.character(task), levels = c("GSM8K", "MATH")),
    text_colour = if_else(auroc > 0.78, "white", pc("ink"))
  )

p2e <- ggplot(task_heatmap, aes(task, stratum_short, fill = auroc)) +
  geom_tile(colour = "white", linewidth = 0.60) +
  geom_text(aes(label = sprintf("%.3f", auroc), colour = text_colour), size = 1.95, show.legend = FALSE) +
  facet_wrap(~method, nrow = 1) +
  scale_colour_identity() +
  scale_fill_gradientn(colours = c("#F6E7D7", "#DCE9F7", pc("cml_dark")), limits = c(0, 1), oob = squish) +
  labs(title = "GSM8K to MATH stress test", subtitle = "MATH is single-seed; values are trace-level AUROC", x = NULL, y = NULL) +
  panel_theme +
  theme(
    legend.position = "none",
    axis.text.x = element_text(size = 5.8),
    axis.text.y = element_text(size = 5.8),
    strip.text = element_text(size = 5.9, face = "bold"),
    panel.spacing.x = unit(0.08, "in")
  )

design2_refined <- "
AABB
AACC
DDEE
DDEE
"

fig2 <- p2a + p2b + p2c + p2d + p2e +
  plot_layout(design = design2_refined, heights = c(1.00, 1.00, 0.98, 0.98)) +
  plot_annotation(tag_levels = "a") &
  theme(plot.tag = element_text(face = "bold", size = 9.5, colour = pc("ink")))

write_csv(protocol_nodes_refined, file.path(derived_dir, "figure1_refined_protocol_nodes.csv"))
write_csv(claim_boundary_refined, file.path(derived_dir, "figure1_refined_claim_boundary.csv"))
write_csv(metric_dashboard, file.path(derived_dir, "figure2_refined_gsm8k_dashboard.csv"))
write_csv(task_heatmap, file.path(derived_dir, "figure2_refined_task_heatmap.csv"))

write_csv(metric_gain_matrix, file.path(derived_dir, "figure2_gain_landscape.csv"))
write_csv(decision_boundary_df, file.path(derived_dir, "figure2_decision_boundary.csv"))
write_csv(stress_slope, file.path(derived_dir, "figure2_math_stress_slope.csv"))
write_csv(fpr_collapse_df, file.path(derived_dir, "figure2_fpr_collapse.csv"))
write_csv(trace_ridge_df, file.path(derived_dir, "figure2_trace_density_ridges.csv"))

mtcr_flow <- mtcr_attr %>%
  select(student_model, standard_cml_accuracy, cml_mtcr_accuracy, gain_pp) %>%
  pivot_longer(cols = c(standard_cml_accuracy, cml_mtcr_accuracy), names_to = "stage", values_to = "accuracy") %>%
  mutate(
    stage = recode(stage, standard_cml_accuracy = "standard CML", cml_mtcr_accuracy = "CML+MTCR"),
    stage = factor(stage, levels = c("standard CML", "CML+MTCR")),
    lineage = if_else(str_detect(student_model, "Qwen"), "Qwen lineage", "Llama lineage"),
    student_short = if_else(str_detect(student_model, "Qwen"), "Qwen", "Llama")
  )

p3a <- ggplot(mtcr_flow, aes(stage, accuracy, group = student_model, colour = lineage)) +
  geom_line(linewidth = 0.82, alpha = 0.86) +
  geom_point(size = 2.45) +
  geom_label(
    data = mtcr_attr %>% mutate(stage = factor("CML+MTCR", levels = c("standard CML", "CML+MTCR")), accuracy = cml_mtcr_accuracy, label = paste0("+", sprintf("%.1f", gain_pp), " pp")),
    aes(x = stage, y = accuracy, label = label, colour = if_else(str_detect(student_model, "Qwen"), "Qwen lineage", "Llama lineage")),
    inherit.aes = FALSE,
    linewidth = 0,
    fill = "white",
    hjust = 1.08,
    size = 2.05,
    show.legend = FALSE
  ) +
  scale_colour_manual(values = lineage_cols) +
  scale_y_continuous(limits = c(0.62, 0.94), breaks = c(0.65, 0.75, 0.85, 0.95), labels = label_number(accuracy = 0.01)) +
  coord_cartesian(xlim = c(0.85, 2.22), clip = "off") +
  labs(title = "Sibling attribution gain", subtitle = "Aggregate accuracy, not per-case transition", x = NULL, y = "Accuracy") +
  panel_theme +
  theme(legend.position = "none")

shared_long <- shared %>%
  pivot_longer(cols = c(baseline_base_relative, cml_standard, cml_mtcr), names_to = "method", values_to = "auroc") %>%
  mutate(
    method = recode(method, baseline_base_relative = "base-relative", cml_standard = "CML", cml_mtcr = "CML+MTCR"),
    method = factor(method, levels = c("base-relative", "CML", "CML+MTCR")),
    lineage = if_else(str_detect(student_model, "Qwen"), "Qwen lineage", "Llama lineage"),
    lineage = factor(lineage, levels = c("Llama lineage", "Qwen lineage")),
    text_colour = tile_text_colour(auroc, midpoint = 0.90)
  )

p3b <- ggplot(shared_long, aes(method, lineage, fill = auroc)) +
  geom_tile(colour = "white", linewidth = 0.70) +
  geom_text(aes(label = sprintf("%.3f", auroc), colour = text_colour), size = 2.15, show.legend = FALSE) +
  scale_colour_identity() +
  scale_fill_gradientn(colours = c("#F6E7D7", "#DCE9F7", pc("cml_dark")), limits = c(0, 1), oob = squish) +
  labs(title = "Shared-ancestor detection", x = NULL, y = NULL) +
  panel_theme +
  theme(axis.text.x = element_text(angle = 18, hjust = 1), legend.position = "none")

calib_long <- calib %>%
  pivot_longer(cols = c(qwen_accuracy, llama_accuracy), names_to = "model", values_to = "accuracy") %>%
  mutate(
    model = recode(model, qwen_accuracy = "R1-Qwen-32B", llama_accuracy = "R1-Llama-8B"),
    model = factor(model, levels = c("R1-Llama-8B", "R1-Qwen-32B")),
    calibration_tasks = factor(calibration_tasks, levels = calib$calibration_tasks),
    text_colour = tile_text_colour(accuracy, midpoint = 0.83)
  )

p3c <- ggplot(calib_long, aes(calibration_tasks, model, fill = accuracy)) +
  geom_tile(colour = "white", linewidth = 0.65) +
  geom_text(aes(label = sprintf("%.3f", accuracy), colour = text_colour), size = 2.05, show.legend = FALSE) +
  scale_colour_identity() +
  scale_fill_gradientn(colours = c("#E6EEF8", "#8DB3D7", pc("qwen")), limits = c(0.62, 0.90), oob = squish) +
  labs(title = "Calibration views", x = "Tasks", y = NULL) +
  panel_theme +
  theme(legend.position = "none")

epoch_long <- epoch %>%
  pivot_longer(cols = c(gsm8k_auroc, math_auroc), names_to = "dataset", values_to = "auroc") %>%
  mutate(
    dataset = recode(dataset, gsm8k_auroc = "GSM8K", math_auroc = "MATH"),
    dataset = factor(dataset, levels = c("MATH", "GSM8K")),
    epochs = factor(epochs, levels = epoch$epochs),
    text_colour = tile_text_colour(auroc, midpoint = 0.92)
  )
epoch_subtitle <- paste0("FPR ", paste(sprintf("%.3f", epoch$false_positive_rate), collapse = " -> "))

p3d <- ggplot(epoch_long, aes(epochs, dataset, fill = auroc)) +
  geom_tile(colour = "white", linewidth = 0.65) +
  geom_text(aes(label = sprintf("%.3f", auroc), colour = text_colour), size = 2.05, show.legend = FALSE) +
  scale_colour_identity() +
  scale_fill_gradientn(colours = c("#F6EDC5", "#8FC5A9", pc("cml_dark")), limits = c(0.75, 1.00), oob = squish) +
  labs(title = "Training duration", subtitle = epoch_subtitle, x = "Epochs", y = NULL) +
  panel_theme +
  theme(legend.position = "none")

calib_gain <- calib_long %>%
  group_by(model) %>%
  mutate(gain_from_one_task = accuracy - accuracy[calibration_tasks == "1"]) %>%
  ungroup()

calib_gain_plot <- calib_gain %>%
  mutate(tasks_num = as.numeric(as.character(calibration_tasks)))

calib_ribbon <- calib_gain_plot %>%
  select(tasks_num, model, gain_from_one_task) %>%
  pivot_wider(names_from = model, values_from = gain_from_one_task) %>%
  mutate(
    lower = pmin(`R1-Qwen-32B`, `R1-Llama-8B`),
    upper = pmax(`R1-Qwen-32B`, `R1-Llama-8B`),
    mid = (lower + upper) / 2
  )

calib_endpoints <- calib_gain_plot %>%
  filter(tasks_num %in% c(1, 16))

p3e <- ggplot(calib_gain_plot, aes(tasks_num, gain_from_one_task, colour = model)) +
  geom_segment(
    data = calib_endpoints %>% select(model, tasks_num, gain_from_one_task) %>% pivot_wider(names_from = tasks_num, values_from = gain_from_one_task, names_prefix = "task_"),
    aes(x = 1, xend = 16, y = task_1, yend = task_16, colour = model),
    inherit.aes = FALSE,
    linewidth = 0.72,
    alpha = 0.82
  ) +
  geom_point(aes(alpha = tasks_num %in% c(1, 16)), size = 2.05) +
  geom_label(
    data = calib_gain_plot %>%
      filter(calibration_tasks == "16") %>%
      mutate(label_y = gain_from_one_task + if_else(model == "R1-Qwen-32B", 0.014, -0.014)),
    aes(x = tasks_num, y = label_y, label = paste0("+", sprintf("%.1f", gain_from_one_task * 100), " pp"), colour = model),
    linewidth = 0,
    fill = "white",
    hjust = -0.04,
    size = 2.15,
    show.legend = FALSE
  ) +
  scale_alpha_manual(values = c("TRUE" = 1, "FALSE" = 0.32), guide = "none") +
  scale_x_continuous(breaks = calib$calibration_tasks) +
  scale_y_continuous(labels = label_percent(accuracy = 1), limits = c(0, 0.245)) +
  scale_colour_manual(values = c("R1-Qwen-32B" = pc("qwen"), "R1-Llama-8B" = pc("llama"))) +
  coord_cartesian(xlim = c(1, 18), clip = "off") +
  labs(title = "Calibration-gain ladder", subtitle = "Intermediate task counts are aggregate ticks", x = "Calibration tasks", y = "Gain vs one task") +
  panel_theme +
  theme(legend.position = "none")

p3f <- ggplot(epoch, aes(factor(epochs), "FPR0", fill = false_positive_rate)) +
  geom_tile(colour = "white", linewidth = 0.72) +
  geom_text(aes(label = sprintf("%.3f", false_positive_rate)), size = 2.28, colour = pc("ink")) +
  scale_fill_gradient(low = pc("cml_soft"), high = pc("baseline"), limits = c(0, 0.012), oob = squish) +
  labs(title = "Epoch false-positive strip", subtitle = "Lower is better; same checkpoints as panel d", x = "Distillation epochs", y = NULL) +
  panel_theme +
  theme(legend.position = "none", axis.text.y = element_blank(), axis.ticks.y = element_blank())

write_csv(calib_gain, file.path(derived_dir, "figure3_calibration_gain.csv"))
write_csv(mtcr_flow, file.path(derived_dir, "figure3_mtcr_attribution_flow.csv"))
write_csv(calib_ribbon, file.path(derived_dir, "figure3_calibration_gain_ribbon.csv"))
write_csv(epoch %>% select(epochs, false_positive_rate), file.path(derived_dir, "figure3_epoch_fpr.csv"))

design3 <- "
AABB
CCDD
EEFF
EEFF
"

fig3 <- p3a + p3b + p3c + p3d + p3e + p3f +
  plot_layout(design = design3, heights = c(0.92, 0.90, 0.90, 0.82)) +
  plot_annotation(tag_levels = "a") &
  theme(plot.tag = element_text(face = "bold", size = 9.5, colour = pc("ink")))

trace_long <- trace_budget %>%
  pivot_longer(cols = c(qwen_auroc, llama_auroc), names_to = "model", values_to = "auroc") %>%
  mutate(model = recode(model, qwen_auroc = "Qwen lineage", llama_auroc = "Llama lineage"))
trace_labels <- trace_long %>%
  filter(trace_size == max(trace_size)) %>%
  mutate(label_y = auroc + if_else(model == "Qwen lineage", 0.018, -0.018))

p4a <- ggplot(trace_long, aes(trace_size, auroc, colour = model, fill = model)) +
  geom_hline(yintercept = c(0.95, 0.99), colour = "#D9E0EA", linetype = "dashed", linewidth = 0.30) +
  geom_line(linewidth = 0.74) +
  geom_point(size = 2.25) +
  geom_label(data = trace_labels, aes(y = label_y, label = model), linewidth = 0, fill = "white", hjust = -0.05, size = 2.15, show.legend = FALSE) +
  annotate("text", x = 11, y = 0.953, label = "0.95", hjust = 0, vjust = -0.35, size = 1.9, colour = "#7B8794") +
  annotate("text", x = 11, y = 0.993, label = "0.99", hjust = 0, vjust = -0.35, size = 1.9, colour = "#7B8794") +
  scale_x_log10(breaks = trace_budget$trace_size, labels = trace_budget$trace_size) +
  scale_y_continuous(limits = c(0.66, 1.035), breaks = seq(0.7, 1.0, 0.1)) +
  scale_colour_manual(values = lineage_cols) +
  scale_fill_manual(values = c("Qwen lineage" = pc("qwen_soft"), "Llama lineage" = pc("llama_soft"))) +
  coord_cartesian(xlim = c(10, 760), clip = "off") +
  labs(title = "Trace budget", subtitle = "More suspect traces rapidly saturate detection", x = "Evaluated traces", y = "AUROC") +
  panel_theme +
  theme(legend.position = "none")

steps_long <- step_depth %>%
  pivot_longer(cols = c(qwen_auroc, llama_auroc), names_to = "model", values_to = "auroc") %>%
  mutate(
    model = recode(model, qwen_auroc = "Qwen lineage", llama_auroc = "Llama lineage"),
    model = factor(model, levels = c("Llama lineage", "Qwen lineage")),
    min_steps = factor(min_steps, levels = step_depth$min_steps),
    text_colour = tile_text_colour(auroc, midpoint = 0.97)
  )

p4b <- ggplot(steps_long, aes(min_steps, model, fill = auroc)) +
  geom_tile(colour = "white", linewidth = 0.68) +
  geom_text(aes(label = sprintf("%.3f", auroc), colour = text_colour), size = 2.08, show.legend = FALSE) +
  scale_colour_identity() +
  scale_fill_gradientn(colours = c("#DDEEE6", "#74A88F", "#075F46"), limits = c(0.90, 1.00), oob = squish) +
  labs(title = "Reasoning-depth filter", x = "Minimum reasoning steps", y = NULL) +
  panel_theme +
  theme(legend.position = "none")

cross_long <- cross_dataset %>%
  pivot_longer(cols = c(qwen_auroc, llama_auroc), names_to = "model", values_to = "auroc") %>%
  mutate(
    model = recode(model, qwen_auroc = "Qwen lineage", llama_auroc = "Llama lineage"),
    dataset = factor(dataset, levels = cross_dataset %>% arrange(qwen_auroc) %>% pull(dataset))
  )

p4c <- ggplot(cross_long, aes(auroc, dataset, colour = model)) +
  geom_segment(aes(x = 0.88, xend = auroc, yend = dataset), colour = "#DDE3EC", linewidth = 0.42) +
  geom_point(size = 2.35) +
  geom_text(
    data = cross_long %>% group_by(dataset) %>% filter(auroc == max(auroc)) %>% ungroup(),
    aes(label = sprintf("%.3f", auroc)),
    hjust = -0.18,
    size = 2.0,
    colour = pc("ink"),
    show.legend = FALSE
  ) +
  scale_colour_manual(values = lineage_cols) +
  coord_cartesian(xlim = c(0.88, 1.02), clip = "off") +
  labs(title = "Cross-dataset generalization", x = "AUROC", y = NULL) +
  panel_theme +
  theme(legend.position = "none")

hyper_long <- hyper %>%
  pivot_longer(cols = c(qwen_auroc, llama_auroc), names_to = "model", values_to = "auroc") %>%
  mutate(
    model = recode(model, qwen_auroc = "Qwen", llama_auroc = "Llama"),
    parameter_type = recode(parameter_type, temperature = "Teacher temperature", lr = "SFT learning rate"),
    parameter_value = factor(parameter_value, levels = unique(parameter_value)),
    text_colour = tile_text_colour(auroc, midpoint = 0.995)
  )

p4d <- ggplot(hyper_long, aes(parameter_value, model, fill = auroc)) +
  geom_tile(colour = "white", linewidth = 0.62) +
  geom_text(aes(label = sprintf("%.3f", auroc), colour = text_colour), size = 2.05, show.legend = FALSE) +
  facet_wrap(~parameter_type, scales = "free_x", nrow = 1) +
  scale_colour_identity() +
  scale_fill_gradientn(colours = c("#E9EEF5", "#86A9C8", "#0F5E8C"), limits = c(0.98, 1.00), oob = squish) +
  labs(title = "Hyperparameter robustness", x = NULL, y = NULL) +
  panel_theme +
  theme(axis.text.x = element_text(angle = 25, hjust = 1), legend.position = "none")

query_threshold_df <- trace_long %>%
  group_by(model) %>%
  summarise(
    traces_for_95 = min(trace_size[auroc >= 0.95]),
    traces_for_99 = min(trace_size[auroc >= 0.99]),
    .groups = "drop"
  ) %>%
  pivot_longer(cols = starts_with("traces_for"), names_to = "threshold", values_to = "trace_size") %>%
  mutate(
    threshold = recode(threshold, traces_for_95 = "AUROC >= 0.95", traces_for_99 = "AUROC >= 0.99"),
    threshold = factor(threshold, levels = c("AUROC >= 0.99", "AUROC >= 0.95")),
    y_pos = as.numeric(threshold) + if_else(model == "Qwen lineage", 0.12, -0.12)
  )

p4e <- ggplot(query_threshold_df, aes(trace_size, y_pos, colour = model, fill = model)) +
  geom_segment(aes(x = 50, xend = trace_size, yend = y_pos), colour = "#DDE3EC", linewidth = 0.42) +
  geom_point(size = 2.25) +
  geom_label(
    aes(label = paste(if_else(model == "Qwen lineage", "Qwen", "Llama"), trace_size)),
    linewidth = 0,
    fill = "white",
    hjust = -0.12,
    size = 2.0,
    show.legend = FALSE
  ) +
  scale_x_log10(breaks = c(50, 100, 200, 500), labels = c(50, 100, 200, 500)) +
  scale_y_continuous(breaks = seq_along(levels(query_threshold_df$threshold)), labels = levels(query_threshold_df$threshold)) +
  scale_colour_manual(values = lineage_cols) +
  scale_fill_manual(values = c("Qwen lineage" = pc("qwen_soft"), "Llama lineage" = pc("llama_soft"))) +
  coord_cartesian(xlim = c(50, 720), clip = "off") +
  labs(title = "Query threshold", x = "Minimum evaluated traces", y = NULL) +
  panel_theme +
  theme(legend.position = "none")

robustness_floor_df <- bind_rows(
  cross_long %>%
    group_by(model) %>%
    summarise(setting = "Cross-dataset floor", floor_auroc = min(auroc), .groups = "drop"),
  hyper_long %>%
    mutate(model = recode(model, Qwen = "Qwen lineage", Llama = "Llama lineage")) %>%
    group_by(model) %>%
    summarise(setting = "Hyperparameter floor", floor_auroc = min(auroc), .groups = "drop")
) %>%
  mutate(
    setting = factor(setting, levels = rev(c("Cross-dataset floor", "Hyperparameter floor"))),
    y_pos = as.numeric(setting) + if_else(model == "Qwen lineage", 0.12, -0.12)
  )

p4f <- ggplot(robustness_floor_df, aes(floor_auroc, y_pos, colour = model)) +
  geom_segment(aes(x = 0.88, xend = floor_auroc, yend = y_pos), colour = "#DDE3EC", linewidth = 0.48) +
  geom_point(size = 2.45) +
  geom_text(aes(label = sprintf("%.3f", floor_auroc)), hjust = -0.16, size = 2.05, show.legend = FALSE) +
  scale_colour_manual(values = lineage_cols) +
  scale_y_continuous(
    breaks = seq_along(levels(robustness_floor_df$setting)),
    labels = levels(robustness_floor_df$setting)
  ) +
  coord_cartesian(xlim = c(0.88, 1.02), clip = "off") +
  labs(title = "Worst-case floor across tested settings", subtitle = "Point estimates, not confidence intervals", x = "Minimum AUROC", y = NULL) +
  panel_theme +
  theme(
    legend.position = c(0.52, 0.16),
    legend.direction = "horizontal",
    legend.text = element_text(size = 5.4),
    legend.key.width = unit(0.18, "in")
  )

write_csv(query_threshold_df, file.path(derived_dir, "figure4_query_thresholds.csv"))
write_csv(robustness_floor_df, file.path(derived_dir, "figure4_robustness_floors.csv"))

design4 <- "
AABB
AACC
DDEE
DDFF
"

fig4 <- p4e + p4b + p4c + p4a + p4d + p4f +
  plot_layout(design = design4, heights = c(0.92, 0.86, 0.82, 0.78)) +
  plot_annotation(tag_levels = "a") &
  theme(plot.tag = element_text(face = "bold", size = 9.5, colour = pc("ink")))

save_pub(fig1, "fig_method_overview", width = 7.2, height = 5.15)
save_pub(fig2, "fig_core_detection", width = 7.2, height = 6.80)
save_pub(fig3, "fig_mtcr_attribution_epoch", width = 7.2, height = 7.25)
save_pub(fig4, "fig_robustness_checks", width = 7.2, height = 7.45)

advanced_override <- file.path(root_dir, "plot_tifs_advanced_figures.R")
if (file.exists(advanced_override)) {
  source(advanced_override, local = TRUE)
}

external_fig1_import <- file.path(root_dir, "import_external_fig1.R")
if (file.exists(external_fig1_import)) {
  source(external_fig1_import, local = TRUE)
}

message("Generated reference-guided R figures in: ", root_dir)
