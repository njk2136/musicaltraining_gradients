#!/bin/bash

while read -r subj
do
sbatch --job-name=batchjob_%j --output=batchjob_%j_"$subj".out /vast/iaslab/BANDA/scripts/seedcorr_pbins.sh "$subj"
done < /vast/iaslab/BANDA/fc_gradients/patients_only/patients_4runs.txt
