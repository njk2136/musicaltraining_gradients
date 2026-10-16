#!/usr/bin/env python3
"""
Draft a longitudinal subject map from the DICOM folder layout:

    DICOM_DIR / Group <A|B> / Year <N> / <Control|Music|Sport ...> / <folder>

- "Group A", "Group B" are recruitment cohorts -> `cohort` column.
- The Control / Music / Sport folder is the study arm -> `group` column.
- Folder names come in two styles:
    study-ID style:  CONTROL18-AC, Sport05-JG, MUSIC108-AR Y3
    scan-ID style:   6918AD-AC   (Group A, Year 1 only)
  Study-ID folders are matched across years by cohort + arm + study number.
  Scan-ID folders have no study number, so they are linked to a study ID by
  initials within the same cohort and arm (flagged LINKED_BY_INITIALS).

Initials and folder names are NOT reliable identifiers: verify every row
against the lab's participant records before finalizing.

Decisions you make from the lab records go in OVERRIDES_FILE, not in the
draft, so they survive every rerun. Columns (tab-separated):
  dicom_folder   folder path exactly as in the draft
  action         a study ID such as CONTROL9 (this folder belongs to that child),
                 or "exclude" (never convert this folder)
  note           free text, for your own record

If SUBJECT_MAP already exists, children already in it keep their numbers and
only new children get new numbers, so rerunning this never relabels anyone.

Usage:
  python3 draft_subject_map.py                 # writes DRAFT_FILE
  python3 draft_subject_map.py --finalize      # DRAFT_FILE -> SUBJECT_MAP

Both files contain folder names with initials: keep them on the secure
machine/server only. Never copy them into the BIDS folder or onto the cluster.
"""
import argparse
import csv
import re
import sys
from collections import defaultdict
from pathlib import Path

# ======================= EDIT =======================
DICOM_DIR   = Path("/Volumes/MusicProject/Longitudinal_study/Anatomy/Dicom Files")
PROJECT_DIR    = Path("/Volumes/MusicProject/Longitudinal_study/gradient_analysis_BIDS")
DRAFT_FILE  = Path("/Users/nickathios/Documents/research/musicaltraining_gradients/scripts/subject_map_DRAFT.tsv")
SUBJECT_MAP = Path("/Users/nickathios/Documents/research/musicaltraining_gradients/scripts/subject_map.tsv")
OVERRIDES_FILE = Path("/Users/nickathios/Documents/research/musicaltraining_gradients/scripts/subject_map_overrides.tsv")
# Top-level folders under DICOM_DIR that are not part of the longitudinal sample
IGNORE_FOLDERS = {"Cross Sectional", "Technical Scans"}
IGNORE_YEARS = {7}
# ====================================================

ARMS = ("control", "music", "sport")
DRAFT_COLS = ["dicom_folder", "sub", "ses", "age", "cohort", "group",
              "study_id", "initials", "year", "flag"]
FINAL_COLS = ["dicom_folder", "sub", "ses", "age", "cohort", "group"]


def subdirs(p):
    return sorted(d for d in p.iterdir() if d.is_dir() and not d.name.startswith("."))


def parse_name(name):
    """'CONTROLl116-IS Y3' -> (116, None, 'IS', 'Y3');  'SPORT108IM' -> (108, None, 'IM', '');
    '6918AD-AC' -> (None, 6918, 'AC', '').  The hyphen before the initials is optional."""
    n = name.strip()
    m = re.fullmatch(r"(?i)(?:control|music|sports?)l*(\d+)\s*-?\s*([A-Za-z]+)(.*)", n)
    if m:
        return int(m.group(1)), None, m.group(2).upper(), m.group(3).strip(" _")
    m = re.fullmatch(r"(?i)(\d+)ad\s*-?\s*([A-Za-z]+)(.*)", n)
    if m:
        return None, int(m.group(1)), m.group(2).upper(), m.group(3).strip(" _")
    return None


def read_overrides():
    if not OVERRIDES_FILE.is_file():
        return {}
    out = {}
    with open(OVERRIDES_FILE, newline="") as f:
        for lineno, r in enumerate(csv.DictReader(f, delimiter="\t"), start=2):
            folder = (r.get("dicom_folder") or "").strip("\r\n")
            action = (r.get("action") or "").strip()
            if not folder and not action:
                continue
            if not folder or not action:
                print(f"WARNING: {OVERRIDES_FILE.name} line {lineno} ignored: needs a TAB between "
                      f"folder and action. Got: {folder!r}")
                continue
            if action.lower() != "exclude":
                m = re.fullmatch(r"(?i)(control|music|sport)s?(\d+)", action)
                if not m:
                    sys.exit(f"ERROR in {OVERRIDES_FILE.name}: action must be a study ID "
                             f"like CONTROL9 or 'exclude', got: {action!r}")
                action = (m.group(1).lower(), int(m.group(2)))
            out[folder] = action
    print(f"Applying {len(out)} overrides from {OVERRIDES_FILE}")
    return out


def scan_folders():
    rows, skipped = [], []
    overrides = read_overrides()
    unused = set(overrides)
    for cohort_dir in subdirs(DICOM_DIR):
        if cohort_dir.name in IGNORE_FOLDERS:
            continue
        cohort = re.sub(r"(?i)^group\s*", "", cohort_dir.name).strip()
        for year_dir in subdirs(cohort_dir):
            ym = re.search(r"(?i)year\s*(\d+)", year_dir.name)
            if not ym:
                skipped.append(year_dir)
                continue
            year = int(ym.group(1))
            if year in IGNORE_YEARS:
                continue
            for arm_dir in subdirs(year_dir):
                arm = next((a for a in ARMS if arm_dir.name.lower().startswith(a)), None)
                for scan in subdirs(arm_dir):
                    parsed = parse_name(scan.name)
                    if arm is None or parsed is None:
                        skipped.append(scan)
                        continue
                    sid, scan_no, initials, suffix = parsed
                    folder = str(scan.relative_to(DICOM_DIR))
                    row = dict(dicom_folder=folder, cohort=cohort, group=arm, year=year,
                               sid=sid, scan_no=scan_no, initials=initials,
                               suffix=suffix, flags=[], override=False)
                    ov = overrides.get(folder)
                    if ov is not None:
                        unused.discard(folder)
                        if ov == "exclude" or str(ov).lower() == "exclude":
                            continue
                        row.update(group=ov[0], sid=ov[1], override=True)
                        row["flags"].append("OVERRIDE")
                    rows.append(row)
    for folder in sorted(unused):
        print(f"WARNING: override folder not found on disk: {folder!r}")
    return rows, skipped


def assign_keys(rows):
    """Give each row a child key; link scan-ID rows to study IDs by initials."""
    initials_to_sid = defaultdict(set)
    sid_initials = defaultdict(set)
    for r in rows:
        if r["sid"] is not None and not r["override"]:
            base = (r["cohort"], r["group"], r["sid"])
            initials_to_sid[(r["cohort"], r["group"], r["initials"])].add(base)
            sid_initials[base].add(r["initials"])

    for r in rows:
        if r["sid"] is not None:
            r["key"] = (r["cohort"], r["group"], r["sid"])
            if len(sid_initials[r["key"]]) > 1:
                r["flags"].append("INITIALS_DIFFER_FOR_SAME_ID")
        else:
            cands = initials_to_sid[(r["cohort"], r["group"], r["initials"])]
            if len(cands) == 1:
                r["key"] = next(iter(cands))
                r["flags"].append("LINKED_BY_INITIALS")
            else:
                r["key"] = (r["cohort"], r["group"], "init-" + r["initials"])
                if len(cands) > 1:
                    r["flags"].append("SEVERAL_IDS_SHARE_INITIALS")

        if r["suffix"] and not re.fullmatch(rf"(?i)y{r['year']}", r["suffix"]):
            r["flags"].append(f"NAME_SUFFIX:{r['suffix']}")
        if r["dicom_folder"] != r["dicom_folder"].strip() or \
           Path(r["dicom_folder"]).name != Path(r["dicom_folder"]).name.strip():
            r["flags"].append("TRAILING_SPACE_IN_FOLDER_NAME")

    arms_for = defaultdict(set)
    for r in rows:
        if r["sid"] is not None:
            arms_for[(r["cohort"], r["sid"], r["initials"])].add(r["group"])
    for r in rows:
        if r["sid"] is not None and len(arms_for[(r["cohort"], r["sid"], r["initials"])]) > 1:
            r["flags"].append("SAME_ID_AND_INITIALS_IN_OTHER_ARM")

    per_visit = defaultdict(list)
    for r in rows:
        per_visit[(r["key"], r["year"])].append(r)
    for visit in per_visit.values():
        if len(visit) > 1:
            for r in visit:
                r["flags"].append("TWO_FOLDERS_SAME_VISIT")


def number_children(rows):
    existing = {}
    if SUBJECT_MAP.is_file():
        with open(SUBJECT_MAP, newline="") as f:
            existing = {r["dicom_folder"]: r["sub"] for r in csv.DictReader(f, delimiter="\t")}
        print(f"Reusing subject numbers from {SUBJECT_MAP} ({len(existing)} rows)")
    sub_of = {}
    for r in rows:
        if r["dicom_folder"] in existing:
            sub_of.setdefault(r["key"], existing[r["dicom_folder"]])
    used = [int(v) for v in list(sub_of.values()) + list(existing.values()) if v.isdigit()]
    nxt = max(used, default=0) + 1

    def order(k):   # cohort, arm, study number (scan-ID-only children last)
        return (k[0], k[1], (0, k[2]) if isinstance(k[2], int) else (1, k[2]))
    for k in sorted({r["key"] for r in rows}, key=order):
        if k not in sub_of:
            sub_of[k] = f"{nxt:03d}"
            nxt += 1
    for r in rows:
        r["sub"] = sub_of[r["key"]]
    return len(sub_of)


def draft():
    if not DICOM_DIR.is_dir():
        sys.exit(f"ERROR: DICOM_DIR not found: {DICOM_DIR}")
    rows, skipped = scan_folders()
    if not rows:
        sys.exit("ERROR: no scan folders found; check the layout described at the top")
    assign_keys(rows)
    n_children = number_children(rows)

    for r in rows:
        k = r["key"][2]
        r.update(ses=f"{r['year']:02d}", age="",
                 study_id=f"{r['group'].upper()}{k}" if isinstance(k, int) else "",
                 flag=";".join(r["flags"]))
    rows.sort(key=lambda r: (r["sub"], r["ses"], r["dicom_folder"]))

    DRAFT_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(DRAFT_FILE, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=DRAFT_COLS, delimiter="\t",
                           extrasaction="ignore", lineterminator="\n")
        w.writeheader()
        w.writerows(rows)

    counts = defaultdict(int)
    for r in rows:
        for fl in r["flags"]:
            counts[fl.split(":")[0]] += 1
    print(f"Found {len(rows)} scan folders -> {n_children} proposed children")
    for fl, n in sorted(counts.items()):
        print(f"   {n:4d} rows  {fl}")
    if skipped:
        print(f"{len(skipped)} folders did not match the expected layout and were skipped:")
        for s in skipped[:10]:
            print(f"   {s.relative_to(DICOM_DIR)}")
    print(f"Draft written to {DRAFT_FILE}")


def finalize():
    if not DRAFT_FILE.is_file():
        sys.exit(f"ERROR: draft not found: {DRAFT_FILE}")
    with open(DRAFT_FILE, newline="") as f:
        rows = [r for r in csv.DictReader(f, delimiter="\t") if (r.get("sub") or "").strip()]
    seen = set()
    for r in rows:
        key = (r["sub"].strip(), r["ses"].strip())
        if key in seen:
            sys.exit(f"ERROR: sub-{key[0]} ses-{key[1]} appears twice; "
                     "delete the row you don't want to convert, then rerun")
        seen.add(key)
    with open(SUBJECT_MAP, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=FINAL_COLS, delimiter="\t",
                           extrasaction="ignore", lineterminator="\n")
        w.writeheader()
        w.writerows(rows)
    print(f"Wrote {len(rows)} rows to {SUBJECT_MAP}")


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--finalize", action="store_true",
                   help="convert the verified draft into the subject map used by makebids.py")
    args = p.parse_args()
    finalize() if args.finalize else draft()
