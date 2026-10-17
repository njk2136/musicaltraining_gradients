#!/bin/bash

for i in $(seq -f "%04g" 1 206);
do
subj=sub-"$i"
sbatch --job-name=batchjob --output=dme.isoctx."$subj".out /vast/iaslab/BANDA/scripts/gradient_embedding_isocortex_indiv.sh "$subj"
done
