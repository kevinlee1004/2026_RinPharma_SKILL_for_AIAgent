---
name: patient-profile
description: Generate a per-patient clinical profile markdown file from SDTM and/or ADaM .xpt datasets. Use this skill whenever the user wants to look at, summarize, review, or write up the data for an individual trial subject — demographics, disposition, adverse events, labs, vital signs, exposure, concomitant medications, medical history — from a study data folder. Trigger on requests like "make a patient profile", "what happened to subject 1015", "summarize this patient's AEs and labs", "profile the patients in this SDTM folder", "which patients are in this study", or any mention of USUBJID, SUBJID, ADSL, ADAE, ADLB, SDTM, or ADaM alongside a request about one subject. Also trigger when the user gives a study directory and a patient number without saying the word "profile". The skill requires the study data location as input up front and asks for the patient number if it wasn't supplied. Do NOT trigger for study-level or population-level analysis (summary tables, TLFs, incidence rates across arms) — this skill is about one patient at a time.
---

# Patient profile from SDTM / ADaM

Produces a markdown profile for one subject, one `##` section per domain, by
reading `.xpt` datasets straight from a study folder.

Paths below are relative to this skill's directory.

## Input

Collect these from the user **before doing any processing**. Do not guess a
study folder and do not profile a subject the user did not name.

| Input | Required | Notes |
|---|---|---|
| Study data location | **Yes** | The study directory containing `.xpt` files. Any `sdtm/` and `adam/` subfolders are found by walking the tree, so one path usually covers both. If the user gave separate SDTM and ADaM paths, pass their common parent or run once per folder. |
| Patient number | Yes | Bare `SUBJID` (`1015`) or full `USUBJID` (`01-701-1015`). If not given, do step 2 and ask which subject the user want. |
| Domains | Yes | Comma list from `dm ds ex ae lb vs cm mh`. If not given, ask the user which domains they want to see (or confirm "everything available") before running step 4. |
| Output file path | No | Defaults to `profile.md` in the working directory. |

If the study location is missing, ask for it and stop there — the rest of the
process cannot start without it. Likewise, if the user hasn't said which
domains they want, ask before generating the profile — do not silently default
to everything available.

## Output

A single markdown file: one `##` section per domain, in the order
`dm` `ds` `ex` `ae` `lb` `vs` `cm` `mh`, each holding a table of that subject's
records. A domain with no dataset in the folder is omitted entirely rather than
printed as an empty heading. Report back to the user which sections came out
populated and name any requested domain that was absent from the data.

## Process

### Step 1 — identify the input

Confirm the study directory, and check it actually holds `.xpt` files. If the
user didn't give a location, ask for it and stop — nothing else in this
process can run without it. Filename case is not significant (`dm.xpt`,
`DM.xpt`). Note whether `adam/` is present: ADaM datasets give you `ADY`,
`TRTEMFL` and actual-arm variables that SDTM alone does not.

### Step 2 — identify the patient number

If the user did not give one, read `adsl.xpt` (preferred) or `dm.xpt` and print
the full subject roster — `USUBJID`, `SUBJID`, site, age, sex, arm, completion
— for every subject in the dataset, not a truncated sample. Show that list to
the user and ask which subject they want. Stop until they answer; do not pick
one for them.

```bash
python scripts/profile.py --data /path/to/study --list-patients --limit 0
```

`--limit 0` disables the script's default 50-row cap so the full roster is
shown; without it, studies with more than 50 subjects get silently truncated.

Ambiguous input must fail loudly with the candidates listed rather than
silently profiling the wrong person — `SUBJID` repeats across sites, so `1015`
can match several people.

### Step 3 — read the patient's data from the `.xpt` files

`scripts/profile.py` is the tool for this. Run it rather than writing fresh
pandas code — the awkward parts (XPORT byte strings, partial ISO dates,
`USUBJID` vs `SUBJID`, ADaM-vs-SDTM precedence, absent domains) are already
handled, and re-deriving them per request reintroduces bugs that are easy to
make and hard to notice.

Requires `pandas` is a fallback reader for files pandas rejects:  

If the study needs something the script does not yet cover — a domain with no
section, or a sponsor-specific variable name — write the Python for it *into
the script* as a new `section_xx()` function (see **Extending it**), so the
next request benefits too.

### Step 4 — create the `.md` file

If the user hasn't already told you which domains they want (see **Input**),
ask now — offer the available list (`dm ds ex ae lb vs cm mh`) and let them
pick specific ones or confirm they want everything. Then pass their choice
with `--domains`:

```bash
python scripts/profile.py --data /path/to/study --patient 1015 \
  --domains dm,ds,ae,lb,vs --out profile.md
```

Only omit `--domains` (which pulls in everything available) if the user
explicitly asked for the full profile:

```bash
python scripts/profile.py --data /path/to/study --patient 1015 --out profile.md
```

Then open the generated file before handing it over. Two failure modes look
like success: a profile where every table says `_No records._` means the
patient matched but the domains didn't load, and a profile missing the section
the user cared about means that domain's file wasn't in the folder.

## Extending it

For a domain with no section yet, or sponsor-specific variables, read
`references/domains.md` — it has the per-domain variable lists, the
SDTM-vs-ADaM tradeoff, and the recipe for adding a `section_xx()` function.
Add the section to the script rather than writing one-off code, so the next
request benefits too.

## Rules

These are properties of CDISC data, not of the script, and they cause wrong
numbers rather than errors — which makes them worth knowing before you trust a
profile.

- **There is no study Day 0.** Day 1 is first dose, the day before is Day −1.
  Computing day as a date difference is off by one for every post-baseline
  record. Use the sponsor's `--DY`/`ADY` variable, which the script does.
- **SDTM dates are character, and legally partial.** `AESTDTC` may be
  `2012-07` or just `2012`. The script passes ISO text through unparsed;
  forcing it to `2012-07-01` invents a precision that was never collected.
  ADaM `--DT` variables are numeric days since 1960-01-01 instead.
- **Labs default to abnormal + baseline.** A full lab listing for one subject
  runs to hundreds or thousands of rows and buries everything else. Pass
  `--all-labs` when the user genuinely wants all of it.
- **Use standardized lab results, not original.** `LBSTRESN`/`AVAL` are
  comparable across sites; `LBORRES` is in the local lab's units. Also,
  `LBSTRESC` holds non-numeric results (`<0.1`, `NEGATIVE`) for which
  `LBSTRESN` is null — null there is not missing data.
- **Severity is `AESEV` *or* `AETOXGR`, never both.** MILD/MODERATE/SEVERE vs
  CTCAE grade 1–5; oncology studies use the grade. The script shows whichever
  exists in one column.
- **`TRTEMFL` only exists in ADAE.** Profiles built from SDTM `AE` cannot flag
  treatment-emergent events, and the script prints a note saying so.
- **`ARM` is planned, `ACTARM`/`TRT01A` is actual.** They differ for
  mis-randomised subjects; a safety profile should reflect the actual arm.
- **ADaM datasets are often population-subset.** ADSL is frequently filtered
  to `SAFFL='Y'`, so a screen-failure subject can exist in DM and be absent
  from ADSL. If a patient isn't found, check DM before concluding the id is wrong.
- **A blank `MHENDTC` does not mean resolved** — check `MHONGO`/`MHENRF`.
- **Multiple DS records per subject are normal**, one per epoch plus
  milestones. `DSCAT` distinguishes a real discontinuation from a
  `PROTOCOL MILESTONE`.
- Do not install opensource package.  Use the existing packages. 

## Troubleshooting

| Symptom | Cause and fix |
|---|---|
| `no .xpt files found under <dir>` | Pointed at a parent that doesn't contain the data, or the files are `.sas7bdat`. This script reads XPORT only. |
| `'1015' matches N subjects` | `SUBJID` repeats across sites. Re-run with the full `USUBJID` from `--list-patients`. |
| `need adsl.xpt or dm.xpt to list patients` | No subject-level dataset in the folder. Patient resolution requires one. |
| `warning: skipping lb.xpt (...)` on stderr | That one file failed to read; the rest of the profile still builds. Usually a malformed XPORT header — `pip install pyreadstat` to enable the fallback reader. |
| Every table reads `_No records._` | The `USUBJID` resolved from ADSL/DM doesn't appear in the other domains — often a study where domains use different id formatting. Check `USUBJID` values in one domain directly. |
| Text cells show `b'WHITE'` | Byte strings leaked through. The script decodes these; if you see it, custom code bypassed `read_xpt()`. |
