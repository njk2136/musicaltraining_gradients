#!/bin/bash
#SBATCH --account=iaslab
#SBATCH --partition=basic
#SBATCH --nodes=1
#SBATCH --ntasks-per-node=1
#SBATCH --mem=30G
#SBATCH --time=3-00:00:00

eval "$(/vast/iaslab/FSMAP/claree_timeseries/tmp/miniforge3/bin/conda shell.bash hook)"

python3 /vast/iaslab/BANDA/scripts/groupgrads_pts.py "$1"
