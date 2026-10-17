#!/bin/bash
#SBATCH --account=iaslab
#SBATCH --partition=basic
#SBATCH --nodes=1
#SBATCH --ntasks-per-node=1
#SBATCH --mem=120G
#SBATCH --time=3-00:00:00

python3 /vast/iaslab/BANDA/scripts/gradient_embedding_isocortex_indiv.py "$1
