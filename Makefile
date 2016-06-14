# TaskFarmer Makefile

# Tell make that these are phony targets.
.PHONY: all clean install uninstall

# Default C compiler (assuming Open MPI).
CC := mpicc

# Default installation directory.
PREFIX := /usr/local

# Default install command
INSTALL := install

# Flags for install command for executable.
IFLAGS_EXEC := -m 0755

# Flags for install command for non-executable files.
IFLAGS := -m 0644

# Build the taskfarmer executable.
all: taskfarmer

taskfarmer: src/taskfarmer.c
	$(CC) src/taskfarmer.c -o taskfarmer

# Remove the taskfarmer executable.
clean:
	rm -f taskfarmer

# Install the executable and man page.
install: all
	$(INSTALL) -d $(IFLAGS_EXEC) $(PREFIX)/bin
	$(INSTALL) -d $(IFLAGS_EXEC) $(PREFIX)/man
	$(INSTALL) -d $(IFLAGS_EXEC) $(PREFIX)/man/man1
	$(INSTALL) $(IFLAGS_EXEC) taskfarmer $(PREFIX)/bin
	$(INSTALL) $(IFLAGS) man/taskfarmer.1 $(PREFIX)/man/man1
	gzip -9f $(PREFIX)/man/man1/taskfarmer.1

# Uninstall the executable and man page.
uninstall:
	rm -f $(PREFIX)/bin/taskfarmer
	rm -f $(PREFIX)/man/man1/taskfarmer.1.gz
