#!/usr/bin/env python3
"""
Descriptive summary of the converted resting-state data, by year and arm:

  1. sessions converted, and sessions with / without a rest scan
  2. TR of the rest scans (are volume counts comparable across years?)
  3. rest scan length distribution (longest run per session)
  4. for each candidate minimum length: usable sessions, and children with
     1+, 2+, 3+ usable sessions (what a longitudinal analysis can use)
  5. field map availability among usable sessions

A session counts as usable at a cutoff if its LONGEST rest run reaches it
(aborted fragments next to a full run don't matter; they will be excluded).

Reads only the BIDS folder (images, sidecars, participants.tsv), so the output
contains no identifying information.

Usage:  python3 rest_summary.py            (also writes rest_summary.txt)
"""
import gzip
import json
import struct
import sys
from collections import defaultdict
from pathlib import Path

# ======================= EDIT =======================
BIDS_DIR = Path("/Users/nickathios/Documents/research/musicaltraining_gradients/raw_bids")
CUTOFFS  = [1, 100, 120, 150, 170, 180]     # minimum rest volumes to compare
# ====================================================

out_lines = []


def say(line=""):
    print(line)
    out_lines.append(line)


def n_volumes(path):
    with gzip.open(path, "rb") as f:
        hdr = f.read(348)
    for e in "<>":
        if struct.unpack(e + "i", hdr[:4])[0] == 348:
            dims = struct.unpack(e + "8h", hdr[40:56])
            pixdim = struct.unpack(e + "8f", hdr[76:108])
            return (dims[4] if dims[0] >= 4 else 1), round(pixdim[4], 3)
    raise ValueError(path)


def table(header, rows):
    widths = [max(len(str(x)) for x in col) for col in zip(header, *rows)]
    fmt = "  ".join("{:>%d}" % w for w in widths)
    say(fmt.format(*header))
    for r in rows:
        say(fmt.format(*r))


def main():
    if not BIDS_DIR.is_dir():
        sys.exit(f"ERROR: BIDS_DIR not found: {BIDS_DIR}")

    arm = {}
    pt = BIDS_DIR / "participants.tsv"
    if pt.is_file():
        lines = pt.read_text().splitlines()
        cols = lines[0].split("\t")
        for ln in lines[1:]:
            d = dict(zip(cols, ln.split("\t")))
            arm[d["participant_id"]] = d.get("group", "n/a") or "n/a"

    sessions = []
    for sdir in sorted(BIDS_DIR.glob("sub-*/ses-*")):
        sub, ses = sdir.parent.name, sdir.name
        runs = []
        for nii in sorted((sdir / "func").glob("*_task-rest*_bold.nii.gz")):
            vols, tr_hdr = n_volumes(nii)
            js = nii.with_name(nii.name.replace(".nii.gz", ".json"))
            tr = json.loads(js.read_text()).get("RepetitionTime", tr_hdr) if js.exists() else tr_hdr
            runs.append((vols, round(float(tr), 3)))
        sessions.append(dict(
            sub=sub, ses=ses, arm=arm.get(sub, "n/a"), runs=runs,
            longest=max((v for v, _ in runs), default=0),
            tr=max(runs)[1] if runs else None,
            fmap=any((sdir / "fmap").glob("*_phasediff.nii.gz"))))

    years = sorted({s["ses"] for s in sessions})
    arms = sorted({s["arm"] for s in sessions})

    say("=" * 70)
    say("1. Sessions converted")
    say("=" * 70)
    rows = []
    for y in years:
        ss = [s for s in sessions if s["ses"] == y]
        rows.append([y, len(ss), sum(1 for s in ss if s["runs"]),
                     sum(1 for s in ss if not s["runs"]),
                     sum(1 for s in ss if len(s["runs"]) > 1)]
                    + [sum(1 for s in ss if s["arm"] == a and s["runs"]) for a in arms])
    rows.append(["total", len(sessions), sum(1 for s in sessions if s["runs"]),
                 sum(1 for s in sessions if not s["runs"]),
                 sum(1 for s in sessions if len(s["runs"]) > 1)]
                + [sum(1 for s in sessions if s["arm"] == a and s["runs"]) for a in arms])
    table(["session", "converted", "with rest", "no rest", "2+ rest runs"]
          + [f"rest:{a}" for a in arms], rows)
    n_kids = {a: len({s["sub"] for s in sessions if s["arm"] == a}) for a in arms}
    say(f"\nChildren: {len({s['sub'] for s in sessions})} ("
        + ", ".join(f"{a}: {n}" for a, n in n_kids.items()) + ")")

    say("\n" + "=" * 70)
    say("2. Rest scan TR by session (volume counts are only comparable within one TR)")
    say("=" * 70)
    for y in years:
        trs = defaultdict(int)
        for s in sessions:
            if s["ses"] == y:
                for _, tr in s["runs"]:
                    trs[tr] += 1
        say(f"{y}: " + (", ".join(f"TR {tr} s in {n} run(s)" for tr, n in sorted(trs.items())) or "no rest"))

    say("\n" + "=" * 70)
    say("3. Longest rest run per session (volumes / minutes)")
    say("=" * 70)
    bins = [(1, 59), (60, 99), (100, 119), (120, 149), (150, 169), (170, 179), (180, 10**6)]
    rows = []
    for y in years + ["total"]:
        ss = [s for s in sessions if (y == "total" or s["ses"] == y) and s["runs"]]
        vals = sorted(s["longest"] for s in ss)
        med = vals[len(vals) // 2] if vals else 0
        rows.append([y, len(ss), min(vals, default=0), med, max(vals, default=0)]
                    + [sum(1 for v in vals if lo <= v <= hi) for lo, hi in bins])
    table(["session", "n", "min", "median", "max"]
          + [f"{lo}-{hi}" if hi < 10**6 else f"{lo}+" for lo, hi in bins], rows)
    tr_all = {s["tr"] for s in sessions if s["tr"]}
    if len(tr_all) == 1:
        tr = tr_all.pop()
        say(f"\nAt TR {tr} s: " + ", ".join(f"{c} vols = {c * tr / 60:.1f} min" for c in CUTOFFS if c > 1))

    say("\n" + "=" * 70)
    say("4. What each minimum length keeps")
    say("=" * 70)
    rows = []
    for c in CUTOFFS:
        ok = [s for s in sessions if s["longest"] >= c]
        per_child = defaultdict(int)
        for s in ok:
            per_child[s["sub"]] += 1
        row = [("any" if c == 1 else c), len(ok)] + \
              [sum(1 for s in ok if s["ses"] == y) for y in years] + \
              [sum(1 for v in per_child.values() if v >= k) for k in (1, 2, 3)]
        rows.append(row)
    table(["min vols", "sessions"] + years + ["kids 1+", "kids 2+", "kids 3+"], rows)

    say("\nBy arm (children with 2+ usable sessions / usable sessions):")
    rows = []
    for c in CUTOFFS:
        row = [("any" if c == 1 else c)]
        for a in arms:
            ok = [s for s in sessions if s["arm"] == a and s["longest"] >= c]
            per_child = defaultdict(int)
            for s in ok:
                per_child[s["sub"]] += 1
            row.append(f"{sum(1 for v in per_child.values() if v >= 2)} / {len(ok)}")
        rows.append(row)
    table(["min vols"] + arms, rows)

    say("\n" + "=" * 70)
    say("5. Field maps among sessions with rest")
    say("=" * 70)
    rows = []
    for y in years:
        ss = [s for s in sessions if s["ses"] == y and s["runs"]]
        rows.append([y, len(ss), sum(1 for s in ss if s["fmap"]), sum(1 for s in ss if not s["fmap"])])
    table(["session", "with rest", "field map", "no field map"], rows)

    out = Path(__file__).with_name("rest_summary.txt")
    out.write_text("\n".join(out_lines) + "\n")
    print(f"\nSaved to {out}")


if __name__ == "__main__":
    main()
