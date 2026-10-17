#!/bin/bash

sbatch --job-name=stress_lvl2_model \
--output=lvl2HRFmodel.out \
/autofs/cluster/iaslab/FSMAP/FSMAP_data/new_models/scripts/stress/05_lvl2HRF_model.sh
