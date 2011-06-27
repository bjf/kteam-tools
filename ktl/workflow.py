#!/usr/bin/env python
#

# UbuntuError
#
class UbuntuError(Exception):
    # __init__
    #
    def __init__(self, error):
        self.msg = error

# Workflow
#
class Workflow:

    # Tasks, tags, etc vary according to the package name
    tdb = {
        'linux' :  {
            'task_assignment' : {
                'prepare-package'       : 'canonical-kernel-team',
                'promote-to-proposed'   : 'ubuntu-sru',
                'verification-testing'  : 'canonical-kernel-team',
                'certification-testing' : 'canonical-hw-cert',
                'regression-testing'    : 'canonical-platform-qa',
                'promote-to-updates'    : 'ubuntu-sru',
                'promote-to-security'   : 'ubuntu-sru',
                'security-signoff'      : 'canonical-security'
                },
            'initial_bug_tags' :
                ['kernel-release-tracking-bug'],
            'subscribers' :
                ["sru-verification", "ubuntu-sru", "hardware-certification"]
            },
        'linux-mvl-dove' :  {
            'task_assignment' : {
                'prepare-package'       : 'canonical-kernel-team',
                'promote-to-proposed'   : 'ubuntu-sru',
                'verification-testing'  : 'canonical-kernel-team',
                #'certification-testing' : 'ubuntu-armel-qa',
                'regression-testing'    : 'ubuntu-armel-qa',
                'promote-to-updates'    : 'ubuntu-sru',
                'promote-to-security'   : 'ubuntu-sru',
                'security-signoff'      : 'canonical-security'
                },
            'initial_bug_tags' :
                ['kernel-release-tracking-bug', 'armel'],
            'subscribers' :
                ["sru-verification", "ubuntu-sru", "ubuntu-armel-qa"]
            },
        'linux-fsl-imx51' :  {
            'task_assignment' : {
                'prepare-package'       : 'canonical-kernel-team',
                'promote-to-proposed'   : 'ubuntu-sru',
                'verification-testing'  : 'canonical-kernel-team',
                #'certification-testing' : 'ubuntu-armel-qa',
                'regression-testing'    : 'ubuntu-armel-qa',
                'promote-to-updates'    : 'ubuntu-sru',
                'promote-to-security'   : 'ubuntu-sru',
                'security-signoff'      : 'canonical-security'
                },
            'initial_bug_tags' :
                ['kernel-release-tracking-bug', 'armel'],
            'subscribers' :
                ["sru-verification", "ubuntu-sru", "ubuntu-armel-qa"]
            },
        'linux-ti-omap4' :  {
            'task_assignment' : {
                'prepare-package'       : 'canonical-kernel-team',
                'promote-to-proposed'   : 'ubuntu-sru',
                'verification-testing'  : 'canonical-kernel-team',
                #'certification-testing' : 'ubuntu-armel-qa',
                'regression-testing'    : 'ubuntu-armel-qa',
                'promote-to-updates'    : 'ubuntu-sru',
                'promote-to-security'   : 'ubuntu-sru',
                'security-signoff'      : 'canonical-security'
                },
            'initial_bug_tags' :
                ['kernel-release-tracking-bug', 'armel'],
            'subscribers' :
                ["sru-verification", "ubuntu-sru", "ubuntu-armel-qa"]
            },
        'default' :  {
            'task_assignment' : {
                'prepare-package'       : 'canonical-kernel-team',
                'promote-to-proposed'   : 'ubuntu-sru',
                'verification-testing'  : 'canonical-kernel-team',
                'certification-testing' : 'canonical-hw-cert',
                'regression-testing'    : 'canonical-platform-qa',
                'promote-to-updates'    : 'ubuntu-sru',
                'promote-to-security'   : 'ubuntu-sru',
                'security-signoff'      : 'canonical-security'
                },
            'initial_bug_tags' :
                ['kernel-release-tracking-bug'],
            'subscribers' :
                ["sru-verification", "ubuntu-sru", "hardware-certification"]
            }
        }

    # assignee
    #
    def assignee(self, packagename, taskname):
        """
        Using the given package name and task name, return the launchpad
        team or person who should be assigned that task. If the
        package name is not in the dictionary, return the default
        """
        if packagename in self.tdb:
            if taskname in self.tdb[packagename]['task_assignment']:
                return self.tdb[packagename]['task_assignment'][taskname]
            else:
                return None
        else:
                return self.tdb['default']['task_assignment'][taskname]

    # initial_tags
    #
    def initial_tags(self, packagename):
        """
        Lookup the given package name and return the tags which
        should be initially applied to the tracking bug
        """
        if packagename in self.tdb:
                return self.tdb[packagename]['initial_bug_tags']
        else:
                return self.tdb['default']['initial_bug_tags']

    # subscribers
    #
    def subscribers(self, packagename):
        """
        Lookup the given package name and return a list of
        teams who should be initially subscribed to the tracking bug
        """
        if packagename in self.tdb:
                return self.tdb[packagename]['subscribers']
        else:
                return self.tdb['default']['subscribers']

if __name__ == '__main__':
    workflow = Workflow()
    db = workflow.tdb

    #for record in db:
    #    print db[record]

    print(workflow.assignee('linux', 'prepare-package'))
    print(workflow.assignee('linux', 'nonexistent-task'))
    print(workflow.initial_tags('linux-ti-omap4'))
    print(workflow.subscribers('linux-ti-omap4'))

# vi:set ts=4 sw=4 expandtab:
