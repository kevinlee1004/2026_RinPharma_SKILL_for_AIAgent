#-----------------------------------------------------------------------------
# disp_analysis.R -- Disposition analysis report from SDTM DS
#
# Reads an SDTM DS (Disposition) .xpt dataset and writes a study-level
# disposition report in markdown. No patient-level listing is produced:
# this report is about the study, not about individual subjects.
#
# Usage:
#   Rscript disp_analysis.R --data <ds.xpt | study dir> [--out disp_analysis.md]
#
# Requires: haven
#-----------------------------------------------------------------------------

suppressMessages(library(haven))

#-- arguments ----------------------------------------------------------------

args    <- commandArgs(trailingOnly = TRUE)
ds_arg  <- NULL
out_md  <- "disp_analysis.md"

i <- 1
while (i <= length(args)) {
  a <- args[i]
  if (a %in% c("--data", "-d")) { ds_arg <- args[i + 1]; i <- i + 2 }
  else if (a %in% c("--out", "-o")) { out_md <- args[i + 1]; i <- i + 2 }
  else if (is.null(ds_arg)) { ds_arg <- a; i <- i + 1 }
  else { i <- i + 1 }
}

if (is.null(ds_arg)) {
  stop("need --data pointing at ds.xpt or a study directory containing it")
}

# Accept either the file itself or a directory to search. Filename case is not
# significant across platforms, and studies nest data under sdtm/.
resolve_ds <- function(p) {
  if (!file.exists(p)) stop("path not found: ", p)
  if (!dir.exists(p)) return(p)
  hits <- list.files(p, pattern = "^ds\\.xpt$", recursive = TRUE,
                     full.names = TRUE, ignore.case = TRUE)
  if (length(hits) == 0) stop("no ds.xpt found under directory: ", p)
  if (length(hits) > 1) {
    message("note: multiple ds.xpt found, using ", hits[1])
  }
  hits[1]
}

ds_path <- resolve_ds(ds_arg)
ds <- as.data.frame(read_xpt(ds_path))

required <- c("USUBJID", "DSDECOD")
missing_vars <- setdiff(required, names(ds))
if (length(missing_vars) > 0) {
  stop("DS is missing required variable(s): ", paste(missing_vars, collapse = ", "))
}

#-- helpers ------------------------------------------------------------------

# Strip haven/SAS attributes and blank out NA so values compare and print cleanly
chr <- function(x) {
  if (is.null(x)) return(character(0))
  x <- as.character(x)
  x[is.na(x)] <- ""
  trimws(x)
}

pct <- function(n, d) if (d > 0) sprintf("%.1f%%", 100 * n / d) else "-"

md_table <- function(df) {
  cells  <- lapply(df, function(col) gsub("|", "\\|", as.character(col), fixed = TRUE))
  df     <- as.data.frame(cells, stringsAsFactors = FALSE, check.names = FALSE)
  header <- paste0("| ", paste(names(df), collapse = " | "), " |")
  rule   <- paste0("|", paste(rep("---", ncol(df)), collapse = "|"), "|")
  body   <- apply(df, 1, function(r) paste0("| ", paste(trimws(r), collapse = " | "), " |"))
  c(header, rule, unname(body))
}

#-- derive subject-level status ----------------------------------------------

# DSCAT == "DISPOSITION EVENT" carries the protocol disposition. The other
# records (final lab visit, final retrieval visit, protocol milestones) are
# follow-up contacts -- counting them as statuses inflates every denominator.
dscat <- if ("DSCAT" %in% names(ds)) chr(ds$DSCAT) else rep("DISPOSITION EVENT", nrow(ds))
is_disp <- dscat == "DISPOSITION EVENT"
if (!any(is_disp)) {
  message("note: no DSCAT == 'DISPOSITION EVENT' records; treating all DS records as dispositions")
  is_disp <- rep(TRUE, nrow(ds))
}

disp  <- ds[is_disp, , drop = FALSE]
other <- ds[!is_disp, , drop = FALSE]

# One disposition per subject is expected. Where a subject has more, keep the
# last by DSSEQ -- the final disposition is the one that describes the outcome.
seqv <- if ("DSSEQ" %in% names(disp)) disp$DSSEQ else seq_len(nrow(disp))
disp <- disp[order(chr(disp$USUBJID), seqv), , drop = FALSE]
n_disp_records <- nrow(disp)
disp <- disp[!duplicated(chr(disp$USUBJID), fromLast = TRUE), , drop = FALSE]
n_dup <- n_disp_records - nrow(disp)

decod <- chr(disp$DSDECOD)
is_sf   <- decod == "SCREEN FAILURE"
is_comp <- decod == "COMPLETED"

disp$STATUS <- ifelse(is_sf, "Screen Failure",
               ifelse(is_comp, "Completed", "Discontinued"))

n_all      <- nrow(disp)
n_enrolled <- sum(!is_sf)   # screen failures never entered the study

#-- build the markdown -------------------------------------------------------

study <- paste(unique(chr(ds$STUDYID)), collapse = ", ")
if (!nzchar(study)) study <- "(STUDYID not in dataset)"

lines <- c(
  "# Disposition Analysis",
  "",
  paste0("**Study:** ", study),
  paste0("**Source dataset:** `", ds_path, "` (SDTM DS -- Disposition)"),
  paste0("**Generated:** ", format(Sys.time(), "%Y-%m-%d %H:%M:%S"), " by `disp_analysis.R`"),
  "",
  "## 1. Overview",
  "",
  paste0("- Subjects in DS: **", length(unique(chr(ds$USUBJID))), "**"),
  paste0("- DS records read: **", nrow(ds), "**"),
  paste0("- Disposition-event records: **", n_disp_records, "**"),
  paste0("- Other-event records (follow-up visits, milestones): **", nrow(other), "**"),
  ""
)

#-- 2. status summary --------------------------------------------------------

status_levels <- c("Completed", "Discontinued", "Screen Failure")
st <- table(factor(disp$STATUS, levels = status_levels))

status_tab <- data.frame(
  Status      = names(st),
  N           = as.integer(st),
  `% of All`  = sapply(as.integer(st), pct, d = n_all),
  check.names = FALSE, stringsAsFactors = FALSE
)
status_tab <- rbind(status_tab,
  data.frame(Status = "**Total**", N = n_all, `% of All` = pct(n_all, n_all),
             check.names = FALSE, stringsAsFactors = FALSE))

lines <- c(lines,
  "## 2. Status Summary",
  "",
  md_table(status_tab),
  "",
  paste0("Excluding the ", sum(is_sf), " screen failure(s), **", n_enrolled,
         "** subject(s) entered the study: **", sum(is_comp), "** completed (",
         pct(sum(is_comp), n_enrolled), " of enrolled) and **",
         sum(disp$STATUS == "Discontinued"), "** discontinued (",
         pct(sum(disp$STATUS == "Discontinued"), n_enrolled), " of enrolled)."),
  "")

#-- 3. reason for discontinuation --------------------------------------------

disc <- disp[disp$STATUS == "Discontinued", , drop = FALSE]

lines <- c(lines, "## 3. Reason for Discontinuation", "")

if (nrow(disc) == 0) {
  lines <- c(lines, "No subject discontinued: every disposition is COMPLETED or SCREEN FAILURE.", "")
} else {
  rt <- sort(table(chr(disc$DSDECOD)), decreasing = TRUE)
  reason_tab <- data.frame(
    `Reason (DSDECOD)`  = names(rt),
    N                   = as.integer(rt),
    `% of Discontinued` = sapply(as.integer(rt), pct, d = nrow(disc)),
    `% of Enrolled`     = sapply(as.integer(rt), pct, d = n_enrolled),
    check.names = FALSE, stringsAsFactors = FALSE
  )
  reason_tab <- rbind(reason_tab,
    data.frame(`Reason (DSDECOD)` = "**Total discontinued**", N = nrow(disc),
               `% of Discontinued` = pct(nrow(disc), nrow(disc)),
               `% of Enrolled`     = pct(nrow(disc), n_enrolled),
               check.names = FALSE, stringsAsFactors = FALSE))

  lines <- c(lines,
    paste0("Counts are subjects, not records; `% of Enrolled` uses the ",
           n_enrolled, " subject(s) who passed screening."),
    "",
    md_table(reason_tab),
    "")
}

#-- 4. data notes -----------------------------------------------------------

no_disp <- setdiff(unique(chr(ds$USUBJID)), chr(disp$USUBJID))

fu_lines <- character(0)
if (nrow(other) > 0) {
  ot <- sort(table(chr(other$DSDECOD)), decreasing = TRUE)
  fu_lines <- c("- Other-event records by `DSDECOD` (follow-up contacts, not statuses):",
                paste0("  - ", names(ot), ": ", as.integer(ot), " record(s)"))
}

lines <- c(lines,
  "## 4. Data Notes",
  "",
  "- Status is derived from `DSDECOD` on records where `DSCAT = \"DISPOSITION EVENT\"`:",
  "  `COMPLETED` -> Completed, `SCREEN FAILURE` -> Screen Failure, every other term -> Discontinued.",
  paste0("- Subjects with a disposition record: **", n_all, "**",
         if (length(no_disp) > 0)
           paste0("; **", length(no_disp), "** subject(s) appear in DS with no disposition event (",
                  paste(utils::head(no_disp, 10), collapse = ", "),
                  if (length(no_disp) > 10) ", ..." else "", ")")
         else "; every subject in DS has one."),
  if (n_dup > 0)
    paste0("- **", n_dup, "** extra disposition record(s) were found beyond one per subject; the last by `DSSEQ` was kept.")
  else
    "- Exactly one disposition record per subject -- no tie-breaking was needed.",
  fu_lines,
  "- Screen failures are reported separately rather than folded into the discontinuation reasons, since they never entered the treatment period.",
  "- This report is study-level. For one subject's disposition history, read that subject's DS records directly.",
  ""
)

writeLines(lines, out_md)
cat("Wrote", out_md, "--", n_all, "subjects,", sum(is_comp), "completed,",
    sum(disp$STATUS == "Discontinued"), "discontinued,", sum(is_sf), "screen failures\n")
