#!/usr/bin/env python3
"""
DICOM -> BIDS conversion for the new pediatric resting-state study.

Steps per subject/session:
  1. Convert DICOMs with dcm2bids v3 (installed locally, e.g. in a conda env)
  2. Delete dcm2bids' temporary folder for that subject (it holds
     non-defaced images named with the original DICOM folder name)
  3. Fill in EchoTime1/EchoTime2 in the phasediff sidecar if missing
     and, if a session has several T1w runs, keep only one (see T1W_KEEP)
  4. Report the number of volumes in each BOLD run; move incomplete runs
     out of the BIDS folder and remove them from field-map IntendedFor
  5. Back up the original anatomical images, then deface them in place

Subject IDs come from a fixed mapping file (SUBJECT_MAP), never from list
position, so running a subset or adding new subjects cannot relabel anyone.

SUBJECT_MAP columns (tab-separated):
  dicom_folder  path below DICOM_DIR for one child at one visit   (required)
  sub           BIDS subject label, the same at every visit        (required)
  ses           BIDS session label, e.g. 01 for Year 1             (required for longitudinal)
  age           age in years at that visit, e.g. 6.4               (optional -> sessions.tsv)
  cohort        recruitment cohort, e.g. A or B                    (optional -> participants.tsv)
  group         experimental group, if any                         (optional -> participants.tsv)
Never put names, initials, or dates in the age/group columns.

Usage:
  python3 makebids.py --all --dry-run       # show what would happen
  python3 makebids.py --all
  python3 makebids.py --subjects 001 002
  python3 makebids.py --subjects 001 --overwrite   # reconvert from scratch
  python3 makebids.py --all --recheck-volumes --dry-run
      # apply EXPECTED_VOLUMES to sessions already converted, without reconverting
  python3 makebids.py --all --stage-dir /Users/me/dcm_stage
      # copy each visit's DICOMs to a local folder first, convert from there,
      # then delete the local copy (much faster when DICOMs are on a network drive)
"""
import argparse
import csv
import gzip
import json
import re
import shlex
import shutil
import struct
import subprocess
import sys
import time
from pathlib import Path

# ======================= EDIT FOR THE NEW STUDY =======================
PROJECT_DIR    = Path("/Volumes/MusicProject/Longitudinal_study/gradient_analysis_BIDS")
DICOM_DIR      = Path("/Volumes/MusicProject/Longitudinal_study/Anatomy/Dicom Files")
BIDS_DIR       = Path("/Users/nickathios/Documents/research/musicaltraining_gradients/raw_bids")
CONFIG_FILE    = Path("/Volumes/MusicProject/Longitudinal_study/gradient_analysis_BIDS/dcm2bids_config.json")
SUBJECT_MAP = Path("/Users/nickathios/Documents/research/musicaltraining_gradients/scripts/subject_map.tsv")
NONDEFACED_DIR = PROJECT_DIR / "nondefaced_anat"   # original anatomicals; keep access restricted
EXCLUDED_DIR   = PROJECT_DIR / "excluded_runs"     # incomplete BOLD runs are moved here
DONE_DIR       = PROJECT_DIR / ".conversion_done"  # one marker per fully finished session

# Expected number of volumes per task label. Runs with fewer volumes are
# moved to EXCLUDED_DIR. Use None to only report volume counts.
EXPECTED_VOLUMES = {"rest": 60}     # floor that removes aborted fragments; final cutoff comes later

# Which T1w to keep when a session has more than one (e.g. a repeat after motion):
#   "last" = keep the final run, move earlier runs to EXCLUDED_DIR
#   "all"  = keep every run (fMRIPrep will average them)
T1W_KEEP = "last"

# Defacing command run on the host; {src} = original, {dst} = output.
# pydeface needs FSL installed and `pip install pydeface` in the same conda env.
DEFACE_CMD = "pydeface {src} --outfile {dst} --force"
DEFACE_SUFFIXES = ("_T1w.nii.gz", "_T2w.nii.gz")
# =======================================================================

BOLD_SIDECARS = ("_bold.nii.gz", "_bold.json", "_sbref.nii.gz", "_sbref.json")


def run(cmd, dry_run):
    cmd = [str(c) for c in cmd]
    print("    $ " + " ".join(shlex.quote(c) for c in cmd))
    if dry_run:
        return 0
    return subprocess.run(cmd).returncode


def out_dir(sub, ses):
    d = BIDS_DIR / f"sub-{sub}"
    return d / f"ses-{ses}" if ses else d


def read_subject_map():
    """Read dicom_folder / sub / (optional) ses columns from SUBJECT_MAP."""
    if not SUBJECT_MAP.is_file():
        sys.exit(f"ERROR: subject map not found: {SUBJECT_MAP}")
    rows, seen = [], set()
    with open(SUBJECT_MAP, newline="") as f:
        for r in csv.DictReader(f, delimiter="\t"):
            # Keep dicom_folder exactly as written: some folder names end in a space
            r = {(k or "").strip(): ((v or "").strip("\r\n") if (k or "").strip() == "dicom_folder"
                                     else (v or "").strip()) for k, v in r.items()}
            if not r.get("dicom_folder") or not r.get("sub"):
                continue
            r["sub"] = r["sub"][4:] if r["sub"].startswith("sub-") else r["sub"]
            r["ses"] = r.get("ses", "")
            r["ses"] = r["ses"][4:] if r["ses"].startswith("ses-") else r["ses"]
            key = (r["sub"], r["ses"])
            if key in seen:
                sys.exit(f"ERROR: duplicate sub/ses in subject map: {key}")
            seen.add(key)
            rows.append(r)
    return rows


def n_volumes(path):
    """Number of volumes from a NIfTI-1 header (no FSL or nibabel needed)."""
    opener = gzip.open if path.suffix == ".gz" else open
    with opener(path, "rb") as f:
        hdr = f.read(348)
    for endian in "<>":
        if struct.unpack(endian + "i", hdr[:4])[0] == 348:
            dims = struct.unpack(endian + "8h", hdr[40:56])
            return dims[4] if dims[0] >= 4 else 1
    raise ValueError(f"not a NIfTI-1 file: {path}")


def marker(row):
    return DONE_DIR / (f"sub-{row['sub']}" + (f"_ses-{row['ses']}" if row["ses"] else ""))


def convert(row, args):
    """Returns "done" (already finished earlier), True (converted now) or False (failed)."""
    sub, ses = row["sub"], row["ses"]
    src = DICOM_DIR / row["dicom_folder"]
    dst = out_dir(sub, ses)
    if not src.is_dir():
        print(f"  ERROR: DICOM folder not found: {src}")
        return False
    if marker(row).exists() and not args.overwrite:
        print(f"  Already converted ({dst}); skipping. Use --overwrite to redo.")
        return "done"
    redo = args.overwrite or dst.exists()
    if dst.exists() and not args.overwrite:
        print("  Found output from an unfinished earlier run; reconverting this session")

    if redo:
        # A reconverted session must be defaced again, so drop its old backup.
        backup = NONDEFACED_DIR / dst.relative_to(BIDS_DIR)
        if backup.exists() and not args.dry_run:
            shutil.rmtree(backup)

    cmd = ["dcm2bids", "-d", src, "-p", sub, "-c", CONFIG_FILE, "-o", BIDS_DIR]
    if ses:
        cmd += ["-s", ses]
    if redo:
        cmd += ["--clobber", "--force_dcm2bids"]

    if not args.dry_run:
        BIDS_DIR.mkdir(parents=True, exist_ok=True)

    staged = None
    if args.stage_dir:
        staged = Path(args.stage_dir) / (f"sub-{sub}" + (f"_ses-{ses}" if ses else ""))
        if staged.exists() and not args.dry_run:
            shutil.rmtree(staged)
        t0 = time.monotonic()
        print(f"  Copying DICOMs to local staging folder {staged}")
        ok = True
        if shutil.which("rsync"):
            ok = run(["rsync", "-a", f"{src}/", f"{staged}/"], args.dry_run) == 0
        elif not args.dry_run:
            try:
                shutil.copytree(src, staged)
            except OSError as e:
                print(f"  {e}")
                ok = False
        if not ok:
            print("  ERROR: copying DICOMs failed")
            if staged.exists():
                shutil.rmtree(staged)
            return False
        print(f"  Copy took {time.monotonic() - t0:.0f} s")
        cmd[cmd.index(src)] = staged

    t0 = time.monotonic()
    try:
        rc = run(cmd, args.dry_run)
    finally:
        if staged is not None and staged.exists() and not args.dry_run:
            shutil.rmtree(staged)
            print(f"  Deleted local DICOM copy {staged}")
    print(f"  Conversion took {time.monotonic() - t0:.0f} s")
    if rc != 0:
        print("  ERROR: dcm2bids failed")
        return False

    tmp = BIDS_DIR / "tmp_dcm2bids" / (f"sub-{sub}" + (f"_ses-{ses}" if ses else ""))
    if tmp.exists() and not args.keep_tmp and not args.dry_run:
        shutil.rmtree(tmp)
        print(f"  Removed temporary folder {tmp}")
    return True


def fix_phasediff(row, args):
    """BIDS requires EchoTime1/EchoTime2 in phasediff sidecars; copy them from the magnitudes."""
    fmap = out_dir(row["sub"], row["ses"]) / "fmap"
    for pd in sorted(fmap.glob("*_phasediff.json")):
        data = json.loads(pd.read_text())
        if "EchoTime1" in data and "EchoTime2" in data:
            continue
        stem = pd.name[: -len("_phasediff.json")]
        mags = [fmap / f"{stem}_magnitude{i}.json" for i in (1, 2)]
        if not all(m.exists() for m in mags):
            print(f"  WARNING: {pd.name} lacks EchoTime1/2 and magnitude sidecars were not found")
            continue
        te1, te2 = (json.loads(m.read_text()).get("EchoTime") for m in mags)
        if te1 is None or te2 is None:
            print(f"  WARNING: could not read EchoTime from magnitude sidecars for {pd.name}")
            continue
        data["EchoTime1"], data["EchoTime2"] = te1, te2
        pd.write_text(json.dumps(data, indent=4))
        print(f"  Added EchoTime1={te1}, EchoTime2={te2} to {pd.name}")


def select_t1w(row, args):
    """Keep one T1w per session (the last run) and drop the run entity from its name."""
    if T1W_KEEP != "last":
        return
    anat = out_dir(row["sub"], row["ses"]) / "anat"
    runs = sorted(anat.glob("*_run-*_T1w.nii.gz"))
    if not runs:
        return
    keep, drop = runs[-1], runs[:-1]
    dest = EXCLUDED_DIR / anat.relative_to(BIDS_DIR)
    for img in drop:
        print(f"  Moving earlier T1w {img.name} to {dest}")
        dest.mkdir(parents=True, exist_ok=True)
        for f in (img, img.with_name(img.name.replace(".nii.gz", ".json"))):
            if f.exists():
                shutil.move(str(f), str(dest / f.name))
    for f in (keep, keep.with_name(keep.name.replace(".nii.gz", ".json"))):
        if f.exists():
            new = f.with_name(re.sub(r"_run-[0-9]+", "", f.name))
            f.rename(new)
    print(f"  Kept {keep.name} as {re.sub(r'_run-[0-9]+', '', keep.name)}")


def check_volumes(row, args):
    sub, ses = row["sub"], row["ses"]
    func = out_dir(sub, ses) / "func"
    if not func.is_dir():
        print("  WARNING: no func folder found")
        return
    removed = []
    for bold in sorted(func.glob("*_bold.nii.gz")):
        task = next((p[5:] for p in bold.name.split("_") if p.startswith("task-")), None)
        nv = n_volumes(bold)
        expected = EXPECTED_VOLUMES.get(task)
        if expected is None:
            print(f"  {bold.name}: {nv} volumes")
            continue
        if nv >= expected:
            print(f"  {bold.name}: {nv} volumes (minimum {expected}) ok")
            continue
        print(f"  {bold.name}: {nv} volumes (minimum {expected}) TOO SHORT -> moving to {EXCLUDED_DIR}")
        stem = bold.name[: -len("_bold.nii.gz")]
        dest = EXCLUDED_DIR / func.relative_to(BIDS_DIR)
        for suffix in BOLD_SIDECARS:
            f = func / (stem + suffix)
            if f.exists() and not args.dry_run:
                dest.mkdir(parents=True, exist_ok=True)
                shutil.move(str(f), str(dest / f.name))
        removed.append(bold.name)

    # Drop moved runs from field-map IntendedFor so they don't point at missing files.
    fmap = out_dir(sub, ses) / "fmap"
    if removed and fmap.is_dir() and not args.dry_run:
        for j in sorted(fmap.glob("*.json")):
            data = json.loads(j.read_text())
            intended = data.get("IntendedFor")
            if not intended:
                continue
            intended = [intended] if isinstance(intended, str) else intended
            keep = [p for p in intended if not any(p.endswith(r) for r in removed)]
            if keep != intended:
                data["IntendedFor"] = keep
                j.write_text(json.dumps(data, indent=4))
                print(f"  Updated IntendedFor in {j.name}")


def deface(row, args):
    anat = out_dir(row["sub"], row["ses"]) / "anat"
    if not anat.is_dir():
        print("  WARNING: no anat folder found; nothing to deface")
        return True
    ok = True
    for img in sorted(anat.glob("*.nii.gz")):
        if not img.name.endswith(DEFACE_SUFFIXES):
            continue
        backup = NONDEFACED_DIR / img.relative_to(BIDS_DIR)
        if backup.exists():
            print(f"  {img.name}: already defaced (original in {backup.parent}); skipping")
            continue
        print(f"  Defacing {img.name}")
        if not args.dry_run:
            backup.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(img, backup)
        cmd = shlex.split(DEFACE_CMD.format(src=shlex.quote(str(backup)),
                                            dst=shlex.quote(str(img))))
        if run(cmd, args.dry_run) != 0:
            print(f"  ERROR: defacing failed for {img.name}; restoring original")
            if not args.dry_run:
                shutil.copy2(backup, img)
                backup.unlink()
            ok = False
    return ok


def write_tables(rows, args):
    """Write participants.tsv, sub-*_sessions.tsv and a minimal dataset_description.json."""
    if args.dry_run:
        return
    desc = BIDS_DIR / "dataset_description.json"
    if not desc.exists():
        desc.write_text(json.dumps({"Name": "CHANGE_ME study name",
                                    "BIDSVersion": "1.10.0",
                                    "DatasetType": "raw"}, indent=4))
    subs = {}
    for r in rows:
        subs.setdefault(r["sub"], []).append(r)
    def one(sub, col):
        vals = {r.get(col, "") for r in subs[sub]} - {""}
        return vals.pop() if len(vals) == 1 else "n/a"
    cols = [c for c in ("cohort", "group") if any(r.get(c) for r in rows)]
    with open(BIDS_DIR / "participants.tsv", "w") as f:
        f.write("\t".join(["participant_id"] + cols) + "\n")
        for sub in sorted(subs):
            f.write("\t".join([f"sub-{sub}"] + [one(sub, c) for c in cols]) + "\n")
    for sub, srows in subs.items():
        sdir = BIDS_DIR / f"sub-{sub}"
        sess = sorted((r for r in srows if r["ses"]), key=lambda r: r["ses"])
        if not sess or not sdir.is_dir():
            continue
        with open(sdir / f"sub-{sub}_sessions.tsv", "w") as f:
            f.write("session_id\tage\n")
            for r in sess:
                if (sdir / f"ses-{r['ses']}").is_dir():
                    f.write(f"ses-{r['ses']}\t{r.get('age') or 'n/a'}\n")


def session_summary(row):
    """One line per session for the conversion report."""
    d = out_dir(row["sub"], row["ses"])
    rest = sorted((d / "func").glob("*_task-rest*_bold.nii.gz"))
    return {
        "sub": f"sub-{row['sub']}",
        "ses": f"ses-{row['ses']}" if row["ses"] else "n/a",
        "rest_runs": len(rest),
        "rest_volumes": ",".join(str(n_volumes(f)) for f in rest) or "n/a",
        "T1w": len(list((d / "anat").glob("*_T1w.nii.gz"))),
        "fieldmap": "yes" if list((d / "fmap").glob("*_phasediff.nii.gz")) else "no",
    }


def main():
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    g = p.add_mutually_exclusive_group(required=True)
    g.add_argument("--all", action="store_true", help="process every row in the subject map")
    g.add_argument("--subjects", nargs="+", metavar="LABEL",
                   help="BIDS subject labels to process (with or without 'sub-')")
    p.add_argument("--no-deface", action="store_true", help="skip defacing")
    p.add_argument("--overwrite", action="store_true", help="reconvert even if output exists")
    p.add_argument("--dry-run", action="store_true", help="print commands without running them")
    p.add_argument("--recheck-volumes", action="store_true",
                   help="only apply EXPECTED_VOLUMES to sessions already converted "
                        "(moves short runs to EXCLUDED_DIR); nothing is reconverted")
    p.add_argument("--stage-dir", metavar="DIR",
                   help="copy each visit's DICOMs to this local folder before converting; "
                        "the copy is deleted right after (keep it on an encrypted disk)")
    p.add_argument("--keep-tmp", action="store_true",
                   help="keep dcm2bids' tmp_dcm2bids folder (for debugging; contains non-defaced data)")
    args = p.parse_args()

    if not CONFIG_FILE.is_file():
        sys.exit(f"ERROR: config not found: {CONFIG_FILE}")
    needed = ["dcm2bids", "dcm2niix"]
    if not args.no_deface:
        needed += [shlex.split(DEFACE_CMD)[0], "flirt"]
    missing_tools = [t for t in needed if shutil.which(t) is None]
    if missing_tools:
        sys.exit("ERROR: not found on PATH: " + ", ".join(missing_tools)
                 + "\n(Is the conda env activated? Is FSL installed?)")

    all_rows = rows = read_subject_map()
    if args.subjects:
        wanted = {s[4:] if s.startswith("sub-") else s for s in args.subjects}
        missing = wanted - {r["sub"] for r in rows}
        if missing:
            sys.exit(f"ERROR: not in subject map: {', '.join(sorted(missing))}")
        rows = [r for r in rows if r["sub"] in wanted]

    print(f"Processing {len(rows)} subject/session(s){' (dry run)' if args.dry_run else ''}")
    failures, report = [], []
    rep_file = SUBJECT_MAP.parent / "conversion_report.tsv"
    interrupted = False
    try:
        for row in rows:
            label = f"sub-{row['sub']}" + (f"_ses-{row['ses']}" if row["ses"] else "")
            if args.recheck_volumes:
                if not (out_dir(row["sub"], row["ses"]) / "func").is_dir():
                    continue
                print(f"\n=== {label} ===")
                check_volumes(row, args)
                if not args.dry_run:
                    report.append(session_summary(row))
                continue
            print(f"\n=== {label}  (DICOM: {row['dicom_folder']}) ===")
            status = convert(row, args)
            if not status:
                failures.append(label)
                continue
            if status != "done":
                if not args.dry_run and not out_dir(row["sub"], row["ses"]).is_dir():
                    print("  ERROR: no series matched the config, so nothing was converted. "
                          "Check this visit's series names.")
                    failures.append(label)
                    report.append({"sub": f"sub-{row['sub']}",
                                   "ses": f"ses-{row['ses']}" if row["ses"] else "n/a",
                                   "rest_runs": 0, "rest_volumes": "n/a", "T1w": 0,
                                   "fieldmap": "no"})
                    write_report(report, rep_file)
                    continue
                if not args.dry_run:
                    marker(row).unlink(missing_ok=True)
                    fix_phasediff(row, args)
                    select_t1w(row, args)
                    check_volumes(row, args)
                if not args.no_deface and not deface(row, args):
                    failures.append(label)
                    continue
                if not args.dry_run:
                    DONE_DIR.mkdir(parents=True, exist_ok=True)
                    marker(row).touch()
            if not args.dry_run and out_dir(row["sub"], row["ses"]).is_dir():
                report.append(session_summary(row))
                write_report(report, rep_file)      # updated after every session
    except KeyboardInterrupt:
        interrupted = True
        print("\n\nInterrupted. Unfinished sessions will be redone on the next run.")

    write_tables(all_rows, args)
    if report:
        write_report(report, rep_file)
        print(f"\nConversion report: {rep_file}")
        for text, key in (("no resting-state scan", "rest_runs"), ("no T1w", "T1w")):
            missing = [f"{r['sub']}_{r['ses']}" for r in report if r[key] == 0]
            if missing:
                print(f"  {len(missing)} session(s) with {text}: {', '.join(missing)}")
        nofmap = [f"{r['sub']}_{r['ses']}" for r in report if r["fieldmap"] == "no" and r["rest_runs"]]
        if nofmap:
            print(f"  {len(nofmap)} session(s) with rest but no field map: {', '.join(nofmap)}")
    print("\nDone." if not failures else f"\nDone with errors in: {', '.join(failures)}")
    sys.exit(1 if failures or interrupted else 0)


def write_report(report, rep_file):
    cols = list(report[0])
    with open(rep_file, "w") as f:
        f.write("\t".join(cols) + "\n")
        for r in report:
            f.write("\t".join(str(r[c]) for c in cols) + "\n")


if __name__ == "__main__":
    main()
