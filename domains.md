# SDTM / ADaM variable reference for patient profiles

Read this when a study uses variables the script does not already look for, or
when you need to write custom extraction code for a domain that has no section
yet. Variable names here are the CDISC standard ones; sponsors add their own.

## Contents

- [Identifying a patient](#identifying-a-patient)
- [Dates and study days](#dates-and-study-days)
- [Per-domain variables](#per-domain-variables)
- [SDTM vs ADaM: which to prefer](#sdtm-vs-adam-which-to-prefer)
- [Adding a new domain section](#adding-a-new-domain-section)

## Identifying a patient

`USUBJID` is the only identifier guaranteed unique across a study, and it is
conventionally `STUDYID-SITEID-SUBJID` (e.g. `01-701-1015`). `SUBJID` is unique
only *within a site*, so two sites can both have subject `1015`.

Users almost always say "1015". `resolve_patient()` handles this: exact
`USUBJID`, then exact `SUBJID`, then a unique suffix/substring match, and it
refuses to guess when more than one subject matches. When it reports multiple
matches, ask the user which site rather than picking one.

## Dates and study days

This is the most common source of wrong numbers in a profile.

| Pattern | Standard | Type | Notes |
|---|---|---|---|
| `AESTDTC`, `LBDTC`, `RFSTDTC` | SDTM | **character**, ISO 8601 | May be partial: `2012-07` or `2012`. Never parse blindly. |
| `ASTDT`, `ADT`, `TRTSDT` | ADaM | **numeric** | Days since 1960-01-01 (SAS epoch). |
| `AESTDY`, `LBDY`, `ADY` | both | numeric | Study day relative to first dose. |

Two traps:

- **There is no Day 0.** Day 1 is the day of first dose; the day before is
  Day −1. Computing `(date - refdate).days` gives you an off-by-one for all
  post-baseline days. Use the sponsor's `--DY`/`ADY` variable when it exists.
- **Partial dates are legal and meaningful.** `2012-07` means the day was never
  collected. Rendering it as `2012-07-01` fabricates precision that a reviewer
  may act on. The script passes ISO text through untouched for this reason.

## Per-domain variables

### DM / ADSL — demographics
`USUBJID` `SUBJID` `SITEID` `AGE` `AGEU` `SEX` `RACE` `ETHNIC` `COUNTRY`
`ARM` `ARMCD` `ACTARM` `RFSTDTC` `RFENDTC` `RFXSTDTC` `RFXENDTC` `DTHFL` `DTHDTC`

ADSL adds: `TRT01P` `TRT01A` `TRTSDT` `TRTEDT` `AGEGR1` `DCSREAS` `EOSSTT`
and population flags `SAFFL` `ITTFL` `EFFFL` `RANDFL` `COMP24FL`.

`ARM` is *planned*, `ACTARM`/`TRT01A` is *actual*. They differ for
mis-randomised subjects, and a safety profile should show the actual arm.

### DS — disposition
`DSTERM` (verbatim) `DSDECOD` (controlled terms) `DSCAT` `DSSTDTC` `DSSTDY` `EPOCH`

One subject has **multiple DS records** — typically one per epoch plus study
completion. `DSCAT` separates `DISPOSITION EVENT` from `PROTOCOL MILESTONE`;
don't report a milestone as a discontinuation.

### AE / ADAE — adverse events
`AETERM` (verbatim) `AEDECOD` (MedDRA PT) `AEBODSYS` (SOC) `AESTDTC` `AEENDTC`
`AESTDY` `AEENDY` `AESER` `AEREL` `AEOUT` `AEACN`

Severity is recorded **one of two ways, not both**: `AESEV`
(MILD/MODERATE/SEVERE) or `AETOXGR`/`ATOXGR` (CTCAE grade 1–5). Oncology
studies use the grade.

`TRTEMFL` (treatment-emergent) exists **only in ADAE**. From SDTM `AE` you must
derive it by comparing `AESTDTC` to first dose — and a partial start date makes
that derivation ambiguous, which is exactly why ADAE is preferred.

### LB / ADLB — labs
`LBTESTCD` `LBTEST` `LBCAT` `LBORRES` `LBORRESU` `LBSTRESC` `LBSTRESN`
`LBSTRESU` `LBNRIND` `LBBLFL` `VISIT` `VISITNUM` `LBDTC` `LBDY`

ADLB: `PARAM` `PARAMCD` `AVAL` `AVALC` `BASE` `CHG` `PCHG` `ANRIND` `BNRIND`
`AVISIT` `AVISITN` `ADT` `ADY` `ABLFL`.

- Use **`LBSTRESN`/`AVAL`** (standardised) for anything comparable.
  `LBORRES` is in whatever unit the local lab reported — mixing sites in one
  table with original units produces nonsense.
- `LBSTRESC` can hold non-numeric results like `<0.1` or `NEGATIVE`, so
  `LBSTRESN` is null for those rows. Don't treat null as missing data.
- Labs are the **largest domain by far** — thousands of rows per subject is
  normal. The script shows abnormal + baseline by default for this reason.
- Reference-range flag is `LBNRIND` (SDTM) / `ANRIND` (ADaM): `NORMAL`, `LOW`,
  `HIGH`, sometimes `ABNORMAL`.

### VS / ADVS — vital signs
`VSTESTCD` `VSTEST` `VSORRES` `VSSTRESN` `VSSTRESU` `VSBLFL` `VSPOS`
`VISIT` `VSDTC` `VSDY`

`VSPOS` (SUPINE/STANDING/SITTING) matters: a blood-pressure drop between
supine and standing is orthostatic hypotension, not a treatment effect.
Multiple readings at one visit are normal and legitimate.

### EX / ADEX — exposure
`EXTRT` `EXDOSE` `EXDOSU` `EXDOSFRQ` `EXROUTE` `EXSTDTC` `EXENDTC`

Records are **dosing intervals, not single days** — one row can span weeks.
Dose reductions appear as separate consecutive records.

### CM — concomitant medications
`CMTRT` `CMDECOD` (WHO Drug) `CMINDC` `CMDOSE` `CMROUTE` `CMSTDTC` `CMENDTC`

### MH — medical history
`MHTERM` `MHDECOD` `MHBODSYS` `MHSTDTC` `MHENRF` `MHONGO`

Ongoing conditions have a blank `MHENDTC` plus `MHONGO`/`MHENRF='ONGOING'` —
blank end date does **not** mean resolved.

## SDTM vs ADaM: which to prefer

Prefer **ADaM** when both exist. It carries derived study days, baseline values,
change-from-baseline, analysis flags and treatment-emergent flags that SDTM
leaves for you to compute. The script's `load()` reflects this by trying the
ADaM dataset first.

Prefer **SDTM** when you need verbatim collected values (`AETERM`, `LBORRES`)
or when the ADaM dataset filtered rows out — ADaM analysis datasets are often
subset to a population (`SAFFL='Y'`), so a screen-failure subject may exist in
DM but not ADSL.

Supplemental qualifiers live in `SUPPAE`, `SUPPDM` etc. as name/value pairs
keyed by `IDVAR`/`IDVARVAL`. Non-standard variables a sponsor collected end up
there, so check `supp*.xpt` if an expected field is missing from the parent.

## Adding a new domain section

1. Write `section_xx(ds, usubjid)` in `scripts/profile.py`.
2. Use `load(ds, "adxx", "xx")` so ADaM wins when present.
3. Pull every field through `val()` / `date_val()` with candidate lists —
   `val(r, df, "ADY", "XXDY")` — so a missing variable blanks instead of raising.
4. Return `md_table(headers, rows)`; return `None` when the domain is absent so
   the section is omitted rather than rendered empty.
5. Register it in `SECTIONS` and add the stem to `DOMAIN_ORDER`.
