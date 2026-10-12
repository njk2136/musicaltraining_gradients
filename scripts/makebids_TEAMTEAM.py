#!/usr/bin/env python

#Preprocessing script for music naturalistic network study (June 2018)

import sys,os
from subprocess import call, check_output
import argparse
from datetime import datetime
import re
import shutil
import numpy as np 
import json

starttime = datetime.now()

#logging colors
sectionColor = "\033[94m"
sectionColor2 = "\033[96m"
groupColor = "\033[90m"
mainColor = "\033[92m"

pink = '\033[95m'
yellow = '\033[93m'
red = '\033[91m'

ENDC = '\033[0m'
BOLD = '\033[1m'
UNDERLINE = '\033[4m'

#command line options - NEED TO INPUT THE PROJECT AND SUBJECTS
#i.e. ./makebids.py --project "MCI_Study" --all
parser = argparse.ArgumentParser()
parser.add_argument("--subjects",help="process listed subjects",nargs='+',action="store")
parser.add_argument("--project",help="process listed subjects",nargs='+',action="store")
parser.add_argument("--all",help="process all subjects", action="store_true")
args = parser.parse_args()

#get project name
project = args.project

#set paths
if project == 'TEAMTEAM_Study':
    tasks = ['task-muskid', 'task-stress_base', 'task-stress_run01','task-stress_run02', 'task-stress_run03']
    trs = [457,334,336,336,336]
else:
    tasks = ['rest']
    trs = [947]
pathbase = "/scratch/lopez.ke/"
projectpath = os.path.join(pathbase,project[0])
dicompath = os.path.join(projectpath,"dicom")
configfile = os.path.join(projectpath,"config_TEAMTEAM.json")
bidsout = os.path.join(projectpath,"raw_bids")
if not os.path.exists(bidsout):
    os.mkdir(bidsout)

#develop list of subjects
subjects = args.subjects

# #Get list of subjects
if args.all:
    subjects = [elem for elem in os.listdir(dicompath) if ".DS" not in elem]
    subjects.sort()
    
#
#Give error if argument not specified
if subjects:
    print(pink + "Running dcm2bids for %d subjects of project %s%s" %(len(subjects),project,mainColor))
else:
    print("Subjects must be specified. Use --all for all subjects or --subjects to list specific subjects.")
    sys.exit()
#
##function to check for success of feat analysis
def checkfile(subjectfunc):
    print(subjectfunc)
    for i,task in enumerate(tasks):
        realtr = trs[i]
        testfiles = [elem for elem in os.listdir(subjectfunc) if task in elem]
        testfiles = [elem for elem in testfiles if '.nii.gz' in elem]
        if len(testfiles) == 1:
            continue
        else:
            for e in testfiles:
                testfile = os.path.join(subjectfunc,e)
                testjson = re.sub('.nii.gz','.json',testfile)
                command = 'fslinfo %s' %testfile
                results = check_output(command,shell = True)
                tr = results.split()[9]
                if int(realtr) != int(tr):
                    print(red + '%s has %sTR. Deleting...%s' %(testfile,tr,mainColor))
                    os.remove(testfile)
                    os.remove(testjson)
                else:
                    #rename BOLD NIFTI
                    newname = re.sub('run-...','',testfile)
                    print(sectionColor + 'Renaming %s to %s because TR = %s%s' %(testfile,newname,tr,mainColor))
                    os.rename(testfile,newname)
                    
                    #Rename JSON
                    newjson = re.sub('run-...','',testjson)
                    print(sectionColor + 'Renaming %s to %s because TR = %s%s' %(testfile,newname,tr,mainColor))
                    os.rename(testjson,newjson)

        
        
#convert from DICOM to NIFTI and put in neurobids in fmri_data
def makebids(subjects):
    for i,sub in enumerate(subjects):
        subid = 'sub-%s' %format(i+1, "03")
        subjectdicom = os.path.join(dicompath,sub)
        subjectnifti = os.path.join(bidsout,subid,'fmap')
        subjectfunc = os.path.join(bidsout,subid,'func')
        if not os.path.exists(subjectnifti):
            print(sectionColor + "Converting %s's files to NIFTI as %s%s"  % (sub,subid,mainColor))
            command = "dcm2bids -d %s -p %s -c %s -o %s" %(subjectdicom,subid,configfile,bidsout)
            print(command)
            call(command,shell = True)
        else:
            print(sectionColor2 + "%s already converted to NIFTI, located at %s. Moving on %s"  % (sub,subjectnifti,mainColor))
        
        #make sure it's the right length, if not delete and rename the correct one
        checkfile(subjectfunc)

def makejson(datatype):
    for task in tasks:
        taskjson = bidsout + '/' + 'task-' + task + '_bold.json'
        json_content = '"TaskName":"%s"' %task
        if not os.path.exists(taskjson):
            srcs = [elem for elem in os.listdir(os.path.join(bidsout,'sub-01',datatype)) if task in elem]
            srcs = [elem for elem in srcs if '.json' in elem]
            srcjson = os.path.join(bidsout,'sub-01',datatype,srcs[0])
            with open(srcjson) as jsonfile:
                data = json.load(jsonfile)
            data

    #     with
    #         data = json.load(jsonfile)
    #     data.update(json_content)
    #     print data
    #     # with open(taskjson,'w') as jsonfile:
    #     #     json.dump(data,jsonfile,indent = 4)
    #
    #
    # print 'Copying' + src,taskjson
    # shutil.copy2(src,taskjson)
    
#call the functions
makebids(subjects)


#####################
#TO DO 
######################

#FIELDMAPS
# 01 - rest/musbid
# 02 - mid
# 03 - dti

#makejson('func')
        
    # testfile = featfolder + "/filtered_func_data.nii.gz"
    # command = fslinfo =
    # if not os.path.exists(testfile):
    #     print red + "WARNING: ANALYSIS DID NOT COMPLETE FOR %s%s" %(featfolder, mainColor)
    #     logfile.write("%s: WARNING: ANALYSIS DID NOT COMPLETE FOR %s\n" % (datetime.now().strftime('%I:%M:%S%p'),featfolder))
    #     sys.exit()
