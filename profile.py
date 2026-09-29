#!/usr/bin/env python3
"""Build a patient profile markdown file from SDTM and/or ADaM .xpt datasets.

Two modes:

  list patients   profile.py --data STUDY_DIR --list-patients
  build profile   profile.py --data STUDY_DIR --patient 1015 --out profile.md

The reader is deliberately tolerant: vendors disagree about filename case,
which domains exist, whether dates are ISO character strings (SDTM `--DTC`)
or numeric SAS dates (ADaM `--DT`), and whether XPORT character columns come
back as `str` or `bytes`. Every accessor goes through `pick()` so a missing
variable degrades to a blank cell instead of a traceback -- a profile that
renders 4 of 6 sections is useful, one that crashes is not.
"""

from __future__ import annotations

import argparse
import datetime as _dt
import os
import re
import sys

SAS_EPOCH = _dt.date(1960, 1, 1)

# Domains rendered, in profile order. Keys are lowercase dataset stems.
# SDTM name first, ADaM equivalent second -- ADaM wins when both exist,
# because it carries derived study days, baselines and analysis flags.
DOMAIN_ORDER = ["dm", "ds", "ex", "ae", "lb", "vs", "cm", "mh"]
ADAM_FOR = {
    "dm": "adsl",
    "ae": "adae",
    "lb": "adlb",
    "vs": "advs",
    "ex": "adex",
    "ds": "adsl",
}


# --------------------------------------------------------------------------
# reading
# --------------------------------------------------------------------------

def read_xpt(path):
    """Read one .xpt into a DataFrame with upper-case columns and str (not bytes) text."""
    try:
        import pandas as pd
    except ImportError:  # pragma: no cover
        sys.exit("pandas is required:  pip install pandas pyreadstat")

    df = None
    errors = []
    # encoding= makes pandas decode character columns for us; on older pandas
    # or unusual XPORT v5 headers this raises, so fall back to pyreadstat.
    for attempt in (
        lambda: pd.read_sas(path, format="xport", encoding="utf-8"),
        lambda: pd.read_sas(path, format="xport"),
    ):
        try:
            df = attempt()
            break
        except Exception as exc:  # noqa: BLE001 - want the next fallback
            errors.append(str(exc))
    if df is None:
        try:
            import pyreadstat

            df, _meta = pyreadstat.read_xport(path)
        except Exception as exc:  # noqa: BLE001
            errors.append(str(exc))
            raise RuntimeError(f"cannot read {path}: {' | '.join(errors)}")

    df.columns = [str(c).upper().strip() for c in df.columns]
    for col in df.columns:
        if df[col].dtype == object:
            df[col] = df[col].map(_clean_text)
    return df


def _clean_text(value):
    if isinstance(value, (bytes, bytearray)):
        return value.decode("utf-8", "replace").strip()
    if isinstance(value, str):
        return value.strip()
    return value


def discover(root):
    """Map dataset stem -> path, searching root and any sdtm/adam subdirectories.

    Filename case varies by vendor (dm.xpt, DM.xpt, Dm.xpt) so match
    case-insensitively. Later hits do not overwrite earlier ones, so a
    top-level dm.xpt beats a copy buried in an archive subfolder.
    """
    found = {}
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if not d.startswith(".")]
        for name in filenames:
            if not name.lower().endswith(".xpt"):
                continue
            stem = os.path.splitext(name)[0].lower()
            found.setdefault(stem, os.path.join(dirpath, name))
    return found


# --------------------------------------------------------------------------
# small helpers
# --------------------------------------------------------------------------

def pick(df, *candidates):
    """First candidate column actually present, else None."""
    for name in candidates:
        if df is not None and name in df.columns:
            return name
    return None


def val(row, df, *candidates, default=""):
    """Scalar from the first present candidate column, blank when missing/NaN."""
    col = pick(df, *candidates)
    if col is None:
        return default
    raw = row.get(col)
    return default if _is_blank(raw) else _fmt_scalar(raw)


def _is_blank(raw):
    if raw is None:
        return True
    if isinstance(raw, str):
        return raw.strip() == ""
    try:
        return bool(raw != raw)  # NaN
    except Exception:  # noqa: BLE001
        return False


# XPORT stores some zeros as a denormalised IBM float that converts to a tiny
# non-zero IEEE double (the CDISC pilot's placebo EXDOSE lands on 5.4e-79).
# Printing it verbatim turns "0 mg" into "5.39761e-79 mg". No real clinical
# measurement is this small, so anything under the threshold displays as 0.
XPORT_ZERO_TOL = 1e-12


def _fmt_scalar(raw):
    if isinstance(raw, float):
        if raw != 0 and abs(raw) < XPORT_ZERO_TOL:
            return "0"
        return str(int(raw)) if raw.is_integer() else f"{raw:g}"
    return str(raw).strip()


def as_date(raw):
    """Normalise SDTM ISO text or ADaM numeric SAS dates to a display string.

    SDTM `--DTC` is ISO 8601 *character* data and legally partial ("2012-07",
    "2012"), so it is returned as-is rather than parsed -- forcing a partial
    date through a parser invents precision that was never collected.
    ADaM `--DT` is numeric days since 1960-01-01.
    """
    if _is_blank(raw):
        return ""
    if isinstance(raw, str):
        return raw.strip()[:10] if re.match(r"^\d{4}", raw.strip()) else raw.strip()
    if isinstance(raw, _dt.datetime):
        return raw.date().isoformat()
    if isinstance(raw, _dt.date):
        return raw.isoformat()
    try:
        return (SAS_EPOCH + _dt.timedelta(days=int(float(raw)))).isoformat()
    except (TypeError, ValueError, OverflowError):
        return _fmt_scalar(raw)


def date_val(row, df, *candidates):
    col = pick(df, *candidates)
    return "" if col is None else as_date(row.get(col))


def md_table(headers, rows, empty="_No records._"):
    """Render a markdown table, dropping columns that are blank for every row."""
    rows = [list(r) for r in rows]
    if not rows:
        return empty
    keep = [i for i, _ in enumerate(headers)
            if any(str(r[i]).strip() for r in rows)]
    if not keep:
        return empty
    head = [headers[i] for i in keep]
    out = ["| " + " | ".join(head) + " |",
           "|" + "|".join("---" for _ in head) + "|"]
    for r in rows:
        cells = [str(r[i]).replace("|", "\\|").replace("\n", " ").strip() for i in keep]
        out.append("| " + " | ".join(cells) + " |")
    return "\n".join(out)


def sort_key(df, row, *candidates):
    """Numeric sort key from the first present study-day/visit column."""
    col = pick(df, *candidates)
    if col is None:
        return 0.0
    raw = row.get(col)
    try:
        return float(raw)
    except (TypeError, ValueError):
        return 0.0


# --------------------------------------------------------------------------
# patient resolution
# --------------------------------------------------------------------------

def subject_frame(datasets):
    """ADSL if present (richer), else DM -- the roster of subjects in the study."""
    for stem in ("adsl", "dm"):
        if stem in datasets:
            return stem, read_xpt(datasets[stem])
    return None, None


def resolve_patient(df, wanted):
    """Match a user-supplied id against USUBJID or SUBJID.

    Users say "1015"; the dataset holds "01-701-1015" because USUBJID is
    STUDYID-SITEID-SUBJID. Try exact USUBJID, then exact SUBJID, then a
    unique suffix/substring match before giving up.
    """
    usubjid = pick(df, "USUBJID")
    if usubjid is None:
        raise SystemExit("no USUBJID column in the subject-level dataset")
    wanted = str(wanted).strip()
    ids = df[usubjid].astype(str).str.strip()

    exact = df[ids == wanted]
    if len(exact):
        return exact.iloc[0][usubjid]

    subjid = pick(df, "SUBJID")
    if subjid is not None:
        hit = df[df[subjid].astype(str).str.strip() == wanted]
        if len(hit) == 1:
            return hit.iloc[0][usubjid]

    loose = df[ids.str.endswith(wanted) | ids.str.contains(re.escape(wanted), na=False)]
    uniq = sorted(set(loose[usubjid].astype(str)))
    if len(uniq) == 1:
        return uniq[0]
    if len(uniq) > 1:
        raise SystemExit(
            f"'{wanted}' matches {len(uniq)} subjects: {', '.join(uniq[:10])}"
            f"{' ...' if len(uniq) > 10 else ''}\nRe-run with a full USUBJID."
        )
    raise SystemExit(f"no subject matching '{wanted}'")


def list_patients(datasets, limit=None):
    stem, df = subject_frame(datasets)
    if df is None:
        raise SystemExit("need adsl.xpt or dm.xpt to list patients")
    usubjid = pick(df, "USUBJID")
    headers = ["USUBJID", "SUBJID", "SITEID", "AGE", "SEX", "ARM", "Completed?"]
    rows = []
    for _, row in df.iterrows():
        rows.append([
            val(row, df, "USUBJID"),
            val(row, df, "SUBJID"),
            val(row, df, "SITEID"),
            val(row, df, "AGE"),
            val(row, df, "SEX"),
            val(row, df, "TRT01A", "TRT01P", "ARM", "ACTARM"),
            val(row, df, "COMP24FL", "COMPLFL", "EOSSTT"),
        ])
    rows.sort(key=lambda r: r[0])
    total = len(rows)
    if limit:
        rows = rows[:limit]
    print(f"{total} subjects in {os.path.basename(datasets[stem])}\n")
    print(md_table(headers, rows))
    if limit and total > limit:
        print(f"\n_...{total - limit} more. Use --limit 0 for all._")


# --------------------------------------------------------------------------
# sections
# --------------------------------------------------------------------------

def section_dm(ds, usubjid):
    df = load(ds, "adsl", "dm")
    if df is None:
        return None
    row = one(df, usubjid)
    if row is None:
        return None
    lines = []
    facts = [
        ("Study", val(row, df, "STUDYID")),
        ("Site", val(row, df, "SITEID")),
        ("Age", " ".join(x for x in [val(row, df, "AGE"), val(row, df, "AGEU")] if x)),
        ("Sex", val(row, df, "SEX")),
        ("Race", val(row, df, "RACE")),
        ("Ethnicity", val(row, df, "ETHNIC")),
        ("Country", val(row, df, "COUNTRY")),
        ("Planned arm", val(row, df, "TRT01P", "ARM")),
        ("Actual arm", val(row, df, "TRT01A", "ACTARM")),
        ("First dose", date_val(row, df, "TRTSDT", "RFXSTDTC", "RFSTDTC")),
        ("Last dose", date_val(row, df, "TRTEDT", "RFXENDTC", "RFENDTC")),
        ("Died", val(row, df, "DTHFL")),
        ("Date of death", date_val(row, df, "DTHDT", "DTHDTC")),
    ]
    lines.append(md_table(["Field", "Value"],
                          [[k, v] for k, v in facts if v]))

    flags = [(f, val(row, df, f)) for f in
             ("SAFFL", "ITTFL", "EFFFL", "RANDFL", "FASFL", "PPROTFL")]
    flags = [(f, v) for f, v in flags if v]
    if flags:
        lines.append("")
        lines.append("**Analysis populations:** " +
                     ", ".join(f"{f}={v}" for f, v in flags))
    return "\n".join(lines)


def section_ds(ds, usubjid):
    df = load(ds, "ds")
    if df is not None:
        rows = []
        for _, r in sorted_rows(df, usubjid, "DSSTDY"):
            rows.append([
                val(r, df, "DSSTDY"),
                date_val(r, df, "DSSTDTC"),
                val(r, df, "EPOCH"),
                val(r, df, "DSCAT"),
                val(r, df, "DSDECOD"),
                val(r, df, "DSTERM"),
            ])
        return md_table(["Day", "Date", "Epoch", "Category", "Decoded", "Term"], rows)

    # No DS domain -- fall back to the disposition variables ADSL carries.
    df = load(ds, "adsl")
    if df is None:
        return None
    row = one(df, usubjid)
    if row is None:
        return None
    facts = [
        ("Completed 24 weeks", val(row, df, "COMP24FL")),
        ("End of study status", val(row, df, "EOSSTT")),
        ("Discontinuation reason", val(row, df, "DCSREAS", "DCREASCD")),
        ("Treatment discontinued", val(row, df, "DCTREAS")),
    ]
    facts = [(k, v) for k, v in facts if v]
    return md_table(["Field", "Value"], [[k, v] for k, v in facts]) if facts else None


def section_ex(ds, usubjid):
    df = load(ds, "adex", "ex")
    if df is None:
        return None
    rows = []
    for _, r in sorted_rows(df, usubjid, "EXSTDY", "ASTDY"):
        rows.append([
            val(r, df, "EXSTDY", "ASTDY"),
            date_val(r, df, "ASTDT", "EXSTDTC"),
            date_val(r, df, "AENDT", "EXENDTC"),
            val(r, df, "EXTRT", "TRTA"),
            " ".join(x for x in [val(r, df, "EXDOSE", "AVAL"),
                                 val(r, df, "EXDOSU", "AVALU")] if x),
            val(r, df, "EXROUTE"),
            val(r, df, "EXDOSFRQ"),
        ])
    return md_table(["Day", "Start", "End", "Treatment", "Dose", "Route", "Frequency"], rows)


def section_ae(ds, usubjid):
    df = load(ds, "adae", "ae")
    if df is None:
        return None
    rows = []
    for _, r in sorted_rows(df, usubjid, "ASTDY", "AESTDY"):
        rows.append([
            val(r, df, "ASTDY", "AESTDY"),
            date_val(r, df, "ASTDT", "AESTDTC"),
            val(r, df, "AENDY", "AEENDY"),
            val(r, df, "AEDECOD", "AETERM"),
            val(r, df, "AEBODSYS", "AESOC"),
            # AESEV (MILD/MODERATE/SEVERE) and AETOXGR (CTCAE 1-5) are
            # alternatives -- studies collect one or the other, not both.
            val(r, df, "ATOXGR", "AETOXGR", "AESEV"),
            val(r, df, "AESER"),
            val(r, df, "AEREL"),
            val(r, df, "AEACN"),
            val(r, df, "AEOUT"),
            val(r, df, "TRTEMFL"),
        ])
    table = md_table(
        ["Day", "Start", "End day", "Event", "Body system",
         "Sev/Grade", "Serious", "Related", "Action", "Outcome", "TE"],
        rows,
    )
    note = ""
    if pick(df, "TRTEMFL") is None and "ae" in ds and "adae" not in ds:
        note = ("\n\n> Read from SDTM `AE`, which has no `TRTEMFL`. "
                "Treatment-emergent status is not flagged here -- compare "
                "`AESTDTC` against first dose to derive it.")
    return table + note


def section_lb(ds, usubjid, all_records=False):
    df = load(ds, "adlb", "lb")
    if df is None:
        return None
    sub = subset(df, usubjid)
    if sub is None or not len(sub):
        return "_No records._"

    # Standardised results (LBSTRESN/AVAL) are the comparable ones; LBORRES is
    # in whatever unit the local lab used. Reference-range flags live in
    # LBNRIND (SDTM) or ANRIND (ADaM).
    flag = pick(df, "ANRIND", "LBNRIND")
    shown, filtered = sub, False
    if not all_records and flag is not None:
        abnormal = sub[~sub[flag].astype(str).str.upper().isin(["NORMAL", "N", "", "NAN"])]
        baseline = pick(df, "ABLFL", "LBBLFL")
        if baseline is not None:
            keep = sub[sub[baseline].astype(str).str.upper() == "Y"]
            abnormal = abnormal.combine_first(keep) if len(keep) else abnormal
        if len(abnormal) and len(abnormal) < len(sub):
            shown, filtered = abnormal, True

    rows = []
    for _, r in sort_frame(shown, df, "ADY", "LBDY", "VISITNUM", "AVISITN"):
        rows.append([
            val(r, df, "ADY", "LBDY"),
            val(r, df, "AVISIT", "VISIT"),
            val(r, df, "PARAM", "LBTEST"),
            val(r, df, "AVAL", "LBSTRESN", "LBSTRESC", "LBORRES"),
            val(r, df, "AVALU", "LBSTRESU", "LBORRESU"),
            val(r, df, "BASE"),
            val(r, df, "CHG"),
            val(r, df, flag or "LBNRIND"),
            val(r, df, "ABLFL", "LBBLFL"),
        ])
    table = md_table(["Day", "Visit", "Test", "Result", "Unit",
                      "Baseline", "Change", "Range", "BL flag"], rows)
    if filtered:
        table += (f"\n\n> Showing {len(shown)} of {len(sub)} lab records "
                  "(abnormal + baseline). Re-run with `--all-labs` for everything.")
    return table


def section_vs(ds, usubjid):
    df = load(ds, "advs", "vs")
    if df is None:
        return None
    rows = []
    for _, r in sorted_rows(df, usubjid, "ADY", "VSDY", "VISITNUM"):
        rows.append([
            val(r, df, "ADY", "VSDY"),
            val(r, df, "AVISIT", "VISIT"),
            val(r, df, "PARAM", "VSTEST"),
            val(r, df, "AVAL", "VSSTRESN", "VSORRES"),
            val(r, df, "AVALU", "VSSTRESU", "VSORRESU"),
            val(r, df, "BASE"),
            val(r, df, "CHG"),
            val(r, df, "VSPOS"),
            val(r, df, "ABLFL", "VSBLFL"),
        ])
    return md_table(["Day", "Visit", "Parameter", "Result", "Unit",
                     "Baseline", "Change", "Position", "BL flag"], rows)


def section_cm(ds, usubjid):
    df = load(ds, "cm")
    if df is None:
        return None
    rows = []
    for _, r in sorted_rows(df, usubjid, "CMSTDY"):
        rows.append([
            val(r, df, "CMSTDY"),
            date_val(r, df, "CMSTDTC"),
            date_val(r, df, "CMENDTC"),
            val(r, df, "CMDECOD", "CMTRT"),
            val(r, df, "CMINDC"),
            val(r, df, "CMDOSE"),
            val(r, df, "CMROUTE"),
        ])
    return md_table(["Day", "Start", "End", "Medication",
                     "Indication", "Dose", "Route"], rows)


def section_mh(ds, usubjid):
    df = load(ds, "mh")
    if df is None:
        return None
    rows = []
    for _, r in sorted_rows(df, usubjid, "MHSTDY"):
        rows.append([
            date_val(r, df, "MHSTDTC"),
            date_val(r, df, "MHENDTC"),
            val(r, df, "MHDECOD", "MHTERM"),
            val(r, df, "MHBODSYS"),
            val(r, df, "MHONGO", "MHENRF"),
        ])
    return md_table(["Start", "End", "Condition", "Body system", "Ongoing"], rows)


SECTIONS = [
    ("dm", "Demographics", section_dm),
    ("ds", "Disposition", section_ds),
    ("ex", "Exposure", section_ex),
    ("ae", "Adverse Events", section_ae),
    ("lb", "Laboratory Results", section_lb),
    ("vs", "Vital Signs", section_vs),
    ("cm", "Concomitant Medications", section_cm),
    ("mh", "Medical History", section_mh),
]


# --------------------------------------------------------------------------
# frame plumbing
# --------------------------------------------------------------------------

_CACHE = {}


def load(datasets, *stems):
    """Read the first available dataset among stems, caching across sections."""
    for stem in stems:
        if stem in datasets:
            if stem not in _CACHE:
                try:
                    _CACHE[stem] = read_xpt(datasets[stem])
                except Exception as exc:  # noqa: BLE001
                    print(f"warning: skipping {stem}.xpt ({exc})", file=sys.stderr)
                    _CACHE[stem] = None
            if _CACHE[stem] is not None:
                return _CACHE[stem]
    return None


def subset(df, usubjid):
    col = pick(df, "USUBJID")
    if col is None:
        return None
    return df[df[col].astype(str).str.strip() == str(usubjid).strip()]


def one(df, usubjid):
    sub = subset(df, usubjid)
    return None if sub is None or not len(sub) else sub.iloc[0]


def sorted_rows(df, usubjid, *day_cols):
    sub = subset(df, usubjid)
    if sub is None or not len(sub):
        return []
    return sort_frame(sub, df, *day_cols)


def sort_frame(sub, df, *day_cols):
    col = pick(df, *day_cols)
    items = list(sub.iterrows())
    if col is not None:
        items.sort(key=lambda kv: sort_key(df, kv[1], col))
    return items


# --------------------------------------------------------------------------
# main
# --------------------------------------------------------------------------

def build(datasets, usubjid, wanted, all_labs=False):
    out = []
    for stem, title, fn in SECTIONS:
        if wanted and stem not in wanted:
            continue
        body = fn(datasets, usubjid, all_labs) if stem == "lb" else fn(datasets, usubjid)
        if body is None:
            continue  # domain absent entirely -- omit rather than print an empty heading
        out.append(f"## {title}")
        out.append("")
        out.append(body)
        out.append("")

    # Credit only the files the sections actually read, which _CACHE records --
    # listing every .xpt in the folder implies sources this profile never touched.
    used = sorted(s for s, df in _CACHE.items() if df is not None)
    src = ", ".join(f"`{s}.xpt`" for s in used) if used else "no datasets"
    head = [f"# Patient Profile: {usubjid}", "",
            f"Generated {_dt.date.today().isoformat()} from {src}", ""]
    return "\n".join(head + out).rstrip() + "\n"


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--data", required=True,
                    help="study directory; sdtm/ and adam/ subfolders are found automatically")
    ap.add_argument("--patient", help="USUBJID or SUBJID; omit to list subjects")
    ap.add_argument("--domains", help="comma list to restrict, e.g. dm,ae,lb")
    ap.add_argument("--out", help="output .md path (default: stdout)")
    ap.add_argument("--list-patients", action="store_true")
    ap.add_argument("--limit", type=int, default=50,
                    help="rows when listing patients; 0 = all")
    ap.add_argument("--all-labs", action="store_true",
                    help="include normal lab results (default: abnormal + baseline)")
    args = ap.parse_args(argv)

    if not os.path.isdir(args.data):
        raise SystemExit(f"not a directory: {args.data}")
    datasets = discover(args.data)
    if not datasets:
        raise SystemExit(f"no .xpt files found under {args.data}")

    if args.list_patients or not args.patient:
        list_patients(datasets, args.limit or None)
        if not args.patient:
            return 0

    stem, roster = subject_frame(datasets)
    if roster is None:
        raise SystemExit("need adsl.xpt or dm.xpt to resolve the patient")
    usubjid = resolve_patient(roster, args.patient)

    wanted = None
    if args.domains:
        wanted = {d.strip().lower() for d in args.domains.split(",") if d.strip()}
        unknown = wanted - {s for s, _, _ in SECTIONS}
        if unknown:
            raise SystemExit(f"unknown domains: {', '.join(sorted(unknown))}")

    md = build(datasets, usubjid, wanted, all_labs=args.all_labs)
    if args.out:
        os.makedirs(os.path.dirname(os.path.abspath(args.out)), exist_ok=True)
        with open(args.out, "w", encoding="utf-8") as fh:
            fh.write(md)
        print(f"wrote {args.out} ({len(md.splitlines())} lines)")
    else:
        sys.stdout.write(md)
    return 0


if __name__ == "__main__":
    sys.exit(main())
