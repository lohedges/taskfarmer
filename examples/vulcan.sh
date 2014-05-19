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

# load openmpi module
module load openmpi

# make sure we're in the right directory
cd /clusterfs/vulcan/pscratch/$user/taskfarmer

# set correct compiler
sed -i '/CC=*/c\CC=mpicc' config.mk

# recompile code
make clean
make

# create task list
shuf examples/commands.txt | head -n 200 > tasks.txt

# delete existing log file
if [ -f log ]; then
    rm log
fi

# disable InfiniBand support for fork
export OMPI_MCA_mpi_warn_on_fork=0
export OMPI_MCA_btl_openib_want_fork_support=0

# launch task farmer
mpirun -np 16 src/taskfarmer -f tasks.txt -v
