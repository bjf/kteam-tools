#!/usr/bin/env python
#

from ktl.workflow                       import Workflow, DefaultAssigneeMissing
from ktl.ubuntu                         import Ubuntu
from ktl.kernel_series                  import KernelSeries
import re

from ktl.log                            import cdebug, cerror, cwarn, center, cleave

class TrackingBug:

    def __init__(self, lp, staging=False, quiet=False, new_package=False):
        self.lp = lp
        self.staging = staging
        self.quiet = quiet
        self.new_package = new_package
        self.wf = Workflow()
        self.ub = Ubuntu()
        self.__dependency_list = None
        self.__dependency_snap_list = None
        self._targeted_series_name = None
        self._series_specified = None
        self._series_target = None
        self._snap_prop_map = {
            'snap-sertification-testing' : 'hw-cert',
            'snap-qa-testing' : 'qa',
            'snap-publish' : 'gated',
        }
        self._valid_dev_tasks = [
            'automated-testing',
            'prepare-package',
            'prepare-package-meta',
            'prepare-package-signed',
            'promote-to-release',
            'regression-testing',
        ]

    # has_dependent_package
    #
    def has_dependent_package(self, series, main_package, dependent_package):
        '''
        Returns true/false depending on if the main package has the specified
        dependent package as a dependency.
        '''
        if self.__dependency_list is None:
            try:
                record = self.ub.lookup(series)
                try:
                    self.__dependency_list = record['dependent-packages'][main_package]
                except KeyError:
                    self.__dependency_list = {}
            except KeyError:
                self.__dependency_list = {}

        retval = dependent_package in self.__dependency_list
        return retval

    # _get_dependent_snap_prop
    def _get_dependent_snap_prop(self, series, main_package, prop):
        '''
        Return the value of the property of the dependent snap for the
        specified series/package. Return None if not found.
        '''
        if self.__dependency_snap_list is None:
            try:
                record = self.ub.lookup(series)
                self.__dependency_snap_list = record['dependent-snaps'][main_package]
            except KeyError:
                self.__dependency_snap_list = {}
        return self.__dependency_snap_list.get(prop, None)

    # valid_series
    #
    def valid_series(self, lp_series, series_specified, targeted_series_name, package):
        retval = False
        while True:
            if not lp_series.active:
                break
            if lp_series.name in ['trunk', 'latest']:
                break
            if lp_series.name == 'upload-to-ppa' and not series_specified:
                cdebug('    no upload-to-ppa', 'yellow')
                break
            if lp_series.name.startswith('prepare-package-'):
                dep = lp_series.name.replace('prepare-package-', '')
                if not self.has_dependent_package(targeted_series_name, package, dep):
                    cdebug('    no %s' % lp_series.name, 'yellow')
            if lp_series.name.startswith('snap-'):
                if self._get_dependent_snap_prop(targeted_series_name, package, 'snap') is None:
                    if lp_series.name.startswith('snap-'):
                        cdebug('    no %s' % lp_series.name, 'yellow')
                        break
                    else:
                        if lp_series.name in self._snap_prop_map.keys():
                            prop = self._get_dependent_snap_prop(targeted_series_name, package, self._snap_prop_map[lp_series.name])
                            if prop is None or not prop:
                                cdebug('    no %s' % lp_series.name, 'yellow')
                                break
            if lp_series.name == 'stakeholder-signoff':
                ks = KernelSeries()
                cursor = ks.lookup_series(codename=targeted_series_name)
                cursor = cursor.lookup_source(package)
                if cursor.stakeholder is None:
                    cdebug('    no stakeholder-signoff', 'yellow')
                    break
            if lp_series.name == 'promote-to-release' and not self.isdev:
                break
            if self.isdev and lp_series.name not in self._valid_dev_tasks:
                break

            retval = True
            break
        return retval

    @property
    def isdev(self):
        retval = False
        if self.targeted_series_name is not None:
            retval = self.ub.is_development_series(self.targeted_series_name)
        return retval

    @property
    def targeted_series_name(self):
        return self._targeted_series_name

    @property
    def series_specified(self):
        return self._series_specified

    @property
    def series_target(self):
        return self._series_target

    def reset_tags(self, bug):
        '''
        Set the bug up with it's initial set of tags. If this is an existing tracking bug and
        we are resetting it to the default then we should remove any/all existing tags.
        '''
        for tag in bug.tags:
            bug.tags.remote(tag)

        taglist = self.wf.initial_tags(self.package, self.isdev)

        # Add the 'block-proposed' tag both for development kernels and for the
        # latest release series
        #if self.isdev or self.ub.last_release == self.targeted_series_name:
        #    taglist.append('block-proposed')
        #if not self.isdev:
        #    taglist.append('block-proposed-%s' % self.targeted_series_name)
        for itag in taglist:
            bug.tags.append(itag)

    def add_subscribers(self, bug):
        '''
        Teams / individuals to be automatically subscribed to the tracking bugs.  These vary
        per package.
        '''
        teams = self.wf.subscribers(self.package, self.isdev)
        for team in teams:
            try:
                lp_team = self.lp.launchpad.people[team]
            except KeyError:
                if not self.quiet:
                    print("Can't subscribe '%s', team not found in Launchpad!" % (team))
                continue
            bug.lpbug.subscribe(person=lp_team)

    def add_kernel_series_nomination(self, bug):
        '''
        Nominate the series for this package.
        '''
        if not self.new_package:
            state = 'Confirmed'
            nomination = bug.lpbug.addNomination(target=self.series_target)
            if nomination.canApprove():
                nomination.approve()
        else:
            state = 'Invalid'
        bug.tags.append(self.targeted_series_name)

        # There should only be 2 tasks at this point, the 'linux (ubuntu)' task and the series
        # specific one we just added. Set them both to "Confirmed".
        # For a new package will have skipped the nomination, and we make this "Invalid"
        # instead.
        #
        for task in bug.tasks:
            if self.targeted_series_name.title() in task.bug_target_name:
                task.status = state

    def reset_tasks(self, bug):
        center(self.__class__.__name__ + '.reset_tasks')

        # Set task assignments and importance. Main project task must be
        # set to In Progress for the bot to do its processing.
        #
        cdebug("")
        cdebug("Setting status and importance", 'blue')
        for task in bug.tasks:
            task_name       = task.bug_target_display_name
            cdebug('    %s' % task_name, 'cyan')
            parts = task_name.partition(self.lp_project.display_name)

            # Is this the main linux task? "linux (Ubuntu)"
            #
            if not self.isdev and 'linux' in parts[0] and self.targeted_series_name.capitalize() not in parts[0]:
                task.status = "Invalid"
                cdebug('        is main linux task', 'white')
                cdebug('        status: %s; importance: %s' % (task.status, task.importance), 'green')

            # Is this the main SRU Workflow task? "Kernel SRU Workflow"
            #
            elif parts[0] == '' and parts[1] == self.lp_project.display_name and parts[2] == '':
                cdebug('        is main SRU Workflow task', 'white')
                task.status = "In Progress"
                task.importance = "Medium"
                cdebug('        status: %s; importance: %s' % (task.status, task.importance))

            # Else, it must be one of the SRU Workflow tasks.
            #
            else:
                cdebug('        is a SRU Workflow task', 'white')
                if parts[0] != '':
                    # The linux series task?
                    #
                    try:
                        task.importance = "Medium"
                    except:
                        cwarn('Failed to set the task (%s) importance to "Medium".' % (task_name))
                    cdebug('        status: %s; importance: %s' % (task.status, task.importance))
                    continue # We don't set the assignee for this task

                task.importance = "Medium"      # All tasks are Medium importance

                # Determine and set the assignee.
                #
                task_name = parts[2].strip()
                try:
                    assignee = self.wf.assignee_ex(self.targeted_series_name, self.package, task_name, self.isdev)
                except DefaultAssigneeMissing as e:
                    print('*** Warning:')
                    print('    %s' % str(e))
                    continue
                if assignee is None:
                    if not self.quiet:
                        print('Note: Found a workflow task named %s with no automatic assignee, leaving unassigned and setting to invalid' % task_name)
                    task.status = "Invalid"
                    cdebug('        status: Invalid')
                else:
                    try:
                        task.assignee = self.lp.launchpad.people[assignee]
                        cdebug('        assigning: %s' % task.assignee.display_name)
                    except:
                        if not self.quiet:
                            print("Can't assign '%s', team not found in Launchpad!" % (assignee))

                # Determine and mark appropriate tasks Invalid
                #
                if self.version is not None:
                    lin_ver = re.findall('([0-9]+\.[^-]+)', self.version)
                    if lin_ver:
                        lin_ver = lin_ver[0]
                        if not self.isdev and self.wf.is_task_invalid(self.package, task_name, lin_ver):
                            task.status = "Invalid"
                            cdebug('        status: Invalid')
                            continue
                if not self.new_abi and task_name.startswith('prepare-package-') and task_name != 'prepare-package-signed':
                    task.status = "Invalid"
                    cdebug('        status: Invalid')

        cleave(self.__class__.__name__ + '.reset_tasks')

    def open_bare(s, package=None, ubuntu_package=False, private=False):
        lp = s.lp.launchpad

        general_task_blacklist = [
            'trunk',
            'latest',
        ]

        package_task_blacklist = [
            'automated-testing',
            'prepare-package',
            'prepare-package-lbm',
            'prepare-package-meta',
            'prepare-package-ports-meta',
            'prepare-package-signed',
            'promote-to-proposed',
            'promote-to-security',
            'promote-to-updates',
            'security-signoff',
            'upload-to-ppa',
            'stakeholder-signoff',
        ]

        s.version = None
        s.new_abi = None
        project = 'kernel-sru-workflow'
        s.lp_project = lp.projects[project]
        try:
            lp_sru_project = lp.projects['kernel-sru-workflow']
            lpbug = lp.bugs.createBug(target=lp_sru_project, title="%s : version to be filled" % package, description="unset", tags=[], private=private)
            bug = s.lp.get_bug(lpbug.id)
            print('LP: #%s' % bug.id)
        except:
            print(' ** Error: Failed to create a \'kernel-sru-workflow\' bug.')
            cleave(s.__class__.__name__ + '.open')
            return None

        sc = s.lp_project.series_collection
        for series in sc:
            if series.display_name in general_task_blacklist:
                continue

            if (ubuntu_package is False) and (series.display_name in package_task_blacklist):
                continue

            cdebug('    adding: %s' % series.display_name)
            nomination = bug.lpbug.addNomination(target=series)
            if nomination.canApprove():
                nomination.approve()

        s.package = 'default'
        s.reset_tasks(bug)
        return bug

    def open(self, package, version, new_abi, master_bug, series_specified, private=False):
        center(self.__class__.__name__ + '.open')
        cdebug('    package: %s' % package)
        cdebug('    version: %s' % version)
        cdebug('    new_abi: %s' % new_abi)
        cdebug('    master_bug: %s' % master_bug)
        cdebug('    series_specified: %s' % series_specified)

        self.__dependency_list = None
        self.__dependency_snap_list = None

        self.package = package
        self.version = version
        self.new_abi = new_abi

        # For the given version, figure out the series.
        # If we can't find the series, don't continue.
        #
        series_target = None
        targeted_series_name = series_specified
        if targeted_series_name:
            lp = self.lp.launchpad
            ubuntu = lp.distributions["ubuntu"]
            sc = ubuntu.series_collection
            for s in sc:
                cdebug('s.name: %s' % s.name)
                if s.name == targeted_series_name:
                    series_target = s
                    self._series_target = series_target
                    break
        if not series_target:
            raise Exception("%s-%s: can't figure out the distro series for it." % (package, version))

        self._targeted_series_name = targeted_series_name
        self._series_specified = series_specified

        # Title: <package>: <version> -proposed tracker
        title = "%s: %s -proposed tracker" % (package, version)

        # Description:
        #    This bug is for tracking the <version> upload package. This bug will
        #    contain status and testing results related to that upload.
        #
        description  = "This bug is for tracking the %s upload package. " % (version)
        description += "This bug will contain status and testing results related to "
        description += "that upload."
        description += "\n\n"
        description += "For an explanation of the tasks and the associated workflow see:"
        description += " https://wiki.ubuntu.com/Kernel/kernel-sru-workflow\n"

        prop_pfx = 'kernel'
        if not self.isdev:
            prop_pfx += '-stable'

        if master_bug:
            description += '-- swm properties --\n'
            description += '%s-master-bug: %s' % (prop_pfx, master_bug)

        cdebug("")
        bug_package = package
        if self.new_package:
            cdebug("New package so using linux package", 'blue')
            bug_package = 'linux'
        cdebug("Creating the bug for " + bug_package, 'blue')
        try:
            bug = self.lp.create_bug(project='ubuntu', package=bug_package, title=title, description=description, private=private)
        except:
            cerror('Bug creation failed: project: "ubuntu", package: %s' % package)
            cerror('                     (It\'s possible the package does not exist, specify new-package?)')
            cleave(self.__class__.__name__ + '.open')
            return None

        id = bug.id
        if not self.quiet:
            if self.staging:
                print("https://bugs.qastaging.launchpad.net/bugs/%s" % (id))
            else:
                print("https://bugs.launchpad.net/bugs/%s" % (id))

        self.reset_tags(bug)         # Add all the tags to the bug
        self.add_subscribers(bug)
        self.add_kernel_series_nomination(bug)

        # ~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
        # Add a task for kernel-sru-workflow and then nominate all the series that belong
        # to that project.
        #

        lp = self.lp.launchpad
        project = 'kernel-sru-workflow'
        cdebug("")
        cdebug("Adding %s task." % project, 'blue')
        self.lp_project = lp.projects[project]
        bug.lpbug.addTask(target=self.lp_project)

        sc = self.lp_project.series_collection
        for series in sc:
            if self.valid_series(series, series_specified, targeted_series_name, package):
                cdebug('    adding: %s' % series.display_name)
                nomination = bug.lpbug.addNomination(target=series)
                if nomination.canApprove():
                    nomination.approve()

        self.reset_tasks(bug)

        cleave(self.__class__.__name__ + '.open')
        return bug

# vi:set ts=4 sw=4 expandtab:
