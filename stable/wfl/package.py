#!/usr/bin/env python
#

import re
from datetime                           import datetime, timedelta
import json

from ktl.kernel_series                  import KernelSeries
from ktl.msgq                           import MsgQueue
from lib.utils                          import date_to_string, dump

from .check_component                   import CheckComponent
from .errors                            import ShankError, ErrorExit
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
        if s.source.routing:
            for (key, destination) in (
                ('ppa', 'build'),
                ('Signing', 'signing'),
                ('Proposed', 'proposed'),
                ('Updates', 'updates'),
                ('Security', 'security'),
                ('Release', 'release'),
                ):
                route = s.source.routing.lookup_destination(destination, primary=True)
                if route is None:
                    continue
                archive = s.lp.launchpad.archives.getByReference(reference=route[0])
                # Record invalid pockets as present but broken.
                s._routing[key] = None
                if archive is None:
                    cwarn("invalid-archive {} {}".format(route[0], route[1]))
                    continue
                s._routing[key] = (archive, route[1])
            s.routing_mode = s.source.routing.name


        cinfo('    test_flavours: %s' % (s.test_flavours()), 'blue')
        cinfo('     Routing mode: {}'.format(s.routing_mode), 'blue')
        cinfo('    Routing table:', 'blue')
        for pocket, pocket_data in s._routing.items():
            if pocket_data is None:
                pocket_data = ('NONE', 'NONE')
            cinfo('        {}: {} {}'.format(pocket, pocket_data[0], pocket_data[1]), 'blue')

        s.pkgs = s.dependent_packages
        if s.pkgs == None:
            raise PackageError('Unable to check package builds for this bug: the package/series combination is invalid')

        s._cache = None
        cleave('package::__init__')

    def routing(self, pocket):
        center(self.__class__.__name__ + '.routing')
        routes = self._routing.get(pocket)
        cleave(self.__class__.__name__ + '.routing')
        return routes

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

            # For the linux and linux-signed packages the versions must be an exact match for the other
            # packages only the abi needs to match the linux packages abi number.
            #
            if dep in ['lbm', 'meta', 'ports-meta'] and s.abi:
                abi = s.abi
                version = s.kernel
            else:
                abi = None
                version = s.version

            s._cache[dep] = {}
            if not s.bug.is_development_series:
                cdebug('Stable Package', 'cyan')
                cdebug('')
                scan_pockets = ('ppa', 'Signing', 'Proposed', 'Security', 'Updates')
            else:
                cdebug('Development Package', 'cyan')
                cdebug('')
                scan_pockets = ('ppa', 'Signing', 'Proposed', 'Release')

            for pocket in scan_pockets:
                if pocket not in s._routing:
                    continue
                if s._routing[pocket] is None:
                    s.bug.overall_reason = "{} pocket routing archive specified but invalid {}".format(pocket, s.source)
                    cwarn(s.bug.overall_reason)
                    continue

                s._cache[dep][pocket] = {}
                (src_archive, src_pocket) = s._routing[pocket]
                info = s.__is_fully_built(s.pkgs[dep], abi, src_archive, version, src_pocket)
                s._cache[dep][pocket]['built']   = info[0]
                s._cache[dep][pocket]['creator'] = info[1]
                s._cache[dep][pocket]['signer']  = info[2]
                s._cache[dep][pocket]['published'] = info[3]
                s._cache[dep][pocket]['most_recent_build'] = info[4]
                s._cache[dep][pocket]['status'] = info[5]
                s._cache[dep][pocket]['version'] = info[6]
                cinfo('%-8s : %-5s / %-10s    (%s : %s) %s [%s %s]' % (pocket, info[0], info[5], info[3], info[4], info[6], src_archive, src_pocket), 'cyan')
            Clog.indent -= 4

        cdebug('')
        cdebug('The Cache:', 'cyan')
        for d in sorted(s._cache):
            cdebug('    %s' % d, 'cyan')
            for p in sorted(s._cache[d]):
                cdebug('        %-8s : %-5s   (%s)' % (p, s._cache[d][p]['built'], date_to_string(s._cache[d][p]['published'])), 'cyan')

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

    # __is_fully_built
    #
    def __is_fully_built(s, package, abi, archive, release=None, pocket=''):
        '''
        Have the source package specified been fully built?
        '''
        center(s.__class__.__name__ + '.__is_fully_built')
        cdebug('package: %s' % package, 'yellow')
        cdebug('    abi: %s' % abi,     'yellow')
        cdebug('archive: %s' % archive, 'yellow')
        cdebug('release: %s' % release, 'yellow')
        cdebug(' pocket: %s' % pocket, 'yellow')

        # Do a loose match, we will select for the specific version we wanted
        # in __find_matches but this way we have the published version for
        # pocket emptyness checks.
        ps = s.__get_published_sources(package, abi, archive, pocket=pocket)
        matches = s.__find_matches(ps, abi, release)
        if len(matches) > 0:
            cdebug('    match: %s (%s)' % (release, abi), 'green')
            fullybuilt, creator, signer, published, most_recent_build, status = s.__sources_built(matches, archive, package, release, pocket)
            version = matches[0].source_package_version
        else:
            fullybuilt   = False
            status  = ''
            creator = None
            signer  = None
            published = None
            most_recent_build = None
            version = None
            if len(ps) > 0:
                version = ps[0].source_package_version

        cleave(s.__class__.__name__ + '.__is_fully_built')
        return fullybuilt, creator, signer, published, most_recent_build, status, version

    # __get_published_sources
    #
    def __get_published_sources(s, package, abi, archive, release=None, pocket=''):
        """
        The parameters are:
          package   - the package name
          release   - the version or version-abi number to match
          abi       - if provided, indicates that release is not an exact version number,
                      and we must do an ABI check
          archive   - launchpad archive to look into
          pocket    - optional, if we want only results of the archive from
                      the specified pocket
        """
        center(s.__class__.__name__ + '.__get_published_sources')
        cdebug('package: %s' % package, 'yellow')
        cdebug('    abi: %s' % abi,     'yellow')
        cdebug('archive: %s' % archive, 'yellow')
        cdebug(' series: %s' % s.distro_series, 'yellow')
        cdebug('release: %s' % release, 'yellow')
        if pocket == '':
            cdebug(' pocket: ppa', 'yellow')
        else:
            cdebug(' pocket: %s' % pocket, 'yellow')
        cdebug('')

        if pocket and not abi:
            # If the abi is not specified then we are looking for an explicit release in a specific
            # pocket.
            #
            cdebug('getPublishedSources: rule 1')
            ps = archive.getPublishedSources(distro_series=s.distro_series, exact_match=True, source_name=package, status='Published', version=release, pocket=pocket)
        elif not pocket and not abi:
            cdebug('getPublishedSources: rule 2')
            ps = archive.getPublishedSources(distro_series=s.distro_series, exact_match=True, source_name=package, status='Published', version=release)
        elif pocket and abi:
            cdebug('getPublishedSources: rule 3')
            ps = archive.getPublishedSources(distro_series=s.distro_series, exact_match=True, source_name=package, status='Published', pocket=pocket)
        else:
            cdebug('getPublishedSources: rule 4')
            ps = archive.getPublishedSources(distro_series=s.distro_series, exact_match=True, source_name=package, status='Published')

        cdebug('records: %d' % len(ps), 'yellow')
        cleave(s.__class__.__name__ + '.__get_published_sources')
        return ps

    # __find_matches
    #
    def __find_matches(s, ps, abi, release):
        center('Sources::__find_matches')
        cdebug('    abi: %s' % abi,     'yellow')
        cdebug('release: %s' % release, 'yellow')
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
                if src_ver == release or src_ver.startswith(release + '+'):
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
        cdebug('archive: %s' % archive, 'yellow')
        cdebug('package: %s' % package, 'yellow')
        cdebug('release: %s' % release, 'yellow')
        cdebug(' pocket: %s' % pocket, 'yellow')

        # If we do get more than one match we should be picking the latest.
        if len(sources) != 1:
            raise ValueError("too many sources")

        source = sources[0]

        package_creator = source.package_creator
        package_signer = source.package_signer
        published = source.date_published
        latest_build = source.date_published
        status = set()
        status.add('UNKNOWN')

        cdebug("source status={}".format(source.status))
        if source.status in ('Pending'):
            status.add('BUILDING')
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
        for build in builds:
            ##print(build, build.buildstate, build.datebuilt)
            cdebug("build arch={} status={}".format(build.arch_tag, build.buildstate))
            if build.buildstate in (
                    'Needs building',
                    'Dependency wait',
                    'Currently building',
                    'Uploading build',
                ):
                    status.add('BUILDING')

            elif build.buildstate in ('Successfully built'):
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

            # Accumulate the latest build completion.
            if build.datebuilt is not None and latest_build < build.datebuilt:
                latest_build = build.datebuilt

            # Accumulate the architectures we are meant to build for.
            arch_build.add(build.arch_tag)

        arch_published = set()
        binaries = source.getPublishedBinaries()
        for binary in binaries:
            ##print(binary, binary.status, binary.date_published)
            if binary.architecture_specific:
                arch_tag = binary.distro_arch_series_link.split('/')[-1]
            else:
                arch_tag = 'all'
            cdebug("binary arch={} status={}".format(arch_tag, binary.status))
            if binary.status in ('Pending'):
                status.add('BUILDING')
            elif binary.status in ('Published'):
                status.add('FULLYBUILT')
            else:
                # Anything else is broken.
                #  Superseded
                #  Deleted
                #  Obsolete
                status.add('FAILEDTOBUILD')

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
                status.add('FULLYBUILT_PENDING')
            else:
                status.add('BUILDING')

        # Pick out the stati in a severity order.
        for state in ('FAILEDTOBUILD', 'BUILDING', 'FULLYBUILT_PENDING', 'FULLYBUILT', 'UNKNOWN'):
            if state in status:
                break

        published = published.replace(tzinfo=None)
        latest_build = latest_build.replace(tzinfo=None)

        cleave('Sources::__sources_built' )
        return state == 'FULLYBUILT', package_creator, package_signer, published, latest_build, state

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
        pkgs = {}
        series = s.kernel_series.lookup_series(codename=s.series)
        source = series.lookup_source(s.name)
        if source is None:
            return None
        for package in source.packages:
            pkgs[package.type if package.type else 'main'] = package.name

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

    # fully_built
    #
    def fully_built(s, pkg):
        center('Package::fully_built')
        cdebug('   pkg: \'%s\'' % pkg)
        retval = False

        try:
            for pocket in s.srcs[pkg]:
                if s.srcs[pkg][pocket]['built']:
                    retval = True
                    break
        except KeyError:
            pass # Eat the KeyError and return False

        cleave('Package::fully_built (%s : %s)' % (pkg, retval))
        return retval

    # all_in_pocket
    #
    def all_in_pocket(s, pocket):
        '''
        All dependent packages are in the pocket 'pocket'.
        '''
        center(s.__class__.__name__ + '.all_in_pocket')
        retval = True

        for pkg in s.srcs:
            try:
                pkg_seen = s.srcs[pkg][pocket]['status'] in ['BUILDING', 'FULLYBUILT', 'FULLYBUILT_PENDING', 'FAILEDTOBUILD']
            except KeyError:
                pkg_seen = False

            if pkg_seen:
                cinfo('        %s is present in %s.' % (pkg, pocket), 'yellow')
            else:
                cinfo('        %s is NOT present in %s.' % (pkg, pocket), 'yellow')
                retval = False

        cleave(s.__class__.__name__ + '.all_in_pocket (%s)' % (retval))
        return retval

    # all_built_and_in_pocket
    #
    def all_built_and_in_pocket(s, pocket):
        '''
        All dependent packages are fully built and in the pocket 'pocket'.
        '''
        center(s.__class__.__name__ + '.all_built_and_in_pocket')
        retval = True

        for pkg in s.srcs:
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
            now = datetime.utcnow()
            comp_date = date_available + period
            if comp_date < now:
                retval = True
            else:
                cinfo('It has been less than {} since the last package was either published or built in {}'.format(period, pocket))
                cinfo('    target: %s' % comp_date)
                cinfo('       now: %s' % now)

        cleave(s.__class__.__name__ + '.all_built_and_in_pocket_for (%s)' % (retval))
        return retval

    # all_failures_in_pocket
    #
    def all_failures_in_pocket(s, pocket):
        failures = []
        for pkg in s.srcs:
            status = s.srcs[pkg].get(pocket, {}).get('status')
            if status == 'BUILDING':
                failures.append("{}:building".format(pkg))
            elif status == 'FAILEDTOBUILD':
                # Signed is allowed to be broken until we have built the main kernel.
                if pkg != 'signed':
                    failures.append("{}:failed".format(pkg))
            elif status == '':
                failures.append("{}:missing".format(pkg))
            elif status == 'FULLYBUILT_PENDING':
                failures.append("{}:queued".format(pkg))

        if (s.srcs.get('signed', {}).get(pocket, {}).get('status') == 'FAILEDTOBUILD' and
                s.srcs.get('main', {}).get(pocket, {}).get('status') == 'FULLYBUILT'):
            failures.append("signed:retry-needed")

        return sorted(failures) if len(failures) > 0 else None

    # creator
    #
    def creator(s, pkg, pocket=None):
        center('Packages::creator')
        cdebug('   pkg: %s' % pkg)
        cdebug('pocket: %s' % pocket)
        retval = None

        if pocket is None:
            for pocket in s.srcs[pkg]:
                if s.srcs[pkg][pocket]['status'] in ['BUILDING', 'FULLYBUILT', 'FULLYBUILT_PENDING', 'FAILEDTOBUILD']:
                    retval = s.srcs[pkg][pocket]['creator']
                    break
        else:
            retval = s.srcs[pkg][pocket]['creator']
        cleave('Packages::creator')
        return retval

    # signer
    #
    def signer(s, pkg, pocket=None):
        center('Packages::signer')
        cdebug('   pkg: %s' % pkg)
        cdebug('pocket: %s' % pocket)
        retval = None

        if pocket is None:
            for pocket in s.srcs[pkg]:
                if s.srcs[pkg][pocket]['built']:
                    retval = s.srcs[pkg][pocket]['signer']
                    break
        else:
            retval = s.srcs[pkg][pocket]['signer']
        cleave('Packages::signer')
        return retval

    # package_fully_built
    #
    def package_fully_built(s, pkg):
        '''
        For the package specified, the status of whether or not it is fully built
        is returned.
        '''
        retval = s.fully_built(pkg)
        return retval

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
        for pkg in bi:
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
        for pkg in bi:
            if bi[pkg][pocket]['built'] is not True:
                cinfo('            %s has not been released.' % (pkg), 'yellow')
                retval = False
                break

        return retval

    # pocket_clear
    #
    def pocket_clear(s, pocket, pocket_next):
        '''
        Check that the proposed pocket is either empty or contains the same version
        as found in -updates/-release.
        '''
        retval = True

        # Release/Updates maps based on development series.
        if pocket_next == 'Release/Updates':
            pocket_next = 'Release' if s.bug.is_development_series else 'Updates'

        bi = s.build_info
        for pkg in bi:
            if bi[pkg][pocket]['version'] not in (None, bi[pkg][pocket_next]['version']):
                cinfo('            {} has {} pending in {}.'.format(pkg, bi[pkg][pocket]['version'], pocket), 'yellow')
                retval = False

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
        for pocket in bi[pkg]:
            if bi[pkg][pocket]['status'] in ['BUILDING', 'FULLYBUILT', 'FULLYBUILT_PENDING', 'FAILEDTOBUILD']:
                retval = True

        cleave(s.__class__.__name__ + '.uploaded (%s)' % (retval))
        return retval

    def upload_version(s, pkg):
        '''
        '''
        center(s.__class__.__name__ + '.upload_version')
        retval = None

        bi = s.build_info
        for pocket in bi[pkg]:
            if bi[pkg][pocket]['status'] in ['BUILDING', 'FULLYBUILT', 'FULLYBUILT_PENDING', 'FAILEDTOBUILD']:
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
        retval = s.all_built_and_in_pocket_for('Proposed', timedelta(hours=1.5))
        cinfo('        Ready for testing: %s' % (retval), 'yellow')
        cleave(s.__class__.__name__ + '.ready_for_testing (%s)' % (retval))
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
        retval = s.all_built_and_in_pocket_for('Updates', timedelta(hours=20))
        cinfo('        Ready for security: %s' % (retval), 'yellow')
        cleave(s.__class__.__name__ + '.ready_for_security (%s)' % (retval))
        return retval

    def check_component_in_pocket(s, tstamp_prop, pocket):
        """
        Check if packages for the given tracking bug were properly copied
        to the right component in the given pocket.
        """
        center(s.__class__.__name__ + '.check_component_in_pocket')
        cdebug('tstamp_prop: ' + tstamp_prop)
        cdebug('     pocket: %s' % pocket)

        # If the packages are not all built and in -proposed then just bail out of
        # here.
        #
        if not s.ready_for_testing:
            cleave(s.__class__.__name__ + '.check_component_in_pocket (False)')
            return False

        check_component = CheckComponent(s.lp, s)

        primary_src_component = None
        missing_pkg = []
        mis_lst = []
        # Run the packages list for this source, do main first as we need to
        # check components against that.
        for (pkg_type, pkg) in sorted(s.pkgs.items(), key=lambda a: (a[0] != 'main', a[0])):
            if pkg_type == 'main':
                check_ver = s.version
            else:
                check_ver = None

            ps = check_component.get_published_sources(s.series, pkg, check_ver, pocket)
            if not ps:
                if check_ver:
                    missing_pkg.append([pkg, check_ver])
                elif 'linux-signed' in pkg:
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
                if pkg_type == 'lrm':
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
            return False

        if mis_lst:
            cdebug('mis_lst is set')

            task_name = 'promote-to-%s' % (pocket,)
            cinfo('        checking %s task status is %s' % (task_name, s.bug.tasks_by_name[task_name].status))
            if s.bug.tasks_by_name[task_name].status != 'Incomplete':
                s.bug.tasks_by_name[task_name].status = 'Incomplete'

                body  = "The following packages ended up in the wrong"
                body += " component in the -%s pocket:\n" % (pocket)
                for item in mis_lst:
                    cdebug('%s %s - is in %s instead of %s' % (item[0], item[1], item[2], item[3]), 'green')
                    body += '\n%s %s - is in %s instead of %s' % (item[0], item[1], item[2], item[3])

                subject = '[ShankBot] [bug %s] Packages copied to the wrong component' % (s.bug.lpbug.id)
                to_address  = "kernel-team@lists.ubuntu.com"
                to_address += ", ubuntu-installer@lists.ubuntu.com"
                cinfo('        sending email alert')
                s.bug.send_email(subject, body, to_address)

                body += "\n\nOnce this is fixed, set the "
                body += "promote-to-%s to Fix Released again" % (pocket)
                s.bug.add_comment('Packages outside of proper component', body)

            cinfo('        packages ended up in the wrong pocket')
            cdebug('check_component_in_pocket leave (False)')
            return False

        cleave(s.__class__.__name__ + '.check_component_in_pocket (True)')
        return True

    # send_testing_message
    #
    def send_testing_message(s, op="sru", ppa=False, flavour="generic"):
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

        # Add the kernel-sru-cycle identifier to the message
        #
        msg['sru-cycle'] = s.bug.sru_cycle

        # At this time only 2 arches have the lowlatency flavour
        #
        if flavour == 'lowlatency':
            msg['arches'] = ['amd64', 'i386']

        if ppa:
            routing = s.routing('ppa')
        else:
            routing = s.routing('Proposed')

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
            if s.bug.local_msgqueue_port:
                mq = MsgQueue(address='localhost', port=s.bug.local_msgqueue_port)
            else:
                mq = MsgQueue()

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

    # test_flavours
    #
    def test_flavours(s):
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
        for flavour in s.test_flavours():
            s.send_testing_request(op=op, ppa=ppa, flavour=flavour)

    # send_testing_request
    #
    def send_testing_request(s, op="sru", ppa=False, flavour="generic"):
        msg = s.send_testing_message(op, ppa, flavour)

        where = " uploaded" if not ppa else " available in ppa"
        subject = "[" + s.series + "] " + s.name + " " + flavour + " " + s.version + where
        s.bug.send_email(subject, json.dumps(msg, sort_keys=True, indent=4), 'brad.figg@canonical.com,po-hsu.lin@canonical.com,sean.feole@canonical.com')
