#!/usr/bin/env python
#

import re
from datetime                           import datetime, timedelta, timezone
import json
from  debian.debian_support             import version_compare

from lazr.restfulclient.errors          import NotFound, Unauthorized

from ktl.kernel_series                  import KernelSeries
from ktl.msgq                           import MsgQueue, MsgQueueCkct
from ktl.utils                          import date_to_string, dump

from .check_component                   import CheckComponent
from .errors                            import ShankError, ErrorExit, WorkflowCrankError
from .git_tag                           import GitTag, GitTagError
from .log                               import cdebug, cerror, cwarn, center, cleave, Clog, cinfo

# PackageError
#
class PackageError(ShankError):
    '''
    Thrown when some basic information about the package that is associated with the
    shankbug could not be determined.
    '''
    pass


# SeriesLookupFailure
#
class SeriesLookupFailure(ShankError):
    '''
    Thrown when the series lookup throws a KeyError exception.
    '''
    pass


# PackageBuild
#
class PackageBuild:

    def __init__(self, bug, series, dependent, pocket, routing, package, version, abi, sloppy):
        self.bug = bug
        self.series = series
        self.dependent = dependent
        self.pocket = pocket
        self.routing = routing
        self.package = package
        self.srch_version = version
        self.srch_abi = abi
        self.srch_sloppy = sloppy

        self._data = None

    # __is_fully_built
    #
    def __is_fully_built(s, package, abi, archive, release, pocket, sloppy):
        '''
        Have the source package specified been fully built?
        '''
        center(s.__class__.__name__ + '.__is_fully_built')
        cdebug('package: %s' % package, 'yellow')
        cdebug('    abi: %s' % abi,     'yellow')
        cdebug('archive: %s' % archive.reference, 'yellow')
        cdebug('release: %s' % release, 'yellow')
        cdebug(' pocket: %s' % pocket, 'yellow')
        cdebug(' sloppy: %s' % pocket, 'yellow')

        # Do a loose match, we will select for the specific version we wanted
        # in __find_matches but this way we have the published version for
        # pocket emptyness checks.
        ps = archive.getPublishedSources(distro_series=s.series, exact_match=True, source_name=package, pocket=pocket, order_by_date=True)
        matches = s.__find_matches(ps, abi, release, sloppy)
        if len(matches) > 0 and matches[0].status in ('Pending', 'Published'):
            cdebug('    match: %s (%s)' % (release, abi), 'green')
            fullybuilt, creator, signer, published, most_recent_build, status = s.__sources_built(matches, archive, package, release, pocket)
            version = matches[0].source_package_version
            changes = matches[0].changesFileUrl()
        else:
            fullybuilt   = False
            status  = ''
            creator = None
            signer  = None
            published = None
            most_recent_build = None
            version = None
            changes = None
            source = None
            if len(ps) > 0:
                source = ps[0]
                if source.status in ('Pending', 'Published'):
                    version = source.source_package_version

            monitor = {
                'type': 'launchpad-source',
                'reference': archive.reference,
                'pocket': pocket,
                #'series': s.series,
                'package': package,
                'last-scanned': s.bug.tracker_instantiated}
            if source:
                monitor['status'] = source.status
                monitor['lp-api'] = source.self_link
            s.bug.debs.monitor_debs_add(monitor)

        cleave(s.__class__.__name__ + '.__is_fully_built')
        return fullybuilt, creator, signer, published, most_recent_build, status, version, changes

    # __find_matches
    #
    def __find_matches(s, ps, abi, release, sloppy):
        center('Sources::__find_matches')
        cdebug('    abi: %s' % abi,     'yellow')
        cdebug('release: %s' % release, 'yellow')
        cdebug(' sloppy: %s' % release, 'yellow')
        cdebug('records: %d' % len(ps), 'yellow')

        match = False
        matches = []
        if abi:
            cdebug('abi match only')
            dep_ver1 = '%s-%s' % (release, abi)
            dep_ver2 = '%s.%s' % (release, abi)
            for p in ps:
                src_ver = p.source_package_version
                cdebug('examining: %s' % src_ver)
                if ((src_ver.startswith(dep_ver1 + '.') or src_ver.startswith(dep_ver2 + '.'))):
                    cdebug('adding: %s' % src_ver, 'green')
                    matches.append(p)
                    match = True
        else:
            cdebug('exact version match required')
            for p in ps:
                src_ver = p.source_package_version
                # Exact match or exact prefix plus '+somethingN'
                if src_ver == release or (sloppy and src_ver.startswith(release + '+')):
                    cdebug('adding: %s' % src_ver, 'green')
                    matches.append(p)
                    match = True

        cleave('Sources::__find_matches (%s)' % match)
        return matches

    # __sources_built
    #
    def __sources_built(s, sources, archive, package, release, pocket):
        '''
        '''
        center('Sources::__sources_built')
        cdebug('sources: %s' % sources, 'yellow')
        cdebug('archive: %s' % archive.reference, 'yellow')
        cdebug('package: %s' % package, 'yellow')
        cdebug('release: %s' % release, 'yellow')
        cdebug(' pocket: %s' % pocket, 'yellow')

        # If we do get more than one match we should be picking the latest.
        if len(sources) == 0:
            raise ValueError("too few sources")

        source = sources[0]

        package_creator = source.package_creator
        package_signer = source.package_signer
        published = source.date_published
        latest_build = source.date_published
        status = set()
        status.add('UNKNOWN')

        cdebug("source status={}".format(source.status))
        if source.status in ('Pending'):
            status.add('PENDING')
        elif source.status in ('Published'):
            status.add('FULLYBUILT')
        else:
            # Anything else is broken.
            #  Superseded
            #  Deleted
            #  Obsolete
            status.add('FAILEDTOBUILD')

        arch_build = set()
        arch_complete = set()
        builds = source.getBuilds()
        if len(builds) == 0:
            s.bug.debs.monitor_debs_add({
                    'type': 'launchpad-nobuilds',
                    'reference': archive.reference,
                    'pocket': pocket,
                    #'status': source.status,
                    'lp-api': source.self_link,
                    'last-scanned': s.bug.tracker_instantiated})
        for build in builds:
            buildstate = build.buildstate
            ##print(build, build.buildstate, build.datebuilt)
            cdebug("build arch={} status={}".format(build.arch_tag, buildstate))
            if build.buildstate in (
                    'Needs building',
                    'Currently building',
                    'Uploading build'):
                status.add('BUILDING')

            elif buildstate == 'Dependency wait':
                status.add('DEPWAIT')

            elif buildstate == 'Successfully built':
                status.add('FULLYBUILT')
                arch_complete.add(build.arch_tag)

            else:
                # Anything else is a failure, currently:
                #  Build for superseded Source
                #  Failed to build
                #  Chroot problem
                #  Failed to upload
                #  Cancelling build
                #  Cancelled build
                status.add('FAILEDTOBUILD')

            if build.buildstate in (
                    'Failed to build',
                    'Needs building',
                    'Currently building',
                    'Uploading build',
                    'Dependency wait'):
                s.bug.debs.monitor_debs_add({
                        'type': 'launchpad-build',
                        'reference': archive.reference,
                        'pocket': pocket,
                        'status': buildstate,
                        'lp-api': build.self_link,
                        'last-scanned': s.bug.tracker_instantiated})

            if buildstate != 'Successfully built':
                s.bug.maintenance_add({
                    'type': 'deb-build',
                    'target': s.bug.target,
                    'detail': {
                        'state': buildstate,
                        'type': s.dependent,
                        'package': build.source_package_name,
                        'url': build.web_link,
                        'lp-api': build.self_link,
                        'log': build.build_log_url,
                    }})

            # Accumulate the latest build completion.
            if build.datebuilt is not None and (latest_build is None or latest_build < build.datebuilt):
                latest_build = build.datebuilt

            # Accumulate the architectures we are meant to build for.
            arch_build.add(build.arch_tag)

        one_per_build = set()
        arch_published = set()
        binaries = source.getPublishedBinaries()
        for binary in binaries:
            ##print(binary, binary.status, binary.date_published)
            if binary.architecture_specific:
                arch_tag = binary.distro_arch_series_link.split('/')[-1]
            else:
                arch_tag = 'all'
            cdebug("binary arch={} status={}".format(arch_tag, binary.status))
            if binary.status == 'Pending':
                status.add('PENDING')
            elif binary.status  == 'Published':
                status.add('FULLYBUILT')
            else:
                # Anything else is broken.
                #  Superseded
                #  Deleted
                #  Obsolete
                status.add('FAILEDTOBUILD')

            if binary.status == 'Pending' and binary.build_link not in one_per_build:
                one_per_build.add(binary.build_link)
                s.bug.debs.monitor_debs_add({
                        'type': 'launchpad-binary',
                        'reference': archive.reference,
                        'pocket': pocket,
                        'status': binary.status,
                        'lp-api': binary.self_link,
                        'last-scanned': s.bug.tracker_instantiated})

            # Accumulate the latest publication time.
            if binary.date_published is not None and published < binary.date_published:
                published = binary.date_published

            # Accumulate the architectures we have publications for.
            if binary.architecture_specific:
                arch_published.add(binary.distro_arch_series_link.split('/')[-1])

        # If our build architecture list does not match our published architecture
        # list then we have a publication missing.  Check if we have publications
        # missing because they are in flight.
        if arch_build != arch_published:
            if arch_build == arch_complete:
                uploads = source.distro_series.getPackageUploads(exact_match=True,
                        archive=archive, pocket=pocket, name=source.source_package_name,
                        version=source.source_package_version)
                queued = False
                for upload in uploads:
                    if upload.status not in ('Done', 'Rejected'):
                        if upload.status in ('New', 'Unapproved'):
                            queued = True
                        cinfo("upload not complete status={}".format(upload.status))
                        s.bug.debs.monitor_debs_add({
                                'type': 'launchpad-upload',
                                'reference': archive.reference,
                                'pocket': pocket,
                                'status': upload.status,
                                'lp-api': upload.self_link,
                                'last-scanned': s.bug.tracker_instantiated})
                if queued:
                    status.add('FULLYBUILT_PENDING')
                else:
                    status.add('PENDING')

            else:
                status.add('BUILDING')

        # Pick out the stati in a severity order.
        for state in ('FAILEDTOBUILD', 'DEPWAIT', 'BUILDING', 'FULLYBUILT_PENDING', 'PENDING', 'FULLYBUILT', 'UNKNOWN'):
            if state in status:
                break

        if published is not None:
            published = published.replace(tzinfo=None)
        if latest_build is not None:
            latest_build = latest_build.replace(tzinfo=None)

        cleave('Sources::__sources_built' )
        return state == 'FULLYBUILT', package_creator, package_signer, published, latest_build, state

    def instantiate(self):
        cdebug("INSTANTIATING {} {} {} {} {} {}".format(self.dependent, self.pocket, self.package, self.srch_version, self.srch_abi, self.srch_sloppy))

        publications = []
        archive_num = 0
        for (src_archive, src_pocket) in self.routing:
            archive_num += 1
            if src_archive is None:
                raise WorkflowCrankError("Routing table entry {}#{} invalid".format(self.pocket, archive_num))
            info = self.__is_fully_built(self.package, self.srch_abi, src_archive, self.srch_version, src_pocket, self.srch_sloppy)
            publications.append(info)
            # If this archive pocket contains the version we are looking for then scan
            # no further.
            if info[5] != '':
                break

        # If we have a match use that, else use the first one.
        if publications[-1][5] != '':
            info = publications[-1]
        else:
            info = publications[0]

        self._data = {}
        self._data['built']   = info[0]
        self._data['creator'] = info[1]
        self._data['signer']  = info[2]
        self._data['published'] = info[3]
        self._data['most_recent_build'] = info[4]
        self._data['status'] = info[5]
        self._data['version'] = info[6]
        self._data['route'] = (src_archive, src_pocket)
        self._data['changes'] = info[7]

        cinfo('DELAYED %-8s %-8s : %-20s : %-5s / %-10s    (%s : %s) %s [%s %s]' % (self.dependent, self.pocket, self.package, info[0], info[5], info[3], info[4], info[6], src_archive.reference, src_pocket), 'cyan')

        # If we find a build is now complete, record _where_ it was built.
        if ((self.pocket == 'ppa' or self.pocket.startswith('build')) and
                self._data['status'] != ''):
            # NOTE: copy-proposed-kernel et al treat auto select build-private so just call this build.
            self.bug.bprops.setdefault('built', {})[self.dependent] = "build#{}".format(archive_num)

    def __getattr__(self, name):
        if self._data is None:
            self.instantiate()
        if name not in self._data:
            raise AttributeError()
        return self._data[name]

    def __getitem__(self, name):
        if self._data is None:
            self.instantiate()
        return self._data[name]

    def get(self, name, default=None):
        if self._data is None:
            self.instantiate()
        return self._data.get(name, default)


# Package
#
class Package():

    # __init__
    #
    def __init__(s, lp, shankbug, ks=None):
        center('package::__init__')
        s.lp = lp
        s.bug = shankbug

        s.kernel_series = KernelSeries() if ks is None else ks
        s.__distro_series = None

        # debs record their versions in their title -- sync back canonical form.
        s.bug.version_from_title()
        s.bug.update_title()

        # Pick up versions from our bug as needed.
        s.series = s.bug.series
        s.name = s.bug.name
        s.version = s.bug.version
        s.source = s.bug.source
        s.kernel = s.bug.kernel
        s.abi = s.bug.abi

        # Look the package routing destinations up in kernel-series, convert the
        # archives to real archive objects.
        s._routing = {}
        s.routing_mode = 'None'
        if s.source is not None and s.source.routing:
            for (key, destination) in (
                ('ppa', 'build'),
                ('build', 'build'),
                ('build-private', 'build-private'),
                ('Signing', 'signing'),
                ('Proposed', 'proposed'),
                ('as-proposed', 'as-proposed'),
                ('Updates', 'updates'),
                ('Security', 'security'),
                ('Release', 'release'),
                ):
                routes = s.source.routing.lookup_destination(destination)
                if routes is None:
                    continue
                route_list = []
                for route in routes:
                    archive = s.lp.launchpad.archives.getByReference(reference=route[0])
                    route_list.append((archive, route[1]))
                s._routing[key] = route_list
            s.routing_mode = s.source.routing.name


        cinfo('     test_flavours: %s' % (s.test_flavours()), 'blue')
        cinfo('test_flavour_meta4: %s' % (s.test_flavour_meta()), 'blue')
        cinfo('     Routing mode: {}'.format(s.routing_mode), 'blue')
        cinfo('    Routing table:', 'blue')
        for pocket, pocket_data in s._routing.items():
            if pocket_data is None:
                cerror('        {}: {} {}'.format(pocket, 'NONE', 'NONE', 'red'))
            else:
                for route in pocket_data:
                    route_reference = "NONE" if route[0] is None else route[0].reference
                    cinfo('        {}: {} {}'.format(pocket, route_reference, route[1]), 'blue')

        if s.source is not None:
            s.pkgs = s.dependent_packages
        else:
            s.pkgs = None
        if s.pkgs == None:
            raise PackageError('Unable to check package builds for this bug: the package/series combination is invalid')

        s._cache = None
        s._version_tried = {}

        s._monitor_debs = []

        cleave('package::__init__')

    @property
    def monitor_debs(s):
        return s._monitor_debs

    def monitor_debs_add(s, what):
        if what not in s._monitor_debs:
            s._monitor_debs.append(what)


    def routing(self, pocket):
        center(self.__class__.__name__ + '.routing')
        routes = self._routing.get(pocket)
        cleave(self.__class__.__name__ + '.routing')
        return routes

    def monitor_routes(self, routes):
        if 'ppa' in routes:
            routes.remove('ppa')
            routes.append('build')
            routes.append('build-private')
        for route_name in routes:
            route_found = self.pocket_route(route_name)
            if route_found is not None:
                cinfo("monitor_routes: {} location found {}".format(route_name, route_found))
                route_list = [route_found]
            else:
                route_list = self.routing(route_name)
            if route_list is None:
                continue
            cinfo("monitor_routes: {} using {}".format(route_name, route_list))
            for route_archive, route_pocket in route_list:
                # Copy over any build related monitors for this archive/pocket.
                for monitor in self.monitor_debs:
                    if (monitor['reference'] == route_archive.reference and
                            monitor['pocket'] == route_pocket):
                        self.bug.monitor_add(monitor)

    def package_version(s, pkg):
        # Look up the specific version of a package for this tracker.
        version = s.bug.bprops.get('versions', {}).get(pkg)
        if version is None and s._version_tried.get(pkg) is None:
            s._version_tried[pkg] = True

            # Lookup the kernel-series package we are referring to.
            package_package = None
            for package in s.source.packages:
                if (package.type == pkg or (
                    package.type is None and pkg == 'main')
                    ):
                    package_package = package
                    break
            if not package_package:
                return None

            # If the package is an ancillary package then if that package has a version
            # then we should take it.
            ancillary_for = s.ancillary_package_for(pkg)
            if ancillary_for is not None:
                return s.bug.bprops.get('versions', {}).get(ancillary_for)

            # Work out the package version form based on its type.
            if pkg == 'lbm':
                version_lookup, version_sloppy = (s.bug.kernel + '-' + s.bug.abi, '.')
            elif pkg in ('meta', 'ports-meta'):
                version_lookup, version_sloppy = (s.bug.kernel + '.' + s.bug.abi, '.')
            else:
                version_lookup, version_sloppy = (s.bug.version, '+')

            # Try and find a matching
            try:
                git_tag = GitTag(package_package, version_lookup, version_sloppy)
                if git_tag.verifiable and git_tag.present:
                    version = git_tag.version
            except GitTagError as e:
                cerror("{} {} ({}): Tag lookup failed -- {}".format(
                    package_package, version_lookup, version_sloppy, e))

            # Cache any positive version matches.
            if version is not None:
                s.bug.bprops.setdefault('versions', {'source': s.bug.version})[pkg] = version

        return version

    # ancillary_package_for
    #
    def ancillary_package_for(self, pkg):
        if pkg in ('lrg', 'lrs'):
            return 'lrm'
        return None

    # signing_package_for
    #
    def signing_package_for(self, pkg):
        return {
                'lrs': 'lrm',
                'signed': 'main',
            }.get(pkg)

    # feeder_package_for
    #
    def feeder_package_for(self, pkg):
        return {
                'signed': 'main',
                'lrm': 'main',
                'lrg': 'lrm',
                'lrs': 'lrg',
                'meta': 'main',
            }.get(pkg)

    # feeder_key
    #
    def feeder_key(self, pkg):
        key = []
        while pkg is not None:
            key.insert(0, pkg)
            pkg = self.feeder_package_for(pkg)
        return key

    # adjunct_package
    #
    def adjunct_package(self, pkg):
        return self.ancillary_package_for(pkg) == 'lrm'

    # __determine_build_status
    #
    def __determine_build_status(s):
        center('Sources::__determine_build_status')

        s._cache = {}

        cinfo('')
        cinfo('Build Status:', 'cyan')

        for dep in iter(s.pkgs):
            cdebug('')
            cinfo('%s: ' % dep, 'blue')
            cinfo('--------------------------------------------------------------------------------', 'blue')
            if dep in s._cache:
                break
            Clog.indent += 4

            # Lookup the package version we are expecting -- if we have it match on explicit version.
            version = s.package_version(dep)
            cinfo("APW: package_version({}) = {}".format(dep, version))
            if version is not None:
                abi = None
                sloppy = False

            # For the linux and linux-signed packages the versions must be an exact match for the other
            # packages only the abi needs to match the linux packages abi number.
            #
            elif dep in ['lbm', 'meta', 'ports-meta'] and s.abi:
                abi = s.abi
                version = s.kernel
                sloppy = True

            else:
                abi = None
                version = s.version
                sloppy = True

            cinfo("{} {} abi={} sloppy={}".format(s.pkgs[dep], version, abi, sloppy))

            s._cache[dep] = {}
            if not s.bug.is_development_series:
                cdebug('Stable Package', 'cyan')
                cdebug('')
                scan_pockets = ['ppa', 'Signing', 'Proposed', 'as-proposed', 'Security', 'Updates']
            else:
                cdebug('Development Package', 'cyan')
                cdebug('')
                scan_pockets = ['ppa', 'Signing', 'Proposed', 'as-proposed', 'Release']
            s.scan_pockets = list(scan_pockets)
            scan_pockets[0] = 'build' if not s.adjunct_package(dep) else 'build-private'

            for pocket in scan_pockets:
                pocket_from = pocket
                if pocket_from not in s._routing:
                    continue
                if s._routing[pocket_from] is None:
                    s.bug.overall_reason = "{} pocket routing archive specified but invalid {}".format(pocket_from, s.source)
                    cwarn(s.bug.overall_reason)
                    continue

                s._cache[dep][pocket] = PackageBuild(s.bug, s.distro_series, dep, pocket_from, s._routing[pocket_from], s.pkgs[dep], version, abi, sloppy)
                if pocket == scan_pockets[0]:
                    s._cache[dep]['ppa'] = s._cache[dep][pocket]
                #cinfo('%-8s : %-5s / %-10s    (%s : %s) %s [%s %s]' % (pocket, info[0], info[5], info[3], info[4], info[6], src_archive.reference, src_pocket), 'cyan')
            Clog.indent -= 4

        #cdebug('')
        #cdebug('The Cache:', 'cyan')
        #for d in sorted(s._cache):
        #    cdebug('    %s' % d, 'cyan')
        #    for p in sorted(s._cache[d]):
        #        cdebug('        %-8s : %-5s   (%s)' % (p, s._cache[d][p]['built'], date_to_string(s._cache[d][p]['published'])), 'cyan')

        cleave('Sources::__determine_build_status')
        return None

    def __all_arches_built(s, matches):
        '''
        Determine if all the builds that have been done for all of the arches. This helps
        us detect when a build has been canceled.
        '''
        center(s.__class__.__name__ + '__all_arches_built')
        retval = False
        if len(matches) > 0:
            for match in matches:
                binary_list = match.getPublishedBinaries()

                # Determine how many arches we have builds for.
                #
                sa = {} # series arches
                for binary in binary_list:
                    if binary.architecture_specific:
                        try:
                            sa[binary.distro_arch_series_link] += 1
                        except KeyError:
                            sa[binary.distro_arch_series_link] = 1
                for arch in sa:
                    cdebug('series/arch : %s' % arch)

                arches_to_build = len(sa)

                # Determine how many builds there actually are. This includes
                # canceled builds which are important to us.
                #
                builds = match.getBuilds()

                if arches_to_build == len(builds):
                    retval = True
                else:
                    cdebug('Only %s of %s arches were built' % (len(builds), arches_to_build))
        else:
            cdebug('No matches found')
        cleave(s.__class__.__name__ + '__all_arches_built (%s)' % retval)
        return retval

    __states_present = ['DEPWAIT', 'BUILDING', 'FULLYBUILT', 'PENDING', 'FULLYBUILT_PENDING', 'FAILEDTOBUILD']
    __pockets_uploaded = ('ppa', 'Signing', 'Proposed', 'Security', 'Updates', 'Release')

    # build_info
    #
    @property
    def build_info(s):
        if s._cache is None:
            s.__determine_build_status()
        return s._cache

    # srcs
    #
    @property
    def srcs(s):
        if s._cache is None:
            s.__determine_build_status()
        return s._cache

    # dependent_packages
    #
    @property
    def dependent_packages(s):
        '''
        Put together a list of all the packages that depend on this package.
        '''
        if 'packages' not in s.bug.bprops:
            pkgs = {}
            series = s.kernel_series.lookup_series(codename=s.series)
            source = series.lookup_source(s.name)
            if source is None:
                return None
            for package in source.packages:
                pkgs[package.type if package.type else 'main'] = package.name
            s.bug.bprops['packages'] = pkgs

        return s.bug.bprops['packages']

    # dependent_packages_for_pocket
    #
    def dependent_packages_for_pocket(self, pocket):
        pkgs = []
        for pkg in self.build_info:
            if pkg == 'lrg' and pocket not in ('ppa', 'build-private', 'Signing'):
                continue
            pkgs.append(pkg)
        cdebug("dependent_packages_for_pocket({})={}".format(pocket, pkgs))
        return pkgs

    # distro_series
    #
    @property
    def distro_series(s):
        '''
        Return the LP distro series link to the series associated with this version
        of this package.
        '''
        if s.__distro_series is None:
            if s.series:
                sc = s.lp.launchpad.distributions["ubuntu"].series_collection
                for ds in sc:
                    if ds.name == s.series:
                        s.__distro_series = ds
                        break

            if s.__distro_series is None:
                emsg = "        ERROR: can't figure out the distro series for %s-%s\n" % (s.name, s.version)
                cerror(emsg)
                raise ErrorExit(emsg)

        return s.__distro_series

    # built_and_in_pocket
    #
    def built_and_in_pocket(s, pkg, pocket):
        '''
        Dependent package is fully built and in the pocket 'pocket'.
        '''
        center(s.__class__.__name__ + '.built_and_in_pocket')
        try:
            pkg_built = s.srcs[pkg][pocket]['built']
        except KeyError:
            pkg_built = False

        if not pkg_built:
            cinfo('        {} is either not fully built yet or not in {}.'.format(pkg, pocket), 'red')

        cleave(s.__class__.__name__ + '.built_and_in_pocket ({})'.format(pkg_built))
        return pkg_built

    # built_and_in_pocket
    #
    def built_and_in_pocket_or_after(s, pkg, pocket):
        '''
        Dependent package is fully built and in the pocket 'pocket'.
        '''
        center(s.__class__.__name__ + '.built_and_in_pocket_or_after')
        found_start = False
        for find_pocket in s.scan_pockets:
            if find_pocket == pocket:
                found_start = True
            if not found_start:
                continue

            try:
                pkg_built = s.srcs[pkg][find_pocket]['built']
            except KeyError:
                pkg_built = False

            if pkg_built:
                break

        if not pkg_built:
            cinfo('        {} is either not fully built yet or not in {} or after.'.format(pkg, pocket), 'red')

        cleave(s.__class__.__name__ + '.built_and_in_pocket_or_after ({})'.format(pkg_built))
        return pkg_built

    # all_in_pocket
    #
    def all_in_pocket(s, pocket):
        '''
        All dependent packages are in the pocket 'pocket'.
        '''
        center(s.__class__.__name__ + '.all_in_pocket')
        retval = True

        for pkg in s.dependent_packages_for_pocket(pocket):
            try:
                pkg_seen = s.srcs[pkg][pocket]['status'] in s.__states_present
            except KeyError:
                pkg_seen = False

            if pkg_seen:
                cinfo('        %s is present in %s.' % (pkg, pocket), 'yellow')
            else:
                cinfo('        %s is NOT present in %s.' % (pkg, pocket), 'yellow')
                retval = False
                break

        cleave(s.__class__.__name__ + '.all_in_pocket (%s)' % (retval))
        return retval

    # __pockets_from
    #
    def __pockets_from(s, pocket_from):
        pockets = []
        found_from = False
        for pocket_next in s.scan_pockets:
            if pocket_next == pocket_from:
                found_from = True
            if found_from:
                pockets.append(pocket_next)
        return pockets

    # pocket_after
    #
    def pocket_after(s, pocket_from):
        pockets = s.__pockets_from(pocket_from)
        if len(pockets) < 2:
            return None
        return pockets[1]

    # __pkg_in
    #
    def __pkg_in(s, pkg, pocket):
        try:
            pkg_in = s.srcs[pkg][pocket]['status'] in s.__states_present
        except KeyError:
            pkg_in = False
        return pkg_in

    # __pkg_built
    #
    def __pkg_built(s, pkg, pocket):
        try:
            pkg_built = s.srcs[pkg][pocket]['built']
        except KeyError:
            pkg_built = False
        return pkg_built

    # __pkg_task
    #
    def __pkg_task(s, pkg):
        if pkg == 'main':
            suffix = ''
        else:
            suffix = '-' + pkg
        return 'prepare-package' + suffix

    # delta_src_dst
    #
    def delta_src_dst(s, src, dst):
        '''
        List of dependent packages in src which are not in dst or later.
        '''
        center(s.__class__.__name__ + '.delta_src_dst({}, {})'.format(src, dst))

        retval = []
        for pkg in s.dependent_packages_for_pocket(dst):
            pkg_in_src = s.__pkg_in(pkg, src)
            pocket = dst
            for pocket in s.__pockets_from(dst):
                pkg_in_dst = s.__pkg_built(pkg, pocket)
                if pkg_in_dst:
                    break

            if pkg_in_src and not pkg_in_dst:
                cinfo('        {} is in {} and not yet in {} or later.'.format(pkg, src, dst), 'red')
                retval.append(pkg)

            elif src == 'ppa' and s.bug.task_status(s.__pkg_task(pkg)) not in ('Fix Released', 'Invalid'):
                cinfo('        {} is missing from {} or later.'.format(pkg, src), 'red')
                retval.append(pkg)

            else:
                cinfo('        {} is in {} and in {}'.format(pkg, src, pocket), 'red')

        cinfo("from {} to {} delta {}".format(src, dst, retval))

        cleave(s.__class__.__name__ + '.delta_src_dst(...)={}'.format(retval))
        return retval

    # delta_in_pocket
    #
    def delta_in_pocket(s, delta, pocket):
        '''
        Are all of the packages in delta in pocket.
        '''
        center(s.__class__.__name__ + '.delta_in_pocket({}, {})'.format(delta, pocket))

        retval = True
        for pkg in delta:
            pkg_in = s.__pkg_in(pkg, pocket)
            if not pkg_in:
                cinfo('        {} is not in {}'.format(pkg, pocket), 'red')
                retval = False
                break

        cleave(s.__class__.__name__ + '.delta_in_pocket(...)={}'.format(retval))
        return retval

    # delta_built_pocket
    #
    def delta_built_pocket(s, delta, pocket):
        '''
        Are all of the packages in delta built in pocket.
        '''
        center(s.__class__.__name__ + '.delta_built_pocket({}, {})'.format(delta, pocket))

        retval = True
        for pkg in delta:
            pkg_in = s.__pkg_built(pkg, pocket)
            if not pkg_in:
                cinfo('        {} is not built in {}'.format(pkg, pocket), 'red')
                retval = False
                break

        cleave(s.__class__.__name__ + '.delta_built_pocket(...)={}'.format(retval))
        return retval

    # all_built_and_in_pocket
    #
    def all_built_and_in_pocket(s, pocket):
        '''
        All dependent packages are fully built and in the pocket 'pocket'.
        '''
        center(s.__class__.__name__ + '.all_built_and_in_pocket')
        retval = True

        for pkg in s.dependent_packages_for_pocket(pocket):
            try:
                pkg_built = s.srcs[pkg][pocket]['built']
            except KeyError:
                pkg_built = False

            if not pkg_built:
                cinfo('        {} is either not fully built yet or not in {}.'.format(pkg, pocket), 'red')
                retval = False
                break

        cleave(s.__class__.__name__ + '.all_built_and_in_pocket ({})'.format(retval))
        return retval

    # all_built_and_in_pocket_or_pocket
    #
    def all_built_in_src_dst(s, src, dst):
        '''
        All dependent packages are fully built and in src or dst.
        '''
        center(s.__class__.__name__ + '.all_built_in_src_dst')
        retval = True

        for pkg in s.dependent_packages_for_pocket(dst):
            try:
                pkg_built_src = s.srcs[pkg][src]['built']
            except KeyError:
                pkg_built_src = False

            try:
                pkg_built_dst = s.srcs[pkg][dst]['built']
            except KeyError:
                pkg_built_dst = False

            if not pkg_built_src and not pkg_built_dst:
                cinfo('        {} is either not fully built yet or not in {} or {}.'.format(pkg, src, dst), 'red')
                retval = False
                break

        cleave(s.__class__.__name__ + '.all_built_in_src_dst ({})'.format(retval))
        return retval

    # built_in_src_dst_delta
    #
    def built_in_src_dst_delta(s, src, dst):
        '''
        List of dependent packages in src which are not in dst.
        '''
        center(s.__class__.__name__ + '.built_in_src_dst_delta')
        retval = []

        for pkg in s.dependent_packages_for_pocket(dst):
            try:
                pkg_built_src = s.srcs[pkg][src]['built']
            except KeyError:
                pkg_built_src = False
            pkg_built_dst = s.built_and_in_pocket_or_after(pkg, dst)

            if pkg_built_src and not pkg_built_dst:
                cinfo('        {} is in {} and not yet in {} or later.'.format(pkg, src, dst), 'red')
                retval.append(pkg)

        cleave(s.__class__.__name__ + '.built_in_src_dst_delta ({})'.format(retval))
        return retval

    # all_built_and_in_pocket_for
    #
    def all_built_and_in_pocket_for(s, pocket, period):
        '''
        Check if we are fully built in a specific pocket and have been there
        for at least period time.
        '''
        center(s.__class__.__name__ + '.all_built_and_in_pocket_for({}, {})'.format(pocket, period))
        retval = False
        if s.all_built_and_in_pocket(pocket):

            # Find the most recent date of either the publish date/time or the
            # date/time of the last build of any arch of any of the dependent
            # package.
            #
            date_available = None
            bi = s.build_info
            for d in sorted(bi):
                if bi[d][pocket]['published'] is None:
                    continue
                if bi[d][pocket]['most_recent_build'] is None:
                    continue

                if bi[d][pocket]['published'] > bi[d][pocket]['most_recent_build']:
                    if date_available is None or bi[d][pocket]['published'] > date_available:
                        date_available = bi[d][pocket]['published']
                else:
                    if date_available is None or bi[d][pocket]['most_recent_build'] > date_available:
                        date_available = bi[d][pocket]['most_recent_build']

            date_available = date_available.replace(tzinfo=timezone.utc)
            now = datetime.now(timezone.utc)
            comp_date = date_available + period
            if comp_date < now:
                retval = True
            else:
                cinfo('It has been less than {} since the last package was either published or built in {}'.format(period, pocket))
                cinfo('    target: %s' % comp_date)
                cinfo('       now: %s' % now)

                # Record when it makes sense to check again.
                s.bug.refresh_at(comp_date, 'package publication to {} for {}'.format(pocket, period))

        cleave(s.__class__.__name__ + '.all_built_and_in_pocket_for (%s)' % (retval))
        return retval

    # attempt_retry_logless
    #
    def attempt_retry_logless(s, pkg):
        retried = False
        for maint in s.bug.maintenance:
            if maint['type'] == 'deb-build' and maint['detail']['type'] == pkg:
                # If we have a maintenance record and it is in 'Failed to build'
                # and we have no log then this is a clear retry candidate.
                if (maint is not None and
                        maint['detail']['state'] == 'Failed to build' and
                        maint['detail']['log'] is None):
                    cinfo("RETRY: {} (logless failure)".format(maint['detail']['lp-api']))
                    if s.attempt_retry(pkg):
                        retried = True
        return retried

    # attempt_retry
    #
    def attempt_retry(s, pkg):
        retried = False
        for record in s.bug.maintenance:
            if record['type'] == 'deb-build' and record['detail']['type'] == pkg:
                cinfo("RETRY: {}".format(record['detail']['lp-api']))
                lp_build = s.lp.launchpad.load(record['detail']['lp-api'])
                if lp_build is None:
                    cinfo("RETRY: {} build not found".format(
                        record['detail']['lp-api']))
                elif not lp_build.can_be_retried:
                    cinfo("RETRY: {} not retryable (state={})".format(
                        record['detail']['lp-api'], lp_build.buildstate))
                    # If this is not retryable but is in progress now,
                    # so just behave as if we retried it.
                    if lp_build.buildstate in (
                            'Needs building',
                            'Currently building',
                            'Uploading build'):
                        retried = True
                else:
                    try:
                        lp_build.retry()
                        retried = True
                        cinfo("RETRY: {} retry successful".format(
                            record['detail']['lp-api']))
                    except Unauthorized as e:
                        cinfo("RETRY: {} retry unsuccessful -- marked manual-retry".format(
                            record['detail']['lp-api']))
                        record['detail']['manual-retry'] = True
        return retried

    # all_failures_in_pocket
    #
    def all_failures_in_pocket(s, pocket, ignore_all_missing=False):
        packages = s.dependent_packages_for_pocket(pocket)
        return s.delta_failures_in_pocket(packages, pocket, ignore_all_missing)

    def __feeder_completed(s, feeder, pocket):
        published = s.srcs[feeder].get(pocket, {}).get('published')
        built = s.srcs[feeder].get(pocket, {}).get('most_recent_build')
        if published is None:
            return built
        if built is None:
            return published
        if built > published:
            return built
        return published

    # delta_failures_in_pocket
    #
    def delta_failures_in_pocket(s, delta, pocket, ignore_all_missing=False):
        failures = {}
        missing = 0
        sources = 0
        for pkg in delta:
            sources += 1
            status = s.srcs[pkg].get(pocket, {}).get('status')
            if status == 'BUILDING':
                failures.setdefault('building', []).append(pkg)
            elif status in ('DEPWAIT', 'FAILEDTOBUILD'):
                real_status = 'depwait' if status == 'DEPWAIT' else 'failed'
                wait_status = 'depwait' if status == 'DEPWAIT' else 'failwait'

                # Check if we failed without a log, if so, hit retry regardless
                # or any feeder existance.
                if status == 'FAILEDTOBUILD':
                    # If we successfully retried it then we should report it as
                    # building.
                    if s.attempt_retry_logless(pkg):
                        failures.setdefault('building', []).append(pkg)
                        continue

                # Look up the dependancy chain looking for something which
                # can be retried.
                active_feeder = pkg
                while True:
                    previous_feeder = active_feeder
                    active_feeder = s.feeder_package_for(active_feeder)
                    if active_feeder is None:
                        break
                    active_feeder_state = s.srcs.get(active_feeder, {}).get(pocket, {}).get('status')
                    if active_feeder_state not in ('DEPWAIT', 'FAILEDTOBUILD'):
                       break

                # If there is nothing above us doing anything.  Then our status
                # is real.
                if active_feeder is None:
                    failures.setdefault(real_status, []).append(pkg)
                    continue

                # If the active feeder is incomplete then we should continue
                # waiting for it.
                if active_feeder_state != 'FULLYBUILT':
                    failures.setdefault(wait_status, []).append(pkg)
                    continue

                # Work out if the previous_feeder is retryable.
                previous_feeder_completed = s.__feeder_completed(previous_feeder, pocket)
                active_feeder_completed = s.__feeder_completed(active_feeder, pocket)
                cinfo("completions {} => {} {} -> {} {}".format(pkg, previous_feeder_completed, previous_feeder, active_feeder, active_feeder_completed))
                previous_feeder_retry = (
                        previous_feeder_completed is not None and
                        active_feeder_completed is not None and
                        previous_feeder_completed - timedelta(hours=2) <= active_feeder_completed)

                # If the previous_feeder is actually us and can be retried
                # actually attempt it.
                if previous_feeder_retry and previous_feeder == pkg:
                    # If the retry fails this requirs a manual retry,
                    # mark us and annotate the maintenance record.
                    if not s.attempt_retry(pkg):
                        failures.setdefault('retry-needed', []).append(pkg)

                    # If it works it should end up in Needs Building state
                    # which implies we should report it as :building.
                    else:
                        failures.setdefault('building', []).append(pkg)

                    # Otherwise we made progress, so no mark is needed.
                    continue

                # If the previous_feeder can be retried, assume it will
                # elsewhere in the pass.  Mark ourselves as waiting.
                if previous_feeder_retry:
                    failures.setdefault(wait_status, []).append(pkg)

                # Otherwise we are genuinely broken.
                else:
                    failures.setdefault(real_status, []).append(pkg)

            elif status == '':
                failures.setdefault('missing', []).append(pkg)
                missing += 1
            elif status == 'PENDING':
                failures.setdefault('pending', []).append(pkg)
            elif status == 'FULLYBUILT_PENDING':
                failures.setdefault('queued', []).append(pkg)

        if ignore_all_missing and sources == missing:
            failures = None

        return failures

    # failures_to_text
    #
    def failures_to_text(self, summary):
        type_state = {}
        for state, members in summary.items():
            state_text = {
                    'missing': 'M',
                    'queued': 'Q',
                    'pending': 'P',
                    'building': 'B',
                    'depwait': 'D',
                    'retry-needed': 'R',
                    'failwait': 'D*',
                    'failed': 'F',
                }.get(state, state)
            for member in members:
                type_state[member] = state_text
        bits = []
        #for state, members in sorted(summary.items()):
        #    members = sorted(members, key=self.feeder_key)
        #    bits.append(','.join(members) + ':' + state)
        for member in sorted(type_state, key=self.feeder_key):
            bits.append("{}:{}".format(member, type_state[member]))
        return ' '.join(bits)

    # creator
    #
    def creator(s, pkg, pocket=None):
        center('Packages::creator')
        cdebug('   pkg: %s' % pkg)
        cdebug('pocket: %s' % pocket)
        retval = None

        bi = s.build_info
        if pocket is None:
            for pocket in s.__pockets_uploaded:
                if pocket not in bi[pkg]:
                    continue
                if bi[pkg][pocket]['status'] in s.__states_present:
                    retval = bi[pkg][pocket]['creator']
                    break
        else:
            retval = bi[pkg][pocket]['creator']
        cleave('Packages::creator')
        return retval

    # signer
    #
    def signer(s, pkg, pocket=None):
        center('Packages::signer')
        cdebug('   pkg: %s' % pkg)
        cdebug('pocket: %s' % pocket)
        retval = None

        bi = s.build_info
        if pocket is None:
            for pocket in s.__pockets_uploaded:
                if pocket not in bi[pkg]:
                    continue
                if bi[pkg][pocket]['built']:
                    retval = bi[pkg][pocket]['signer']
                    break
        else:
            retval = bi[pkg][pocket]['signer']
        cleave('Packages::signer')
        return retval

    # bugs
    #
    @property
    def bugs(self):
        center(self.__class__.__name__ + '.bugs')

        # Find an upload record for the main package.
        changes_url = None
        bugs = None
        pkg = 'main'
        bi = self.build_info
        for pocket in self.__pockets_uploaded:
            if pkg not in bi or pocket not in bi[pkg]:
                    continue
            if bi[pkg][pocket]['status'] in self.__states_present:
                changes_url = bi[pkg][pocket]['changes']
                cdebug("CHANGES: url={}".format(changes_url))

                # If we managed to find a changes file then we can extract the list.
                if changes_url is not None:
                    changes_url = changes_url.replace('https://launchpad.net/', 'https://api.launchpad.net/devel/')
                    try:
                        changes = self.lp.launchpad._browser.get(changes_url)
                        bugs = []
                        for line in changes.decode('utf-8').rstrip().split('\n'):
                            if line.startswith('Launchpad-Bugs-Fixed:'):
                                bugs = line.split(' ')[1:]
                    except NotFound:
                        pass
                    except Unauthorized:
                        continue
                    break

        cleave(self.__class__.__name__ + '.bugs {}'.format(bugs))
        return bugs

    # packages_released
    #
    @property
    def packages_released(s):
        '''
        '''
        retval = True

        if s.bug.is_development_series:
            pocket = 'Release'
        else:
            pocket = 'Updates'

        bi = s.build_info
        for pkg in s.dependent_packages_for_pocket(pocket):
            if bi[pkg][pocket]['built'] is not True:
                cinfo('            %s has not been released.' % (pkg), 'yellow')
                retval = False
                break

        return retval

    # packages_released_to_security
    #
    @property
    def packages_released_to_security(s):
        '''
        '''
        retval = True

        pocket = 'Security'

        bi = s.build_info
        for pkg in s.dependent_packages_for_pocket(pocket):
            if bi[pkg][pocket]['built'] is not True:
                cinfo('            %s has not been released.' % (pkg), 'yellow')
                retval = False
                break

        return retval

    # pocket_route
    #
    def pocket_route(s, pocket):
        '''
        '''
        retval = None

        bi = s.build_info
        for pkg in bi:
            if pocket not in bi[pkg]:
                continue
            if bi[pkg][pocket]['status'] != "":
                retval = bi[pkg][pocket]['route']
                cinfo('            pocket {} packages found in {}'.format(pocket, retval), 'yellow')
                break

        return retval

    # pocket_clear
    #
    def pocket_clear(s, pocket, pockets_after):
        '''
        Check that the proposed pocket is either empty or contains the same version
        as found in -updates/-release.
        '''
        retval = True

        # Release/Updates maps based on development series.
        pockets_srch = []
        for pocket_next in pockets_after:
            if pocket_next == 'Release/Updates':
                pocket_next = 'Release' if s.bug.is_development_series else 'Updates'
            pockets_srch.append(pocket_next)

        bi = s.build_info
        for pkg in bi:
            if pocket not in bi[pkg]:
                continue
            found = False
            if bi[pkg][pocket]['version'] is None:
                found = True
            for pocket_next in pockets_srch:
                if found:
                    break
                if pocket_next not in bi[pkg]:
                    continue
                try:
                    if version_compare(bi[pkg][pocket]['version'], bi[pkg][pocket_next]['version']) <= 0:
                        found = True
                except ValueError:
                    pass
                if pkg not in s.dependent_packages_for_pocket(pocket_next):
                    found = True
                cinfo("APW: {} <= {} = {}".format(bi[pkg][pocket]['version'], bi[pkg][pocket_next]['version'], version_compare(bi[pkg][pocket]['version'], bi[pkg][pocket_next]['version'])))
            if not found:
                cinfo('            {} has {} pending in {}.'.format(pkg, bi[pkg][pocket]['version'], pocket), 'yellow')
                retval = False

        # We are ready to go but proposed is not clear.  Consider any
        # bug we are marked as replacing.
        s.bug.dup_replaces()

        # If proposed is not clear, consider if it is full due to a bug
        # which has been duplicated against me.
        if not retval:
            duplicates = s.bug.workflow_duplicates
            for dup_wb in duplicates:
                # Consider only those supporting debs.
                if dup_wb.debs and dup_wb.debs.all_built_and_in_pocket(pocket):
                    cinfo('            %s is duplicate of us and owns the binaries in -proposed, overriding' % (dup_wb.lpbug.id,), 'yellow')
                    retval = True
                    break

        return retval

    # uploaded
    #
    def uploaded(s, pkg):
        '''
        '''
        center(s.__class__.__name__ + '.uploaded')
        retval = False

        bi = s.build_info
        for pocket in s.__pockets_uploaded:
            if pocket not in bi[pkg]:
                continue
            cdebug("checking for {} in {} is '{}'".format(pkg, pocket, bi[pkg][pocket]['status']))
            if bi[pkg][pocket]['status'] in s.__states_present:
                retval = True
                break

        cleave(s.__class__.__name__ + '.uploaded (%s)' % (retval))
        return retval

    def upload_version(s, pkg):
        '''
        '''
        center(s.__class__.__name__ + '.upload_version')
        retval = None

        bi = s.build_info
        for pocket in bi[pkg]:
            if bi[pkg][pocket]['status'] in s.__states_present:
                retval = bi[pkg][pocket]['version']
                break

        cleave(s.__class__.__name__ + '.upload_version (%s)' % (retval))
        return retval

    # ready_for_testing
    #
    @property
    def ready_for_testing(s):
        '''
        In order to determine if we're ready for testing the packages need to be
        fully built and published to -proposed. We build in a delay after these
        two conditions are met so that the packages are available in the archive
        to the lab machines that will be installing them.
        '''
        center(s.__class__.__name__ + '.ready_for_testing')
        # We only have mirrors on the primary archive, so if we are not routing
        routing = s.routing('Proposed')
        (archive, pocket) = routing[0]
        if archive.reference == 'ubuntu':
            delay = timedelta(hours=1)
        else:
            delay = timedelta(hours=0)
        retval = s.all_built_and_in_pocket_for('Proposed', delay)
        cinfo('        Ready for testing: %s' % (retval), 'yellow')
        cleave(s.__class__.__name__ + '.ready_for_testing (%s)' % (retval))
        return retval

    # ready_for_testing_as_proposed
    #
    @property
    def ready_for_testing_as_proposed(s):
        '''
        If we have an as-proposed route check if the packages are fully published
        there and return that as current status.  If we do not have an as-proposed
        route fallback to the status in the primary proposed route.
        '''
        center(s.__class__.__name__ + '.ready_for_testing_as_proposed')
        ptap_status = s.bug.task_status(':promote-to-as-proposed')
        if ptap_status == 'Fix Released':
            retval = True

        elif ptap_status != 'Invalid':
            retval = False

        else:
            retval = s.ready_for_testing

        cinfo('        Ready for testing (as-proposed): %s' % (retval), 'yellow')
        cleave(s.__class__.__name__ + '.ready_for_testing_as_proposed (%s)' % (retval))
        return retval

    # ready_for_security
    #
    @property
    def ready_for_security(s):
        '''
        When routinely releasing to -security we will floor our infrastructure
        if the packages have not had sufficient time to mirror out to
        -updates first.  Make them wait in -updates for 20 hours.
        '''
        center(s.__class__.__name__ + '.ready_for_security')
        retval = s.all_built_and_in_pocket('Security')
        if not retval:
            retval = s.all_built_and_in_pocket_for('Updates', timedelta(hours=4))
        cinfo('        Ready for security: %s' % (retval), 'yellow')
        cleave(s.__class__.__name__ + '.ready_for_security (%s)' % (retval))
        return retval

    # Expand a cycle-spin combo so that it is comparible as text.  0 extend
    # the spin number to three digits: 2021.06.31-1 -> 2021.05.31-001.
    # Format: YYYY.MM.DD-SSS.
    def cycle_key(self, cycle):
        if cycle != '-':
            cycle_bits = cycle.split('-')
            try:
                cycle_spin = int(cycle_bits[-1])
            except ValueError:
                cycle_spin = 0
            cycle_bits[-1] = '{:03}'.format(cycle_spin)
            cycle = '-'.join(cycle_bits)
        return cycle

    # older_tracker_in_ppa
    #
    @property
    def older_tracker_in_ppa(s):
        # The target trackers are returned in cycle order.
        target_trackers = s.bug.target_trackers
        #cinfo("older_tracker_in_ppa: {}".format(target_trackers))

        my_cycle_key = s.cycle_key(s.bug.sru_cycle)
        my_id = str(s.bug.lpbug.id)
        for tracker_nr, tracker_data in target_trackers:
            # If we find ourselves then we have considered everything "older".
            if tracker_nr == my_id:
                return None

            # If we find we have an older cycle than the current entry we are older
            # than it.  This only can occur when we are new and have not yet saved
            # a single status.
            if my_cycle_key < tracker_data.get('cycle', '-'):
                return None

            # Consider if this is a blocker if it promote-to-proposed is not
            # Fix Released.
            cinfo("    considering {}".format(tracker_nr))
            ptp_status = tracker_data.get('task', {}).get('promote-to-proposed', {}).get('status', 'Invalid')
            if ptp_status not in ('Invalid', 'Fix Released'):
                cinfo("      promote-to-proposed {} considered blocking".format(ptp_status))
                return tracker_nr

        return None

    # older_tracker_in_proposed
    #
    @property
    def older_tracker_in_proposed(s):
        # The target trackers are returned in cycle order.
        target_trackers = s.bug.target_trackers
        #cinfo("older_tracker_in_ppa: {}".format(target_trackers))

        for tracker_nr, tracker_data in target_trackers:
            # If we find ourselves then we have considered everything "older".
            if tracker_nr == str(s.bug.lpbug.id):
                return None
            # Consider if this is a blocker if it promote-to-proposed is
            # Fix Released and promote-to-updates/release is not Fix Released.
            cinfo("    considering {}".format(tracker_nr))
            ptp_status = tracker_data.get('task', {}).get('promote-to-proposed', {}).get('status', 'Invalid')
            ptu_status = tracker_data.get('task', {}).get('promote-to-updates', {}).get('status', 'Invalid')
            if ptu_status == 'Invalid':
                ptu_status = tracker_data.get('task', {}).get('promote-to-release', {}).get('status', 'Invalid')
            if ptp_status == 'Fix Released' and ptu_status not in ('Invalid', 'Fix Released'):
                cinfo("      promote-to-proposed {} plus promote-to-{{updates,release}} {} considered blocking".format(ptp_status, ptu_status))
                return tracker_nr

        return None

    def check_component_in_pocket(s, tstamp_prop, pocket):
        """
        Check if packages for the given tracking bug were properly copied
        to the right component in the given pocket.
        """
        center(s.__class__.__name__ + '.check_component_in_pocket')
        cdebug('tstamp_prop: ' + tstamp_prop)
        cdebug('     pocket: %s' % pocket)

        # Check if this is a route with components enabled.
        routing = s.bug.debs.routing(pocket)
        if routing is None:
            cleave(s.__class__.__name__ + '.check_component_in_pocket (True) -- no route')
            return (True, [])
        if routing[0][0].reference.startswith('~'):
            cleave(s.__class__.__name__ + '.check_component_in_pocket (True) -- ppa route')
            return (True, [])

        # If the packages are not all built and in -proposed then just bail out of
        # here.
        #
        if not s.bug.debs.all_built_and_in_pocket(pocket):
            cleave(s.__class__.__name__ + '.check_component_in_pocket (False)')
            return (None, [])

        check_component = CheckComponent(s.lp, s)

        primary_src_component = None
        missing_pkg = []
        mis_lst = []
        # Run the packages list for this source, do main first as we need to
        # check components against that.
        for pkg_type in sorted(s.dependent_packages_for_pocket(pocket), key=lambda a: (a != 'main', a)):
            pkg = s.pkgs[pkg_type]
            if pkg_type == 'main':
                check_ver = s.version
            else:
                check_ver = None

            ps = check_component.get_published_sources(s.series, pkg, check_ver, pocket)
            if not ps:
                if check_ver:
                    missing_pkg.append([pkg, check_ver])
                elif pkg_type == 'signed':
                    missing_pkg.append([pkg, 'for version=%s' % (s.version)])
                else:
                    missing_pkg.append([pkg, 'with ABI=%s' % (s.abi)])
                continue

            # We are going to use the primary package source component as
            # our guide.  If we do not have that, then we cannot check.
            if pkg_type == 'main':
                primary_src_component = ps[0].component_name

            # Packages are versioned in a number of ways, try these in 'longest'
            # match order.
            src_ver = ps[0].source_package_version
            match = False
            # <version>+N                      -- signed/lrm respins
            if src_ver.startswith(s.version + '+'):
                cdebug("version is full +N")
                match = True
            # <version>                        -- signed/lrm
            elif src_ver == s.version:
                cdebug("version is exact")
                match = True
            # <base version>.<abi>.<upload>    -- meta/ports-meta
            elif src_ver.startswith(s.kernel + '.' + s.abi + '.'):
                cdebug("version is base.abi.upload")
                match = True
            # <base version>-<abi>.<upload>    -- lbm
            # qualify with package type as this one is abigious against older
            # versions.  We will not use this form for new types.
            elif (pkg_type == 'lbm' and
                    src_ver.startswith(s.kernel + '-' + s.abi + '.')):
                cdebug("version is base-abi.upload (for lbm)")
                match = True

            # If we have a match:
            if match:
                if pkg_type == 'lrm' or s.ancillary_package_for(pkg_type) == 'lrm':
                    if primary_src_component == 'main':
                        which_component = 'restricted'
                    else:
                        which_component = 'multiverse'
                else:
                    which_component = primary_src_component
                mis_lst.extend(check_component.mismatches_list(s.series,
                               pkg, ps[0].source_package_version,
                               pocket, ps, which_component))
            else:
                missing_pkg.append([pkg, 'for version=%s' % (s.version)])

        if missing_pkg:
            cdebug('missing_pkg is set')
            cinfo('        packages not yet available in pocket')
            cdebug('check_component_in_pocket leave (False)')
            return (None, None)

        if mis_lst:
            cdebug('mis_lst is set')
            cinfo('        packages ended up in the wrong pocket')
            cdebug('check_component_in_pocket leave (False)')
            return (False, mis_lst)

        cleave(s.__class__.__name__ + '.check_component_in_pocket (True)')
        return (True, None)

    # send_testing_message
    #
    def send_testing_message(s, op="sru", ppa=False, flavour="generic", meta=None):
        # Send a message to the message queue. This will kick off testing of
        # the kernel packages in the -proposed pocket.
        #
        msg = {
            "key"            : "kernel.publish.proposed.%s" % s.series,
            "op"             : op,
            "who"            : ["kernel"],
            "pocket"         : "proposed",
            "date"           : str(datetime.utcnow()),
            "series-name"    : s.series,
            "kernel-version" : s.version,
            "package"        : s.name,
            "flavour"        : flavour,
        }
        if meta is not None:
            msg['meta-pkg'] = meta

        # Construct the appropriate testing meta package.
        # XXX: note this is currently limited to those packages which are
        #      converted to have the new interfaces.
        #if s.bug.swm_config.hack_kernel_testing:
        #    msg['meta-pkg'] = 'kernel-testing--{}--full--{}'.format(s.name, flavour)

        # Add the kernel-sru-cycle identifier to the message
        #
        msg['sru-cycle'] = s.bug.sru_cycle

        if ppa:
            routing = s.pocket_route('build')
        else:
            # If we have an as-proposed route we will get here when that publishes
            # and we should be preferring it for testing as there is no cache on the
            # front of it and so package publication is deterministic.
            routing = s.pocket_route('as-proposed')
            if routing is None:
                routing = s.pocket_route('Proposed')
        (archive, pocket) = routing
        if archive.reference != 'ubuntu':
            msg['pocket'] = 'ppa'
            # XXX: need to find out what this used for, if it is exclusively
            #      used to look things up using lp.archive.getByReference()
            #      then this ~ handling is not required.
            # XXX: it appears this is used to do an apt-add-repository which
            #      would need a ppa: prefix, though it will add one if missing
            #      and apt-add-repository does handle a ~ prefix as expected
            #      so it is highly likely this is not needed.
            msg['ppa']    = archive.reference.replace('~', 'ppa:')
            msg['key']    = 'kernel.published.ppa.%s' % s.series

        if s.bug._dryrun or s.bug._no_announcements:
            cinfo('    dryrun - Sending msgq announcement', 'red')
            for i, v in msg.items():
                cinfo('        [' + str(i) + '] = ' + str(v), 'red')
        else:
            #if s.bug.local_msgqueue_port:
            #    mq = MsgQueue(address='localhost', port=s.bug.local_msgqueue_port)
            #else:

            # XXX: HACK, connect to both the old and new rabbitmq services for
            # ckct and emit the request into both.  The request will either be
            # understood and consumed or lost in each.  Once we have migrated
            # everything to the new server we can drop the first of these.
            mq = MsgQueue()
            mq.publish(msg['key'], msg)

            mq = MsgQueueCkct()
            mq.publish(msg['key'], msg)

        return msg

    # send_boot_testing_requests
    #
    def send_boot_testing_requests(s):
        s.send_testing_requests(op="boot", ppa=True)

    # send_proposed_testing_requests
    #
    def send_proposed_testing_requests(s):
        s.send_testing_requests(op="sru", ppa=False)

    # test_flavour_meta
    #
    def test_flavour_meta(s):
        if s.source is None:
            return []

        # If we have no testable flavours fall back to legacy mode.
        testables = s.source.testable_flavours
        cdebug("test_flavour_meta: testables={}".format(testables))
        if len(testables) == 0:
            return []

        # If any of the testables have a meta_pkg specified then
        # emit testing for those combinations.
        # NOTE: entries supporting kernel-series will have synthetic
        # meta_pkg entries of the right form.
        result = []
        for flavour in testables:
            if flavour.meta_pkg is not None:
                result.append((flavour.name, flavour.meta_pkg))
        if len(result):
            return result

        # Otherwise if we have no meta-pkg definitions, use the flavour
        # and first variant.
        variants = s.source.variants
        if variants is None or len(variants) == 0:
            variants = ['']
        if variants[0] == '--':
            variants[0] = ''
        for flavour in testables:
            result.append((flavour.name, 'linux-' + flavour.name + variants[0]))

        return result

    # test_flavours
    #
    def test_flavours(s):
        if s.bug.swm_config is not None and s.bug.swm_config.hack_kernel_testing:
            return sorted([x.name for x in s.source.testable_flavours])

        # XXX: this makes no sense at all to be limited to xenial.
        generic = (s.name == 'linux' or
                   s.name.startswith('linux-hwe') or
                   s.name.startswith('linux-lts-'))
        if generic and s.series == 'xenial':
            flavours = [ 'generic', 'lowlatency' ]
        elif generic:
            flavours = [ 'generic' ]
        else:
            flavours = [ s.name.replace('linux-', '') ]

        return flavours

    # send_testing_requests
    #
    def send_testing_requests(s, op="sru", ppa=False):
        for flavour_meta in s.test_flavour_meta():
            s.send_testing_request(op=op, ppa=ppa, flavour=flavour_meta[0], meta=flavour_meta[1])

    # send_testing_request
    #
    def send_testing_request(s, op="sru", ppa=False, flavour="generic", meta=None):
        msg = s.send_testing_message(op, ppa, flavour, meta)

        where = " uploaded" if not ppa else " available in ppa"
        subject = "[" + s.series + "] " + s.name + " " + flavour + " " + s.version + where
        s.bug.announce('swm-testing-started', subject=subject, body=json.dumps(msg, sort_keys=True, indent=4))
        #s.bug.send_email(subject, json.dumps(msg, sort_keys=True, indent=4), 'brad.figg@canonical.com,po-hsu.lin@canonical.com,sean.feole@canonical.com')
