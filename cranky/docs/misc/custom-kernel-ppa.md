#		Custom kernel howto

## Preface

Steps to create a custom kernel and publish it as a custom ppa.

## Setup

Follow the steps documented in crank-turning-setup.md and
cranking-the-kernel.md.

### Clone kernel repository

Use cranky clone to clone the repositories required to build the kernel.
We will keep using a "disco" release as an example.
```
$ mkdir -p canonical/kernel/ubuntu
$ cd canonical/kernel/ubuntu
$ cranky clone disco:linux
```

If the command completes successfully you should be able to see the following
files:
```
$ ls -d linux-signed linux-meta linux
linux  linux-meta  linux-signed
```

At this point all the required source code are available on your local machine.

### Launchpad settings

Create a new ppa to host the new custom kernel.

For example if your ppa is called "kernel", it can be referenced as
ppa:arighi/kernel (replacing "arighi" with your actual Launchpad username).

See the following documentation if you're not familiar with the concept of PPA:
https://help.launchpad.net/Packaging/PPA

[ NOTE: make sure you have your PGP key uploaded to your Launchpad, this will
be required later to properly sign the packages ]

## Apply custom changes to the kernel

Go to the kernel source directory:
```
$ cd ~/canonical/kernel/ubuntu/disco/linux
```

Apply all the changes/patches there as a regular git repository.

Update the debian changelog in debian.master/changelog.

**Note** custom / test kernels always have a suffix "+foo" in the version string
(replace "foo" with a more descriptive name), for example 5.0.0-7.8+foo is a
test kernel based on 5.0.0-7.8.

## Build the source packages

Build the source packages using the following commands:
```
$ pwd
$ cd ~/canonical/kernel/ubuntu/disco/linux
$ cranky build-sources
```

If the command completes successfully you should see something like the following:
```
$ cd ~/canonical/kernel/ubuntu/disco
$ ls *_source.changes
linux-meta_5.0.0.7.8+foo_source.changes  linux-signed_5.0.0-7.8+foo_source.changes  linux_5.0.0-7.8+foo_source.changes
```

## Sign the source packages

All the source.changes files must be signed before uploading them to your ppa.

To do so use debsign:
```
$ debsign -k YOUR_PGP_KEY_ID linux-signed_5.0.0-7.8+foo_source.changes
$ debsign -k YOUR_PGP_KEY_ID linux-meta_5.0.0.7.8+foo_source.changes
$ debsign -k YOUR_PGP_KEY_ID linux_5.0.0-7.8+foo_source.changes
```

## Upload packages to your ppa using dput

Use the following command to upload the packages to your ppa:
```
$ dput ppa:<your_launchpad_username>/kernel linux_5.0.0-7.8+foo_source.changes
$ dput ppa:<your_launchpad_username>/kernel linux-meta_5.0.0.7.8+foo_source.changes
$ dput ppa:<your_launchpad_username>/kernel linux-signed_5.0.0-7.8+foo_source.changes
```

At this point you should receive an "Accepted" message in your inbox and you
should be able to see that the packages are building in Launchpad.

When the build process is done you should be able to add your ppa to your test
system and install your custom test kernel.
