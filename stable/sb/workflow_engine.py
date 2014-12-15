#!/usr/bin/env python
#
# shank is the "stable bot" or "stab-bot".
#

from ktl.check_component                import CheckComponent
from ktl.utils                          import stdo, date_to_string, run_command
from ktl.ubuntu                         import Ubuntu
from ktl.workflow                       import Properties
from ktl.tracking_bug                   import TrackingBug
from datetime                           import datetime
from urllib                             import quote
from ktl.messaging                      import Email, Status
from ktl.bugs                           import DeltaTime
from ktl.termcolor                      import colored
import traceback
from ktl.shanky                         import send_to_shankbot

from sb.package                         import Package, PackageError
from sb.workflow_bug                    import WorkflowBug
from sb.log                             import cinfo, cdebug, cwarn, cnotice, cerror

def verbose(msg, color='green'):
    stdo(colored(msg, color))

# StateVerificationError
#
class StateVerificationError(Exception):
    '''
    '''
    def __init__(s):
        pass

# TaskActions
#
class TaskActions(dict):
    '''
    For every workflow task there is one or more action(s) that are to
    be perfomed on it. The action the be performed depends on the current
    state (status) of that task.

    This class (a dictionary) helps building the master dictionary of
    tasks and actions.
    '''
    # __init__
    #
    def __init__(s, d, *args):
        dict.__init__(s, *args)
        s.actions = {}

        # Initialize them all to 'None'
        #
        for t in ['New', 'Incomplete', 'Opinion', 'Invalid', 'Won\'t Fix', 'Expired', 'Confirmed', 'Triaged', 'In Progress', 'Fix Committed', 'Fix Released', 'Unknown']:
            s[t] = None

        # Set the individual ones that have a non-None value
        #
        for k in d:
            s[k] = d[k]

# WorkflowEngine
#
class WorkflowEngine():
    # __init__
    #
    def __init__(s, args, lp):
        s.args = args

        s.state_map = {
            'upload-to-ppa'             : TaskActions({'Confirmed'    : s.upload_to_ppa_confirmed}),
            'prepare-package'           : TaskActions({'New'          : s.prep_package_main_new,               'In Progress'  : s.prep_package_main_new,       }),
            'prepare-package-lbm'       : TaskActions({'New'          : s.prep_package_lbm_new,                'In Progress'  : s.prep_package_lbm_new,        }),
            'prepare-package-meta'      : TaskActions({'New'          : s.prep_package_meta_new,               'In Progress'  : s.prep_package_meta_new,       }),
            'prepare-package-ports-meta': TaskActions({'New'          : s.prep_package_ports_meta_new,         'In Progress'  : s.prep_package_ports_meta_new, }),
            'prepare-package-signed'    : TaskActions({'New'          : s.prep_package_signed_new,             'In Progress'  : s.prep_package_signed_new,     }),
            'package-testing'           : TaskActions({'New'          : s.pkg_testing_new,                     'Fix Released' : s.package_testing_fix_committed }),
            'promote-to-proposed'       : TaskActions({'Fix Released' : s.promote_to_proposed_fix_released}),
            'verification-testing'      : TaskActions({'Fix Released' : s.verification_testing_fix_released}),
            'certification-testing'     : TaskActions({'Invalid'      : s.certification_testing_invalid,       'Fix Released' : s.certification_testing_fix_released}),
            'regression-testing'        : TaskActions({'Invalid'      : s.regression_testing_invalid,          'Fix Released' : s.regression_testing_fix_released}),
            'promote-to-updates'        : TaskActions({'Fix Released' : s.check_for_final_close}),
            'promote-to-security'       : TaskActions({'Fix Released' : s.check_for_final_close}),
            'promote-to-release'        : TaskActions({'Fix Released' : s.promote_to_release_fix_released}),
            'security-signoff'          : TaskActions({'Invalid'      : s.security_signoff_finished,           'Fix Released' : s.security_signoff_finished}),
        }

        s.lp = lp

    def verbose(s, msg, color='green'):
        cinfo(colored(msg, color))

    # get_buglist
    #
    def get_buglist(s, project):
        '''
        Perform a search of Launchpad to get a list of all the bugs that match
        our criteria.

        A list of the bug ids is returned.
        '''
        retval = []

        search_tags            = [   # A list of the tags we care about
                'kernel-release-tracking-bug'
            ]
        search_tags_combinator = "All"
        search_status          = ["New", "In Progress", "Incomplete", "Fix Committed"] # A list of the bug statuses that we care about
        search_since           = datetime(year=2013, month=1, day=1)
        lp_project = s.lp.default_service.projects[project]
        tasks = lp_project.search_tasks(status=search_status, tags=search_tags, tags_combinator=search_tags_combinator, modified_since=search_since)

        for task in tasks:
            bug = task.bug
            cinfo('found: %s' % bug.id)
            retval.append(bug.id)

        return retval

    # initialize
    #
    def initialize(s):
        '''
        There are certain things (like connecting to LP) that I don't like to do
        in the constructor because they are so time consuming. Those thinngs are
        done here.
        '''
        s.ubuntu = Ubuntu()

        # Get set up for email and status messages
        if 'mail_notify' in s.cfg:
            mcfg = s.cfg['mail_notify']
            try:
                port = mcfg['smtp_port']
            except:
                port = 587

            if 'smtp_user' not in mcfg:
                s.email = Email(mcfg['smtp_server'].encode('UTF-8'), smtp_port = port)
            else:
                s.email = Email(mcfg['smtp_server'].encode('UTF-8'), mcfg['smtp_user'].encode('UTF-8'), mcfg['smtp_pass'].encode('UTF-8'), port)

        scfg = s.cfg['status_net']
        s.status = Status(scfg['url'], scfg['user'], scfg['pass'])

        return

    # crank
    #
    def crank(s, bugid, sauron):
        cdebug('WorkflowEngine::crank enter')
        s.initialize()

        s.sauron = sauron
        s.printlink =  '%s : (%s)' % (bugid, s.bug_url(bugid))
        cinfo('')
        cinfo('Processing: %s' % s.printlink, 'cyan')

        # If the bug was modified (task status changed) on that crank of the bug then
        # crank it again.
        #
        modified = True
        while modified:
            bug = WorkflowBug(s.lp.default_service, s.projects_tracked, bugid, sauron, s.args.dryrun)
            if bug.is_valid:
                try:
                    modified = s.process_bug_tasks(bug)

                except PackageError:
                    pass
            else:
                modified = False

        cdebug('WorkflowEngine::crank leave')

    # process_bug_tasks
    #
    def process_bug_tasks(s, shankbug):
        '''
        Go through every workflow task and perform the associated actions
        based on the current state (status) of that task.
        '''
        cdebug('    WorkflowEngine::process_bug_tasks enter')
        # Determine this bugs project.
        #
        for task in shankbug.lpbug.tasks:
            task_name = task.bug_target_name
            if task_name in s.projects_tracked:
                s.projectname = task_name
                break
        master_task_name = s.projectname

        s.wfb = shankbug
        s.wfb.tasks_by_name = s.wfb.tasks_by_name

        # initialize any per-bug variables that we use
        s.bugtags = []
        for atag in shankbug.lpbug.tags:
            s.bugtags.append(atag)
        performReleaseTest = False
        s.certification_testing_complete = False
        s.verification_testing_complete = False
        s.regression_testing_complete = False
        s.security_signoff_complete = False
        s.security_publishing_required = False

        # Initialize the properties object
        s.props = Properties(shankbug.lpbug)

        # Go through each task.
        #
        cinfo('')
        cinfo('    Processing Workflow Tasks:', 'cyan')

        for workflow_task_name in sorted(shankbug.tasks_by_name):
            if workflow_task_name in ['kernel-sru-workflow', 'kernel-development-workflow']:
                continue

            task = shankbug.tasks_by_name[workflow_task_name]
            cinfo('')
            cinfo("        %-25s  %15s  %10s  %s (%s)" % (task.name, task.status, task.importance, task.assignee, workflow_task_name))

            therest = task_name[len(master_task_name)+1:].strip()
            task_name = therest

            try:
                action = s.state_map[workflow_task_name][task.status]

            except KeyError:
                cerror('            ' + s.printlink)
                cerror('            Error: No action found for state <%s> and task <%s>' % (task.status, workflow_task_name))

            if action is None:
                cinfo('            Action: No action for task %s in state %s' % (task.name, task.status))

            else:
                res_action = action(task)

        # Now process any tests which require information from multiple tasks
        # will require info stored in class variables during task processing
        if s.projectname == 'kernel-sru-workflow':
            if s.verification_and_testing_completed():
                if s.release_ready():
                    s.release()

        # Now flush any property changes to the bug description
        s.props.flush()

        cdebug('    WorkflowEngine::process_bug_tasks leave (%s)' % shankbug.modified)
        return shankbug.modified

    def bug_url(s, bug_id):
        if s.args.staging:
            lpserver = 'bugs.qastaging.launchpad.net'
        else:
            lpserver = 'bugs.launchpad.net'
        retval = 'https://%s/bugs/%s' % (lpserver, bug_id)
        return retval

    def send_comment(s, taskobj, subject, body):
        """
        Add comment to tracking bug
        """
        cinfo('        ')
        if s.args.dryrun:
            cinfo('                Dryrun - Adding comment to tracking bug')
        else:
            cinfo('                Adding comment to tracking bug')
            taskobj.lp_task.bug.add_comment(body, subject)

    def send_email(s, taskobj, subject, body, to_address=None):
        """
        Send email to the configured list or recipient
        """
        if s.args.dryrun or s.args.dryrun_email:
            cinfo('Dryrun - Sending email')
            return

        cinfo('Sending email')

        if not 'mail_notify' in s.cfg:
            s.verbose('No mail_notify config found, can\'t send email\n')
            return

        mcfg = s.cfg['mail_notify']
        if not to_address:
            to_address = mcfg['to_address']
        body_top = 'The following message is regarding the following Kernel SRU Tracking bug:\n%s\n' % s.bug_url(taskobj.bug.id)
        body_top = body_top + ('%s\n\n' % s.wfb.title)
        msg = body_top + body
        subj =  '[ShankBot] ' + subject
        s.email.send(mcfg['from_address'], to_address, subj, msg)
        return

    def has_new_abi(s):
        tasks_abi = [ 'prepare-package-lbm', 'prepare-package-meta', 'prepare-package-ports-meta' ]
        for taskname in tasks_abi:
            if taskname in s.wfb.tasks_by_name:
                if s.wfb.tasks_by_name[taskname].status != "Fix Released":
                    return False
        return True

    def send_upload_announcement(s, task, pocket):
        """
        Send email with upload announcement
        """
        s.verbose('        ')
        if s.args.dryrun or s.args.dryrun_email:
            cinfo('Dryrun - Sending upload announcement')
            return
        cinfo('Sending upload announcement')

        from_addr = None
        if 'mail_notify' in s.cfg:
            if 'from_address' in s.cfg['mail_notify']:
                from_addr = s.cfg['mail_notify']['from_address']
        if not from_addr:
            cwarn('        No valid email config found, can\'t send upload announcement')
            return

        dest  = "kernel-team@lists.ubuntu.com"
        dest += ", ubuntu-installer@lists.ubuntu.com"
        if 'upload_announce_to' in s.cfg:
            for addr in s.cfg['upload_announce_to']:
                dest += ", %s" % (addr)

        bug = task.bug
        series = s.ubuntu.series_name(s.wfb.pkg_name, s.wfb.pkg_version)
        abi_bump = s.has_new_abi()

        subj = "[" + series + "] " + s.wfb.pkg_name + " " + s.wfb.pkg_version + " uploaded"
        if abi_bump:
            subj += " (ABI bump)"

        send_to_shankbot(subj)

        msg  = "A new " + series + " kernel has been uploaded into "
        msg += pocket + ". "
        if abi_bump:
            msg += "Note the ABI bump. "
        msg += "\nThe full changelog about all bug fixes contained in this "
        msg += "upload can be found at:\n\n"
        msg += "https://launchpad.net/ubuntu/" + series + "/+source/"
        msg += s.wfb.pkg_name + "/" + s.wfb.pkg_version + "\n\n"
        msg += "-- \nThis message was created by an automated script,"
        msg += " maintained by the\nUbuntu Kernel Team."

        s.email.send(from_addr, dest, subj, msg)
        return

    def send_ppc64el_test_request(s, task, pocket):
        """
        Send email with upload announcement
        """
        s.verbose('        ')
        if s.args.dryrun or s.args.dryrun_email:
            cinfo('Dryrun - Sending upload announcement')
            return
        cinfo('Sending upload announcement')

        from_addr = None
        if 'mail_notify' in s.cfg:
            if 'from_address' in s.cfg['mail_notify']:
                from_addr = s.cfg['mail_notify']['from_address']
        if not from_addr:
            cwarn('        No valid email config found, can\'t send upload announcement')
            return

        dest  = "paul.larson@canonical.com, brad.figg@canonical.com"

        bug = task.bug
        series = s.ubuntu.series_name(s.wfb.pkg_name, s.wfb.pkg_version)
        abi_bump = s.has_new_abi()

        subj = "[" + series + "] " + s.wfb.pkg_name + " " + s.wfb.pkg_version + " uploaded"
        if abi_bump:
            subj += " (ABI bump)"

        msg  = "Paul,\n\nA new " + series + " kernel has been uploaded into "
        msg += pocket + ". "
        if abi_bump:
            msg += "Note the ABI bump. "
        msg += "\nThe full changelog about all bug fixes contained in this "
        msg += "upload can be found at:\n\n"
        msg += "https://launchpad.net/ubuntu/" + series + "/+source/"
        msg += s.wfb.pkg_name + "/" + s.wfb.pkg_version + "\n\n"
        msg += "Please test this kernel on PPC64EL hardware.\n\n"
        msg += "-- \nThis message was created by an automated script,"
        msg += " maintained by the\nUbuntu Kernel Team."

        s.email.send(from_addr, dest, subj, msg)
        return

    def send_status_update(s, taskobj, message):
        """
        Send a status update to twitter, status.net, identi.ca, etc
        """
        s.verbose('        ')
        if s.args.dryrun:
            s.verbose('Dryrun - Sending Status')
            return

        s.verbose('Sending Status')

        bugurl = quote(s.bug_url(taskobj.bug.id))

        kinfo = s.ubuntu.lookup(s.wfb.pkg_version.split('-')[0])
        series_name = kinfo['name']
        pkgid = '%s package %s %s ' % (series_name, s.wfb.pkg_name, s.wfb.pkg_version)

        s.status.update(bugurl + ' : ' + pkgid + ' ' + message)
        return

    # set_tagged_timestamp
    #
    def set_tagged_timestamp(s, taskobj, keyvalue):
        '''
        Add the supplied key with a timestamp. We do not replace existing keys
        '''
        if not s.args.dryrun and keyvalue not in taskobj.bug.properties:
            cinfo('                Adding tagged timestamp <%s> to tracking bug' % keyvalue)

            now = datetime.utcnow()
            now.replace(tzinfo=None)
            tstamp = date_to_string(now)
            props = {keyvalue:tstamp}
            s.props.set(props)

        else:
            if s.args.dryrun and keyvalue not in taskobj.bug.properties:
                cinfo('dryrun:         Adding tagged timestamp <%s> to tracking bug' % keyvalue)

    # set_phase
    #
    """
    Add the phase we're entering as a 'property',
    along with a time stamp
    """
    def set_phase(s, taskobj, phasetext):
        bug_prop = 'kernel'
        if s.projectname == 'kernel-sru-workflow':
            bug_prop += '-stable'
        bug_prop += '-phase'
        bug_prop_chg = bug_prop + '-changed'
        # We have to check here to see whether the same status is already set,
        # or we will overwrite the timestamp needlessly
        if bug_prop in taskobj.bug.properties:
            if taskobj.bug.properties[bug_prop] == phasetext:
                # we already have this one
                cdebug('                Not overwriting identical phase property (%s)' % phasetext)
                return
        # Handle dryrun mode
        if s.args.dryrun:
            cinfo('                Dryrun - Changing bug phase to <%s>' % phasetext)
            return
        else:
            cinfo('                Changing bug phase to <%s>' % phasetext)
        # Add phase and time stamp
        now = datetime.utcnow()
        now.replace(tzinfo=None)
        tstamp = date_to_string(now)
        props = {bug_prop:phasetext, bug_prop_chg:tstamp}
        s.props.set(props)

    #
    # Begin action methods for state transitions
    #

    # master_bug_property_name
    #
    @property
    def master_bug_property_name(s):
        retval = 'kernel'
        if s.projectname == 'kernel-sru-workflow':
            retval += '-stable'
        retval += '-master-bug'
        return retval

    # is_derivative_package
    #
    def is_derivative_package(s, bug):
        return s.master_bug_property_name in bug.properties

    # master_bug
    #
    def master_bug(s, bug):
        '''
        Find the 'master' bug of which this is a derivative and return that bug.
        '''
        return s.lp.default_service.get_bug(bug.properties[s.master_bug_property_name])

    # verify_master_bug_tasks
    #
    def verify_master_bug_tasks(s, bug, tasks):
        """
        check if the dictionary of tasks is in one of the provided list of
        status on the master bug listed in the bug, returns:
        * -1 if we were unable to check the status
        * 0 if the task on the master tracking bug is not Confirmed/ Fix Released
        * 1 if this isn't a derivative (doesn't have a master tracking bug
        * 2 if the task on the master tracking bug is Confirmed or Fix Released
        The tasks provided must be a dictionary in the form:
            'task name' : [ list of desired status ]
        """
        s.master_bug_missing     = -1
        s.master_bug_bad_status  = 0
        s.master_bug_good_status = 2
        s.not_derivative         = 1

        retval = s.not_derivative
        if s.is_derivative_package(bug):
            try:
                master = s.master_bug(bug)

                retval = s.master_bug_good_status
                for task in master.tasks:
                    task_name = task.bug_target_name

                    if (not task_name.startswith(s.projectname) or task_name == s.projectname):
                        continue

                    short_name = task_name[len(s.projectname)+1:].strip()
                    for tname in iter(tasks):
                        if short_name.lower() == tname:
                            if not task.status in tasks[tname]:
                                retval = s.master_bug_bad_status
                                s.verbose("%s doesn't match any of these " "status in bug %s: %s." % (tname, master.id, tasks[tname]))
                                s.verbose(" Waiting on master bug\n")
                            return retval
            except:
                traceback.print_exc()
                print("ERROR: Unable to get the master bug\n")
                retval = s.master_bug_missing

        return retval

    def prepare_package_fixed(s):
        """
        Check if all prepare-package tasks are finished, returning a
        boolean value indicating so
        """
        for task in iter(s.wfb.tasks_by_name):
            if task.startswith('prepare-package'):
                if (s.wfb.tasks_by_name[task].status != 'Fix Released' and
                    s.wfb.tasks_by_name[task].status != 'Invalid'):
                    return False
        return True

    def upload_to_ppa_confirmed(s, taskobj):
        cdebug('            upload_to_ppa_confirmed enter')
        s.set_phase(taskobj, 'ReadyToBePackaged')
        cdebug('            upload_to_ppa_confirmed leave (True)')
        return True

    # noop
    #
    def noop(s, taskobj):
        """
        Don't do anything.
        """
        return False

    # -----------------------------------------------------------------------------------------------------------------------------
    # Prepare Package Tasks Handling

    # common_prep_package_new
    #
    def common_prep_package_new(s, taskobj, pkg, task):
        cdebug('            WorkflowEngine::common_prep_package_new enter')
        if s.wfb.package_fully_built(pkg):
            cdebug('                %s : fully built' % (pkg), 'green')

            # This task can be marked "Fix Released"
            #
            if s.args.dryrun:
                cinfo('                Dryrun - changing status of %s from %s to %s' % (task, s.wfb.tasks_by_name[task].status, 'Fix Released'))
                cinfo('                Dryrun - setting assignee of %s to %s' % (task, s.wfb.creator(pkg)))
            else:
                cinfo('                changing status of %s from %s to %s' % (task, s.wfb.tasks_by_name[task].status, 'Fix Released'))
                s.wfb.tasks_by_name[task].status = 'Fix Released'

                try:
                    if s.args.debug_assignee:
                        s.wfb.tasks_by_name[task].assignee = s.lp.default_service.launchpad.people[s.args.debug_assignee]
                    else:
                        s.wfb.tasks_by_name[task].assignee = s.wfb.creator(pkg)
                except KeyError:
                    pass

        else:
            cdebug('                %s : not built' % (pkg), 'red')
        cdebug('            WorkflowEngine::common_prep_package_new leave')

    # prep_package_main_new
    #
    def prep_package_main_new(s, taskobj):
        s.common_prep_package_new(taskobj, 'main', 'prepare-package')
        return False

    # prep_package_meta_new
    #
    def prep_package_meta_new(s, taskobj):
        s.common_prep_package_new(taskobj, 'meta', 'prepare-package-meta')
        return False

    # prep_package_ports_meta_new
    #
    def prep_package_ports_meta_new(s, taskobj):
        s.common_prep_package_new(taskobj, 'ports-meta', 'prepare-package-ports-meta')
        return False

    # prep_package_signed_new
    #
    def prep_package_signed_new(s, taskobj):
        s.common_prep_package_new(taskobj, 'signed', 'prepare-package-signed')
        return False

    # prep_package_lbm_new
    #
    def prep_package_lbm_new(s, taskobj):
        s.common_prep_package_new(taskobj, 'lbm', 'prepare-package-lbm')
        return False

    def prep_package_new(s, taskobj):
        '''
             Task: prepare_package
            State: New
        '''
        cdebug('            prep_package_new enter')

        p = Package(s.lp.production_service, s.wfb)
        p.ignore_promotions = s.args.dryrun_ignore_promotions
        cinfo('        Needs work')
        p.determine_build_status()

        if p.updates is not None:
            cinfo('')
            cinfo('        Based on the build status of packages:', 'cyan')
            for task in p.updates:
                try:
                    s.wfb.tasks_by_name[task].status = p.updates[task]['status']
                except KeyError:
                    pass

                try:
                    if s.args.debug_assignee:
                        s.wfb.tasks_by_name[task].assignee = s.lp.default_service.launchpad.people[s.args.debug_assignee]
                    else:
                        s.wfb.tasks_by_name[task].assignee = s.lp.default_service.launchpad.people[p.updates[task]['assignee']]
                except KeyError:
                    pass

            if 'promote-to-release' in p.updates and p.updates['promote-to-release']['status'] == 'Fix Released':
                cdebug("promote-to-release is Fix Released")
                s.final_promote_to_release_tasks(taskobj)

        cdebug('            prep_package_new leave')
        return False

    # -----------------------------------------------------------------------------------------------------------------------------
    # Package Testing Tasks Handling

    # pkg_testing_new
    #
    def pkg_testing_new(s, taskobj):
        cdebug('            WorkflowEngine::pkg_testing_new enter')

        if s.wfb.all_dependent_packages_fully_built():
            cdebug('                all dependent packages : fully built', 'green')

            if s.__promote_to_proposed(taskobj):
                # This task can be marked "Confirmed"
                #
                s.wfb.tasks_by_name['package-testing'].status = 'Confirmed'
        else:
            cdebug('                all dependent packages : not built', 'red')

        cdebug('            WorkflowEngine::pkg_testing_new leave')
        return False

    # __promote_to_proposed
    #
    def __promote_to_proposed(s, taskobj):
        """
        """
        cdebug('            __promote_to_proposed enter')

        retval = False

        if s.projectname == 'kernel-sru-workflow':
            taskname = 'promote-to-proposed'
        else:
            taskname = 'package-testing'

        cdebug('                %s status: %s' % (taskname, s.wfb.tasks_by_name[taskname].status))

        # Even though we came in here do to one of the prepare-package* tasks being
        # set to 'Fix Released' we don't actually do anything unless the next state
        # (promote-to-proposed or package-testing) is 'New'.
        #
        if s.wfb.tasks_by_name[taskname].status == 'New':
            # check if all prepare-package tasks are finished
            if not s.prepare_package_fixed():
                cdebug('                __promote_to_proposed leave (%s)' % retval)
            else:
                s.handle_derivatives(taskobj, taskname)
                s.__ppa_announce(taskobj)
                retval = True

        else:
            cdebug('                doing nothing, the task is not \'New\'')

        cdebug('            __promote_to_proposed leave (%s)' % retval)
        return retval

    # __ppa_announce
    #
    def __ppa_announce(s, taskobj):
        """
        Right now all we want to do is send some email.
        """
        cdebug('            __ppa_announce enter')

        s.wfb.tasks_by_name['package-testing'].status = 'In Progress'

        s.set_tagged_timestamp(taskobj, 'ppa-package-testing-start')
        s.set_phase(taskobj, 'PPA Testing')

        #-------------------------------------------------------------------

        if s.args.dryrun or s.args.dryrun_email:
            cinfo('Dryrun - Sending email')
            return

        cinfo('Sending email')

        if not 'mail_notify' in s.cfg:
            s.verbose('No mail_notify config found, can\'t send email\n')
            return

        to_address = "brad.figg@canonical.com, ubuntu.kernel.bot@gmail.com"
        subj =  '%s: %s Available in PPA' % (s.wfb.pkg_name, s.wfb.pkg_version)
        send_to_shankbot(subj)

        mcfg = s.cfg['mail_notify']
        msg  = ''
        msg += 'Title: %s\n\n' % s.wfb.title
        msg += 'ID: %s\n' % taskobj.bug.id
        msg += 'URL: %s\n' % s.bug_url(taskobj.bug.id)
        msg += 'Version: %s\n' % s.wfb.pkg_version
        msg += 'Package: %s\n' % s.wfb.pkg_name
        if '-lts-' in s.wfb.series:
            series = s.wfb.series.split('-lts-')[1]
        else:
            series = s.wfb.series
        msg += 'Series: %s\n' % series
        msg += ""
        s.email.send(mcfg['from_address'], to_address, subj, msg)

        cdebug('            __ppa_announce leave (False)')
        return False

    def final_promote_to_release_tasks(s, taskobj):
        if s.projectname == 'kernel-development-workflow':
            cdebug("kernel-development-workflow")
            s.set_tagged_timestamp(taskobj, 'kernel-Prepare-package-end')
            s.set_tagged_timestamp(taskobj, 'kernel-Package-testing-start')
            s.set_phase(taskobj, 'Testing')
            s.send_upload_announcement(taskobj, 'proposed')

            if s.wfb.series in ['trusty', 'utopic']:
                s.send_ppc64el_test_request(taskobj, 'proposed')

            series = s.ubuntu.series_name(s.wfb.pkg_name, s.wfb.pkg_version)
            # If this is running remotely we need to use ssh. If it's running as the kernel-ppa
            # user on zinc, we can't use ssh.
            #
            #cmd = 'ssh zinc.canonical.com \'echo "<html>%s</html>" > /srv/kernel.ubuntu.com/www/kernel-pkg-status/%s.html\'' % (s.wfb.title, series)
            with open('/srv/kernel.ubuntu.com/www/kernel-pkg-status/%s.html' % series, 'w') as f:
                f.write('<html>%s</html>' % s.wfb.title)

    def handle_derivatives(s, taskobj, taskname):
        cdebug('            handle_derivatives enter')

        # if this is a derivative tracking bug, first wait until
        # that packages on the master tracking bug are also ready or
        # already promoted. The way derivative package bugs are
        # opened already ensures this, but check the tasks on the
        # master bug anyway just in case...
        tsk_st = {
            'prepare-package'            : [ 'Fix Released' ],
            'prepare-package-lbm'        : [ 'Fix Released', 'Invalid' ],
            'prepare-package-meta'       : [ 'Fix Released', 'Invalid' ],
            'prepare-package-ports-meta' : [ 'Fix Released', 'Invalid' ],
            'prepare-package-signed'     : [ 'Fix Released' ],
            taskname                     : [ 'Confirmed', 'Fix Released' ]
        }
        # If the master bug's tasks are not completely ready.
        #
        if s.verify_master_bug_tasks(taskobj.bug, tsk_st) <= 0:
            cdebug('                verify_master_bug_tasks failed')
            cdebug('            handle_derivatives leave (False)')
            return False

        # open new tracking bugs for derivative packages if needed
        series = s.ubuntu.series_name(s.wfb.pkg_name, s.wfb.pkg_version)
        if not series:
            print("ERROR: Can't find series for %s-%s to get derivatives\n" % (s.wfb.pkg_name, s.wfb.pkg_version))
            cdebug('            handle_derivatives leave (False)')
            return False

        der_list = []
        record = s.ubuntu.lookup(series)
        if 'derivative-packages' in record:
            if s.wfb.pkg_name in record['derivative-packages']:
                der_list = record['derivative-packages'][s.wfb.pkg_name]
        bp_list = []
        for entry in s.ubuntu.db.itervalues():
            if 'backport-packages' in entry:
                bp_entries = entry['backport-packages']
                for bp_entry in iter(bp_entries):
                    if (bp_entries[bp_entry][0] == s.wfb.pkg_name and bp_entries[bp_entry][1] == record['series_version']):
                        # For trusty and future backports we are changing the naming convention to
                        # be ~<series_version> instead of ~<series_name>.
                        #
                        if entry['name'] == 'precise':
                            bp_list.append([bp_entry, "%s1" % entry['name']])             # precise backports are versioned <kernel-version>~precise1
                        else:
                            bp_list.append([bp_entry, "%s.1" % entry['series_version']])  # post-precise lts backports are versioned <kernel-version>~<series-version>.1

        der_bug_list = []
        bp_bug_list  = []
        m_bug_list   = []

        tb = TrackingBug(s.lp.default_service, s.args.staging)
        for der_pkg in der_list:
            cdebug('                    derivative package: %s' % der_pkg)
            if s.args.dryrun or s.args.dryrun_derivative_trackers:
                cinfo('        Dryrun - Would open tracking bug for derivative package %s' % (der_pkg))
                continue
            try:
                print('        ')
                bug = tb.open(der_pkg, '<version to be filled>', True, taskobj.bug.id, series)
            except:
                traceback.print_exc()
                bug = None
            if bug:
                # Friendly comment on the bug stating that this is a derivative
                msgder =  "This tracking bug was opened to be worked from "
                msgder += "%s-%s update (bug %s)" % (s.wfb.pkg_name, s.wfb.pkg_version, taskobj.bug.id)
                subder =  "Derivative package tracking bug"
                bug.add_comment(msgder, subder)
                cinfo('        Action: Opened tracking bug %s for derivative package %s' % (bug.id, der_pkg))
                der_bug_list.append([der_pkg, bug.id])
            else:
                m_bug_list.append('%s' % (der_pkg))

        for bp_pkg in bp_list:
            cdebug('                    backport package: %s' % bp_pkg)
            if s.args.dryrun or s.args.dryrun_derivative_trackers:
                cinfo('        Dryrun - Would open tracking bug for backport package %s' % (bp_pkg[0]))
                continue
            try:
                bug = tb.open(bp_pkg[0], '%s~%s' % (s.wfb.pkg_version, bp_pkg[1]), s.has_new_abi(), taskobj.bug.id)
            except:
                traceback.print_exc()
                bug = None
            if bug:
                cinfo('        Action: Opened tracking bug %s for backport package %s (%s)' % (bug.id, bp_pkg[0], bp_pkg[1]))
                bp_bug_list.append([bp_pkg[0], bp_pkg[1], bug.id])
            else:
                m_bug_list.append('%s (%s)' % (bp_pkg[0], bp_pkg[1]))

        # comment about publishing and possible new tracking bugs opened
        msgbody  = 'All builds are complete, packages in this bug'
        if taskname == 'promote-to-proposed':
            msgbody += ' can be copied to -proposed.'
        else:
            msgbody += ' are available in -proposed.'
        if der_bug_list:
            msgbody += '\n\nDerivative packages from packages here can be worked on,'
            msgbody += ' the following tracking bugs were opened for them:'
            for pkg_bug in der_bug_list:
                msgbody += '\n%s - bug %s' % (pkg_bug[0], pkg_bug[1])
        if bp_bug_list:
            msgbody += '\n\nBackport packages from packages here can be worked on,'
            msgbody += ' the following tracking bugs were opened for them:'
            for pkg_bug in bp_bug_list:
                msgbody += '\n%s (%s) - bug %s' % (pkg_bug[0], pkg_bug[1], pkg_bug[2])
        if m_bug_list:
            msgbody += '\n\nIt was not possible to create or handle the'
            msgbody += ' tracking bugs for the following packages'
            msgbody += ' (their tracking bugs based on this update'
            msgbody += ' must be handled manually):'
            for ln in m_bug_list:
                msgbody += '\n%s' % (ln)
        task = s.wfb.tasks_by_name[s.projectname]
        s.send_comment(task, 'Packages available', msgbody)

        # Set promote-to-proposed
        s.wfb.tasks_by_name[taskname].status = 'Confirmed'
        # Add time stamp and status
        if s.projectname == 'kernel-sru-workflow':
            s.set_tagged_timestamp(taskobj, 'kernel-stable-Prepare-package-end')
            s.set_tagged_timestamp(taskobj, 'kernel-stable-Promote-to-proposed-start')
            s.set_phase(taskobj, 'CopyToProposed')
        else:
            s.set_tagged_timestamp(taskobj, 'kernel-Prepare-package-end')
            s.set_tagged_timestamp(taskobj, 'kernel-Package-testing-start')
            s.set_phase(taskobj, 'Testing')
            s.send_upload_announcement(taskobj, 'proposed')

            cmd = 'ssh zinc.canonical.com \'echo "<html>%s</html>" > /srv/kernel.ubuntu.com/www/kernel-pkg-status/%s.html\'' % (s.wfb.title, series)
            status, result = run_command(cmd)

        cdebug('            handle_derivatives leave')


    def has_prep_task(s, taskname):
        if taskname in s.wfb.tasks_by_name:
            if s.wfb.tasks_by_name[taskname].status == "Fix Released":
                return True
        return False

    def check_component_in_pocket(s, taskobj, tstamp_prop, pocket):
        """
        Check if packages for the given tracking bug were properly copied
        to the right component in the given pocket.
        """
        cdebug('                check_component_in_pocket enter')
        cdebug('                    tstamp_prop: ' + tstamp_prop)
        bug = taskobj.bug
        cdebug('                   taskobj.name: %s' % taskobj.name, 'green')
        cdebug('                         pocket: %s' % pocket, 'green')

        # Set promote-to-proposed timestamp first, used for checking below
        s.set_tagged_timestamp(taskobj, tstamp_prop)

        # Wait publishing tasks to complete. Usually archive admin sets
        # the promote-to-<pocket> task to Fix Released right away after
        # doing the copy, but actual publishing takes more time. It's
        # said that the publishing should take at most 1 hour to
        # complete, but could be a bit more in some cases, or could
        # vary. Anyway, just wait arbitrarily 1 hour before we do the
        # actual processing, to avoid sru-workflow-manager to complain
        # about packages in wrong component while real copying/publishing
        # still didn't finish
        if not s.args.ignore_timestamp:
            if tstamp_prop in bug.properties:
                date_str = bug.properties[tstamp_prop]
                timestamp = datetime.strptime(date_str, '%A, %d. %B %Y %H:%M UTC')
                delta = DeltaTime(timestamp, datetime.utcnow())
                if delta.hours < 1:
                    cinfo('                Waiting 1 hour after promote-to-%s was Fix Released (%d)' % (pocket, delta.hours))
                    cdebug('                   timestamp : %s' % str(timestamp))
                    cdebug('                         now : %s' % str(datetime.utcnow()))
                    cdebug('                       delta : %s' % str(delta))
                    cdebug('                check_component_in_pocket leave (False)')
                    return False
            else:
                cdebug('                     tstamp_prop (%s) not in bug.properties' % tstamp_prop)
                cdebug('                check_component_in_pocket leave (False)')
                return False

        # Do the checking for proper packages in pocket->component
        series_name     = s.ubuntu.series_name(s.wfb.pkg_name, s.wfb.pkg_version)
        check_component = CheckComponent(s.lp.production_service)

        name_meta       = 'linux-meta'
        name_ports_meta = 'linux-ports-meta'
        name_signed     = 'linux-signed'
        name_split = s.wfb.pkg_name.split('-', 1)
        if len(name_split) > 1:
            name_meta       = '%s-meta-%s'       % (name_split[0], name_split[1])
            name_ports_meta = '%s-ports-meta-%s' % (name_split[0], name_split[1])
            name_signed     = '%s-signed-%s'     % (name_split[0], name_split[1])

        name_map = {
                'prepare-package-lbm'        : 'linux-backports-modules',
                'prepare-package-meta'       : name_meta,
                'prepare-package-ports-meta' : name_ports_meta,
                'prepare-package-signed'     : name_signed
            }
        ver_split = s.wfb.pkg_version.split('-')
        main_version = ver_split[0]
        pkg_list = [ s.wfb.pkg_name ]
        for name in iter(name_map):
            if s.has_prep_task(name):
                if 'lbm' in name:
                    pkg_list.append('%s-%s' % (name_map[name], main_version))
                else:
                    pkg_list.append(name_map[name])

        missing_pkg = []
        pkg_abi = ''
        dep_ver1 = main_version
        dep_ver2 = main_version
        if len(ver_split) > 1:
            pkg_abi = ver_split[1].split('.')[0]
            dep_ver1 = '%s-%s' % (main_version, pkg_abi)
            dep_ver2 = '%s.%s' % (main_version, pkg_abi)
        mis_lst = []
        for pkg in pkg_list:
            cdebug('                    pkg: %s' % pkg, 'green')
            if pkg == s.wfb.pkg_name:
                check_ver = s.wfb.pkg_version
            else:
                check_ver = None

            ps = check_component.get_published_sources(series_name, pkg, check_ver, pocket)
            if not ps:
                if check_ver:
                    missing_pkg.append([pkg, check_ver])
                elif pkg == name_signed:
                    missing_pkg.append([pkg, 'for version=%s' % (s.wfb.pkg_version)])
                else:
                    missing_pkg.append([pkg, 'with ABI=%s' % (pkg_abi)])
                continue

            if pkg == name_signed:
                src_ver = ps[0].source_package_version
                if src_ver.startswith(s.wfb.pkg_version):
                    mis_lst.extend(check_component.mismatches_list(series_name,
                                   pkg, ps[0].source_package_version,
                                   pocket, ps))
                else:
                    missing_pkg.append([pkg, 'for version=%s' % (s.wfb.pkg_version)])
            elif not check_ver:
                src_ver = ps[0].source_package_version
                # special hardcoded case for lrm on hardy...
                if src_ver.startswith(dep_ver1) or src_ver.startswith(dep_ver2):
                    mis_lst.extend(check_component.mismatches_list(series_name,
                                   pkg, ps[0].source_package_version,
                                   pocket, ps))
                else:
                    missing_pkg.append([pkg, 'with ABI=%s' % (pkg_abi)])
            else:
                mis_lst.extend(check_component.mismatches_list(series_name,
                               pkg, check_ver, pocket, ps))

        if not missing_pkg:
            cdebug('                    missing_pkg is set')
            if mis_lst:
                cdebug('                    mis_lst is set')
                s.wfb.tasks_by_name['promote-to-%s' % (pocket)].status = 'Incomplete'
                msgbody  = "The following packages ended up in the wrong"
                msgbody += " component in the -%s pocket:\n" % (pocket)
                for item in mis_lst:
                    cdebug('                           %s %s - is in %s instead of %s' % (item[0], item[1], item[2], item[3]), 'green')
                    msgbody += '\n%s %s - is in %s instead of %s' % (item[0], item[1], item[2], item[3])
                bugbody = msgbody
                bugbody += "\n\nOnce this is fixed, set the "
                bugbody += "promote-to-%s to Fix Released again" % (pocket)
                s.send_comment(taskobj, 'Packages outside of proper component', bugbody)
                if not s.args.dryrun:
                    s.props.set({tstamp_prop:None})
                s.send_email(taskobj, '[bug %s] Packages copied to the wrong component'
                                % (bug.id), msgbody)
                cwarn('                    packages ended up in the wrong pocket')
                cdebug('                check_component_in_pocket leave (False)')
                return False
        else:
            # Even if we already waited 1 hour, wait more (1 day) before
            # complaining if we don't find the packages published to
            # the pocket, in case the copy/publishing take more hours
            # after promote-to-<pocket> is set to Fix Released the first
            # time
            if delta.days >= 1:
                s.wfb.tasks_by_name['promote-to-%s' % (pocket)].status = 'Incomplete'
                msgbody  = "Promote-to-%s is Fix Released, but " % (pocket)
                msgbody += "some packages for this update aren't published "
                msgbody += "in Launchpad, on -%s pocket:\n" % (pocket)
                for item in missing_pkg:
                    msgbody += '\n%s %s' % (item[0], item[1])
                s.send_comment(taskobj, 'Can\'t find packages published in -%s' % (pocket), msgbody)
                if not s.args.dryrun:
                    s.props.set({tstamp_prop:None})
                cdebug('                check_component_in_pocket leave (False)')
                return False

            for item in missing_pkg:
                cwarn('                    Didn\'t find <%s> <%s> on -%s yet' % (item[0], item[1], pocket))

            cdebug('                check_component_in_pocket leave (False)')
            return False

        cdebug('                check_component_in_pocket leave (True)')
        return True

    def set_testing_to_confirmed(s, taskobj):
        if s.wfb.tasks_by_name['certification-testing'].status == 'New':
            s.wfb.tasks_by_name['certification-testing'].status = 'Confirmed'
            s.set_tagged_timestamp(taskobj, 'kernel-stable-Certification-testing-start')
        if s.wfb.tasks_by_name['regression-testing'].status == 'New':
            s.wfb.tasks_by_name['regression-testing'].status = 'Confirmed'
            s.set_tagged_timestamp(taskobj, 'kernel-stable-Regression-testing-start')
        if s.wfb.tasks_by_name['security-signoff'].status == 'New':
            s.wfb.tasks_by_name['security-signoff'].status = 'Confirmed'
            s.set_tagged_timestamp(taskobj, 'kernel-stable-Security-signoff-start')

    def promote_to_proposed_fix_released(s, taskobj):
        """
        When promote-to-proposed is set to Fix Released, we begin verification testing by setting
        verification-testing to In Progress, add tags to the bugs, and spam with text
        """
        cdebug('            promote_to_proposed_fix_released enter')
        # Exit if processed already
        task = s.wfb.tasks_by_name['verification-testing']
        if task.status != 'New':
            cdebug('                verification-testing task is not "New"')
            cdebug('            promote_to_proposed_fix_released leave (False)')
            return False

        # Check if packages were copied to the right pocket->component
        if not s.check_component_in_pocket(taskobj, 'kernel-stable-Promote-to-proposed-end', 'proposed'):
            cdebug('                packages not copied correctly')
            cdebug('            promote_to_proposed_fix_released leave (False)')
            return False

        # Update remaining time stamps and status, send announcement
        s.set_tagged_timestamp(taskobj, 'kernel-stable-Verification-testing-start')
        s.set_phase(taskobj, 'Verification & Testing')
        s.wfb.tasks_by_name['verification-testing'].status = 'In Progress'
        s.set_testing_to_confirmed(taskobj)
        s.send_upload_announcement(taskobj, 'proposed')

        # Now tag all bugs verification-needed and spam with a comment
        # Automate this in the future but for now send an email
        #
        cinfo('The SRU bugs are ready to be tagged and spammed.')
        return False

    def verification_testing_fix_released(s, taskobj):
        """
        When verification-testing is set to Fix Released, we set three tasks to Confirmed.
        These are certification-testing, regression-testing, and security-signoff
        """
        cdebug('            verification_testing_fix_released enter')
        # Add time stamp and status
        if ((s.wfb.tasks_by_name['certification-testing'].status != 'Fix Released' and
             s.wfb.tasks_by_name['certification-testing'].status != 'Invalid') or
            (s.wfb.tasks_by_name['security-signoff'].status != 'Fix Released' and
             s.wfb.tasks_by_name['security-signoff'].status != 'Invalid') or
            (s.wfb.tasks_by_name['regression-testing'].status != 'Fix Released' and
             s.wfb.tasks_by_name['regression-testing'].status != 'Invalid')):
            s.set_tagged_timestamp(taskobj, 'kernel-stable-Verification-testing-end')
            s.set_phase(taskobj, 'Testing')

        s.set_testing_to_confirmed(taskobj)
        s.verification_testing_complete = True
        cdebug('            verification_testing_fix_released leave (False)')
        return False

    def certification_testing_fix_released(s, taskobj):
        """
        When certification-testing is set to Fix Released, we check the tags
        If tagged certification-testing-failed then we alert people
        If certification-testing-passed then we save the tag and state and trigger
        running of the test to see if we're ready for publishing
        """
        cdebug('            certification_testing_fix_released enter')
        if 'certification-testing-failed' in s.bugtags:
            cinfo('                Certification tagged as FAIL', 'yellow')
            s.set_tagged_timestamp(taskobj, 'kernel-stable-Certification-testing-end')
            # Send email and possibly a status update -spc- TODO
            msgbody = 'The bug was tagged as certification-testing-failed\n'
            s.send_comment(taskobj, 'Certification FAILURE', msgbody)
            # stop further processing by this bot
            s.wfb.tasks_by_name[s.projectname].status = 'Incomplete'
            s.set_phase(taskobj, 'TestFail')
            cdebug('            certification_testing_fix_released leave (False)')
            return False
        elif 'certification-testing-passed' in s.bugtags:
            cinfo('                Certification tagged as PASSED', 'yellow')
            s.set_tagged_timestamp(taskobj, 'kernel-stable-Certification-testing-end')
            # TODO send a status.net update?
            s.certification_testing_complete = True
            cdebug('            certification_testing_fix_released leave (True)')
            return True
        else:
            cwarn('                certification-testing task set to Fix Released but no status tag (certification-testing-[passed|failed])!')
            # Send email and possibly a status update -spc- TODO
            msgbody = 'The certification-testing task was set to Fix Released but neither the certification-testing-passed or certification-testing-failed tag was applied\n'
            s.send_comment(taskobj, 'Certification completed but no status tags applied', msgbody)
            # reset task state so Certification team fixes it
            s.wfb.tasks_by_name['certification-testing'].status = 'Incomplete'
            cdebug('            certification_testing_fix_released leave (False)')
            return False

    def certification_testing_invalid(s, taskobj):
        """
        When certification-testing is set to Invalid, this indicates
        that certification testing will not be performed on this release.
        We consider the task to be 'done' in that we trigger a release test,
        but we don't check any tags
        """
        s.certification_testing_complete = True
        s.set_tagged_timestamp(taskobj, 'kernel-stable-Certification-testing-end')
        return True

    def regression_testing_invalid(s, taskobj):
        """
        When regression-testing is Invalid, it means we want to skip
        testing for that update. So just ignore and return the value to
        perform the release test
        """
        s.regression_testing_complete = True
        return True

    def regression_testing_fix_released(s, taskobj):
        """
        When regression-testing is set to Fix Released, we check the tags
        If tagged qa-testing-failed then we alert people
        If qa-testing-passed then we save the tag and state and trigger
        running of the test to see if we're ready for publishing
        """
        cdebug('            regression_testing_fix_released enter')
        if 'qa-testing-failed' in s.bugtags:
            cinfo('                Regression Testing tagged as FAIL', 'yellow')
            s.set_tagged_timestamp(taskobj, 'kernel-stable-Regression-testing-end')
            # Send email and possibly a status update -spc- TODO
            msgbody = 'The bug was tagged as qa-testing-failed\n'
            s.send_comment(taskobj, 'Regression Testing FAILURE', msgbody)
            # stop further processing by this bot
            s.wfb.tasks_by_name[s.projectname].status = 'Incomplete'
            s.set_phase(taskobj, 'TestFail')
            cdebug('            regression_testing_fix_released leave (False)', 'yellow')
            return False
        elif 'qa-testing-passed' in s.bugtags:
            cinfo('                Regression Testing tagged as PASSED', 'yellow')
            s.set_tagged_timestamp(taskobj, 'kernel-stable-Regression-testing-end')
            # TODO send a status.net update?
            s.regression_testing_complete = True
            cdebug('            regression_testing_fix_released leave (True)')
            return True
        else:
            cwarn('                regression-testing task set to Fix Released but no status tag (qa-testing-[passed|failed])!')
            # Send email and possibly a status update -spc- TODO
            msgbody = 'The regression-testing task was set to Fix Released but neither the qa-testing-passed or qa-testing-failed tag was applied\n'
            s.send_comment(taskobj, 'Regression Testing completed but no status tags applied', msgbody)
            # reset task so QA team can fix it
            s.wfb.tasks_by_name['regression-testing'].status = 'Incomplete'
            # stop further processing by this bot
            s.wfb.tasks_by_name[s.projectname].status = 'Incomplete'
            s.set_phase(taskobj, 'OnHold')
            cdebug('            regression_testing_fix_released leave (False)')
            return False

    def package_testing_fix_committed(s, taskobj):
        """
        When package-testing is set to Fix Released, that means the
        development kernel passed all wanted testing and is acked to go
        to the release pocket by the Ubuntu Kernel Team
        """
        cdebug('            package_testing_fix_committed enter')
        try:
            if s.wfb.tasks_by_name['promote-to-release'].status == 'New':
                # if this is a derivative tracking bug, first wait until
                # that packages on the master tracking bug are also ready or
                # already promoted. The way derivative package bugs are
                # opened already ensures this, but check the tasks on the
                # master bug anyway just in case...
                tsk_st = { 'promote-to-release' : [ 'Confirmed', 'Fix Released' ] }

                # If the master bug's tasks are not completely ready.
                #
                if s.verify_master_bug_tasks(taskobj.bug, tsk_st) <= 0:
                    cdebug('            package_testing_fix_committed leave (False)')
                    return False

                # Set promote-to-proposed
                s.wfb.tasks_by_name['promote-to-release'].status = 'Confirmed'
                # Add time stamp and status
                s.set_tagged_timestamp(taskobj, 'kernel-Package-testing-end')
                s.set_tagged_timestamp(taskobj, 'kernel-Promote-to-release-start')
                s.set_phase(taskobj, 'CopyToRelease')
        except:
            cerror('Exception thrown processing the package-testing task when set to Fix Released')
        cdebug('            package_testing_fix_committed leave (False)')
        return False

    def promote_to_release_fix_released(s, taskobj):
        """
        When promote-to-release is set to Fix Released, the development
        kernel is copied to the -release pocket, marking the end of the
        workflow for it. Some final checks are done here to verify that
        everything is ok
        """

        cdebug('            promote_to_release_fix_released enter')

        # Ensure all tasks are closed
        if not s.prepare_package_fixed():
            cdebug('            promote_to_release_fix_released leave')
            return

        if (s.wfb.tasks_by_name['package-testing'].status != 'Fix Released' or
            s.wfb.tasks_by_name['package-testing'].status != 'Invalid'):
            s.wfb.tasks_by_name['package-testing'].status = "Won't Fix"

        # Do we halted processing?
        if (s.wfb.tasks_by_name[s.projectname].status != 'In Progress'):
            cwarn('*** promote-to-release halted on bug with status!=In Progress\n')
            cdebug('            promote_to_release_fix_released leave')
            return

        if not s.check_component_in_pocket(taskobj, 'kernel-Promote-to-release-end', 'release'):
            cdebug('            promote_to_release_fix_released leave: False')
            return False

        s.final_promote_to_release_tasks(taskobj)

        s.wfb.tasks_by_name[s.projectname].status = 'Fix Released'
        s.set_phase(taskobj, 'Released')
        msgbody = 'The package has been published and the bug is being set to Fix Released\n'
        s.send_comment(taskobj, 'Package Released!', msgbody)
        s.send_status_update(taskobj, 'has been published.')

        cdebug('            promote_to_release_fix_released leave (fell out the bottom)')

    def security_signoff_finished(s, taskobj):
        """
        When security-signoff is set to either Invalid or Fix Released, it is done.
        If set to Fix Released, we set a flag to indicate that the package must
        be copied to the -security pocket.
        """
        s.security_signoff_complete = True
        s.set_tagged_timestamp(taskobj, 'kernel-stable-Security-signoff-end')
        # Trigger the release test
        return True

    # verify_state
    #
    def verify_state(s, task_name, required_states):
        '''
        A helper function to verify that a given task is set to one of the given,
        required states (status). If the task is not set to one of the given
        status, a comment to that affect is added to the bug and the task is set
        to 'Incomplete'.
        '''
        taskobj = s.wfb.tasks_by_name[task_name]
        if taskobj.status not in required_states:
            cerror('        %s set to invalid state. Required: %s' % (task_name, required_states))

            # Send email and possibly a status update
            #
            msgbody = '%s is not set to one of the following (correct) states:\n' % task_name
            for statename in required_states:
                msgbody = msgbody + statename + ', '
            msgbody = msgbody + '\n'
            msgbody = msgbody + '%s task was set to state %s\n' % (task_name, taskobj.status)
            msgbody = msgbody + 'Further processing of this bug by Workflow Manager is halted.\n'
            s.send_comment(taskobj, '%s is not set to a correct state' % task_name, msgbody)

            # Setting the tas to 'Incomplete' will stop further processing of the bug.
            #
            s.wfb.tasks_by_name[s.projectname].status = 'Incomplete'
            raise StateVerificationError()

    # within_publishing_window
    #
    def within_publishing_window(s):
        '''
        We do not publish kernel updates to the -security/-updates pockets just before
        the weekend. We do not want to encounter a bad regression when there is very
        little staff on hand to deal with it. Therefor we do not mark the tasks ready
        to publish if we are between 1800UTC Friday and 2100 UTC Sunday.

        Returns:
            True  - Within the publishing window; it's ok to publish.
            False - Outside the window; should not publish.
        '''
        retval = False
        now   = datetime.utcnow()
        today = now.weekday()

        if today in [0, 1, 2, 3]:          # Monday - Thursday
            retval = True
        elif today == 4 and now.hour < 18: # Friday, before 18:00 UTS
            retval = True
        elif today == 6 and now.hour > 20: # Sunday, after 21:00 UTS
            retval = True

        return retval

    # testing_completed
    #
    def testing_completed(s):
        '''
        Make sure that all testing that is supposed to be done, has been and has
        been successfull.

        Returns:
            True  - Testing completed and successful.
            False - Testing incomplete or failed.
        '''
        retval = False
        regression_testing_ok = False
        certification_testing_ok = False

        if s.wfb.tasks_by_name['regression-testing'].status == 'Invalid':
            regression_testing_ok = True
        elif 'qa-testing-passed' in s.bugtags:
            regression_testing_ok = True

        if s.wfb.tasks_by_name['certification-testing'].status == 'Invalid':
            certification_testing_ok = True
        elif 'certification-testing-passed' in s.bugtags:
            certification_testing_ok = True

        return regression_testing_ok and certification_testing_ok

    def hold_updates_security_copy(s):
        """
        The security team wants to avoid updates being copied to
        security/updates on Friday before the weekend. If there is some
        last minute crisis/regression on the kernel copied to
        -updates/-security, there are little resources to deal with this
        on the weekend. Also USN processing may be affected the by time
        of the kernel release. It was agreed that we should delay kernel
        copying to -updates/-security if we are between 1800UTC Fri -
        2100UTC Sun, this function is used to check that so we delay
        setting the promote to -updates/-security tasks to Confirmed.
        """
        now = datetime.utcnow()
        wday = now.weekday()
        retval = False
        if wday == 5:
            retval = True
        elif wday == 4 and now.hour >= 18:
            retval = True
        elif wday == 6 and now.hour < 21:
            retval = True
        return retval

    # verification_and_testing_completed
    #
    def verification_and_testing_completed(s):
        '''
        Make sure all the preconditions for setting the release states have been met.
        '''
        retval = True

        cnotice('')
        if not s.verification_testing_complete:
            cnotice('        verification testing has not been completed')
            retval = False
        if not s.certification_testing_complete:
            cnotice('        certification testing has not been completed')
            retval = False
        if not s.regression_testing_complete:
            cnotice('        regression testing has not been completed')
            retval = False
        if not s.security_signoff_complete:
            cnotice('        security signoff has not been completed')
            retval = False

        if retval:
            cnotice('        Cert and regression testing and security signoff all complete', 'yellow')

        return retval

    # release_ready
    #
    def release_ready(s):
        retval = True

        cdebug('            release_ready enter')
        try:
            # Some general sanity checks before we pull the lever to publish
            s.verify_state('prepare-package',       ['Fix Released'])
            s.verify_state('promote-to-proposed',   ['Fix Released'])
            s.verify_state('verification-testing',  ['Fix Released'])
            s.verify_state('certification-testing', ['Invalid', 'Fix Released'])
            s.verify_state('regression-testing',    ['Invalid', 'Fix Released'])
            s.verify_state('security-signoff',      ['Invalid', 'Fix Released'])
            # confirmed is in the next two in case we rerun the release test after
            # a dumb failure like email send fail or something
            s.verify_state('promote-to-security',   ['New', 'Confirmed', 'Invalid', 'Incomplete', 'Fix Released'])
            s.verify_state('promote-to-updates',    ['New', 'Confirmed', 'Incomplete', 'Fix Released'])

            if s.wfb.tasks_by_name[s.projectname].status != 'In Progress':
                cinfo('                Task %s is NOT In Progress' % s.projectname, 'red')
                retval = False

            if s.wfb.tasks_by_name['promote-to-security'].status == 'Incomplete':
                cinfo('                Task promote-to-security is Incomplete', 'red')
                retval = False

            if s.wfb.tasks_by_name['promote-to-updates'].status == 'Incomplete':
                cinfo('                Task promote-to-updates is Incomplete', 'red')
                retval = False

        except StateVerificationError as e:
            retval = False # An error has already been sent and the appropriate things done to the bug itself.

        cdebug('            release_ready leave(%s)' % retval)
        return retval


    # release
    #
    # This is not performed during processing for a specific task but only if several tasks are
    # in the correct state
    #
    def release(s):
        """
        Check results from multiple tasks to see whether release
        to -updates and -security are required
        """
        cinfo('')
        cinfo('    Performing Release Test:', 'cyan')

        cdebug('            release enter')

        if s.wfb.tasks_by_name['security-signoff'].status == 'Fix Released':
            # publishing to security is required
            s.security_publishing_required = True

        # one last check for test results
        #
        if s.testing_completed():
            cdebug('                all testing has been completed')
            tbug = s.wfb.lpbug

            tsk_st = {
                'promote-to-updates'  : [ 'Confirmed', 'Fix Released' ],
                'promote-to-security' : [ 'Confirmed', 'Fix Released', 'Invalid' ]
            }
            mb_status = s.verify_master_bug_tasks(tbug, tsk_st)

            # We don't publish on Fri/Sat/Sun (see comment on function
            # within_publishing_window). Also, only allow the
            # promote-to-{updates,security} on derivative packages
            # if the master packages are already ready for promotion
            # or already promoted to the updates/security pockets.

            # Either this is not a derivative bug at all or the master bug of which
            # this is a derivative is has the specified tasks in one of the accepted
            # states.
            #
            if (s.within_publishing_window() and mb_status > s.master_bug_bad_status):
                task = s.wfb.tasks_by_name[s.projectname]

                # If this is a derivative, it's supposed to be
                # rebased on top of master, or to have security
                # fixes as master has. Thus, we also enable
                # publishing to the security pocket for the
                # derivative if master will be or is published to
                # -security. In case we have an error getting the
                # status of the master security task, return (try
                # again later)
                tsk_st = { 'promote-to-security' : [ 'Confirmed', 'Fix Released' ] }
                mb_status = s.verify_master_bug_tasks(tbug, tsk_st)

                if s.security_publishing_required or mb_status == s.master_bug_good_status:
                    s.verbose('Requires publishing to the -security pocket\n')
                    if s.wfb.tasks_by_name['promote-to-security'].status == 'New':
                        s.wfb.tasks_by_name['promote-to-security'].status = 'Confirmed'
                else:
                    if s.wfb.tasks_by_name['promote-to-security'].status == 'New':
                        s.wfb.tasks_by_name['promote-to-security'].status = 'Invalid'

                if s.wfb.tasks_by_name['promote-to-updates'].status == 'New':
                    s.wfb.tasks_by_name['promote-to-updates'].status = 'Confirmed'
                    s.set_tagged_timestamp(task, 'kernel-stable-Promote-to-updates-start')
                    s.set_phase(task, 'CopyToUpdates')
            else:
                if not s.within_publishing_window():
                    cinfo('                Unable to set promote-to-{updates,security} tasks because we are outside of', 'yellow')
                    cinfo('                the publishing window.', 'yellow')
                else:
                    cinfo('                Unable to set promote-to-{updates,security} tasks because the master bug of', 'yellow')
                    cinfo('                this derivative is not ready for release. (mb_status:%s)' % mb_status, 'yellow')

        else:
            # don't have required testing signoffs
            s.verbose('ERROR: test completion tags not found during release test!\n')
            # Send email and possibly a status update
            msgbody = 'During the release test either the certification-testing-passed or the qa-testing-passed tag was not found\n'
            msgbody = msgbody + 'Tags on this bug are:\n'
            for ftag in s.bugtags:
                msgbody = msgbody + '    ' + ftag + '\n'
            msgbody = msgbody + '\n'
            msgbody = msgbody + 'Further processing of this bug by Workflow Manager is halted.\n'
            s.send_comment(s.wfb.tasks_by_name[s.projectname], 'Test completion tags not found during release test', msgbody)
            # stop further processing by this bot
            s.wfb.tasks_by_name[s.projectname].status = 'Incomplete'
            s.set_phase(s.wfb.tasks_by_name[s.projectname], 'OnHold')

        # this method is not associated with a task state transition so no status returned
        cdebug('            release leave')

        return

    def check_for_final_close(s, taskobj):
        """
        If either of the publishing tasks is set to complete (Fix Released) we
        make a check to see whether we can set the entire tracking bug to Fix Released (done)
        """
        cdebug('            check_for_final_close enter')

        if s.wfb.tasks_by_name[s.projectname].status == 'Fix Released':
            cdebug('                Bug already closed, aborting check')
            cdebug('            check_for_final_close leave: False')
            return False

        if ((s.wfb.tasks_by_name['promote-to-updates'].status == 'Fix Released') and
            (s.wfb.tasks_by_name['promote-to-security'].status == 'Invalid' or
            s.wfb.tasks_by_name['promote-to-security'].status == 'Fix Released')):

            # Check if packages were copied to the right pocket->component
            current_time = datetime.utcnow()
            pok_sec = True
            if s.wfb.tasks_by_name['promote-to-security'].status == 'Fix Released':
                pok_sec = s.check_component_in_pocket(taskobj, 'kernel-stable-Promote-to-updates-end', 'security')
            pok_upd = s.check_component_in_pocket(taskobj, 'kernel-stable-Promote-to-updates-end', 'updates')
            if not (pok_sec and pok_upd):
                cdebug('            check_for_final_close leave: False')
                return False

            print s.printlink,
            print ' Everything is done, setting bug to Fix Released'
            s.wfb.tasks_by_name[s.projectname].status = 'Fix Released'
            s.set_phase(taskobj, 'Released')

            # Send email and possibly a status update -spc- TODO
            msgbody = 'The package has been published and the bug is being set to Fix Released\n'
            s.send_comment(taskobj, 'Package Released!', msgbody)

            task = s.wfb.tasks_by_name['promote-to-updates']
            s.send_status_update(task, 'has been published.')

        # We should never trigger a release test from this, since it should have lready been done
        cdebug('            check_for_final_close leave: False')
        return False

# vi:set ts=4 sw=4 expandtab:

