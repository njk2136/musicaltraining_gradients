#!/usr/bin/env python3
"""
Fill the `age` column of the draft subject map from the lab spreadsheet.

Rows are matched on study ID (CONTROL18, MUSIC109, SPORT07, ...): the draft's
`study_id` column vs the spreadsheet's "Subject ID" column. Matching ignores
case, spaces, leading zeros and anything after the number (e.g. "-AC"), so
"Control18", "CONTROL 18" and "CONTROL18-AC" all match CONTROL18.

Ages are read from the MRI age columns and written in years (2 decimals).
Values above 25 are taken as months and divided by 12.

Only the ID and MRI age columns are read; nothing else from the spreadsheet is
used or copied. A backup of the draft is saved before it is changed.

Usage:
  1. In Excel: File > Save As > "CSV UTF-8 (Comma delimited) (.csv)"
  2. python3 fill_ages.py              (fills empty ages only)
     python3 fill_ages.py --overwrite  (replaces ages already in the draft)
  3. python3 draft_subject_map.py --finalize
"""
import argparse
import csv
import re
import shutil
import sys
from collections import defaultdict
from pathlib import Path

# ======================= EDIT =======================
SHEET_CSV  = Path("/Volumes/MusicProject/Longitudinal_study/Behavioral/Summary Spreadsheets/all_data.csv")
DRAFT_FILE = Path("/Users/nickathios/Documents/research/musicaltraining_gradients/scripts/subject_map_DRAFT.tsv")
ID_COLUMN  = "Subject ID"
AGE_COLUMNS = {                 # BIDS session -> spreadsheet column
    "01": "Age Y1 MRI months",
    "03": "Age Y3 MRI months",
    "05": "Age Y5 MRI",
}
# ====================================================


def norm_id(s):
    m = re.search(r"(?i)(control|music|sports?)\D*?0*(\d+)", s or "")
    if not m:
        return None
    arm = m.group(1).lower().rstrip("s")
    return f"{arm}{int(m.group(2))}"


def parse_sheet_id(s):
    """'SPORT10-EM' -> ('sport', 10, 'EM'); initials may be missing."""
    m = re.search(r"(?i)(control|music|sports?)\D*?0*(\d+)\s*-?\s*([A-Za-z]*)", s or "")
    if not m:
        return None
    return m.group(1).lower().rstrip("s"), int(m.group(2)), m.group(3).upper()


def to_years(raw):
    try:
        v = float(str(raw).strip())
    except ValueError:
        return None
    return round(v / 12 if v > 25 else v, 2)


def main():
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--overwrite", action="store_true", help="replace ages already in the draft")
    args = p.parse_args()

    for f in (SHEET_CSV, DRAFT_FILE):
        if not f.is_file():
            sys.exit(f"ERROR: not found: {f}")

    # --- spreadsheet: only the ID and MRI age columns ---
    def clean(h):
        return re.sub(r"\s+", " ", (h or "").replace("\u00a0", " ")).strip().lower()

    raw_text = SHEET_CSV.read_bytes()
    for enc in ("utf-8-sig", "mac_roman", "latin-1"):
        try:
            text = raw_text.decode(enc)
            break
        except UnicodeDecodeError:
            continue
    first = text.splitlines()[0] if text else ""
    delim = max([",", ";", "\t"], key=first.count)
    rows = list(csv.reader(text.splitlines(), delimiter=delim))

    # The header may not be the first row (e.g. a title row above it)
    hdr_i = next((i for i, r in enumerate(rows[:15])
                  if clean(ID_COLUMN) in [clean(h) for h in r]), None)
    if hdr_i is None:
        print(f"ERROR: column {ID_COLUMN!r} not found in the first 15 rows of {SHEET_CSV.name}.")
        print(f"Detected separator: {delim!r}. First cells of the first rows:")
        for r in rows[:3]:
            print("   ", [c[:30] for c in r[:4]])
        sys.exit(1)
    header = [clean(h) for h in rows[hdr_i]]
    id_col = header.index(clean(ID_COLUMN))
    age_col = {}
    for ses, name in AGE_COLUMNS.items():
        if clean(name) not in header:
            close = [rows[hdr_i][i] for i, h in enumerate(header) if "mri" in h]
            sys.exit(f"ERROR: column {name!r} not found. Columns mentioning MRI: {close}")
        age_col[ses] = header.index(clean(name))

    ages, seen, unparsed = {}, defaultdict(int), []
    by_initials = defaultdict(set)   # (arm, cohort, initials) -> study keys, for rows without a study ID
    for r in rows[hdr_i + 1:]:
        if id_col >= len(r) or not r[id_col].strip():
            continue
        key = norm_id(r[id_col])
        if key is None:
            unparsed.append(r[id_col].strip())
            continue
        seen[key] += 1
        arm_, num_, ini_ = parse_sheet_id(r[id_col])
        if ini_:
            by_initials[(arm_, "A" if num_ < 100 else "B", ini_)].add(key)
        for ses, c in age_col.items():
            if c < len(r) and r[c].strip():
                ages[(key, ses)] = r[c].strip()
    dups = sorted(k for k, n in seen.items() if n > 1)
    if dups:
        sys.exit("ERROR: these study IDs appear more than once in the spreadsheet, "
                 "fix them first: " + ", ".join(dups))

    # --- draft ---
    with open(DRAFT_FILE, newline="") as f:
        reader = csv.DictReader(f, delimiter="\t")
        fields = reader.fieldnames
        draft = list(reader)
    if "study_id" not in fields or "age" not in fields:
        sys.exit("ERROR: draft has no study_id/age column; regenerate it with the latest "
                 "draft_subject_map.py first")

    stats = defaultdict(list)
    for r in draft:
        label = f"sub-{r['sub']}_ses-{r['ses']}"
        key = norm_id(r.get("study_id", ""))
        if r["ses"] not in AGE_COLUMNS:
            continue
        if r.get("age", "").strip() and not args.overwrite:
            stats["already had an age (kept)"].append(label)
            continue
        via_initials = False
        if key is None:
            cands = by_initials.get(((r.get("group") or "").lower(), r.get("cohort", ""),
                                     (r.get("initials") or "").upper()), set())
            if len(cands) == 1:
                key = next(iter(cands))
                via_initials = True
            else:
                why = "several spreadsheet IDs share these initials" if cands else "no match"
                stats["no study ID in draft (enter by hand)"].append(f"{label} ({why})")
                continue
        if key not in seen:
            stats["study ID not in spreadsheet"].append(f"{label} ({r['study_id']})")
            continue
        raw = ages.get((key, r["ses"]))
        if raw is None:
            stats["age blank in spreadsheet"].append(f"{label} ({r['study_id']})")
            continue
        yrs = to_years(raw)
        if yrs is None:
            stats["age not a number"].append(f"{label} ({r['study_id']}: {raw!r})")
            continue
        r["age"] = f"{yrs:.2f}"
        stats["filled"].append(label)
        if via_initials:
            stats["filled by matching arm + initials (please verify)"].append(
                f"{label} -> {key.upper()}")

    backup = DRAFT_FILE.with_suffix(".tsv.bak")
    shutil.copy2(DRAFT_FILE, backup)
    with open(DRAFT_FILE, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields, delimiter="\t", lineterminator="\n")
        w.writeheader()
        w.writerows(draft)

    print(f"Draft updated: {DRAFT_FILE}  (backup: {backup.name})")
    for k in ("filled", "filled by matching arm + initials (please verify)",
              "already had an age (kept)", "no study ID in draft (enter by hand)",
              "study ID not in spreadsheet", "age blank in spreadsheet", "age not a number"):
        if stats[k]:
            print(f"\n{len(stats[k]):4d}  {k}")
            if k != "filled" and k != "already had an age (kept)":
                for x in stats[k]:
                    print(f"        {x}")
    if unparsed:
        print(f"\nSpreadsheet IDs that aren't study IDs (ignored): {', '.join(sorted(set(unparsed)))}")

    # --- sanity checks ---
    by_sub = defaultdict(list)
    for r in draft:
        if r.get("age", "").strip():
            try:
                by_sub[r["sub"]].append((r["ses"], float(r["age"])))
            except ValueError:
                pass
    odd = []
    for sub, vals in sorted(by_sub.items()):
        vals.sort()
        for ses, a in vals:
            if not 4 <= a <= 16:
                odd.append(f"sub-{sub}_ses-{ses}: age {a} is outside 4-16 years")
        for (s1, a1), (s2, a2) in zip(vals, vals[1:]):
            if a2 <= a1:
                odd.append(f"sub-{sub}: age does not increase from ses-{s1} ({a1}) to ses-{s2} ({a2})")
    if odd:
        print("\nCheck these:")
        for x in odd:
            print(f"   {x}")
    print("\nNext: python3 draft_subject_map.py --finalize, then python3 makebids.py --all")


if __name__ == "__main__":
    main()
