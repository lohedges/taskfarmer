# TaskFarmer

Copyright &copy; 2013, 2014 Lester Hedges.
Released under the [GPL](http://www.gnu.org/copyleft/gpl.html).

## About
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

* A process opens the task file and obtains an exclusive lock.
* All tasks are read into a buffer.
* First task is read and buffer is truncated.
* Truncated buffer is written back to the file.
* File is unlocked and closed (other processes can now access it).
* Task is launched.

A Python implementation is provided in the `python/` directory, although this
is known to suffer from significant start up lag on clusters that don't
natively support Python shared libraries on their compute nodes.

## Installation
A `Makefile` is included for building and installing TaskFarmer. You will first
need to make sure that you have [Open MPI](http://www.open-mpi.org/) installed.
If you use an alternative MPI implementation, such as `aprun` on the Cray Linux
Environment (CLE), you will need to change the compiler in `config.mk`
accordingly (change to `cc` for compiling on
[Hopper](http://www.nersc.gov/users/computational-systems/hopper/) at
[NERSC](http://www.nersc.gov/)). You can also use `config.mk` to configure other
options, such as the installation path.

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
$ mpirun -np CORES taskfarmer [-h] -f FILE [-v] [-w] [-r] [-s SLEEP_TIME] [-m MAX_RETRIES]
```

TaskFarmer supports the following short- and long-form command-line
options:

	-h/--help               show help message and exit
	-f FILE, --file FILE    location of task file (required)
	-v, --verbose           enable verbose mode (status updates to stdout)
	-w, --wait-on-idle      wait for more tasks when idle
	-r, --retry             retry failed tasks
	-s SLEEP_TIME, --sleep-time SLEEP_TIME
	                        sleep duration when idle (seconds)
	-m MAX_RETRIES, --max-retries MAX_RETRIES
	                        maximum number of times to retry failed tasks

It is possible to change the state of idle cores using the `--wait-on-idle`
option. When set, a core will sleep for a specified period of time if it
cannot find a task to execute. After the waiting period the process will
check whether more tasks have been added to the task file. The amount of time
that a process sleeps for can be changed with the `--sleep-time` option, the
default is 300 seconds. This cycle will continue until the wall time is
reached. By default `wait-on-idle` is deavtivated meaning that each process
exits when the task file is empty.

The `--retry` and `--max-retries` options allow TaskFarmer to retry failed
tasks up to a maximum number of attempts. The default number of retries is 10.

## Examples
Try the following:

``` bash
$ shuf examples/commands.txt | head -n 100 > tasks.txt | mpirun -np 4 src/taskfarmer -f tasks.txt
```

A collection of example [PBS](http://en.wikipedia.org/wiki/Portable_Batch_System) and
[SLURM](https://computing.llnl.gov/linux/slurm/) batch scripts are included in the `examples/` directory.

## Tips
* System commands in the task file should redirect their standard output
  to a separate log file to avoid littering the standard output of TaskFarmer
  itself. As an example, the `tasks.txt` file could contain a command like

	``` bash
	$ echo "Hello, I'm a task" > job.log
	```

   with TaskFarmer launched as follows

	``` bash
	$ mpirun -np 4 taskfarmer -f tasks.txt > sched.log
	```

* The `wc` command-line utility is handy for checking the number of remaining
  tasks in a task file without the need to trawl through any of TaskFarmer's
  logs. For example, if task files are stored in a directory called `task_files`
  then the following command will provide a concise output showing the number of
  remaining tasks in each file as well as the total.

	``` bash
	$ wc -l task_files/*
	```

* Since tasks are read from the task file line-by-line it is possible to
  introduce dependencies between tasks by placing multiple tasks on a single
  line separated by semicolons. For example

	``` bash
	$ perform_calculation > data.txt; analyze_data < data.txt
	```

## Words of caution

* When individual simulations are very short it is probably dangerous to
  modify the task file externally as it will likely conflict with TaskFarmer's
  I/O. The file should only be modified when all cores are active (running tasks)
  or in an idle state (task file is emtpy). It is recommended to modify the task
  file using a redirection, rather than opening it and editing directly,
  e.g. `cat more_tasks >> tasks.txt`.
* Clusters that use InfiniBand interconnects can cause problems when using fork()
  in OpenMPI. A workaround can be achieved by disabling InfiniBand support for
  fork by setting the following (BASH style) environment variables:

``` bash
$ export OMPI_MCA_mpi_warn_on_fork=0
$ export OMPI_MCA_btl_openib_want_fork_support=0
```
* At present, when the `--retry` option is set, failed tasks are only relaunched
  by the same process on which they failed. This is fine when task failures are
  caused by buggy or unstable code, but is unlikely to help when failure results
  from a bad core or node on a cluster.

* Very large task files containing complex shell commands can be problematic since
  each process needs to be able to load the file to memory. This problem can be
  mitigated through judicious choice of command names (e.g. using short form
  options) and use of relative paths where possible.

* For clusters that don't impose a wall time, TaskFarmer provides a way of
  running an infinite number of tasks. As long as the task file isn't empty tasks
  will continue to be launched on free cores within the allocation. Use your new
  power wisely!
