#!/usr/bin/env python
#

from datetime                           import datetime

from .log                               import center, cleave, cdebug, cinfo
from .launchpad                         import Launchpad
from .launchpad_stub                    import LaunchpadStub
from .bug                               import WorkflowBug, WorkflowBugError
from .package                           import PackageError, SeriesLookupFailure
from .bugmail                           import BugMailConfigFileMissing
import wfl.wft

# WorkflowManager
#
class WorkflowManager():
    # __init__
    #
    def __init__(s, args, test_mode=False):
        center('WorkflowManager.__init__')
        s.test_mode = test_mode
        s.args = args
        s._lp = None
        s._task_map = {
            'upload-to-ppa'             : wfl.wft.UploadToPPA,
            'prepare-package'           : wfl.wft.PreparePackage,
            'prepare-package-lbm'       : wfl.wft.PreparePackageLBM,
            'prepare-package-meta'      : wfl.wft.PreparePackageMeta,
            'prepare-package-ports-meta': wfl.wft.PreparePackagePortsMeta,
            'prepare-package-signed'    : wfl.wft.PreparePackageSigned,
            'automated-testing'         : wfl.wft.AutomatedTesting,
            'promote-to-proposed'       : wfl.wft.PromoteToProposed,
            'verification-testing'      : wfl.wft.VerificationTesting,
            'certification-testing'     : wfl.wft.CertificationTesting,
            'regression-testing'        : wfl.wft.RegressionTesting,
            'promote-to-updates'        : wfl.wft.PromoteToUpdates,
            'promote-to-security'       : wfl.wft.PromoteToSecurity,
            'promote-to-release'        : wfl.wft.PromoteToRelease,
            'security-signoff'          : wfl.wft.SecuritySignoff,
            'snap-release-to-edge'      : wfl.wft.SnapReleaseToEdge,
            'snap-release-to-beta'      : wfl.wft.SnapReleaseToBeta,
            'snap-release-to-candidate' : wfl.wft.SnapReleaseToCandidate,
            'snap-release-to-stable'    : wfl.wft.SnapReleaseToStable,
        }

        WorkflowBug.sauron            = s.args.sauron
        WorkflowBug.dryrunn           = s.args.dryrun
        WorkflowBug.no_assignments    = s.args.no_assignments
        WorkflowBug.no_announcements  = s.args.no_announcements
        WorkflowBug.no_timestamps     = s.args.no_timestamps
        WorkflowBug.no_status_changes = s.args.no_status_changes
        WorkflowBug.no_phase_changes  = s.args.no_phase_changes
        WorkflowBug.local_msgqueue_port = s.args.local_msgqueue_port

        cleave('WorkflowManager.__init__')

    @property
    def lp(s):
        if s._lp is None:
            if s.test_mode is True:
                s._lp = LaunchpadStub(s.args)
            else:
                s._lp = Launchpad(False)
        return s._lp

    @property
    def buglist(s):
        '''
        Return a list of all the bugs that need to be processed.
        '''
        center('WorkflowManager.buglist')
        retval = {}
        if s.args.bugs:
            for bugid in s.args.bugs:
                lpbug = s.lp.default_service.get_bug(bugid)
                retval[bugid] = lpbug.title
        else:
            for project in WorkflowBug.projects_tracked:
                cinfo('project: %s' % project, 'magenta')
                search_tags            = ['kernel-release-tracking-bug']
                search_tags_combinator = "All"
                search_status          = ["New", "In Progress", "Incomplete", "Fix Committed"] # A list of the bug statuses that we care about
                search_since           = datetime(year=2013, month=1, day=1)
                lp_project = s.lp.default_service.projects[project]
                tasks = lp_project.search_tasks(status=search_status, tags=search_tags, tags_combinator=search_tags_combinator, modified_since=search_since)

                for task in tasks:
                    bug = task.bug
                    cinfo('    LP: #%s - %s' % (bug.id, bug.title), 'magenta')
                    retval[bug.id] = bug.title

        cleave('WorkflowManager.buglist')
        return retval

    # manage
    #
    def manage(s):
        '''
        This drives the overall process. It gets a list of the bugs that need to
        be worked (if not specified) and then runs through each of them.
        '''
        center('WorkflowManager.manage')
        try:
            for bugid in s.buglist:
                s.crank(bugid)

        except BugMailConfigFileMissing as e:
            print(e.message)

        # Handle the user presses <ctrl-C>.
        #
        except KeyboardInterrupt:
            pass

        cleave('WorkflowManager.manage')
        return 0

    # crank
    #
    def crank(s, bugid):
        '''
        For the specified bug, continue to process all of the bugs tasks until none
        of them are changed from the previous processing.
        '''
        center('WorkflowManager.crank')

        s.printlink = '%s : (%s)' % (bugid, s.lp.bug_url(bugid))
        cinfo('')
        cinfo('Processing: %s' % s.printlink, 'cyan')

        # If the bug was modified (task status changed) on that crank of the bug then
        # crank it again.
        #
        modified = True
        try:
            bug = WorkflowBug(s.lp.default_service, bugid)
            while modified:
                try:
                    cinfo('        ---------------------------------------  c r a n k  ---------------------------------------', 'green')
                    modified = s.process_bug_tasks(bug)

                except PackageError:
                    pass
            bug.save()

        except WorkflowBugError:
            # Bug doesn't exist?
            modified = False

        except SeriesLookupFailure as e:
            for l in e.message:
                print(l)

        cleave('WorkflowManager.crank')

    # process_bug_tasks
    #
    def process_bug_tasks(s, bug):
        '''
        Go through every workflow task and perform the associated actions
        based on the current state (status) of that task.
        '''
        center('WorkflowManager.process_bug_tasks')

        # Determine this bugs project.
        #
        for task in bug.lpbug.tasks:
            task_name = task.bug_target_name
            if task_name in WorkflowBug.projects_tracked:
                s.projectname = task_name
                break

        retval = False
        for workflow_task_name in sorted(bug.tasks_by_name):
            if workflow_task_name in WorkflowBug.projects_tracked:
                continue

            task = bug.tasks_by_name[workflow_task_name]
            cinfo('')
            cinfo("        %-25s  %15s  %10s  %s (%s)" % (task.name, task.status, task.importance, task.assignee, workflow_task_name), 'magenta')

            therest = task_name[len(s.projectname) + 1:].strip()
            task_name = therest

            cls = s._task_map[workflow_task_name](s.lp, task, bug)
            if cls.evaluate_status(task.status) and not s.args.dryrun:
                retval = True
                cinfo('        True')

        cleave('WorkflowManager.process_bug_tasks')
        return retval

# vi:set ts=4 sw=4 expandtab:
