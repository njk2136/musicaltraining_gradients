#!/bin/bash
#SBATCH --job-name=fmriprep
#SBATCH --account=kathios_1985          # check with: myaccount
#SBATCH --partition=main
#SBATCH --time=48:00:00
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=16
#SBATCH --mem=64G
#SBATCH --mail-type=END,FAIL
#SBATCH --mail-user=kathios@usc.edu
#SBATCH --array=1-73%10                 # use the range make_fmriprep_jobs.py prints; %10 = max 10 at once
#SBATCH --output=logs/fmriprep_%A_%a.out
#SBATCH --error=logs/fmriprep_%A_%a.err
# ------------------------------------------
# One job per child. Each job runs only that child's sessions with a rest scan
# (from fmriprep_jobs.tsv) and builds a separate anatomical reference per
# session, since the children grow a lot between visits.
# Submit from the folder holding this script, after `mkdir -p logs`.

set -uo pipefail

# ======================= SETTINGS =======================
MODULES=("apptainer")
CONTAINER=/CHANGE_ME/fmriprep_XX.X.X.sif
FS_LICENSE_HOST=/home1/kathios/licenses/freesurfer/license.txt

PROJECT=/project2/kathios_1985/musical_training_gradients
BIDS_DIR=${PROJECT}/raw_bids
OUT_DIR=${PROJECT}/derivatives/fmriprep
TEMPLATEFLOW_HOST_HOME=${PROJECT}/templateflow       # on /project2 so it isn't purged
SCRATCH_ROOT=/scratch1/${USER}/fmriprep_work
JOBS=${SLURM_SUBMIT_DIR}/fmriprep_jobs.tsv
# ========================================================

for m in "${MODULES[@]}"; do module load "$m"; done
if command -v apptainer >/dev/null 2>&1; then
    RUNTIME=apptainer; ENVPFX=APPTAINERENV
elif command -v singularity >/dev/null 2>&1; then
    RUNTIME=singularity; ENVPFX=SINGULARITYENV
else
    echo "ERROR: neither apptainer nor singularity found" >&2; exit 1
fi

# --- This task's child and sessions ---
LINE=$(sed -n "${SLURM_ARRAY_TASK_ID}p" "${JOBS}")
[[ -n "${LINE}" ]] || { echo "ERROR: no line ${SLURM_ARRAY_TASK_ID} in ${JOBS}" >&2; exit 1; }
SUB=$(cut -f1 <<< "${LINE}")
SESSIONS=$(cut -f2 <<< "${LINE}" | tr ',' ' ')

# --- Resources from the SLURM request ---
NCPUS=${SLURM_CPUS_PER_TASK:-16}
OMP=$(( NCPUS > 8 ? 8 : NCPUS ))
MEM_MB=$(( ${SLURM_MEM_PER_NODE:-64000} - 4000 ))

WORK_DIR=${SCRATCH_ROOT}/sub-${SUB}
mkdir -p "${OUT_DIR}" "${WORK_DIR}" "${TEMPLATEFLOW_HOST_HOME}"

[[ -f "${CONTAINER}" ]]       || { echo "ERROR: container not found: ${CONTAINER}" >&2; exit 1; }
[[ -f "${FS_LICENSE_HOST}" ]] || { echo "ERROR: FS license not found: ${FS_LICENSE_HOST}" >&2; exit 1; }

export "${ENVPFX}_TEMPLATEFLOW_HOME=/templateflow"

cmd=(
  "${RUNTIME}" run --cleanenv
  -B "${BIDS_DIR}:/data:ro"
  -B "${OUT_DIR}:/out"
  -B "${WORK_DIR}:/work"
  -B "${TEMPLATEFLOW_HOST_HOME}:/templateflow"
  -B "${FS_LICENSE_HOST}:/opt/fs_license.txt:ro"
  "${CONTAINER}"
  /data /out participant
  --participant-label "${SUB}"
  --session-label ${SESSIONS}
  --subject-anatomical-reference sessionwise
  -w /work
  --fs-license-file /opt/fs_license.txt
  --nprocs "${NCPUS}" --omp-nthreads "${OMP}" --mem-mb "${MEM_MB}"
  --output-spaces MNIPediatricAsym:cohort-1:res-native MNI152NLin2009cAsym:res-native
  --cifti-output 91k
  --project-goodvoxels
  --use-syn-sdc warn
  --skip-bids-validation
  -v
)

echo "Task ${SLURM_ARRAY_TASK_ID}: sub-${SUB}, sessions: ${SESSIONS} on $(hostname)"
echo "Commandline: ${cmd[*]}"
"${cmd[@]}"
exitcode=$?

echo -e "sub-${SUB}\t${SESSIONS// /,}\t${SLURM_ARRAY_TASK_ID}\t${exitcode}" \
    >> "${SLURM_SUBMIT_DIR}/fmriprep_status_${SLURM_ARRAY_JOB_ID}.tsv"
echo "Finished sub-${SUB} with exit code ${exitcode}"
exit ${exitcode}
