#!/usr/bin/env python
#
from datetime                           import datetime, timedelta
import yaml
import re
from lib.utils                          import date_to_string
from .log                               import cdebug, center, cleave, cinfo
from .package                           import Package, PackageError
from .check_component                   import CheckComponent
import json
from ktl.msgq                           import MsgQueue
from ktl.shanky                         import send_to_shankbot
from .errors                            import ShankError
from .deltatime                         import DeltaTime
from .task                              import WorkflowBugTask
from ktl.kernel_series                  import KernelSeries


# WorkflowBugError
#
class WorkflowBugError(ShankError):
    '''
    Thrown when some goes wrong with the WorkflowBug (e.g. when trying to
    process a non-existing bug).
    '''
    def __init__(s, emsg):
        super(ShankError, s).__init__(emsg)


# WorkflowBugProperties
#
class WorkflowBugProperties:

    # __init__
    #
    def __init__(self, bug):
        # get the current properties and save them
        self.bug = bug
        self.oldprops = bug.properties
        self.newprops = {}

    # setBugProperties
    #
    # Note - this should perhaps be in lpltk
    def set(self, newprops):
        """
        Set key:value pairs in the bug description. This follows a convention established in lpltk
        Input: a lpltk bug object and a dictionary of key:value pairs
        This function only stages the changes and does not write them to the
        bug description, to avoid rewriting the description multiple times
        """
        self.newprops.update(newprops)

    # flushBugProperties
    #
    # Note - this should perhaps be in lpltk
    def flush(self):
        """
        If needed, rewrite the bug description including
        changes staged by calls to setBugProperties
        """
        # See whether we really need to write anything new
        rmlist = []
        for keyname in self.newprops:
            if keyname in self.oldprops:
                if self.oldprops[keyname] == self.newprops[keyname]:
                    rmlist.append(keyname)
                    continue
        for keyname in rmlist:
            del self.newprops[keyname]
        if len(self.newprops) == 0:
            return

        # Set a name:value pair in a bug description
        olddescr = self.bug.description
        newdscr = ''
        re_kvp = re.compile("^(\s*)([\.\-\w]+):\s*(.*)$")
        last_key = {'': 'bar'}
        # copy everything, removing an existing one with this name if it exists
        foundProp = False
        for line in olddescr.split("\n"):
            # Skip empty lines after we start properties
            if line == '' and foundProp:
                continue
            m = re_kvp.match(line)
            if m:
                foundProp = True
                # There is a property on this line (assume only one per line)
                # see if it matches the one we're adding
                level = m.group(1)
                item = m.group(2)
                key = item
                if len(level) > 0:
                    key = "%s.%s" % (last_key[''], item)
                last_key[level] = item
                if key in self.newprops:
                    # we're going to be adding this one, remove the existing one
                    continue
            newdscr = newdscr + line + '\n'

        for k in self.newprops:
            if self.newprops[k]:
                newdscr = newdscr + '%s:%s\n' % (k, self.newprops[k])
        self.bug.description = newdscr
        return

# WorkflowBug
#
class WorkflowBug():
    '''
    A helper class. Tries to encapsulate most of the common methods for working with the
    workflow bug.
    '''
    projects_tracked  = ['kernel-development-workflow', 'kernel-sru-workflow']
    dryrun            = False
    no_assignments    = False
    no_announcements  = False
    sauron            = False
    no_timestamps     = False
    no_status_changes = False
    no_phase_changes  = False
    local_msgqueue_port = None

    # __init__
    #
    def __init__(s, lp, bugid):
        '''
        When instantiated the bug's title is processed to find out information about the
        related package. This information is cached.
        '''
        s.lp = lp
        try:
            s.lpbug = s.lp.get_bug(bugid)
        except KeyError:
            s.is_valid = False
            cdebug('Failed to get bug #%s' % bugid, 'red')
            raise WorkflowBugError('Invalid bug number %s' % bugid)

        # Pass along any "global" settings to the WorkflowBugTask.
        #
        WorkflowBugTask.dryrun = WorkflowBug.dryrun
        WorkflowBugTask.no_status_changes = WorkflowBug.no_status_changes
        WorkflowBugTask.no_assignments = WorkflowBug.no_assignments
        WorkflowBugTask.no_timestamps = WorkflowBug.no_timestamps

        s.title = s.lpbug.title
        s._tags = None
        s.props = WorkflowBugProperties(s.lpbug)
        s.bprops = {}
        s.bprops = s.load_bug_properties()

        # If a bug isn't to be processed, detect this as early as possible.
        #
        (s.is_workflow, s.is_valid) = s.check_is_valid(s.lpbug)
        s.properties = s.lpbug.properties

        try:
            s.__package = Package(s.lp, s)
            ks = KernelSeries().lookup_series(codename=s.__package.series)
            s.is_development_series = ks.development

            # If the package is only partial (valid == False) then we are not valid either.
            if not s.__package.valid:
                s.is_valid = False

            cinfo('                      title: "%s"' % s.title, 'blue')
            cinfo('                   is_valid: %s' % s.is_valid, 'blue')
            cinfo('                is_workflow: %s' % s.is_workflow, 'blue')
            cinfo('                      valid: %s' % s.__package.valid, 'blue')
            cinfo('                   pkg_name: "%s"' % s.__package.name, 'blue')
            cinfo('                pkg_version: "%s"' % s.__package.version, 'blue')
            cinfo('                     series: "%s"' % s.__package.series, 'blue')
            cinfo('      is development series: %s' % s.is_development_series, 'blue')
            for d in s.__package.pkgs:
                cinfo('                        dep: "%s"' % d, 'blue')

            if s.is_derivative_package:
                cinfo('                 derivative: yes (%s)' % s.master_bug_id, 'blue')
            else:
                cinfo('                 derivative: no', 'blue')

            cinfo('               routing_mode: %s' % (s.__package.routing_mode), 'blue')
            cinfo('              test_flavours: %s' % (s.test_flavours()), 'blue')
            cinfo('')

            cinfo('    Targeted Project:', 'cyan')
            cinfo('        %s' % s.workflow_project, 'magenta')
            cinfo('')
            if len(s.properties) > 0:
                cinfo('    Properties:', 'cyan')
                for prop in s.properties:
                    cinfo('        %s: %s' % (prop, s.properties[prop]), 'magenta')

        except PackageError as e:
            # Report why we are not valid.
            for l in e.message:
                cinfo(l, 'red')
            s.is_valid = False
            s.__package = None

        s.tasks_by_name = s._create_tasks_by_name_mapping()

    # _remove_live_tag
    #
    def _remove_live_tag(s):
        # If this task is now closed, also drop the live tag.
        if s.is_valid and s.tasks_by_name[s.workflow_project].status == 'Fix Released':
            if s._dryrun:
                cinfo('    dryrun - workflow task is closed -- removing -live tag', 'red')
            else:
                cinfo('    action - workflow task is closed -- removing -live tag', 'red')

                # Drop the "-live" tag as this one is moving dead.
                if 'kernel-release-tracking-bug-live' in s.lpbug.tags:
                    s.lpbug.tags.remove('kernel-release-tracking-bug-live')

    # save
    #
    def save(s):
        s.props.flush()
        s.save_bug_properties()
        s._remove_live_tag()

    @property
    def _dryrun(s):
        return WorkflowBug.dryrun

    @property
    def _no_announcements(s):
        return WorkflowBug.no_announcements

    @property
    def _sauron(s):
        return WorkflowBug.sauron

    # master_bug_property_name
    #
    @property
    def master_bug_property_name(s):
        retval = 'kernel'
        if not s.is_development_series:
            retval += '-stable'
        retval += '-master-bug'
        return retval

    # is_derivative_package
    #
    @property
    def is_derivative_package(s):
        return s.master_bug_property_name in s.properties

    # master_bug
    #
    @property
    def master_bug_id(s):
        '''
        '''
        return s.properties[s.master_bug_property_name]

    # master_bug
    #
    @property
    def master_bug(s):
        '''
        Find the 'master' bug of which this is a derivative and return that bug.
        '''
        return WorkflowBug(s.lp, s.master_bug_id)

    # is_proposed_only
    #
    @property
    def is_proposed_only(s):
        return s.__package.proposed_only


    # load_bug_properties
    #
    def load_bug_properties(s):
        center(s.__class__.__name__ + '.load_bug_properties')
        retval = {}
        started = False
        buf = ''

        description = s.lpbug.description
        for l in description.split('\n'):
            if started:
                buf += l + '\n'
            if l.startswith('-- swm properties --'):
                started = True

        if started and buf is not None:
            try:
                retval = yaml.safe_load(buf)
            except:
                cinfo('Exception thrown trying to load bug properties', 'red')
                retval = {}

        cleave(s.__class__.__name__ + '.load_bug_properties')
        return retval

    # save_bug_properties
    #
    def save_bug_properties(s):
        center(s.__class__.__name__ + '.save_bug_properties')

        retval = None
        newd = ''

        if len(s.bprops) > 0:
            new_props = yaml.dump(s.bprops, default_flow_style=False).strip()

            description = s.lpbug.description
            for l in description.split('\n'):
                if l.startswith('-- swm properties --'):
                    break
                newd += l + '\n'

            newd += '-- swm properties --\n'
            newd += new_props

            if s.lpbug.description != newd:
                if s._dryrun:
                    cinfo('    dryrun - updating SWM properties', 'red')
                else:
                    cinfo('    action - updating SWM properties', 'red')
                    s.lpbug.description = newd
            else:
                cinfo('    noop - SWM properties unchanged', 'yellow')
            for line in new_props.split('\n'):
                cinfo('        ' + line, 'magenta')

        cleave(s.__class__.__name__ + '.save_bug_properties')
        return retval

    # check_is_valid
    #
    def check_is_valid(s, bug):
        '''
        Determine if this bug is one that we want to be processing. Bugs that we
        should not be processing are ones that are not currently "In Progress".
        '''
        workflow = False
        valid = False
        for t in s.lpbug.tasks:
            task_name       = t.bug_target_name

            if task_name in WorkflowBug.projects_tracked:
                workflow = True
                s.workflow_project = task_name
                if t.status == 'In Progress':
                    valid = True
                    continue
                else:
                    if s._sauron:
                        continue
                    cdebug('        Not processing this bug because master task state is set to %s' % (t.status))
                    cdebug('        Quitting this bug')

        return (workflow, valid)

    # _create_tasks_by_name_mapping
    #
    def _create_tasks_by_name_mapping(s):
        '''
        We are only interested in the tasks that are specific to the workflow project. Others
        are ignored.
        '''
        tasks_by_name = {}

        cinfo('')
        cinfo('    Scanning bug tasks:', 'cyan')

        for t in s.lpbug.tasks:
            task_name       = t.bug_target_name

            if task_name.startswith(s.workflow_project):
                if '/' in task_name:
                    task_name = task_name[len(s.workflow_project) + 1:].strip()
                tasks_by_name[task_name] = WorkflowBugTask(t, task_name, s.__package, s)
            else:
                cinfo('        %-25s' % (task_name), 'magenta')
                cinfo('            Action: Skipping non-workflow task', 'magenta')

        return tasks_by_name

    # package_fully_built
    #
    def package_fully_built(s, pkg):
        '''
        For the package specified, the status of whether or not it is fully built
        is returned.
        '''
        retval = s.__package.fully_built(pkg)
        return retval

    # packages_released
    #
    @property
    def packages_released(s):
        '''
        '''
        retval = True

        if s.is_development_series:
            pocket = 'Release'
        else:
            pocket = 'Updates'

        bi = s.__package.build_info
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

        bi = s.__package.build_info
        for pkg in bi:
            if bi[pkg][pocket]['built'] is not True:
                cinfo('            %s has not been released.' % (pkg), 'yellow')
                retval = False
                break

        return retval

    # proposed_pocket_clear
    #
    @property
    def proposed_pocket_clear(s):
        '''
        Check that the proposed pocket is either empty or contains the same version
        as found in -updates/-release.
        '''
        retval = True

        if s.is_development_series:
            pocket = 'Release'
        else:
            pocket = 'Updates'

        bi = s.__package.build_info
        for pkg in bi:
            if bi[pkg]['Proposed']['version'] not in (None, bi[pkg][pocket]['version']):
                cinfo('            %s has %s pending in -proposed.' % (pkg, bi[pkg]['Proposed']['version']), 'yellow')
                retval = False

        # If proposed is not clear, consider if it is full due to a bug
        # which has been duplicated against me.
        if not retval:
            # XXX: XXX: lpltk does NOT let me get to the duplicate list!?!?!?!
            duplicates = s.lpbug.lpbug.duplicates
            #duplicates = [ s.lp.get_bug('1703532') ]
            for dup in duplicates:
                dup_wb = WorkflowBug(s.lp, dup.id)
                if not dup_wb.is_workflow:
                    continue
                if dup_wb.is_valid and dup_wb.__package and dup_wb.__package.all_built_and_in_proposed:
                    cinfo('            %s is duplicate of us and owns the binaries in -proposed, overriding' % (dup.id,), 'yellow')
                    retval = True
                    break

        return retval

    # all_dependent_packages_fully_built
    #
    @property
    def all_dependent_packages_fully_built(s):
        '''
        For the kernel package associated with this bug, the status of whether or
        not all of the dependent packages (meta, signed, lbm, etc.) are fully built
        is returned.
        '''
        retval = True

        bi = s.__package.build_info
        for pkg in bi:
            pkg_built = False
            try:
                for pocket in bi[pkg]:
                    if bi[pkg][pocket]['built']:
                        pkg_built = True
                        break
            except KeyError:
                pkg_built = False

            if not pkg_built:
                cinfo('        %s is not fully built yet.' % (pkg), 'yellow')
                retval = False
                break

        return retval

    # valid_package
    #
    def valid_package(s, pkg):
        center(s.__class__.__name__ + '.valid_package')

        retval = pkg in s.__package.pkgs

        cleave(s.__class__.__name__ + '.valid_package')
        return retval


    # uploaded
    #
    def uploaded(s, pkg):
        '''
        '''
        center(s.__class__.__name__ + '.uploaded')
        retval = False

        bi = s.__package.build_info
        for pocket in bi[pkg]:
            if bi[pkg][pocket]['status'] in ['BUILDING', 'FULLYBUILT', 'FAILEDTOBUILD']:
                retval = True

        cleave(s.__class__.__name__ + '.uploaded (%s)' % (retval))
        return retval

    # any_in_pocket
    #
    def any_in_pocket(s, pocket):
        center(s.__class__.__name__ + '.any_in_pocket')

        retval = s.__package.any_in_pocket(pocket) 

        cleave(s.__class__.__name__ + '.any_in_pocket (%s)' % (retval))
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
        retval = False
        if s.__package.all_built_and_in_proposed:

            # Find the most recent date of either the publish date/time or the
            # date/time of the last build of any arch of any of the dependent
            # package.
            #
            date_available = None
            bi = s.__package.build_info
            for d in sorted(bi):
                for p in sorted(bi[d]):
                    if bi[d][p]['published'] is None:
                        continue
                    if bi[d][p]['most_recent_build'] is None:
                        continue

                    if bi[d][p]['published'] > bi[d][p]['most_recent_build']:
                        if date_available is None or bi[d][p]['published'] > date_available:
                            date_available = bi[d][p]['published']
                    else:
                        if date_available is None or bi[d][p]['most_recent_build'] > date_available:
                            date_available = bi[d][p]['most_recent_build']
            now = datetime.utcnow()
            comp_date = date_available + timedelta(hours=2)
            if comp_date < now:
                # It has been at least 2 hours since the package was either published or fully built
                # in proposed.
                #
                retval = True
            else:
                cinfo('It has been less than 2 hrs since the last package was either published or built.')
                cinfo('    build time + 2 hrs: %s' % comp_date)
                cinfo('                   now: %s' % now)

        cinfo('        Ready for testing: %s' % (retval), 'yellow')
        cleave(s.__class__.__name__ + '.ready_for_testing (%s)' % (retval))
        return retval

    # creator
    #
    def creator(s, pkg):
        '''
        Returns the name of the person that created the source package.
        '''
        retval = s.__package.creator(pkg)
        return retval

    @property
    def ckt_ppa(s):
        '''
        '''
        return s.__package.ckt_ppa

    @property
    def pkg_name(s):
        '''
        Property: The name of the package associated with this bug.
        '''
        return s.__package.name

    @property
    def pkg_version(s):
        '''
        Returns the full version as specified in the bug title.
        '''
        return s.__package.version

    @property
    def series(s):
        '''
        Decoded from the kernel version in the bug title, the series name associated
        with that kernel version is returned.
        '''
        return s.__package.series

    @property
    def source(s):
        '''
        Decoded from the kernel version in the bug title, the KS source object associated
        with that kernel version is returned.
        '''
        return s.__package.source

    @property
    def abi(s):
        '''
        The abi number from the full version in the bug title is returned.
        '''
        return s.__package.abi

    @property
    def kernel_version(s):
        '''
        Decoded from the version string in the title, the kernel version is returned.
        This is just the kernel version without the ABI or upload number.
        '''
        return s.__package.kernel

    @property
    def tags(s):
        '''
        Returns a list of the tags on the bug.
        '''
        if s._tags is None:
            s._tags = []
            for t in s.lpbug.tags:
                s._tags.append(t)
        return s._tags

    # modified
    #
    @property
    def modified(s):
        '''
        Have any of the tasks statuses been changed?
        '''
        retval = False
        for t in s.tasks_by_name:
            if s.tasks_by_name[t].modified:
                retval = True
                break
        return retval

    # _has_prep_task
    #
    def _has_prep_task(s, taskname):
        if taskname in s.tasks_by_name:
            if s.tasks_by_name[taskname].status == "Fix Released":
                return True
        return False

    # relevant_packages_list
    #
    def relevant_packages_list(s):
        '''
        For every tracking bug there are 'prepare-package-*' tasks. Not every tracking bug has all the
        same 'prepare-pacakge-*' tasks. Also, there is a specific package associated with each of the
        'prepare-package-*' tasks.

        This method builds a list of the packages that are relevant to this particular bug.
        '''
        center(s.__class__.__name__ + '.relevant_packages_list')
        name_meta       = 'linux-meta'
        name_ports_meta = 'linux-ports-meta'
        name_signed     = 'linux-signed'
        name_split = s.pkg_name.split('-', 1)
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
        ver_split = s.pkg_version.split('-')
        main_version = ver_split[0]
        package_list = [s.pkg_name]
        for name in iter(name_map):
            if s._has_prep_task(name):
                if 'lbm' in name:
                    package_list.append('%s-%s' % (name_map[name], main_version))
                else:
                    package_list.append(name_map[name])

        for p in package_list:
            cdebug('pkg: %s' % p)
        cleave(s.__class__.__name__ + '.relevant_packages_list')
        return package_list

    # phase_key
    #
    @property
    def phase_key(s):
        retval = 'kernel'
        if not s.is_development_series:
            retval += '-stable'
        retval += '-phase'
        return retval

    # phase
    #
    @property
    def phase(s):
        return s.properties[s.phase_key]

    @phase.setter
    def phase(s, phasetext):
        """
        Add the phase we're entering as a 'property', along with a time stamp.
        """
        center(s.__class__.__name__ + '.set_phase')
        bug_prop_chg = s.phase_key + '-changed'

        # We have to check here to see whether the same status is already set,
        # or we will overwrite the timestamp needlessly
        if s.phase_key in s.properties:
            if s.phase == phasetext:
                # we already have this one
                cdebug('Not overwriting identical phase property (%s)' % phasetext)
                cleave(s.__class__.__name__ + '.set_phase')
                return
        # Handle dryrun mode
        if s._dryrun or WorkflowBug.no_phase_changes:
            cinfo('    dryrun - Changing bug phase to <%s>' % phasetext, 'red')
            cleave(s.__class__.__name__ + '.set_phase')
            return
        else:
            cdebug('Changing bug phase to <%s>' % phasetext)
        # Add phase and time stamp
        now = datetime.utcnow()
        now.replace(tzinfo=None)
        tstamp = date_to_string(now)
        props = {s.phase_key: phasetext, bug_prop_chg: tstamp}
        s.props.set(props)

        s.bprops['phase'] = phasetext
        cleave(s.__class__.__name__ + '.set_phase')

    # has_new_abi
    #
    def has_new_abi(s):
        tasks_abi = ['prepare-package-lbm', 'prepare-package-meta', 'prepare-package-ports-meta']
        retval = False
        for taskname in tasks_abi:
            if taskname in s.tasks_by_name:
                if s.tasks_by_name[taskname].status != "Invalid":
                    return True
        return retval

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
        flavours = s.__package.test_flavours
        if not flavours:
            # XXX: this makes no sense at all to be limited to xenial.
            generic = (s.pkg_name == 'linux' or
                       s.pkg_name.startswith('linux-hwe') or
                       s.pkg_name.startswith('linux-lts-'))
            if generic and s.series == 'xenial':
                flavours = [ 'generic', 'lowlatency' ]
            elif generic:
                flavours = [ 'generic' ]
            else:
                flavours = [ s.pkg_name.replace('linux-', '') ]

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
        subject = "[" + s.series + "] " + s.pkg_name + " " + flavour + " " + s.pkg_version + where
        s.send_email(subject, json.dumps(msg, sort_keys=True, indent=4), 'brad.figg@canonical.com,po-hsu.lin@canonical.com,kleber.souza@canonical.com')

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
            "kernel-version" : s.pkg_version,
            "package"        : s.pkg_name,
            "flavour"        : flavour,
        }

        # Add the kernel-sru-cycle identifier to the message
        #
        cycle = None
        for t in s.tags:
            if t.startswith('kernel-sru-cycle-'):
                cycle = t.replace('kernel-sru-cycle-', '')
        if cycle is None:
            cycle = '1962.11.02-00'
        msg['sru-cycle'] = cycle

        # At this time only 2 arches have the lowlatency flavour
        #
        if flavour == 'lowlatency':
            msg['arches'] = ['amd64', 'i386']

        if ppa:
            msg['pocket'] = 'ppa'
            if s.series in ['precise']:
                msg['ppa'] = 'ppa:canonical-kernel-esm/ppa'
            else:
                msg['ppa'] = 'ppa:canonical-kernel-team/ppa'
            msg['key']    = 'kernel.published.ppa.%s' % s.series
        elif s.series in ['precise']:
            msg['pocket'] = 'ppa'
            msg['ppa']    = 'ppa:canonical-kernel-esm/proposed'
            msg['key']    = 'kernel.published.ppa.%s' % s.series

        if s._dryrun or s._no_announcements:
            cinfo('    dryrun - Sending msgq announcement', 'red')
            for i, v in msg.items():
                cinfo('        [' + str(i) + '] = ' + str(v), 'red')
        else:
            if WorkflowBug.local_msgqueue_port:
                mq = MsgQueue(address='localhost', port=WorkflowBug.local_msgqueue_port)
            else:
                mq = MsgQueue()

            mq.publish(msg['key'], msg)

        return msg

    def send_email(s, subject, body, to):
        from .bugmail import BugMail
        BugMail.load_config('email.yaml')
        BugMail.to_address = to
        BugMail.send(subject, body)

    # send_upload_announcement
    #
    def send_upload_announcement(s, pocket):
        """
        Send email with upload announcement
        """
        center(s.__class__.__name__ + '.send_upload_announcement')

        # -------------------------------------------------------------------------------------------------------------
        # Email Notice
        # -------------------------------------------------------------------------------------------------------------

        cdebug('Sending upload announcement')

        to_address  = "kernel-team@lists.ubuntu.com"
        to_address += ", ubuntu-installer@lists.ubuntu.com"

        abi_bump = s.has_new_abi()

        subject = "[" + s.series + "] " + s.pkg_name + " " + s.pkg_version + " uploaded"
        if abi_bump:
            subject += " (ABI bump)"

        if s._dryrun or s._no_announcements:
            cinfo('    dryrun - Sending announcement to shankbot', 'red')
        else:
            send_to_shankbot(subject + '\n')

        body  = "A new " + s.series + " kernel has been uploaded into "
        body += pocket + ". "
        if abi_bump:
            body += "Note the ABI bump. "
        body += "\nThe full changelog about all bug fixes contained in this "
        body += "upload can be found at:\n\n"
        body += "https://launchpad.net/ubuntu/" + s.series + "/+source/"
        body += s.pkg_name + "/" + s.pkg_version + "\n\n"
        body += "-- \nThis message was created by an automated script,"
        body += " maintained by the\nUbuntu Kernel Team."

        if s._dryrun or s._no_announcements:
            cinfo('    dryrun - Sending email announcement', 'red')
        else:
            s.send_email(subject, body, to_address)

        cleave(s.__class__.__name__ + '.send_upload_announcement')
        return

    def add_comment(s, subject, body):
        """
        Add comment to tracking bug
        """
        center(s.__class__.__name__ + '.add_comment')
        if s._dryrun:
            cinfo('    dryrun - Adding comment to tracking bug', 'red')
            cdebug('')
            cdebug('subject: %s' % (subject))
            for l in body.split('\n'):
                cdebug('comment: %s' % (l))
            cdebug('')
        else:
            cdebug('Adding comment to tracking bug')
            s.lpbug.add_comment(body, subject)
        cleave(s.__class__.__name__ + '.add_comment')

    # set_tagged_timestamp
    #
    def set_tagged_timestamp(s, keyvalue):
        '''
        Add the supplied key with a timestamp. We do not replace existing keys
        '''
        center(s.__class__.__name__ + '.set_tagged_timestamp')

        # if s._dryrun or s.no_timestamps:
        #     cinfo('    dryrun - Adding tagged timestamp <%s> to tracking bug' % keyvalue, 'red')
        # else:
        #     if keyvalue not in s.lpbug.properties:
        #         cdebug('Adding tagged timestamp <%s> to tracking bug' % keyvalue)
        #         now = datetime.utcnow()
        #         now.replace(tzinfo=None)
        #         tstamp = date_to_string(now)
        #         props = {keyvalue : tstamp}
        #         s.props.set(props)

        cleave(s.__class__.__name__ + '.set_tagged_timestamp')

    # timestamp
    #
    def timestamp(s, keyvalue):
        '''
        Add the supplied key with a timestamp. We do not replace existing keys
        '''
        center(s.__class__.__name__ + '.timestamp')

        # if s._dryrun or s.no_timestamps:
        #     cinfo('    dryrun - Adding timestamp for \'%s\'' % keyvalue, 'red')
        # else:
        #     if keyvalue not in s.bprops:
        #         cinfo('    Adding timestamp for \'%s\'' % keyvalue)
        #         now = datetime.utcnow().replace(tzinfo=None)
        #         s.bprops[keyvalue] = date_to_string(now)

        cleave(s.__class__.__name__ + '.timestamp')

    # _publishing_settle_time
    #
    def _publishing_settle_time(s, tstamp_prop, pocket):
        '''
        Determine if we have waited long enough for the archive to have published the packages. Usually
        an archive admin sets the promote-to-<pocket> task to "Fix Released" right away after doing the copy.
        However, actual publishing takes more time.

        Someone said that the publishing could take at most 1 hour to complete. Therefore, we wait 1 hour
        before we do the "final" processing which verifies all the components got copied to the right places
        in the archive.
        '''
        center(s.__class__.__name__ + '._publishing_settle_time')
        retval = False

        if tstamp_prop in s.lpbug.properties:
            date_str = s.lpbug.properties[tstamp_prop]
            timestamp = datetime.strptime(date_str, '%A, %d. %B %Y %H:%M UTC')
            delta = DeltaTime(timestamp, datetime.utcnow())
            if delta.hours < 1:
                cinfo('    Waiting 1 hour after promote-to-%s was Fix Released (%d)' % (pocket, delta.hours), 'yellow')
                cinfo('    timestamp : %s' % str(timestamp), 'yellow')
                cinfo('          now : %s' % str(datetime.utcnow()), 'yellow')
                cinfo('        delta : %s' % str(delta), 'yellow')
            else:
                retval = True
        else:
            cinfo('tstamp_prop (%s) not in bug.properties' % tstamp_prop, 'yellow')

        cleave(s.__class__.__name__ + '._publishing_settle_time (%s)' % retval)
        return True

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
            center(s.__class__.__name__ + '.check_component_in_pocket (False)')
            return False

        check_component = CheckComponent(s.lp, s.__package)

        pkg_list = s.relevant_packages_list()

        primary_src_component = None
        missing_pkg = []
        mis_lst = []
        for pkg in pkg_list:
            if pkg == s.pkg_name:
                check_ver = s.pkg_version
            else:
                check_ver = None

            ps = check_component.get_published_sources(s.series, pkg, check_ver, pocket)
            if not ps:
                if check_ver:
                    missing_pkg.append([pkg, check_ver])
                elif 'linux-signed' in pkg:
                    missing_pkg.append([pkg, 'for version=%s' % (s.pkg_version)])
                else:
                    missing_pkg.append([pkg, 'with ABI=%s' % (s.abi)])
                continue

            # We are going to use the primary package source component as
            # our guide.  If we do not have that, then we cannot check.
            if pkg == s.pkg_name:
                primary_src_component = ps[0].component_name

            if 'linux-signed' in pkg:
                src_ver = ps[0].source_package_version
                if src_ver.startswith(s.pkg_version):
                    mis_lst.extend(check_component.mismatches_list(s.series,
                                   pkg, ps[0].source_package_version,
                                   pocket, ps, primary_src_component))
                else:
                    missing_pkg.append([pkg, 'for version=%s' % (s.pkg_version)])
            elif not check_ver:
                src_ver = ps[0].source_package_version

                # source_package_version for linux-ports-meta and linux-meta is
                # <kernel-version>.<abi>.<upload #> and for linux-backports-modules
                # it is <kernel-version-<abi>.<upload #>
                #
                v1 = s.kernel_version + '.' + s.abi
                v2 = s.kernel_version + '-' + s.abi
                if src_ver.startswith(v1) or src_ver.startswith(v2):
                    mis_lst.extend(check_component.mismatches_list(s.series,
                                   pkg, ps[0].source_package_version,
                                   pocket, ps, primary_src_component))
                else:
                    missing_pkg.append([pkg, 'with ABI=%s' % (s.abi)])
            else:
                mis_lst.extend(check_component.mismatches_list(s.series,
                               pkg, check_ver, pocket, ps, primary_src_component))

        if missing_pkg:
            cdebug('missing_pkg is set')
            cinfo('        packages not yet available in pocket')
            cdebug('check_component_in_pocket leave (False)')
            return False

        if mis_lst:
            cdebug('mis_lst is set')

            task_name = 'promote-to-%s' % (pocket,)
            if s.tasks_by_name[task_name] != 'Incomplete':
                s.tasks_by_name['promote-to-%s' % (pocket)].status = 'Incomplete'

                body  = "The following packages ended up in the wrong"
                body += " component in the -%s pocket:\n" % (pocket)
                for item in mis_lst:
                    cdebug('%s %s - is in %s instead of %s' % (item[0], item[1], item[2], item[3]), 'green')
                    body += '\n%s %s - is in %s instead of %s' % (item[0], item[1], item[2], item[3])

                subject = '[ShankBot] [bug %s] Packages copied to the wrong component' % (s.lpbug.id)
                to_address  = "kernel-team@lists.ubuntu.com"
                to_address += ", ubuntu-installer@lists.ubuntu.com"
                s.send_email(subject, body, to_address)

                body += "\n\nOnce this is fixed, set the "
                body += "promote-to-%s to Fix Released again" % (pocket)
                s.add_comment('Packages outside of proper component', body)
                if not s._dryrun:
                    s.props.set({tstamp_prop: None})

            cinfo('        packages ended up in the wrong pocket')
            cdebug('check_component_in_pocket leave (False)')
            return False

        cleave(s.__class__.__name__ + '.check_component_in_pocket (True)')
        return True

# vi:set ts=4 sw=4 expandtab:
