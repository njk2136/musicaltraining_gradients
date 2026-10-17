import numpy as np
import nibabel as nib
import pandas as pd
from sklearn.metrics import pairwise_distances
import sklearn
import os
import sys
sys.path.append('/vast/iaslab/BANDA/fc_gradients/mapalign-master')
from mapalign import embed
#from neuromaps import transforms
from brainspace.gradient import alignment

# Cortex
data_dir = '/vast/iaslab/BANDA/fc_gradients/'
out_dir = '/vast/iaslab/BANDA/fc_gradients/group_gradients/'
#data_dir = '/vast/iaslab/BANDA/fc_gradients/group_gradients/'

numGrads = 10

#tmp = nib.nifti2.load(outdir + '/100307_tfMRI_MOTOR_level2_hp200_s2.cortex_only.1map.dscalar.nii')
tmp_cifti = nib.cifti2.load(data_dir + '/100307_tfMRI_MOTOR_level2_hp200_s2.cortex_only.1map.dscalar.nii')
hcp1003_ctx_gradients = nib.cifti2.load(data_dir + 'HCP3T_N1003_isocortical_gradients_signFlipped.dscalar.nii').get_fdata()
ref_ctx = hcp1003_ctx_gradients[0:10,:]

aff = np.load(out_dir + 'controls_group_avg_affinity_filtered.npy')

emb, res = embed.compute_diffusion_map(aff, n_components=10, alpha=0.5, return_result=True, skip_checks=True)
    #np.save(outdir + '/' + subj + '/cosine_affinity_CTXbyCTX_' + subj + '_emb.npy', emb)
    #np.save(outdir + '/' + subj + '/cosine_affinity_CTXbyCTX_' + subj + '_res.npy', res)
    # align BANDA grads to HCP grads
realigned = alignment.procrustes(emb, ref_ctx.T, center=True, scale=True)
for g in range(numGrads):
    img = nib.cifti2.Cifti2Image(emb[:,g].reshape(-1,1).T, nib.cifti2.Cifti2Header(tmp_cifti.header.matrix))
    img.to_filename(out_dir +'CTXbyCTX_controls' + '_g' + str(g+1) + '.raw.dscalar.nii')
    img = nib.cifti2.Cifti2Image(realigned[:,g].reshape(-1,1).T, nib.cifti2.Cifti2Header(tmp_cifti.header.matrix))
    img.to_filename(out_dir + 'CTXbyCTX_controls' +'_g' + str(g+1) + '.aligned2HCP.dscalar.nii')
