# TaskFarmer makefile
#
# Author : Lester. O. Hedges
# Email  : lester.hedges@gmail.com
# Date   : July 11th 2013

# Tell make that these are phony targets
.PHONY: all clean install uninstall

include config.mk

# Build all of the executable files
all:
	$(MAKE) -C src

# Clean up the executable files
clean:
	$(MAKE) -C src clean

# Install the executable and man page
install:
	$(MAKE) -C src
	$(INSTALL) -d $(IFLAGS_EXEC) $(PREFIX)/bin
	$(INSTALL) -d $(IFLAGS_EXEC) $(PREFIX)/man
	$(INSTALL) -d $(IFLAGS_EXEC) $(PREFIX)/man/man1
	$(INSTALL) $(IFLAGS_EXEC) src/taskfarmer $(PREFIX)/bin
	$(INSTALL) $(IFLAGS) man/taskfarmer.1 $(PREFIX)/man/man1

# Uninstall the executable and man page
uninstall:
	rm -f $(PREFIX)/bin/taskfarmer
	rm -f $(PREFIX)/man/man1/taskfarmer.1
