/*
  Copyright (c) 2013, 2014 Lester Hedges <lester.hedges@gmail.com>

  This program is free software: you can redistribute it and/or modify
  it under the terms of the GNU General Public License as published by
  the Free Software Foundation, either version 3 of the License, or
  (at your option) any later version.

  This program is distributed in the hope that it will be useful,
  but WITHOUT ANY WARRANTY; without even the implied warranty of
  MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the
  GNU General Public License for more details.

  You should have received a copy of the GNU General Public License
  along with this program. If not, see <http://www.gnu.org/licenses/>.
*/

/*
  TaskFarmer: A simple task farmer for running serial tasks with mpirun.
  Run "taskfarmer -h" for help.

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
   - All tasks are read into a buffer.
   - First task is read and buffer is truncated.
   - Truncated buffer is written back to the file.
   - File is unlocked and closed (other processes can now access it).
   - Task is launched.

  Usage:

  mpirun -np CORES taskfarmer [-h] -f FILE [-v] [-w] [-s SLEEP_TIME]

  TaskFarmer supports the following short- and long-form command-line
  options.

   -h/--help                show help message and exit
   -f FILE, --file FILE     location of task file (required)
   -v, --verbose            enable verbose mode (status updates to stdout)
   -w, --wait-on-idle       wait for more tasks when idle
   -r, --retry              retry failed tasks
   -s SLEEP_TIME, --sleep-time SLEEP_TIME
                            sleep duration when idle (seconds)
   -m MAX_RETRIES, --max-retries MAX_RETRIES
                            maximum number of times to retry failed tasks

  It is possible to change the state of idle cores using the "--wait-on-idle"
  option. When set, a core will sleep for a specified period of time if it
  cannot find a task to execute. After the waiting period the process will
  check whether more tasks have been added to the task file. The amount of time
  that a process sleeps for can be changed with the "--sleep-time" option, the
  default is 300 seconds. This cycle will continue until the wall time is
  reached. By default "wait-on-idle" is deactivated meaning that each process
  exits when the task file is empty.

  The "--retry" and "--max-retries" options allow TaskFarmer to retry failed
  tasks up to a maximum number of attempts. The default number of retries is 10.

  As an example, try running the following

   shuf tests/commands.txt | head -n 100 > tasks.txt
            | mpirun -np 4 src/taskfarmer -f tasks.txt

  Tips:

   - System commands in the task file should redirect their standard output
     to a separate log file to avoid littering the standard output of
     TaskFarmer itself. As an example, the tasks.txt file could contain
     a command like

      echo "Hello, I'm a task" > job.log

     with TaskFarmer launched as follows

      mpirun -np 4 taskfarmer -f tasks.txt > sched.log

   - The wc command-line utility is handy for checking the number of remaining
     tasks in a task file without the need to trawl through any of TaskFarmer's
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
     TaskFarmer's I/O. The file should only be modified when all cores are
     active (running tasks) or in an idle state (task file is emtpy). It is
     recommended to modify the task file using a redirection, rather than
     opening it and editing directly, e.g. cat more_task >> tasks.txt.

   - Clusters that use InfiniBand interconnects can cause problems when
     using fork() in OpenMPI. A workaround can be achieved by disabling
     InfiniBand support for fork by setting the following (BASH style)
     environment variables:

        export OMPI_MCA_mpi_warn_on_fork=0
        export OMPI_MCA_btl_openib_want_fork_support=0

   - At present, when the "--retry" option is set, failed tasks are only
     relaunched by the same process on which they failed. This is fine when
     task failures are caused by buggy or unstable code, but is unlikely to
     help when failure results from a bad core or node on a cluster.

   - Very large task files containing complex shell commands can be problematic
     since each process needs to be able to load the file to memory. This
     problem can be mitigated through judicious choice of command names
     (e.g. using short form options) and use of relative paths where possible.

   - For clusters that don't impose a wall time, TaskFarmer provides a way
     of running an infinite number of tasks. As long as the task file isn't
     empty task will continue to be launched on free cores within the
     allocation. Use your new power wisely!
*/

#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <errno.h>
#include <fcntl.h>
#include <unistd.h>
#include <sys/stat.h>
#include <mpi.h>

typedef enum { false, true } bool;

// FUNCTION PROTOTYPES
void parse_command_line_arguments(int, char**, int, char*, bool*, bool*, bool*, int*, int*);
void print_help_message();
void lock_file(struct flock*, int);
void unlock_file(struct flock*, int);

// BEGIN MAIN FUNCTION
int main(int argc, char **argv)
{
    int i, attempts;
    int rank, size;

    MPI_Init(&argc, &argv);                 // start MPI
    MPI_Barrier(MPI_COMM_WORLD);            // wait for all processes to start
    MPI_Comm_rank(MPI_COMM_WORLD, &rank);   // get current process id
    MPI_Comm_size(MPI_COMM_WORLD, &size);   // get number of processes

    // set default parameters
    char task_file[1024];
    bool verbose = false;
    bool wait_on_idle = false;
    int sleep_time = 300;
    bool retry = false;
    int max_retries = 10;

    // initialize buffer pointers
    char *buffer_in;
    char *buffer_out;
    char *system_command;

    // file statistics struct
    struct stat file_stats;

    // parse all command-line arguments
    parse_command_line_arguments(argc, argv, rank, task_file,
        &verbose, &wait_on_idle, &retry, &sleep_time, &max_retries);

    // initialize file lock structure
    struct flock fl;
    fl.l_whence = SEEK_SET;
    fl.l_start = 0;
    fl.l_len = 0;
    fl.l_pid = getpid();

    // file descriptor
    int fd;

    // number of bytes read from file
    int num_read;

    // loop indefinitely
    while (true)
    {
        // try to open the task file
        if ((fd = open(task_file, O_RDWR)) == -1)
        {
            perror("[ERROR] open");
            MPI_Finalize();
            exit(1);
        }

        // attempt to lock file
        lock_file(&fl, fd);

        // get file statistics
        if (fstat(fd, &file_stats) == -1)
        {
            perror("[ERROR] fstat");
            MPI_Finalize();
            exit(1);
        }

        // allocate buffer memory
        buffer_in = malloc(file_stats.st_size);
        buffer_out = malloc(file_stats.st_size);

        // read task file into buffer
        num_read = read(fd, buffer_in, file_stats.st_size);

        // check that there are tasks to process
        if (num_read > 0)
        {
            // read first task
            for (i=0;i<num_read;i++)
            {
                // found newline
                if (buffer_in[i] == '\n') break;
            }

            // allocate memory for system command
            system_command = malloc((i+1)*sizeof(char));

            // copy task into system command buffer and terminate
            strncpy(system_command, buffer_in, i);
            system_command[i] = '\0';

            // copy remaining tasks into output buffer and terminate
            strcpy(buffer_out, buffer_in+i+1);
            buffer_out[num_read-i-1] = '\0';

            // return to start of file
            lseek(fd, 0, SEEK_SET);

            // truncate file
            ftruncate(fd, 0);

            // write truncated task list buffer to file
            write(fd, buffer_out, strlen(buffer_out));

            // attempt to unlock file
            unlock_file(&fl, fd);

            // close file descriptor
            close(fd);

            // free task file buffers
            free(buffer_in);
            free(buffer_out);

            // zero attempts
            attempts = 0;

            // report task launch
            if (verbose)
                printf("Rank %04d launching: %s\n", rank, system_command);

            // retry if task fails
            while (attempts < max_retries && system(system_command) != 0)
            {
                attempts++;

                if (verbose)
                {
                    if (retry)
                        printf("Warning: system command failed, %s (%d/%d)\n", system_command, attempts, max_retries);
                    else
                        printf("Warning: system command failed, %s\n", system_command);
                }
            }

            // free system command buffer
            free(system_command);
        }

        else
        {
            if (wait_on_idle)
            {
                // report process wait
                if (verbose)
                    printf("Rank %04d waiting for more tasks\n", rank);

                // attempt to unlock file
                unlock_file(&fl, fd);

                // close file descriptor
                close(fd);

                // free memory
                free(buffer_in);
                free(buffer_out);

                // sleep for wait period
                sleep(sleep_time);
            }

            else
            {
                // report that task file is empty
                if (verbose)
                    printf("Task file is empty: Rank %04d exiting\n", rank);

                // attempt to unlock file
                unlock_file(&fl, fd);

                // close file descriptor
                close(fd);

                // free memory
                free(buffer_in);
                free(buffer_out);

                // clean up and exit
                MPI_Finalize();
                exit(0);
            }
        }
    }

    return 0;
}
// END MAIN FUNCTION

// FUNCTION DECLARATIONS

/* Parse arguments from command-line

   Arguments:

     int argc                  number of command-line arguments
     char **argv               array of command-line arguments
     int rank                  process id
     char *task_file           pointer to task file buffer
     bool *verbose             pointer to verbose flag
     bool *wait_on_idle        pointer to wait flag
     bool *retry               pointer to retry flag
     int *sleep_time           pointer to sleep duration variable
     int *max_retries          pointer to maximum retries variable
*/
void parse_command_line_arguments(int argc, char **argv, int rank, char *task_file,
    bool *verbose, bool *wait_on_idle, bool* retry, int *sleep_time, int *max_retries)
{
    int i = 1;
    bool file;

    if (argc < 2)
    {
        if (rank == 0)
        {
            print_help_message();
        }

        MPI_Finalize();
        exit(0);
    }

    else
    {
        if (argc == 2)
        {
            if (strcmp(argv[1],"-h") == 0 || strcmp(argv[1],"--help") == 0)
            {
                if (rank == 0)
                {
                    print_help_message();
                }

                MPI_Finalize();
                exit(0);
            }
        }

        else
        {
            while (i < argc)
            {
                if (strcmp(argv[i],"-f") == 0 || strcmp(argv[i],"--file") == 0)
                {
                    i++;
                    file = true;
                    strcpy(task_file, argv[i]);
                }

                else if (strcmp(argv[i],"-v") == 0 || strcmp(argv[i],"--verbose") == 0)
                {
                    *verbose = true;
                }

                else if (strcmp(argv[i],"-w") == 0 || strcmp(argv[i],"--wait-on-idle") == 0)
                {
                    *wait_on_idle = true;
                }

                else if (strcmp(argv[i],"-r") == 0 || strcmp(argv[i],"--retry") == 0)
                {
                    *retry = true;
                }

                else if (strcmp(argv[i],"-s") == 0 || strcmp(argv[i],"--sleep-time") == 0)
                {
                    i++;
                    *sleep_time = atof(argv[i]);
                }

                else if (strcmp(argv[i],"-m") == 0 || strcmp(argv[i],"--max-retries") == 0)
                {
                    i++;
                    *max_retries = atof(argv[i]);
                }

                else if (strcmp(argv[i],"-h") == 0 || strcmp(argv[i],"--help") == 0)
                {
                    if (rank == 0)
                    {
                        print_help_message();
                    }

                    MPI_Finalize();
                    exit(0);
                }

                else
                {
                    if (rank == 0)
                    {
                        fprintf(stderr, "[ERROR]: Unknown command-line option %s\n", argv[i]);
                        fprintf(stderr, "For help run \"taskfarmer -h\"\n");
                    }

                    MPI_Finalize();
                    exit(1);
                }

                i++;
            }
        }
    }

    if (!file)
    {
        if (rank == 0)
        {
            fprintf(stderr, "[ERROR]: A task file must be specified with \"-f/--file\"\n");
            fprintf(stderr, "For help run \"taskfarmer -h\"\n");
        }

        MPI_Finalize();
        exit(1);
    }

    // only attempt to launch tasks once if retry option is unset
    if (!*retry) *max_retries = 1;
    else
    {
        // make sure number of retries is a positive, non-zero integer
        if (*max_retries <= 0)
        {
            if (rank == 0)
            {
                fprintf(stderr, "[ERROR]: Maximum number of retries must be greater than zero!\n");
            }

            MPI_Finalize();
            exit(1);
        }
    }

    if (*wait_on_idle)
    {
        // make sure sleep time is a positive, non-zero integer
        if (*sleep_time <= 0)
        {
            if (rank == 0)
            {
                fprintf(stderr, "[ERROR]: Sleep time must be greater than zero!\n");
            }

            MPI_Finalize();
            exit(1);
        }
    }
}

// Print help message to stdout
void print_help_message()
{
    puts("TaskFarmer - a simple task farmer for running serial tasks with mpirun.\n\n"
         "Usage: mpirun -np CORES taskfarmer [-h] -f FILE [-v] [-w] [-r] [-s SLEEP_TIME] [-m MAX_RETRIES]\n\n"

         "Available options:\n"
         " -h/--help                 : Print this help information\n"
         " -f/--file <string>        : Location of task file (required)\n"
         " -v/--verbose              : Print status updates to stdout\n"
         " -w/--wait-on-idle         : Wait for more tasks when idle\n"
         " -r/--retry                : Retry failed tasks\n"
         " -s/--sleep-time <int>     : Sleep duration when idle (seconds)\n"
         " -m/--max-retries <int>    : Maximum number of retries for failed tasks\n");
}

/* Attempt to acquire a file lock

   Arguments:

     struct flock *fl          pointer to file lock structure
     int fd                    file descriptor
*/
void lock_file(struct flock *fl, int fd)
{
    // set to write/exclusive lock
    fl->l_type = F_WRLCK;

    // try to lock file
    if (fcntl(fd, F_SETLKW, fl) == -1)
    {
        perror("[ERROR] fcntl");
        MPI_Finalize();
        exit(1);
    }
}

/* Attempt to release a file lock

   Arguments:

     struct flock *fl          pointer to file lock structure
     int fd                    file descriptor
*/
void unlock_file(struct flock *fl, int fd)
{
    // set to unlocked
    fl->l_type = F_UNLCK;

    // try to unlock file
    if (fcntl(fd, F_SETLK, fl) == -1)
    {
        perror("[ERROR] fcntl");
        MPI_Finalize();
        exit(1);
    }
}
