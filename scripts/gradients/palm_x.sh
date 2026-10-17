#!/bin/bash
#SBATCH --account=iaslab
#SBATCH --partition=basic
#SBATCH --nodes=1
#SBATCH --ntasks-per-node=1
#SBATCH --mem=45G
#SBATCH --time=0-04:00:00

/usr/bin/singularity run --cleanenv \
--bind '/autofs/cluster/iaslab/FSMAP/FSMAP_data/new_models/stress/clare:/scratch/data' \
--bind '/autofs/cluster/iaslab/users/jtheriault/atlases:/scratch/atlases' \
--bind '/autofs/cluster/iaslab/FSMAP/FSMAP_data/new_models/scripts/stress:/scratch/scripts' \
/autofs/cluster/iaslab/users/jtheriault/singularity_images/jtnipyutil_python_only/2023-11-18/jtnipyutil_pythononly-2023-11-18-dad50bddc846.simg \
python3 /scratch/scripts/05_lvl2HRF_TFCE_model.py "$1"
