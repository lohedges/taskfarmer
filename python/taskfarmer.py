#!/usr/bin/env python2

# Copyright (c) 2013, 2014 Lester Hedges <lester.hedges@gmail.com>
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

"""A simple Python task farmer for running serial tasks with mpirun.

About:

Execute a list of system commands from a task file one-by-one. This allows
many simulations to be run within a single mpirun allocation. A new task is
launched whenever a process becomes available, hence ensuring 100% utilization
of the cores for the duration of the wall time, or until the task file is
empty, whichever occurs first. This is useful for running many short
simulations on a small number of cores, or to avoid resource wastage when
individual simulations have markedly different run times. The task file can
be updated dynamically, allowing simulations to be added or deleted as
required.

A master-worker type scenario is avoided by exploiting a file lock. This
ensures that only one process has access to the task file at any given time.

The order of operations is as follows:

    - A process opens the task file and obtains an exclusive lock.
    - tasks are read into a list.
    - First task is popped off the list.
    - Truncated list is written back to the file.
    - File is unlocked and closed (other processes can now access it).
    - Task is checked for validity and executed.

Usage:

    mpirun -np CORES taskfarmer.py [-h] -f FILE [-v] [-w] [-r]
        [-s SLEEP_TIME] [-m MAX_RETRIES] [-d [DISALLOWED [DISALLOWED ...]]]

PyTaskFarmer supports the following short- and long-form command-line
options.

    -h/--help               show help message and exit
    -f FILE, --file FILE    location of task file (required)
    -v, --verbose           enable verbose mode (status updates to stdout)
    -w, --wait-on-idle      wait for more tasks when idle
    -r, --retry             retry failed tasks
    -s SLEEP_TIME, --sleep-time SLEEP_TIME
                            sleep duration when idle (seconds)
    -m MAX_RETRIES, --max-retries MAX_RETRIES
                            maximum number of times to retry failed tasks
    -d [DISALLOWED [DISALLOWED ...]], --disallowed [DISALLOWED [DISALLOWED ...]]
                            list of disallowed commands

Commands from the task file are checked against the "disallowed" list before
being executed. This avoids undesired consequences if the task file is
corrupted, or if I/O error is encountered.

It is possible to change the state of idle cores using the "wait-on-idle"
option. When set to "True" a core will sleep for a specified period of time
if it cannot find a task to execute. After the waiting period the process will
check whether more tasks have been added to the task file. The amount of time
that a process sleeps for can be changed with the "sleep-time" option, the
default is 300 seconds. This cycle will continue until the wall time is
reached. By default "wait-on-idle" is set to "False" meaning that each process
calls "sys.exit()" when the task file is empty.

The "--retry" and "--max-retries" options allow PyTaskFarmer to retry failed
tasks up to a maximum number of attempts. The default number of retries is 10.

As an example, try running the following:

    shuf tests/commands.txt | head -n 100 > tasks.txt
            | mpirun -np 4 taskfarmer.py -f tasks.txt

Tips:

    - System commands in the task file should redirect their standard output
      to a separate log file to avoid littering the standard output of
      PyTaskFarmer itself. As an example, the tasks.txt file could contain a
      command like

            echo "Hello, I'm a task" > job.log

      with PyTaskFarmer launched as follows

            mpirun -np 4 taskfarmer.py -f tasks.txt > sched.log

    - The wc command-line utility is handy for checking the number of remaining
      tasks in a task file without the need to trawl through any of PyTaskFarmer's
      logs. For example, if task files are stored in a directory called task_files
      then the following command will provide a concise output showing the number of
      remaining tasks in each file as well as the total.

            wc -l task_files/*

    - Since tasks are read from the task file line-by-line it is possible to
      introduce dependencies between tasks by placing multiple tasks on a single
      line separated by semicolons. For example

            perform_calculation > data.txt; analyze_data < data.txt

Words of caution:

    - When individual simulations are very short it is probably dangerous
      to modify the task file externally as it will likely conflict with
      PyTaskFarmer's I/O. The file should only be modified when all cores are
      active (running tasks) or in an idle state (task file is emtpy). It is
      recommended to modify the task file using a redirection, rather than
      opening it and editing directly, e.g. cat more_tasks >> tasks.txt.

    - At present, when the "--retry" option is set, failed tasks are only
      relaunched by the same process on which they failed. This is fine when
      task failures are caused by buggy or unstable code, but is unlikely to
      help when failure results from a bad core or node on a cluster.

    - Very large task files containing complex shell commands can be problematic
      since each process needs to be able to load the file to memory. This
      problem can be mitigated through judicious choice of command names
      (e.g. using short form options) and use of relative paths where possible.

    - For clusters that don't impose a wall time, PyTaskFarmer provides a way
      of running an infinite number of tasks. As long as the task file isn't
      empty tasks will continue to be launched on free cores within the
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

# validate positive, non-zero arguments
class validate_argument(argparse.Action):
    def __call__(self, parser, namespace, values, option_string=None):
        if values <= 0:
            parser.error("{0} must be greater than zero.".format(option_string))

        setattr(namespace, self.dest, values)

# create argument parser object
parser = argparse.ArgumentParser(description=
    'A simple Python task farmer for running serial tasks with mpirun.')

# parse command-line options
parser.add_argument('-f','--file', type=str,
    help='location of task file', required=True)
parser.add_argument('-v','--verbose', action='store_true',
    help='enable verbose mode', default=False)
parser.add_argument('-w','--wait-on-idle', action='store_true',
    help='wait for more tasks when idle', default=False)
parser.add_argument('-r','--retry', action='store_true',
    help='retry failed tasks', default=False)
parser.add_argument('-s','--sleep-time', action=validate_argument, type=int,
    help='sleep duration when idle (seconds)', default=300)
parser.add_argument('-m','--max-retries', action=validate_argument, type=int,
    help='maximum times to retry failed tasks', default=10)
parser.add_argument('-d','--disallowed', nargs='*',
    help='disallowed commands', default=['rm'])
args = parser.parse_args()

# only attempt to launch tasks once if retry option is unset
if not args.retry:
    max_retries = 1

# check if command is valid
def is_allowed(task):
    # check command isn't empty string
    if task.isspace():
        return False, "task string is empty"

    # check for null character
    if '\x00' in task:
        return False, "null character present"

    # check command isn't empty
    if len(task) is 0:
        return False, "task string has zero length"

    # check all disallowed commands
    for cmd in args.disallowed:
        cmd1 = cmd + " "
        cmd2 = " " + cmd + " "

        # invalid command
        if (task.startswith(cmd1)) or (cmd2 in task):
            return False, cmd + " found"

    return True, "no error"

# loop indefinitely
while True:
    # try to open the task file
    try:
        f = open(args.file, 'r+')
    except IOError:
        print >> sys.stderr, "I/O Error:", task_file, "doesn't exist!"
        sys.exit()

    # lock file
    flock(f, LOCK_EX)

    # read file into task list
    tasks = f.readlines()

    # work out number of tasks
    num_tasks = len(tasks)

    # check that there are tasks to process
    if num_tasks > 0:
        # pop first task off task list
        task = tasks.pop(0).strip('\n')

        # rewind to beginning of file
        f.seek(0)
        f.truncate()

        # write remaining task list to file
        f.writelines(tasks)

        # ensure buffer is flushed before unlocking
        f.flush()

        # unlock and close file
        flock(f, LOCK_UN)
        f.close()

        # zero attempts
        attempts = 0

        # check that task is allowed
        allowed, error = is_allowed(task)
        if allowed:
            if args.verbose:
                print "Rank %04d" %rank, "launching:", task

            # attempt to execute task
            while attempts < args.max_retries and os.system(task) != 0:
                attempts += 1
                if args.verbose:
                    if args.retry:
                        print >> sys.stderr, "Warning: system command failed,", \
                            task, "(%d/%d)" % (attempts, args.max_retries)
                    else:
                        print >> sys.stderr, "Warning: system command failed,", task
        else:
            print >> sys.stderr, "Warning:", error

    else:
        if args.wait_on_idle:
            # sleep for wait period
            if args.verbose:
                print "Rank %04d" %rank, "waiting for more tasks"

            # unlock and close file
            flock(f, LOCK_UN)
            f.close()

            # sleep
            time.sleep(args.sleep_time)
        else:
            # all tasks launched, clean up and exit
            if args.verbose:
                print "Task file is empty: Rank %04d" %rank, "exiting"

            # unlock and close file
            flock(f, LOCK_UN)

            # exit
            sys.exit()
