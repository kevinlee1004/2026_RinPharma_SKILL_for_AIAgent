#!/usr/bin/env python3
"""disp_analysis.py -- Disposition analysis report from SDTM DS.

Reads an SDTM DS (Disposition) .xpt dataset and writes a study-level
disposition report in markdown. No patient-level listing is produced:
this report is about the study, not about individual subjects.

Usage:
    python disp_analysis.py --data <ds.xpt | study dir> [--out disp_analysis.md]

Requires pandas. pyreadstat is used as a fallback reader for files pandas
rejects (malformed XPORT headers are common in vendor transfers).

The numbers this produces are intended to match scripts/disp_analysis.R
exactly -- same derivation rules, same denominators, same section order.
"""

import argparse
import os
import sys
from datetime import datetime

import pandas as pd


# --- reading -----------------------------------------------------------------

def resolve_ds(path):
    """Accept either ds.xpt itself or a directory to search for it.

    Filename case is not significant across platforms and studies commonly
    nest their data under sdtm/, so walk the tree rather than guessing.
    """
    if not os.path.exists(path):
        sys.exit(f"path not found: {path}")
    if os.path.isfile(path):
        return path
    hits = []
    for root, _dirs, files in os.walk(path):
        hits += [os.path.join(root, f) for f in files if f.lower() == "ds.xpt"]
    if not hits:
        sys.exit(f"no ds.xpt found under directory: {path}")
    hits.sort()
    if len(hits) > 1:
        print(f"note: multiple ds.xpt found, using {hits[0]}", file=sys.stderr)
    return hits[0]


def read_xpt(path):
    """Read an XPORT file, decoding the byte strings pandas returns."""
    try:
        df = pd.read_sas(path, format="xport", encoding="latin-1")
    except Exception as exc:  # noqa: BLE001 - fall back rather than fail the run
        try:
            import pyreadstat
        except ImportError:
            sys.exit(f"could not read {path}: {exc}\n"
                     f"install pyreadstat to enable the fallback reader")
        df, _meta = pyreadstat.read_xport(path)
    for col in df.columns:
        if df[col].dtype == object:
            df[col] = df[col].map(
                lambda v: v.decode("latin-1") if isinstance(v, bytes) else v
            )
    return df


# --- formatting --------------------------------------------------------------

def chr_(df, name):
    """Column as clean strings; missing becomes '' so comparisons are safe."""
    if name not in df.columns:
        return pd.Series([""] * len(df), index=df.index, dtype=object)
    return df[name].astype("string").fillna("").astype(str).str.strip()


def pct(n, d):
    return f"{100 * n / d:.1f}%" if d > 0 else "-"


def md_table(rows, header):
    """rows: list of tuples already stringified."""
    esc = lambda v: str(v).replace("|", "\\|")  # noqa: E731
    out = ["| " + " | ".join(esc(h) for h in header) + " |",
           "|" + "|".join("---" for _ in header) + "|"]
    out += ["| " + " | ".join(esc(c) for c in r) + " |" for r in rows]
    return out


# --- main --------------------------------------------------------------------

def main():
    ap = argparse.ArgumentParser(description="Disposition analysis from SDTM DS")
    ap.add_argument("data_pos", nargs="?", help="ds.xpt or a study directory")
    ap.add_argument("--data", "-d", dest="data", help="ds.xpt or a study directory")
    ap.add_argument("--out", "-o", default="disp_analysis.md", help="output .md path")
    args = ap.parse_args()

    src = args.data or args.data_pos
    if not src:
        ap.error("need --data pointing at ds.xpt or a study directory containing it")

    ds_path = resolve_ds(src)
    ds = read_xpt(ds_path)

    missing = [v for v in ("USUBJID", "DSDECOD") if v not in ds.columns]
    if missing:
        sys.exit("DS is missing required variable(s): " + ", ".join(missing))

    usubjid = chr_(ds, "USUBJID")

    # DSCAT == "DISPOSITION EVENT" carries the protocol disposition. The other
    # records (final lab visit, final retrieval visit, protocol milestones) are
    # follow-up contacts -- counting them as statuses inflates every denominator.
    if "DSCAT" in ds.columns:
        is_disp = chr_(ds, "DSCAT") == "DISPOSITION EVENT"
    else:
        is_disp = pd.Series([True] * len(ds), index=ds.index)
    if not is_disp.any():
        print("note: no DSCAT == 'DISPOSITION EVENT' records; "
              "treating all DS records as dispositions", file=sys.stderr)
        is_disp = pd.Series([True] * len(ds), index=ds.index)

    disp = ds[is_disp].copy()
    other = ds[~is_disp].copy()

    # One disposition per subject is expected. Where a subject has more, keep the
    # last by DSSEQ -- the final disposition is the one that describes the outcome.
    disp["_usubjid"] = chr_(disp, "USUBJID")
    disp["_seq"] = (pd.to_numeric(disp["DSSEQ"], errors="coerce")
                    if "DSSEQ" in disp.columns else range(len(disp)))
    disp = disp.sort_values(["_usubjid", "_seq"], kind="mergesort")
    n_disp_records = len(disp)
    disp = disp.drop_duplicates("_usubjid", keep="last")
    n_dup = n_disp_records - len(disp)

    decod = chr_(disp, "DSDECOD")
    is_sf = decod == "SCREEN FAILURE"
    is_comp = decod == "COMPLETED"
    status = pd.Series("Discontinued", index=disp.index)
    status[is_comp] = "Completed"
    status[is_sf] = "Screen Failure"

    n_all = len(disp)
    n_enrolled = int((~is_sf).sum())
    n_comp = int(is_comp.sum())
    n_disc = int((status == "Discontinued").sum())
    n_sf = int(is_sf.sum())

    study = ", ".join(sorted(set(chr_(ds, "STUDYID")) - {""})) or "(STUDYID not in dataset)"

    lines = [
        "# Disposition Analysis",
        "",
        f"**Study:** {study}",
        f"**Source dataset:** `{ds_path}` (SDTM DS -- Disposition)",
        f"**Generated:** {datetime.now():%Y-%m-%d %H:%M:%S} by `disp_analysis.py`",
        "",
        "## 1. Overview",
        "",
        f"- Subjects in DS: **{usubjid.nunique()}**",
        f"- DS records read: **{len(ds)}**",
        f"- Disposition-event records: **{n_disp_records}**",
        f"- Other-event records (follow-up visits, milestones): **{len(other)}**",
        "",
    ]

    # --- 2. status summary ---------------------------------------------------
    rows = [(s, int((status == s).sum()), pct(int((status == s).sum()), n_all))
            for s in ("Completed", "Discontinued", "Screen Failure")]
    rows.append(("**Total**", n_all, pct(n_all, n_all)))

    lines += ["## 2. Status Summary", ""]
    lines += md_table(rows, ("Status", "N", "% of All"))
    lines += [
        "",
        f"Excluding the {n_sf} screen failure(s), **{n_enrolled}** subject(s) entered "
        f"the study: **{n_comp}** completed ({pct(n_comp, n_enrolled)} of enrolled) "
        f"and **{n_disc}** discontinued ({pct(n_disc, n_enrolled)} of enrolled).",
        "",
    ]

    # --- 3. reason for discontinuation --------------------------------------
    lines += ["## 3. Reason for Discontinuation", ""]
    if n_disc == 0:
        lines += ["No subject discontinued: every disposition is COMPLETED or "
                  "SCREEN FAILURE.", ""]
    else:
        disc_decod = decod[status == "Discontinued"]
        counts = disc_decod.value_counts()
        counts = counts.sort_values(ascending=False, kind="mergesort")
        rows = [(r, int(n), pct(int(n), n_disc), pct(int(n), n_enrolled))
                for r, n in counts.items()]
        rows.append(("**Total discontinued**", n_disc, pct(n_disc, n_disc),
                     pct(n_disc, n_enrolled)))
        lines += [
            f"Counts are subjects, not records; `% of Enrolled` uses the "
            f"{n_enrolled} subject(s) who passed screening.",
            "",
        ]
        lines += md_table(rows, ("Reason (DSDECOD)", "N", "% of Discontinued",
                                 "% of Enrolled"))
        lines += [""]

    # --- 4. data notes ------------------------------------------------------
    no_disp = sorted(set(usubjid) - set(disp["_usubjid"]))

    lines += [
        "## 4. Data Notes",
        "",
        '- Status is derived from `DSDECOD` on records where `DSCAT = "DISPOSITION EVENT"`:',
        "  `COMPLETED` -> Completed, `SCREEN FAILURE` -> Screen Failure, every other "
        "term -> Discontinued.",
    ]
    if no_disp:
        shown = ", ".join(no_disp[:10]) + (", ..." if len(no_disp) > 10 else "")
        lines.append(f"- Subjects with a disposition record: **{n_all}**; "
                     f"**{len(no_disp)}** subject(s) appear in DS with no disposition "
                     f"event ({shown})")
    else:
        lines.append(f"- Subjects with a disposition record: **{n_all}**; "
                     f"every subject in DS has one.")
    if n_dup > 0:
        lines.append(f"- **{n_dup}** extra disposition record(s) were found beyond one "
                     f"per subject; the last by `DSSEQ` was kept.")
    else:
        lines.append("- Exactly one disposition record per subject -- no tie-breaking "
                     "was needed.")
    if len(other) > 0:
        oc = chr_(other, "DSDECOD").value_counts()
        oc = oc.sort_values(ascending=False, kind="mergesort")
        lines.append("- Other-event records by `DSDECOD` (follow-up contacts, not "
                     "statuses):")
        lines += [f"  - {r}: {int(n)} record(s)" for r, n in oc.items()]
    lines += [
        "- Screen failures are reported separately rather than folded into the "
        "discontinuation reasons, since they never entered the treatment period.",
        "- This report is study-level. For one subject's disposition history, read "
        "that subject's DS records directly.",
        "",
    ]

    with open(args.out, "w") as fh:
        fh.write("\n".join(lines) + "\n")

    print(f"Wrote {args.out} -- {n_all} subjects, {n_comp} completed, "
          f"{n_disc} discontinued, {n_sf} screen failures")


if __name__ == "__main__":
    main()
