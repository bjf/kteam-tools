#!/usr/bin/env python
#

from   ktl.utils                import fileage
from   ktl.kernel               import *
from   launchpadlib.launchpad   import Launchpad   
from   urllib                   import urlopen
import json
import re
    
def compare_versions(version1, version2):
    #print 'comparing ', version1, 'and', version2
    # 2.6.35-26.46

    r1 = re.split('[-\.\~]', version1)
    r2 = re.split('[-\.\~]', version2)
    for i in range(0, len(r1)):
        if r1[i] != r2[i]:
            return  int(r1[i]) - int(r2[i])

    return 0

# KernelError
#
class KernelError(Exception):
    # __init__
    #
    def __init__(self, error):
        self.msg = error

# Kernel
#
class Archive:
    debug               = False

    # for Launchpad API
    cachedir = "/tmp/.launchpadlib/cache/"

    # How often should we fetch files? (seconds)
    #file_lifetime = 900 # 15 minutes
    file_lifetime = 60 # 1 minute (for testing)

    #statuses = ['Pending', 'Published']
    statuses = ['Published']

    # related to the kernel ppa
    __ppa_get_deleted       = False
    __ppa_get_obsolete      = False
    __ppa_get_superseded    = False
    ppa = None
    allppainfo = False
    teamname = 'canonical-kernel-team'
    ppaname = 'ppa'
    ppafilename = 'ckt-ppa.json'

    # related to the kernel distro archive
    __distro_get_deleted       = False
    __distro_get_obsolete      = False
    __distro_get_superseded    = False
    distro = None
    alldistroinfo = False
    distrofilename = 'distro-archive.json'

    # version
    #
    def ppa_versions(self, force = False):
        self.__fetch_ppa_if_needed(force)
        return self.ppa

    # version
    #
    def distro_versions(self, force = False):
        self.__fetch_distro_if_needed(force)
        return self.distro

    # __fetch_ppa_if_needed
    #
    def __fetch_ppa_if_needed(self, force):
        # see if there is a local json file that is recent
        # if there is, return the data
        age = fileage(self.ppafilename)

        if force or (not age) or (age > self.file_lifetime):
            # fetch from the PPA
            print 'Fetching from Launchpad'

            statuses = list(self.statuses)
            if self.__ppa_get_deleted:
                statuses.append('Deleted')
            if self.__ppa_get_obsolete:
                statuses.append('Obsolete')
            if self.__ppa_get_superseded:
                statuses.append('Superseded')

            jf = open(self.ppafilename, 'w+')

            outdict = {}
            lp = Launchpad.login_anonymously('kernel team tools', 'production', self.cachedir)
            person = lp.people[self.teamname]
            ppa = person.getPPAByName(name=self.ppaname)

            for astatus in statuses:
                psrc = ppa.getPublishedSources(status=astatus)
                for p in  psrc:
                    fd = urlopen(p.self_link)
                    sourceinfo = json.load(fd)

                    # Add some plain text fields for some info
                    sourceinfo['creator'] = sourceinfo['package_creator_link'].split('/')[-1].strip('~') 
                    sourceinfo['signer'] = sourceinfo['package_signer_link'].split('/')[-1].strip('~') 
                    rm = re.match('[0-9]\.[0-9]\.[0-9][0-9]', sourceinfo['source_package_version'])
                    version = rm.group(0)
                    sourceinfo['series'] = map_kernel_version_to_ubuntu_release[version]['name']
                    # And strip some things we don't care about
                    if not self.allppainfo:
                        for delkey in ['archive_link', 'distro_series_link', 'http_etag', 'package_maintainer_link', \
                                           'resource_type_link', 'package_creator_link', 'package_signer_link', \
                                           'section_name', 'scheduled_deletion_date', 'removal_comment', 'removed_by_link']:
                            del sourceinfo[delkey]

                    key = p.source_package_name + '-' + p.source_package_version
                    outdict[key] = sourceinfo
            jf.write(json.dumps(outdict, sort_keys=True, indent=4))
            jf.close()

            self.ppa = outdict
        else:
            # read from the local file
            f = open(self.ppafilename, 'r')
            # read it
            self.ppa = json.load(f)
            f.close()
        return


    # __fetch_distro_if_needed
    #
    def __fetch_distro_if_needed(self, force):
        # see if there is a local json file that is recent
        # if there is, return the data
        age = fileage(self.distrofilename)

        if force or (not age) or (age > self.file_lifetime):
            # fetch from the PPA
            print 'Fetching from Distro archives'

            statuses = list(self.statuses)
            if self.__distro_get_deleted:
                statuses.append('Deleted')
            if self.__distro_get_obsolete:
                statuses.append('Obsolete')
            if self.__distro_get_superseded:
                statuses.append('Superseded')

            jf = open(self.ppafilename, 'w+')

            lp = Launchpad.login_anonymously('kernel team tools', 'production', self.cachedir)
            masteroutdict = {}

            # get a list of the series that we want info about
            #for key, info in map_release_number_to_ubuntu_release.items():
            #    if not info['supported']:
            #        continue

#
#

            #archive = lp.distributions['ubuntu'].getSeries(name_or_version=info['name']).main_archive
            archive = lp.distributions['ubuntu'].getArchive(name='primary')

            for astatus in statuses:
                for pname in kernel_package_names:
                    print 'fetching for package', pname
                    print 'fetching for status', astatus
                    outdict = {}
                    psrc = archive.getPublishedSources(status=astatus, exact_match = True, source_name = pname)
                    for p in  psrc:
                        fd = urlopen(p.self_link)
                        sourceinfo = json.load(fd)
                        #print json.dumps(sourceinfo, sort_keys=True, indent=4)

                        # Add some plain text fields for some info
                        field = sourceinfo['package_creator_link']
                        if field:
                            sourceinfo['creator'] = field.split('/')[-1].strip('~') 
                        else:
                            sourceinfo['creator'] = 'Unknown'
                        field = sourceinfo['package_signer_link']
                        if field:
                            sourceinfo['signer'] = field.split('/')[-1].strip('~') 
                        else:
                            sourceinfo['signer'] = 'Unknown'
                        rm = re.match('[0-9]\.[0-9]\.[0-9][0-9]', sourceinfo['source_package_version'])
                        version = rm.group(0)
                        try:
                            sourceinfo['series'] = map_kernel_version_to_ubuntu_release[version]['name']
                        except:
                            sourceinfo['series'] = 'Unknown'
                        # And strip some things we don't care about
                        if not self.allppainfo:
                            for delkey in ['archive_link', 'distro_series_link', 'http_etag', 'package_maintainer_link', \
                                               'resource_type_link', 'package_creator_link', 'package_signer_link', \
                                               'section_name', 'scheduled_deletion_date', 'removal_comment', 'removed_by_link']:
                                del sourceinfo[delkey]

                        key = p.source_package_name + '-' + p.source_package_version
                        print '    found: ', key
                        outdict[key] = sourceinfo

                    if len(outdict) == 0:
                        print 'Nothing from ', astatus, pname
                        continue

                    #
                    # Now we have every package in the archive
                    # Remove all the unsupported ones
                    # we add Unknown because we used it to flag some funky dapper packages earlier
                    unsupported = ['Unknown']
                    resultsbyseries = {}
                    for key, release in map_release_number_to_ubuntu_release.items():
                        if not release['supported']:
                            if self.debug:
                                print 'DEBUG: Fetching from archive, will skip release ', release['name']
                            unsupported.append(release['name'])
                        else:
                            resultsbyseries[release['name']] = dict()

                    # remove unwanted ones and group by series
                    print 'items in outdict BEFORE:', len(outdict)
                    for name, sourceinfo in outdict.items():
                        if sourceinfo['series'] in unsupported:
                            if self.debug:
                                print 'DEBUG: Fetching from archive, skipping ', name
                            del(outdict[name])
                        else:
                            print '$$', name
                            print '|||', sourceinfo['series']
                            #print sourceinfo
                            resultsbyseries[sourceinfo['series']][name] = outdict[name]

                    print 'items in outdict AFTER:', len(outdict)
                    print 'we have results for', len(resultsbyseries), 'series'
                    #print json.dumps(resultsbyseries, sort_keys=True, indent=4)

                    # Order them within series and remove all but the highest version
                    for seriesname, seriespackages in resultsbyseries.items():
                        if len(seriespackages) == 0:
                            continue
                        # now for each series collection, we want the highest version number
                        tmplist = {}
                        for dname, tpinfo in resultsbyseries[seriesname].items():
                            if self.debug:
                                print 'Name', dname, 'tpinfo', tpinfo
                            tmplist[tpinfo['source_package_version']] = dname

                            slist = sorted(tmplist, compare_versions, reverse=True)

                        print '111'
                        print tmplist
                        print slist
                        print '222'
                        for k in range(1, len(slist)):
                            print 'deleting', tmplist[slist[k]]
                            del(outdict[tmplist[slist[k]]])
                    masteroutdict.update(outdict)

            jf.write(json.dumps(masteroutdict, sort_keys=True, indent=4))
            jf.close()
            self.ppa = masteroutdict
        else:
            # read from the local file
            f = open(self.ppafilename, 'r')
            # read it
            self.ppa = json.load(f)
            f.close()
        return self.ppa

# vi:set ts=4 sw=4 expandtab:
