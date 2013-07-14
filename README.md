# TaskFarmer

Copyright &copy; 2013 Lester Hedges.

## About
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

* A process opens the job file and obtains an exclusive lock.
* All jobs are read into a buffer.
* First job is read and buffer is truncated.
* Truncated buffer is written back to the file.
* File is unlocked and closed (other processes can now access it).
* Job is launched.

A Python implementation is provided in the `python/` directory, although this
is known to suffer from significant start up lag on clusters that don't
natively support Python shared libraries on their compute nodes.

## Installation
A `Makefile` is included for building and installing TaskFarmer. You will first
need to make sure that you have [Open MPI](http://www.open-mpi.org/) installed.
If you use an alternative MPI implementation (e.g. cray-mpich2) you will need
to change the compiler in `config.mk` accordingly. You can also use `config.mk`
to configure other options, such as the installation path.

To compile TaskFarmer, then install the executable and man page:

```bash
$ make
$ sudo make install
```

TaskFarmer can be completely removed from your system as follows:

```bash
$ sudo make uninstall
```

## Usage
``` bash
$ mpirun -np CORES taskfarmer [-h] -f FILE [-v] [-w] [-s SLEEP_TIME]
```

TaskFarmer supports the following short- and long-form command-line
options:

	-h/--help               show help message and exit
	-f FILE, --file FILE    location of job file (required)
	-v, --verbose           enable verbose mode (status updates to stdout)
	-w, --wait-on-idle      wait for more jobs when idle
	-s SLEEP_TIME, --sleep-time SLEEP_TIME
	                        sleep duration when idle (seconds)

It is possible to change the state of idle cores using the `--wait-on-idle`
option. When set, a core will sleep for a specified period of time if it
cannot find a job to execute. After the waiting period the process will
check whether more jobs have been added to the job file. The amount of time
that a process sleeps for can be changed with the `--sleep-time` option, the
default is 300 seconds. This cycle will continue until the wall time is
reached. By default `wait-on-idle` is deavtivated meaning that each process
exits when the job file is empty.

## Examples
Try the following:

``` bash
$ shuf tests/commands.txt | head -n 100 > jobs.txt | mpirun -np 4 src/taskfarmer -f jobs.txt
```

An example PBS submit script is included in the `tests` directory.

## Tips
* System commands in the job file should redirect their standard output
  to a separate log file to avoid littering the standard output of TaskFarmer
  itself. As an example, the `jobs.txt` file could contain a command like

	``` bash
	$ echo "Hello, I'm a job" > job.log
	```

   with TaskFarmer launched as follows

	``` bash
	$ mpirun -np 4 taskfarmer -f jobs.txt > sched.log
	```

## Words of caution

* When individual simulations are very short it is probably dangerous to
  modify the job file externally as it will likely conflict with TaskFarmer's
  I/O. The file should only be modified when all cores are active (running jobs)
  or in an idle state (job file is emtpy). It is recommended to modify the job
  file using a redirection, rather than opening it and editing directly,
  e.g. `cat more_jobs >> jobs.txt`.
* For clusters that don't impose a wall time, TaskFarmer provides a way of
  running an infinite number of jobs. As long as the job file isn't empty jobs
  will continue to be launched on free cores within the allocation. Use your new
  power wisely!
