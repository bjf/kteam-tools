#!/bin/bash

patch="${0%.trigger}"
series="$1"
build="$2"

if ! egrep -q -s 'BOOT_TARGETS1 :=.* vmlinux\.strip' arch/powerpc/Makefile; then
	git am -C0 "$patch"
fi
