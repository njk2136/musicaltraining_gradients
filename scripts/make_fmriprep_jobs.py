#!/usr/bin/env python3
"""
Build the job list for fmriprep_array.sh: one line per child, with the sessions
that have both a resting-state run and a T1w. Sessions without rest are left
out, so fMRIPrep never spends time on them; children with no usable session
get no job at all.

Run once on the cluster after uploading raw_bids (rerun if the dataset changes):
  python3 make_fmriprep_jobs.py
"""
import sys
from pathlib import Path

# ======================= EDIT =======================
BIDS_DIR = Path("/project2/kathios_1985/musical_training_gradients/raw_bids")
JOBS     = Path(__file__).with_name("fmriprep_jobs.tsv")
# ====================================================

if not BIDS_DIR.is_dir():
    sys.exit(f"ERROR: BIDS_DIR not found: {BIDS_DIR}")

lines, n_ses, skipped = [], 0, []
for sub in sorted(BIDS_DIR.glob("sub-*")):
    sessions = []
    for ses in sorted(sub.glob("ses-*")):
        has_rest = any((ses / "func").glob("*_task-rest*_bold.nii.gz"))
        has_t1w = any((ses / "anat").glob("*_T1w.nii.gz"))
        if has_rest and has_t1w:
            sessions.append(ses.name[4:])
        elif has_rest:
            skipped.append(f"{sub.name}_{ses.name} (rest but no T1w)")
    if sessions:
        lines.append(f"{sub.name[4:]}\t{','.join(sessions)}")
        n_ses += len(sessions)

JOBS.write_text("\n".join(lines) + "\n")
print(f"{len(lines)} children, {n_ses} sessions -> {JOBS}")
for s in skipped:
    print(f"  skipped {s}")
print(f"In fmriprep_array.sh use:  #SBATCH --array=1-{len(lines)}%10")
