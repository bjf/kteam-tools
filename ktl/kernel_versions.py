#!/usr/bin/python

# Copyright (C) 2009-2013  Canonical Ltd.
# Authors:
#   Andy Whitcroft <apw@canonical.com>
# Based on sru-report by:
#   Martin Pitt <martin.pitt@ubuntu.com>
#   Jean-Baptiste Lallement <jean-baptiste.lallement@canonical.com>

# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation; version 3 of the License.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program.  If not, see <http://www.gnu.org/licenses/>.

from __future__ import print_function

from functools import cmp_to_key

import logging
import os

import apt_pkg
from launchpadlib.launchpad import Launchpad as _Launchpad

# Work around non-multiple-instance-safety of launchpadlib (bug #459418).
class Launchpad(_Launchpad):
    @classmethod
    def _get_paths(cls, service_root, launchpadlib_dir=None):
        service_root, launchpadlib_dir, cache_path, service_root_dir = (
            _Launchpad._get_paths(
                service_root, launchpadlib_dir=launchpadlib_dir))
        cache_path += "-sru-report"
        if not os.path.exists(cache_path):
            os.makedirs(cache_path, 0o700)
        return service_root, launchpadlib_dir, cache_path, service_root_dir

class KernelVersions:
    def __init__(s):
        s.lp = None
        s.ubuntu = None
        s.archive = None
        s.releases = {}  # name -> distro_series
        s.broken_bugs = set()
        s.ignored_commenters = []

        s.lpinit()
        apt_pkg.init_system()


    def _pocket_data(s, series, sourcename):
        global archive

        distro_series = s.releases[series]

        logging.debug(
            'Fetching publishing history for %s/%s' %
            (distro_series.name, sourcename))
        pubs = s.archive.getPublishedSources(source_name=sourcename,
                                           exact_match=True,
                                           distro_series=distro_series)

        # Take the latest pocket the package made it into as its 'pocket'.
        pockets = {}
        for pub in pubs:
            #print(pub.source_package_version, pub.pocket, pub.status)
            if pub.status == 'Deleted':
                continue
            version = pub.source_package_version
            pocket = pub.pocket
            if version not in pockets:
                pockets[version] = []
            if pocket not in pockets[version]:
                pockets[version].append(pocket)
        
        return pockets


    def current_in_pocket(s, pocket, series, sourcename, infer_release=False):
        '''Get the current version of this package published in the specified pocket'''
        pockets = s._pocket_data(series, sourcename)

        pocket = pocket.capitalize()

        result = None
        for version in sorted(pockets.keys(), key=cmp_to_key(apt_pkg.version_compare)):
            if pocket in pockets[version]:
                result = version
            # If a package is introduced post release then there is no -release
            # version, the very first -updates version stands in for this version.
            if infer_release and not result and \
                    pocket == 'Release' and 'Updates' in pockets[version]:
                result = version

        return result


    def all_viable(s, series, sourcename):
        '''Get all viable versions of this package published ever, only the last -proposed is considered'''
        pockets = s._pocket_data(series, sourcename)

        result = []
        for version in sorted(pockets.keys(), key=cmp_to_key(apt_pkg.version_compare)):
            #print(version, pockets[version])
            if pockets[version] != ['Proposed']:
                result.append(version)

        if pockets[version] == ['Proposed']:
            result.append(version)

        return result


    def lpinit(s):
        '''Init LP credentials, archive, distro list and sru-team members'''
        logging.debug("Initializing LP Credentials")
        lp = Launchpad.login_anonymously('kernel-versions', 'production')
        s.ubuntu = lp.distributions['ubuntu']
        s.archive = s.ubuntu.getArchive(name='primary')
        for series in s.ubuntu.series:
            if series.active:
                s.releases[series.name] = series
        logging.debug('Active releases found: %s' % ' '.join(s.releases))

