---
name: KL-disp-analysis
description: Generate a study-level disposition analysis report in markdown from an SDTM DS (Disposition) .xpt dataset, using either R or Python. Use this skill whenever the user asks about patient status, subject disposition, completion or discontinuation in a clinical trial — "how many patients completed the study", "why did subjects drop out", "summarize patient status from ds.xpt", "disposition analysis", "screen failure counts", "discontinuation reasons", "write an R script to read ds.xpt", "dropout rate for this study". Trigger on any mention of DS, DSDECOD, DSCAT, DSTERM, disposition, EOSSTT, completion rate, withdrawal, or screen failures alongside a study data folder, even if the user does not use the word "disposition". Also trigger when the user asks for a script (R or Python) that reads ds.xpt and writes a status summary. Do NOT trigger for a single named subject's history — that is one patient at a time, which KL-patient-profile handles — and do not trigger for non-disposition domains (AE incidence, lab shifts, exposure).
---

# Disposition analysis from SDTM DS

Produces a **study-level** markdown report of subject disposition — how many
subjects completed, how many discontinued and why, how many never got past
screening — from an SDTM `DS` dataset.

Two bundled scripts do the work, one per language, and they are written to
produce byte-identical reports. Run the one the user asked for rather than
writing fresh code: the parts that quietly produce wrong numbers (screen
failures inflating the denominator, follow-up visits counted as statuses,
duplicate disposition records) are already handled here, and re-deriving them
per request reintroduces mistakes that look like plausible output.

Paths below are relative to this skill's directory.

## Input

Collect these before processing. The data path is the only one you cannot
proceed without.

| Input | Required | Notes |
|---|---|---|
| **Language** | No — but ask if unclear | `R` or `Python`. Ask when the user has not said and there is no signal in the conversation; sponsors are usually standardized on one, so guessing wastes their time. If they clearly don't care, use R — `haven` is the lighter dependency. |
| **Input data path** | **Yes** | Either `ds.xpt` itself or a study directory. Both scripts walk a directory tree for `ds.xpt` (case-insensitive), so a study root with `sdtm/` underneath is fine. If missing, ask and stop — nothing downstream works without it. |
| **Output script path** | No | Where to leave the analysis script. Defaults to the working directory. The script is a deliverable, not a temp file: the user re-runs it when the data refreshes, so copy it out of the skill rather than running it in place. |
| **Output report path** | No | Defaults to `disp_analysis.md` in the working directory. |

## Output

Two files.

1. **The analysis script** — `disp_analysis.R` or `disp_analysis.py`, copied to
   the user's working directory so they own and can re-run it.
2. **The markdown report** — exactly these four `##` sections, in this order:

```markdown
# Disposition Analysis
**Study:** / **Source dataset:** / **Generated:**

## 1. Overview
## 2. Status Summary
## 3. Reason for Discontinuation
## 4. Data Notes
```

**No patient-level listing.** This report is about the study, not about
individuals — a per-subject table would run to hundreds of rows and bury the
summary the user came for. If they want one subject's history, that is the
`KL-patient-profile` skill.

## Process

### 1. Confirm the input and the language

Check the path exists and holds `ds.xpt`. Settle on R or Python before running
anything, so you are not producing a script in the wrong language.

Dependencies, if the run fails on a missing library:

```bash
Rscript -e 'install.packages("haven")'     # R
pip install pandas pyreadstat              # Python
```

### 2. Copy the script to the user's working directory

```bash
cp scripts/disp_analysis.R  ./disp_analysis.R     # or
cp scripts/disp_analysis.py ./disp_analysis.py
```

Copy first, then run the copy. The user asked for a script; leaving it inside
the skill directory means they have nothing to keep.

### 3. Run it

```bash
Rscript disp_analysis.R --data /path/to/study --out disp_analysis.md
python3 disp_analysis.py --data /path/to/study --out disp_analysis.md
```

`--data` takes the `.xpt` file or a directory to search. Both scripts print a
one-line summary of subject counts to stdout — compare it against the report
you hand over, and treat a mismatch as a bug rather than a rounding quirk.

### 4. Read the report before handing it over

Two failure modes look like success: a report where every status lands in one
bucket (usually `DSCAT` absent or non-standard, so the disposition filter did
not narrow anything), and a report with no discontinuation section at all
(legitimate for a complete study, suspicious for a large one). Section 4 tells
you which happened — it records how many subjects lacked a disposition record
and what the non-disposition records were.

Then report the headline numbers in your reply: subjects, completed,
discontinued, screen failures, and the leading discontinuation reason. Name
anything odd that section 4 flagged.

### 5. Extend the script if the study needs more

For a sponsor-specific variable or an extra breakdown (by site, by treatment
epoch, timing of discontinuation), edit the script the user now owns and
re-run. Keep the two languages in step if you change derivation logic — they
are meant to agree, and a silent divergence between them is worse than either
being wrong on its own, because it destroys the reason to trust either.

## Notes

These are properties of CDISC DS data, not of the scripts. They cause wrong
numbers rather than errors, which is what makes them worth knowing.

- **`DSCAT` separates real dispositions from everything else.** Only
  `DSCAT = "DISPOSITION EVENT"` records carry the protocol disposition.
  `OTHER EVENT` records — final lab visit, final retrieval visit — and
  `PROTOCOL MILESTONE` records are contacts, not outcomes. In the CDISC pilot
  study that distinction is 306 dispositions out of 596 DS records: counting
  all of them nearly doubles the denominator.
- **Multiple DS records per subject is normal**, so a raw `DSDECOD` frequency
  is a record count, not a subject count. The scripts reduce to one disposition
  per subject, keeping the last by `DSSEQ`.
- **Screen failures are not discontinuations.** A subject who failed screening
  never entered the treatment period. Folding them into the dropout reasons
  understates the completion rate; the report keeps them in their own status row
  and computes `% of Enrolled` on the post-screening population.
- **`DSDECOD` is controlled terminology, `DSTERM` is verbatim.** Summarize on
  `DSDECOD` — the pilot study has 92 subjects under one `DSDECOD` of
  `ADVERSE EVENT` spread across many distinct `DSTERM` strings, so a `DSTERM`
  frequency fragments into near-singletons that summarize nothing.
- **`DSSTDY` (study day), not a date difference.** There is no study Day 0:
  Day 1 is first dose and the day before is Day −1, so subtracting dates is off
  by one for every post-baseline record.
- **DS dates are character and legally partial.** `DSSTDTC` may be `2014-07` or
  just `2014`. Pass ISO text through unparsed; coercing it to `2014-07-01`
  invents precision that was never collected.
- **ADaM says the same thing differently.** If `adsl.xpt` is present, `EOSSTT`,
  `DCSREAS` and `DCDECOD` carry disposition already derived, and `ADSL` is
  often subset to a population flag such as `SAFFL='Y'` — which means a
  screen-failure subject can exist in DS and be absent from ADSL. When the two
  disagree, DS is the collected source and ADSL is a derivation; say which one
  the report used.
- **A completion rate needs its denominator stated.** 110 of 306 and 110 of 254
  are both defensible for the same study. The report gives both and labels them,
  because an unlabelled percentage here is the single easiest way to mislead.

## Troubleshooting

| Symptom | Cause and fix |
|---|---|
| `no ds.xpt found under directory: <dir>` | Pointed above or below the data, or the files are `.sas7bdat`. These scripts read XPORT only. |
| `DS is missing required variable(s): ...` | Not a DS dataset, or a sponsor extract without `USUBJID`/`DSDECOD`. Check the file with a quick read of its columns. |
| `note: no DSCAT == 'DISPOSITION EVENT' records` on stderr | `DSCAT` is absent or uses sponsor values. The script falls back to treating every record as a disposition — verify that assumption against the data before trusting the counts. |
| Everything lands in `Discontinued` | `DSDECOD` is not standard CT (e.g. `COMPLETE` rather than `COMPLETED`). Inspect the distinct `DSDECOD` values and adjust the mapping in the script. |
| Python: `could not read <path>` | Malformed XPORT header. `pip install pyreadstat` enables the fallback reader. |
| R and Python reports disagree | A real bug — one of the two was edited without the other. Diff them (ignoring the `Source dataset` and `Generated` lines, which differ by design) and fix the derivation, not the report. |

## Status

Both scripts have been run against `cdisc/sdtm/ds.xpt` (CDISCPILOT01, 596
records / 306 subjects) and produce byte-identical reports apart from the
source-path and timestamp lines: 110 completed, 144 discontinued, 52 screen
failures, adverse event the leading reason at 92 subjects. Expect to adjust the
`DSDECOD` mapping for sponsors that deviate from CDISC controlled terminology.
