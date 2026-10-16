#!/usr/bin/env python3
"""
Import a resting-state scan that only exists as an old NIfTI file (no DICOMs).

The NIfTI is copied into BIDS as sub-XXX_ses-YY_task-rest_bold.nii.gz and gets
a JSON sidecar copied from a REFERENCE session that was converted from DICOM
with the same protocol (TR, slice timing, phase encoding, echo spacing).
Before anything is written, the script checks that matrix size, number of
volumes, TR and voxel orientation match the reference, because copied slice
timing and phase-encoding direction are only valid if the image is stored
the same way. If anything differs, it stops and writes nothing.

If the session has field maps, the imported run is added to their IntendedFor.

Usage:
  python3 import_nifti_rest.py --sub 018 --ses 01 --ref-sub 001 --ref-ses 01 \\
      --nifti "/Volumes/.../EPI RESTING STATE nifti/EPIRESTINGSTATE6304AD.nii.gz"
"""
import argparse
import gzip
import json
import shutil
import struct
import sys
from pathlib import Path

# ======================= EDIT =======================
BIDS_DIR = Path("/Users/nickathios/Documents/research/musicaltraining_gradients/raw_bids")
# ====================================================


def read_header(path):
    opener = gzip.open if str(path).endswith(".gz") else open
    with opener(path, "rb") as f:
        hdr = f.read(348)
    for e in "<>":
        if struct.unpack(e + "i", hdr[:4])[0] == 348:
            dims = struct.unpack(e + "8h", hdr[40:56])
            pixdim = struct.unpack(e + "8f", hdr[76:108])
            qform_code, sform_code = struct.unpack(e + "2h", hdr[252:256])
            srow = [struct.unpack(e + "4f", hdr[280 + 16 * i: 296 + 16 * i]) for i in range(3)]
            return dict(dims=dims[1:5], tr=round(pixdim[4], 4), sform_code=sform_code,
                        qform_code=qform_code, srow=srow)
    sys.exit(f"ERROR: not a NIfTI-1 file: {path}")


def orientation(h):
    """For each voxel axis: which world axis it runs along and in which direction."""
    if h["sform_code"] <= 0:
        return None
    out = []
    for col in range(3):
        v = [h["srow"][row][col] for row in range(3)]
        i = max(range(3), key=lambda k: abs(v[k]))
        out.append(("+" if v[i] > 0 else "-") + "xyz"[i])
    return tuple(out)


def session_dir(sub, ses):
    return BIDS_DIR / f"sub-{sub}" / f"ses-{ses}"


def main():
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--sub", required=True)
    p.add_argument("--ses", required=True)
    p.add_argument("--nifti", required=True, type=Path)
    p.add_argument("--ref-sub", required=True)
    p.add_argument("--ref-ses", required=True)
    p.add_argument("--force", action="store_true", help="replace an existing rest run")
    a = p.parse_args()

    ses_dir = session_dir(a.sub, a.ses)
    ref_dir = session_dir(a.ref_sub, a.ref_ses)
    stem = f"sub-{a.sub}_ses-{a.ses}_task-rest"
    dest_nii = ses_dir / "func" / f"{stem}_bold.nii.gz"
    dest_json = dest_nii.with_name(f"{stem}_bold.json")
    ref_nii = ref_dir / "func" / f"sub-{a.ref_sub}_ses-{a.ref_ses}_task-rest_bold.nii.gz"
    ref_json = ref_nii.with_name(ref_nii.name.replace(".nii.gz", ".json"))

    for path, what in ((a.nifti, "NIfTI to import"), (ref_nii, "reference rest scan"),
                       (ref_json, "reference sidecar"), (ses_dir, "target session folder")):
        if not path.exists():
            sys.exit(f"ERROR: {what} not found: {path}")
    if dest_nii.exists() and not a.force:
        sys.exit(f"ERROR: {dest_nii.name} already exists (use --force to replace it)")

    new, ref = read_header(a.nifti), read_header(ref_nii)
    print(f"Import:    dims {new['dims']}  TR {new['tr']}  orientation {orientation(new)}")
    print(f"Reference: dims {ref['dims']}  TR {ref['tr']}  orientation {orientation(ref)}")
    problems = []
    if new["dims"][:3] != ref["dims"][:3]:
        problems.append("matrix size differs")
    if new["dims"][3] != ref["dims"][3]:
        problems.append(f"number of volumes differs ({new['dims'][3]} vs {ref['dims'][3]})")
    if abs(new["tr"] - ref["tr"]) > 1e-3:
        problems.append("TR differs")
    o_new, o_ref = orientation(new), orientation(ref)
    if o_new is None or o_ref is None:
        problems.append("orientation can't be verified (no sform in header)")
    elif o_new != o_ref:
        problems.append("voxel orientation differs, so the reference slice timing and "
                        "phase-encoding direction would be wrong")
    if problems:
        sys.exit("STOPPED, nothing written:\n  - " + "\n  - ".join(problems))

    dest_nii.parent.mkdir(parents=True, exist_ok=True)
    if str(a.nifti).endswith(".gz"):
        shutil.copy2(a.nifti, dest_nii)
    else:
        with open(a.nifti, "rb") as fi, gzip.open(dest_nii, "wb") as fo:
            shutil.copyfileobj(fi, fo)

    meta = json.loads(ref_json.read_text())
    for k in ("AcquisitionTime", "AcquisitionDateTime", "SeriesNumber",
              "ConversionSoftware", "ConversionSoftwareVersion"):
        meta.pop(k, None)
    meta["TaskName"] = "rest"
    meta["ImportNote"] = (f"Imported from a pre-existing NIfTI (no DICOMs available). "
                          f"Acquisition parameters copied from sub-{a.ref_sub} ses-{a.ref_ses}, "
                          f"same protocol; matrix, volumes, TR and orientation verified.")
    dest_json.write_text(json.dumps(meta, indent=4))
    print(f"Wrote {dest_nii.name} and {dest_json.name}")

    # Add the run to this session's field maps, using the reference's IntendedFor style
    fmap = ses_dir / "fmap"
    ref_style = None
    for j in sorted((ref_dir / "fmap").glob("*.json")) if (ref_dir / "fmap").is_dir() else []:
        it = json.loads(j.read_text()).get("IntendedFor")
        if it:
            ref_style = it[0] if isinstance(it, list) else it
            break
    if fmap.is_dir():
        if ref_style and ref_style.startswith("bids::"):
            entry = f"bids::sub-{a.sub}/ses-{a.ses}/func/{dest_nii.name}"
        else:
            entry = f"ses-{a.ses}/func/{dest_nii.name}"
        for j in sorted(fmap.glob("*.json")):
            d = json.loads(j.read_text())
            it = d.get("IntendedFor", [])
            it = [it] if isinstance(it, str) else list(it)
            if entry not in it:
                d["IntendedFor"] = it + [entry]
                j.write_text(json.dumps(d, indent=4))
                print(f"Added to IntendedFor in {j.name}")
    else:
        print("No field maps in this session; it will need fieldmap-less correction")


if __name__ == "__main__":
    main()
