#!/usr/bin/env python

try:
    from urllib.request import urlopen, Request
    from urllib.parse import urlencode, urljoin
    from urllib.error import URLError, HTTPError
except ImportError:
    from urllib2 import urlopen, urlencode, Request, URLError, HTTPError

import json
from .errors import ShankError

from wfl.log                                    import center, cleave, cinfo, cerror, cdebug


# SnapStoreError
#
class SnapStoreError(ShankError):
    """
    Thrown when something goes wrong with the snap store (e.g. snap not found).
    """
    pass


# SnapStore
#
class SnapStore:
    """
    A helper class to handle Snapcraft store operations.
    """
    base_url = "https://search.apps.ubuntu.com/api/v1/snaps/details/"
    common_headers = {'X-Ubuntu-Series': '16'}

    # __init__
    #
    def __init__(s, bug, snap):
        """
        :param bug: WorkflowBug object
        """
        s.bug = bug
        s._dependent_snap = snap
        s._snap_store_versions = {}  # dictionary with {<channel>: {<arch>: <version>[, ...]}[, ...]}

    # _get_snap_info
    #
    def _get_snap_info(s, channel):
        """
        Query the snap store URL to get the information about the kernel snap
        on the provided channel and store it in the private variables.

        :return: nothing
        """
        cdebug("    dependent_snap.name = %s" % str(s._dependent_snap.name))
        cdebug("    dependent_snap.arches = %s" % str(s._dependent_snap.arches))

        s._snap_store_versions[channel] = {}
        for arch in s._dependent_snap.arches:
            try:
                headers = s.common_headers
                headers['X-Ubuntu-Architecture'] = arch
                params = urlencode({'fields': 'version', 'channel': channel})
                url = "%s?%s" % (urljoin(s.base_url, s._dependent_snap.name), params)
                req = Request(url, headers=headers)
                with urlopen(req) as resp:
                    version = json.loads(resp.read().decode('utf-8'))['version']
                    s._snap_store_versions[channel][arch] = version
            except HTTPError as e:
                # Error 404 is returned if the snap has never been published
                # to the given channel.
                store_err = False
                if hasattr(e, 'code') and e.code == 404:
                    ret_body = e.read().decode()
                    store_err_str = 'has no published revisions in the given context'
                    if store_err_str in ret_body:
                        store_err = True
                        s._snap_store_versions[channel][arch] = None
                if not store_err:
                    raise SnapStoreError('failed to retrieve store URL (%s)' % str(e))
            except (URLError, KeyError) as e:
                raise SnapStoreError('failed to retrieve store URL (%s: %s)' %
                                     (type(e), str(e)))

    # match_version
    #
    def match_version(s, channel):
        """
        Check if the snap version on the store for the given channel corresponds
        to the kernel version and abi numbers of the kernel package.

        :param channel: store channel name
        :return: True if the snap version for all arches on the given channel match the
        kernel version and ABI from the tracking bug, False otherwise
        """

        try:
            s._get_snap_info(channel)
        except:
            raise

        # Loop over the store version for all arches and check if they are consistent.
        store_version = None
        for arch in s._snap_store_versions[channel].keys():
            if s._snap_store_versions[channel][arch] is None:
                # Return False if there are no published version for one of the arches
                return False
            if store_version is None:
                store_version = s._snap_store_versions[channel][arch]
            elif store_version != s._snap_store_versions[channel][arch]:
                return False

        return (store_version is not None and
                store_version == s.bug.pkg_version)
