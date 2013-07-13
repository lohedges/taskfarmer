# TaskFarmer makefile
#
# Author : Lester. O. Hedges
# Email  : lester.hedges@gmail.com
# Date   : July 11th 2013

# Common Makefile configurations

# C compiler
CC=mpicc

# Installation directory
PREFIX=/usr/local

# Install command
INSTALL=install

# Flags for install command for executable
IFLAGS_EXEC=-m 0755

# Flags for install command for non-executable files
IFLAGS=-m 0644
