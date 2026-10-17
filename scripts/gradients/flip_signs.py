
import numpy as np
import nibabel as nib
import pandas as pd
from sklearn.metrics import pairwise_distances
import sklearn
import os
import sys
sys.path.append('/work/swglab/data/BANDA_U01/analysis/proj_clare_networkICA/clare_U01masks_ICA/fc_gradients/mapalign-master')
from mapalign import embed
from neuromaps import transforms
from brainspace.gradient import alignment

hcp1003_ctx_gradients = nib.cifti2.load('/work/swglab/data/BANDA_U01/analysis/proj_clare_networkICA/clare_U01masks_ICA/fc_gradients/HCP3T_N1003_isocortical_gradients.dscalar.nii').get_fdata()
tmp_cifti = nib.cifti2.load('/work/swglab/data/BANDA_U01/analysis/proj_clare_networkICA/clare_U01masks_ICA/fc_gradients/HCP3T_N1003_isocortical_gradients.dscalar.nii')
hcp1003_ctx_gradients[0,:] = hcp1003_ctx_gradients[0,:]*-1
hcp1003_ctx_gradients[1,:] = hcp1003_ctx_gradients[1,:]*-1
img = nib.cifti2.Cifti2Image(hcp1003_ctx_gradients, nib.cifti2.Cifti2Header(tmp_cifti.header.matrix))
img.to_filename('/work/swglab/data/BANDA_U01/analysis/proj_clare_networkICA/clare_U01masks_ICA/fc_gradients/HCP3T_N1003_isocortical_gradients_signFlipped.dscalar.nii')
