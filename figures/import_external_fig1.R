suppressPackageStartupMessages({
  library(grid)
  library(png)
  library(ragg)
  library(svglite)
})

`%||%` <- function(x, y) {
  if (length(x) == 0 || is.na(x) || !nzchar(x)) y else x
}

script_file <- sub("^--file=", "", grep("^--file=", commandArgs(FALSE), value = TRUE)[1] %||% "")
root_dir <- if (nzchar(script_file)) {
  dirname(normalizePath(script_file))
} else {
  getwd()
}

source_path <- file.path(
  root_dir,
  "source_external",
  "fig1_cml_protocol_external_source_20260624_155038.png"
)
if (!file.exists(source_path)) {
  stop("Missing external Figure 1 source: ", source_path, call. = FALSE)
}

img <- png::readPNG(source_path)
height_px <- dim(img)[1]
width_px <- dim(img)[2]
width_in <- 7.2
height_in <- width_in * height_px / width_px

draw_external_fig1 <- function() {
  grid.newpage()
  grid.raster(img, x = 0.5, y = 0.5, width = unit(1, "npc"), height = unit(1, "npc"))
}

png_out <- file.path(root_dir, "fig_method_overview.png")
pdf_out <- file.path(root_dir, "fig_method_overview.pdf")
svg_out <- file.path(root_dir, "fig_method_overview.svg")
tiff_out <- file.path(root_dir, "fig_method_overview.tiff")

file.copy(source_path, png_out, overwrite = TRUE)

grDevices::cairo_pdf(pdf_out, width = width_in, height = height_in, family = "Arial")
draw_external_fig1()
dev.off()

svglite::svglite(svg_out, width = width_in, height = height_in)
draw_external_fig1()
dev.off()

ragg::agg_tiff(tiff_out, width = width_in, height = height_in, units = "in", res = 600, compression = "lzw", background = "white")
draw_external_fig1()
dev.off()

message("Imported external Figure 1 source into manuscript figure artifacts.")
