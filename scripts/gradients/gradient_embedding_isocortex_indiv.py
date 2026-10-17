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

# argv[0] is always the script itself
subj = sys.argv[1]
datadir = '/work/swglab/data/BANDA_U01/analysis/proj_clare_networkICA/clare_U01masks_ICA/data/BIDS/dataset'
#outdir = '/work/swglab/data/BANDA_U01/analysis/proj_clare_networkICA/clare_U01masks_ICA/fc_gradients'
outdir = '/scratch/katsumi/BANDA/fc_gradients'
numGrads = 10
mw_mask = np.loadtxt(outdir + '/medialwall.txt')

tmp = nib.nifti2.load(outdir + '/100307_tfMRI_MOTOR_level2_hp200_s2.cortex_only.1map.dscalar.nii')
tmp_cifti = nib.cifti2.load(outdir + '/100307_tfMRI_MOTOR_level2_hp200_s2.cortex_only.1map.dscalar.nii')

hcp1003_ctx_gradients = nib.cifti2.load('/work/swglab/data/BANDA_U01/analysis/proj_clare_networkICA/clare_U01masks_ICA/fc_gradients/HCP3T_N1003_isocortical_gradients_signFlipped.dscalar.nii').get_fdata()
ref_ctx = hcp1003_ctx_gradients[0:10,:]

if not os.path.exists(outdir + '/' + subj):
    os.mkdir(outdir + '/' + subj)

aff = np.zeros([59412, 59412]) ##cifti resolution
run_count = 0
for r in range(4):
    thisRunBOLD = datadir + '/' + subj + '/func/ds' + subj + ('_run-%02d' % (r+1)) + '_bold.nii'
    if os.path.exists(thisRunBOLD):
        run_count += 1

for r in range(run_count):
    thisRunBOLD = datadir + '/' + subj + '/func/ds' + subj + ('_run-%02d' % (r + 1)) + '_bold.nii'
    data_bh = []
    gii = transforms.mni152_to_fslr(thisRunBOLD, '32k')
    # save con.gii
    nib.save(gii[0], outdir + '/' + subj + '/' + subj + '_run-%02d' % (r + 1) + '_bold_lh.func.gii')
    nib.save(gii[1], outdir + '/' + subj + '/' + subj + '_run-%02d' % (r + 1) + '_bold_rh.func.gii')
    data_bh = np.concatenate((gii[0].agg_data(),gii[1].agg_data()), axis = 1)
    data_bh_noMW = data_bh[:,np.where(mw_mask==0)[0]]
    R = np.corrcoef(data_bh_noMW.T)
    perc = np.array([np.percentile(x, 90) for x in R])
    for i in range(R.shape[0]):
        R[i, R[i,:] < perc[i]] = 0
    R[R < 0] = 0
    aff += 1 - pairwise_distances(R, metric='cosine')

aff /= run_count
np.save(outdir + '/' + subj + '/cosine_affinity_CTXbyCTX_' + subj + '_aff.npy', aff)
print('Computing FC gradients based on %d runs.' % run_count)
emb, res = embed.compute_diffusion_map(aff, n_components=10, alpha=0.5, return_result=True)
np.save(outdir + '/' + subj + '/cosine_affinity_CTXbyCTX_' + subj + '_emb.npy', emb)
np.save(outdir + '/' + subj + '/cosine_affinity_CTXbyCTX_' + subj + '_res.npy', res)
# align BANDA grads to HCP grads
realigned = alignment.procrustes(emb, ref_ctx.T, center=True, scale=True)
for g in range(numGrads):
    img = nib.cifti2.Cifti2Image(emb[:,g].reshape(-1,1).T, nib.cifti2.Cifti2Header(tmp_cifti.header.matrix))
    img.to_filename(outdir + '/' + subj + '/CTXbyCTX_' + subj + '_g' + str(g+1) + '.raw.dscalar.nii')
    img = nib.cifti2.Cifti2Image(realigned[:,g].reshape(-1,1).T, nib.cifti2.Cifti2Header(tmp_cifti.header.matrix))
    img.to_filename(outdir + '/' + subj + '/CTXbyCTX_' + subj + '_g' + str(g+1) + '.aligned2HCP.dscalar.nii')
