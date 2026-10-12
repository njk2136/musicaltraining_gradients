#!/bin/bash
#SBATCH --time=23:00:00
#SBATCH -N 1
#SBATCH -n 1
#SBATCH -p short

module load anaconda3/2022.01
source activate my_dcm2bids_env
module load python/3.8.1

python /scratch/lopez.ke/TEAMTEAM_Study/makebids_TEAMTEAM.py --project TEAMTEAM_Study --all