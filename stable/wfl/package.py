#!/usr/bin/env python
#

import re
from datetime                           import datetime

from ktl.ubuntu                         import Ubuntu
from ktl3.utils                         import date_to_string, dump

from .errors                            import ShankError, ErrorExit
from .log                               import cdebug, cerror, cwarn, center, cleave, Clog, cinfo

# PackageError
#
class PackageError(ShankError):
    '''
    Thrown when some basic information about the package that is associated with the
    shankbug could not be determined.
    '''
    def __init__(s, emsg):
        super(ShankError, s).__init__(emsg)

# SeriesLookupFailure
#
class SeriesLookupFailure(ShankError):
    '''
    Thrown when the series lookup throws a KeyError exception.
    '''
    def __init__(s, emsg):
        super(ShankError, s).__init__(emsg)

# Package
#
class Package():

    # __init__
    #
    def __init__(s, lp, shankbug):
        center('package::__init__')
        s.lp = lp
        s.bug = shankbug

        s.ubuntu = Ubuntu()
        s.__distro_series = None

        esm = s.lp.launchpad.people['canonical-kernel-esm']
        s.esm_build_ppa    = esm.getPPAByName(name='ppa')
        s.esm_proposed_ppa = esm.getPPAByName(name='proposed')

        ckt = s.lp.launchpad.people['canonical-kernel-team']
        s.ckt_ppa = ckt.getPPAByName(name='ppa')

        s.main_archive = s.lp.launchpad.distributions["ubuntu"].main_archive

        # Determine some properties of the package we are looking at based on the
        # bug title. This information is used further on.
        #
        s.package = s.__title_decode(s.bug.lpbug.title)
        if not s.valid:
            cwarn('        Unable to check package builds for this bug: either the package name or')
            cwarn('        the version are not properly indicated in the bug title.')
            raise PackageError(['Unable to check package builds for this bug: either the package name or',
                                'the version is not properly indicated in the bug title.'])

        setattr(s, 'series', s.ubuntu.series_name(s.name, s.version))

        s.pkgs = s.dependent_packages

        s._cache = None
        cleave('package::__init__')

    def __title_decode(s, txt):
        matched = False
        #                              .- package name (group(1))
        #                             /           .- kernel version (group(2))
        #                            /           /          .- version/abi separator (group(3))
        #                           /           /          /
        ver_rc     = re.compile("(\S+): (\d+\.\d+\.\d+)([-\.])(\d+)\.(\d+)([~a-z\d.]*)")
        #                                                       /      /       /
        #                                                      /      /       .- backport extra (m.group(6))
        #                                                     /      .- upload number (m.group(5))
        #                                                    .- abi (group(4))

        #info('     Extract package info\n')
        setattr(s, 'valid', False)
        setattr(s, 'hwe', False)
        m = ver_rc.search(txt)
        if m is not None:
            matched = True
            cdebug('package: %s' % m.group(1))
            cdebug('version: %s%s%s.%s%s' % (m.group(2), m.group(3), m.group(4), m.group(5), m.group(6)))
            cdebug(' kernel: %s' % m.group(2))
            cdebug('    abi: %s' % m.group(4))

            setattr(s, 'name', m.group(1))
            setattr(s, 'version', '%s%s%s.%s%s' % (m.group(2), m.group(3), m.group(4), m.group(5), m.group(6)))
            setattr(s, 'kernel', m.group(2))
            setattr(s, 'abi', m.group(4))

            if m.group(6):
                s.hwe = True

            setattr(s, 'test_series', s.ubuntu.lookup(m.group(2))['name'])
            setattr(s, 'test_series_version', s.ubuntu.index_by_series_name[s.test_series]['series_version'])

            s.valid = True

        if not matched:
            cwarn(' ** None of the regular expressions matched the title (%s)' % txt)

    # __determine_build_status
    #
    def __determine_build_status(s):
        center('Sources::__determine_build_status')

        pockets = {
            'kernel-development-workflow' : ['ckt-ppa', 'Proposed', 'Release'],
            'kernel-sru-workflow'         : ['esm-build-ppa', 'esm-proposed-ppa', 'ckt-ppa', 'Proposed', 'Security', 'Updates']
        }

        archives = {
            'esm-build-ppa'    : s.esm_build_ppa,
            'esm-proposed-ppa' : s.esm_proposed_ppa,
            'ckt-ppa'          : s.ckt_ppa,
            'Proposed'         : s.main_archive,
            'Security'         : s.main_archive,
            'Updates'          : s.main_archive,
            'Release'          : s.main_archive,
        }

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
            for pocket in pockets[s.bug.workflow_project]:
                # print(dep + ' : ' + pocket)
                s._cache[dep][pocket] = {}

                info = s.__is_fully_built(s.dependent_packages[dep], abi, archives[pocket], version, None if '-ppa' in pocket else pocket)
                s._cache[dep][pocket]['built']   = info[0]
                s._cache[dep][pocket]['creator'] = info[1]
                s._cache[dep][pocket]['signer']  = info[2]
                s._cache[dep][pocket]['published'] = info[3]
                s._cache[dep][pocket]['most_recent_build'] = info[4]
                s._cache[dep][pocket]['status'] = info[5]
                cinfo('%-16s : %-5s / %-10s    (%s : %s)' % (pocket, info[0], info[5], info[3], info[4]), 'cyan')

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

        ps = s.__get_published_sources(package, abi, archive, release, pocket)
        matches = s.__find_matches(ps, abi, release)
        if len(matches) > 0:
            cdebug('    match: %s (%s)' % (release, abi), 'green')
            fullybuilt, creator, signer, published, most_recent_build, status = s.__sources_built(matches, archive, package, release, pocket)
            fullybuilt = fullybuilt and s.__all_arches_built(matches)
        else:
            fullybuilt   = False
            status  = ''
            creator = None
            signer  = None
            published = None
            most_recent_build = None

        cleave(s.__class__.__name__ + '.__is_fully_built')
        return fullybuilt, creator, signer, published, most_recent_build, status

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

        cleave(s.__class__.__name__ + '.__get_published_sources')
        return ps

    # __find_matches
    #
    def __find_matches(s, ps, abi, release):
        center('Sources::__find_matches')
        cdebug('    abi: %s' % abi,     'yellow')
        cdebug('release: %s' % release, 'yellow')

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
                cdebug('adding: %s' % src_ver, 'green')
                matches.append(p)
                match = True

        cleave('Sources::__find_matches (%s)' % match)
        return matches

    # __sources_built
    #
    def __sources_built(s, matches, archive, package, release, pocket):
        '''
        '''
        center('Sources::__sources_built')
        cdebug('matches: %s' % matches, 'yellow')
        cdebug('archive: %s' % archive, 'yellow')
        cdebug('package: %s' % package, 'yellow')
        cdebug('release: %s' % release, 'yellow')
        cdebug(' pocket: %s' % pocket, 'yellow')
        retval = False
        lst_date = None
        fullybuilt = False
        creator = ''
        signer  = ''
        published = None
        status = ''

        # built - The date/time of the last build of any of the arches built. We want
        #         the one that finished most recently.
        #
        most_recent_build = None
        for pkg in matches:
            src_id = str(pkg.self).rsplit('/', 1)[1]

            build_summaries = archive.getBuildSummariesForSourceIds(source_ids=[src_id])[src_id]
            status = build_summaries['status']
            try:
                creator = pkg.package_creator
                signer  = pkg.package_signer
            except:
                # Just eat the error
                pass

            if build_summaries['status'] == 'FULLYBUILT':
                cdebug('"%s" %s built (pocket:%s)' % (package, release, pocket), 'magenta')
                retval = True
                fullybuilt = True
                published = pkg.date_published.replace(tzinfo=None)

                for b in build_summaries['builds']:
                    built = datetime.strptime(b['datebuilt'], '%Y-%m-%dT%X.%f+00:00')
                    if most_recent_build is None:
                        most_recent_build = built
                    else:
                        if most_recent_build < built:
                            most_recent_build = built
            else:
                cdebug('"%s" %s not fully built yet, skipping (pocket:%s)' % (package, release, pocket), 'green')
            # prefer newer published items...
            if lst_date:
                if lst_date > pkg.date_published:
                    continue
            lst_date = pkg.date_published

        cleave('Sources::__sources_built (%s)' % retval)
        return fullybuilt, creator, signer, published, most_recent_build, status

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
        try:
            series = s.ubuntu.series_name(s.name, s.version)
        except KeyError:
            raise SeriesLookupFailure(['Unable to determine the series from the kernel version specified',
                                       'in the bug title.'])

        entry = s.ubuntu.lookup(series)
        if entry:
            if 'dependent-packages' in entry:
                if s.name in entry['dependent-packages']:
                    pkgs.update(entry['dependent-packages'][s.name])

        # The package depends upon itself
        #
        pkgs['main'] = s.name

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

    # all_built_and_in_proposed
    #
    @property
    def all_built_and_in_proposed(s):
        '''
        All dependent packages are fully built and in the proposed pocket.
        '''
        center(s.__class__.__name__ + '.all_built_and_in_proposed')
        retval = True

        for pkg in s.srcs:
            try:
                pkg_built = s.srcs[pkg]['Proposed']['built']
            except KeyError:
                pkg_built = False

            if not pkg_built:
                cinfo('        %s is either not fully built yet or not in proposed.' % pkg, 'red')
                retval = False
                break

        cleave(s.__class__.__name__ + '.all_built_and_in_proposed (%s)' % (retval))
        return retval

    # creator
    #
    def creator(s, pkg, pocket=None):
        center('Packages::creator')
        cdebug('   pkg: %s' % pkg)
        cdebug('pocket: %s' % pocket)
        retval = None

        if pocket is None:
            for pocket in s.srcs[pkg]:
                if s.srcs[pkg][pocket]['status'] in ['BUILDING', 'FULLYBUILT', 'FAILEDTOBUILD']:
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

