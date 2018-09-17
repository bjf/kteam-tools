#!/usr/bin/python3

import os
import sys
import yaml

sys.path.append(os.path.realpath(os.path.join(os.path.dirname(__file__), os.pardir, os.pardir, 'libs')))

from ktl.kernel_series              import KernelSeries


def abort(msg):
    print(msg, file=sys.stderr)
    sys.exit(1)


class Config:
    def __init__(self, filename=None):
        if not filename:
            for path in (
                os.path.join(os.environ['HOME'], '.cranky.yaml'),
                os.path.join(os.environ['HOME'], '.cranky'),
                ):
                if os.path.exists(path):
                    filename = path
                    break

        with open(filename) as yfd:
            self.config = yaml.load(yfd)


    def lookup(self, element, default=None):
        config = self.config

        while len(element) > 0:
            if not config:
                return default
            config = config.get(element.pop(0))
        return config


if len(sys.argv) < 2:
    abort("Usage: {} <cmd> ...".format(sys.argv[0]))

# Load up the kernel-series information.
ks = KernelSeries(use_local=True)

# Load up the application config.
config = Config()

if sys.argv[1] == 'source-packages-path':
    if len(sys.argv) != 4:
        abort("Usage: {0} {1} <series> <source>".format(*sys.argv))

    (series_codename, source_name) = sys.argv[2:]

    series = ks.lookup_series(codename=series_codename)
    if not series:
        abort("{}: {}: series not found".format(sys.argv[0], series_codename))
    source = series.lookup_source(source_name)
    if not source:
        abort("{}: {}: source not found in {}".format(sys.argv[0], source_name, series_codename))

    for package in source.packages:
        which = package.type if package.type else 'main'
        which_suffix = '-' + package.type if package.type else ''

        package_path = config.lookup(['package-path', which])
        if not package_path:
            package_path = config.lookup(['package-path', 'default'], '{series}{type_suffix}')

        print(os.path.expanduser(package_path.format(series=series.codename, type=which, type_suffix=which_suffix)))
