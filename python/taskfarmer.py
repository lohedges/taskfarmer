#!/usr/bin/env python2

# Copyright (C) 2013 Lester Hedges <lester.hedges@gmail.com>
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program. If not, see <http://www.gnu.org/licenses/>.

"""A simple Python task farmer for running serial jobs with mpirun.

About:

Execute a list of system commands from a job file one-by-one. This allows
many simulations to be run within a single mpirun allocation. A new job is
launched whenever a process becomes available, hence ensuring 100% utilization
of the cores for the duration of the wall time, or until the job file is
empty, whichever occurs first. This is useful for running many short
simulations on a small number of cores, or to avoid resource wastage when
individual simulations have markedly different run times. The job file can
be updated dynamically, allowing simulations to be added or deleted as
required.

A master-worker type scenario is avoided by exploiting a file lock. This
ensures that only one process has access to the job file at any given time.

The order of operations is as follows:

    - A process opens the job file and obtains an exclusive lock.
    - Jobs are read into a list.
    - First job is popped off the list.
    - Truncated list is written back to the file.
    - File is unlocked and closed (other processes can now access it).
    - Job is checked for validity and executed.

Usage:

    mpirun -np CORES taskfarmer.py [-h] -f FILE [-v] [-w] [-s SLEEP_TIME]
                        [-d [DISALLOWED [DISALLOWED ...]]]

PyTaskFarmer supports the following short- and long-form command-line
options.

    -h/--help               show help message and exit
    -f FILE, --file FILE    location of job file (required)
    -v, --verbose           enable verbose mode (status updates to stdout)
    -w, --wait-on-idle      wait for more jobs when idle
    -s SLEEP_TIME, --sleep-time SLEEP_TIME
                            sleep duration when idle (seconds)
    -d [DISALLOWED [DISALLOWED ...]], --disallowed [DISALLOWED [DISALLOWED ...]]
                            list of disallowed commands

Commands from the job file are checked against the "disallowed" list before
being executed. This avoids undesired consequences if the job file is
corrupted, or if I/O error is encountered.

It is possible to change the state of idle cores using the "wait-on-idle"
option. When set to "True" a core will sleep for a specified period of time
if it cannot find a job to execute. After the waiting period the process will
check whether more jobs have been added to the job file. The amount of time
that a process sleeps for can be changed with the "sleep-time" option, the
default is 300 seconds. This cycle will continue until the wall time is
reached. By default "wait-on-idle" is set to "False" meaning that each process
calls "sys.exit()" when the job file is empty.

As an example, try running the following:

    shuf tests/commands.txt | head -n 100 > jobs.txt
            | mpirun -np 4 taskfarmer.py -f jobs.txt

Tips:

    - System commands in the job file should redirect their standard output
      to a separate log file to avoid littering the standard output of
      PyTaskFarmer itself. As an example, the jobs.txt file could contain a
      command like

            echo "Hello, I'm a job" > job.log

      with PyTaskFarmer launched as follows

            mpirun -np 4 taskfarmer.py -f jobs.txt > sched.log

Words of caution:

    - When individual simulations are very short it is probably dangerous
      to modify the job file externally as it will likely conflict with
      PyTaskFarmer's I/O. The file should only be modified when all cores are
      active (running jobs) or in an idle state (job file is emtpy). It is
      recommended to modify the job file using a redirection, rather than
      opening it and editing directly, e.g. cat more_jobs >> jobs.txt.

    - For clusters that don't impose a wall time, PyTaskFarmer provides a way
      of running an infinite number of jobs. As long as the job file isn't
      empty jobs will continue to be launched on free cores within the
      allocation. Use your new power wisely!
"""

import os
import sys
import time
import argparse
from mpi4py import MPI
from fcntl import flock, LOCK_EX, LOCK_UN

# process rank
rank = MPI.COMM_WORLD.Get_rank()

# create argument parser object
parser = argparse.ArgumentParser(description=
        'A simple Python task farmer for running serial jobs with mpirun.')

# parse command-line options
parser.add_argument('-f','--file', type=str,
        help='location of job file', required=True)
parser.add_argument('-v','--verbose', action='store_true',
        help='enable verbose mode', default=False)
parser.add_argument('-w','--wait-on-idle', action='store_true',
        help='wait for more jobs when idle', default=False)
parser.add_argument('-s','--sleep-time', type=int,
        help='sleep duration when idle (seconds)', default=300)
parser.add_argument('-d','--disallowed', nargs='*',
        help='disallowed commands', default=['rm'])
args = parser.parse_args()

# check if command is valid
def is_allowed(job):
    # check command isn't empty string
    if job.isspace():
        return False, "job string is empty"

    # check for null character
    if '\x00' in job:
        return False, "null character present"

    # check command isn't empty
    if len(job) is 0:
        return False, "job string has zero length"

    # check all disallowed commands
    for cmd in args.disallowed:
        cmd1 = cmd + " "
        cmd2 = " " + cmd + " "

        # invalid command
        if (job.startswith(cmd1)) or (cmd2 in job):
            return False, cmd + " found"

    return True, "no error"

# loop indefinitely
while True:
    # try to open the job file
    try:
        f = open(args.file, 'r+')
    except IOError:
        print >> sys.stderr, "I/O Error:", job_file, "doesn't exist!"
        sys.exit()

    # lock file
    flock(f, LOCK_EX)

    # read file into job list
    jobs = f.readlines()

    # work out number of jobs
    num_jobs = len(jobs)

    # check that there are jobs to process
    if num_jobs > 0:
        # pop first job off job list
        job = jobs.pop(0).strip('\n')

        # rewind to beginning of file
        f.seek(0)
        f.truncate()

        # write remaining job list to file
        f.writelines(jobs)

        # ensure buffer is flushed before unlocking
        f.flush()

        # unlock and close file
        flock(f, LOCK_UN)
        f.close()

        # check that job is allowed
        allowed, error = is_allowed(job)
        if allowed:
            if args.verbose:
                print "Rank %04d" %rank, "launching:", job
            # execute job
            if os.system(job) != 0:
                print >> sys.stderr, "Warning: system command failed,", job
        else:
            print >> sys.stderr, "Warning:", error

    else:
        if args.wait_on_idle:
            # sleep for wait period
            if args.verbose:
                print "Rank %04d" %rank, "waiting for more jobs"

            # unlock and close file
            flock(f, LOCK_UN)
            f.close()

            # sleep
            time.sleep(args.sleep_time)
        else:
            # all jobs launched, clean up and exit
            if args.verbose:
                print "Job file is empty: Rank %04d" %rank, "exiting"

            # unlock and close file
            flock(f, LOCK_UN)

            # exit
            sys.exit()
