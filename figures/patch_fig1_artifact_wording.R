library(grid)
library(png)

script_arg <- commandArgs(trailingOnly = FALSE)
file_arg <- "--file="
script_path <- normalizePath(sub(file_arg, "", script_arg[grepl(file_arg, script_arg)][1]), winslash = "/", mustWork = FALSE)
root_dir <- dirname(script_path)
if (!dir.exists(file.path(root_dir, "source_external"))) {
  root_dir <- normalizePath(file.path(getwd(), "figures"), winslash = "/", mustWork = TRUE)
}

source_path <- file.path(root_dir, "source_external", "fig1_cml_protocol_external_source_20260624_155038.png")
archive_dir <- file.path(root_dir, "archive", "fig1_external_original_before_artifactwording_20260624")
archive_path <- file.path(archive_dir, basename(source_path))

if (!file.exists(source_path)) {
  stop("Missing Fig. 1 source image: ", source_path)
}
if (!dir.exists(archive_dir)) {
  dir.create(archive_dir, recursive = TRUE, showWarnings = FALSE)
}
if (!file.exists(archive_path)) {
  file.copy(source_path, archive_path, overwrite = FALSE)
}

# Always patch from the archived PI-selected source to avoid accumulating raster edits.
img <- readPNG(archive_path)
h <- dim(img)[1]
w <- dim(img)[2]

png(source_path, width = w, height = h, bg = "white")
grid.newpage()
pushViewport(viewport(width = unit(1, "npc"), height = unit(1, "npc")))
grid.raster(img, width = unit(1, "npc"), height = unit(1, "npc"), interpolate = TRUE)

# Remove the old lower-right claim-boundary declarations without regenerating the
# PI-selected schematic.
subtitle_x <- 1378 / w
subtitle_y <- 101 / h
subtitle_width <- 420 / w
subtitle_height <- 52 / h
grid.rect(
  x = unit(subtitle_x, "npc"),
  y = unit(1 - subtitle_y, "npc"),
  width = unit(subtitle_width, "npc"),
  height = unit(subtitle_height, "npc"),
  gp = gpar(fill = "#FFFFFF", col = NA)
)

lower_x <- 1398 / w
lower_y <- 732 / h
lower_width <- 514 / w
lower_height <- 278 / h
grid.rect(
  x = unit(lower_x, "npc"),
  y = unit(1 - lower_y, "npc"),
  width = unit(lower_width, "npc"),
  height = unit(lower_height, "npc"),
  gp = gpar(fill = "#FFFFFF", col = NA)
)
grid.rect(
  x = unit(1398 / w, "npc"),
  y = unit(1 - (878 / h), "npc"),
  width = unit(514 / w, "npc"),
  height = unit(70 / h, "npc"),
  gp = gpar(fill = "#FFFFFF", col = NA)
)

grid.roundrect(
  x = unit(1398 / w, "npc"),
  y = unit(1 - (744 / h), "npc"),
  width = unit(438 / w, "npc"),
  height = unit(142 / h, "npc"),
  r = unit(7, "pt"),
  gp = gpar(fill = "#F8FAFC", col = "#64748B", lwd = 1.4)
)
grid.text(
  "Decision report",
  x = unit(1398 / w, "npc"),
  y = unit(1 - (695 / h), "npc"),
  gp = gpar(col = "#111827", fontsize = 22, fontfamily = "sans", fontface = "bold")
)
grid.text(
  paste(
    "\u2022 distillation flag",
    "\u2022 candidate teacher",
    "\u2022 score and threshold",
    sep = "\n"
  ),
  x = unit(1240 / w, "npc"),
  y = unit(1 - (732 / h), "npc"),
  just = c("left", "top"),
  gp = gpar(col = "#111827", fontsize = 18, fontfamily = "sans", lineheight = 1.05)
)
popViewport()
dev.off()

message("Patched Fig. 1 source image decision-report wording: ", source_path)
