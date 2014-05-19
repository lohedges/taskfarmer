#!/usr/bin/env bash
#SBATCH --job-name=test
#SBATCH --partition=vulcan
#SBATCH --account=vulcan
#SBATCH --qos=vulcan_debug
#SBATCH --nodes=2
#SBATCH --ntasks-per-node=8
#SBATCH --time=00:05:00
#SBATCH --export=ALL

# get user name
user=`whoami`

# make sure we're in the right directory
cd /clusterfs/vulcan/pscratch/$user/taskfarmer/python

# create task list
shuf examples/commands.txt | head -n 200 > tasks.txt

# delete existing log file
if [ -f log ]; then
    rm log
fi

# load python modules
module load python/2.7.3 mpi4py

# launch task farmer
mpirun -np 16 taskfarmer.py -f tasks.txt -v
