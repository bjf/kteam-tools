
from wfl.log                                    import center, cleave, cinfo, cdebug
from .base                                      import TaskHandler

class Promoter(TaskHandler):
    # __init__
    #
    def __init__(s, lp, task, bug):
        center(s.__class__.__name__ + '.__init__')
        super(Promoter, s).__init__(lp, task, bug)
        cleave(s.__class__.__name__ + '.__init__')

    def _kernel_block(s):
        '''
        If a 'kernel-block' tag exist return True.
        '''
        center(s.__class__.__name__ + '._kernel_block')
        retval = False

        if 'kernel-block' in s.bug.tags or 'kernel-block-proposed' in s.bug.tags:
            retval = True

        cleave(s.__class__.__name__ + '._kernel_block (%s)' % retval)
        return retval

    def _kernel_block_ppa(s):
        '''
        If a 'kernel-block-ppa' tag exist return True.
        '''
        center(s.__class__.__name__ + '._kernel_block_ppa')
        retval = False

        if 'kernel-block-ppa' in s.bug.tags:
            retval = True

        cleave(s.__class__.__name__ + '._kernel_block_ppa (%s)' % retval)
        return retval

    def _kernel_unblock_ppa(s):
        '''
        If a 'kernel-unblock-ppa' tag exist return True.
        '''
        center(s.__class__.__name__ + '._kernel_unblock_ppa')
        retval = False

        if 'kernel-unblock-ppa' in s.bug.tags:
            retval = True

        cleave(s.__class__.__name__ + '._kernel_unblock_ppa (%s)' % retval)
        return retval

    def _block_proposed(s):
        '''
        If any 'block-proposed' tags still exist return True.
        '''
        center(s.__class__.__name__ + '.block_proposed')
        retval = False

        if ('block-proposed' in s.bug.tags) or ('block-proposed-%s' % s.bug.series in s.bug.tags):
            return True

        cleave(s.__class__.__name__ + '.block_proposed (%s)' % retval)
        return retval

    def _add_block_proposed(s):
        '''
        Add the block proposed tags
        '''
        center(s.__class__.__name__ + '._add_block_proposed')
        retval = False

        try:
            series_tag = 'block-proposed-%s' % s.bug.series
            s.bug.lpbug.tags.append(series_tag)
            s.bug.lpbug.tags.append('block-proposed')
        except:
            pass

        cleave(s.__class__.__name__ + '._add_block_proposed (%s)' % retval)
        return retval

    def _remove_block_proposed(s):
        '''
        Remove 'block-proposed' tags in order to signal britney.
        '''
        center(s.__class__.__name__ + '.remove_block_proposed')

        try:
            series_tag = 'block-proposed-%s' % s.bug.series
            if series_tag in s.bug.lpbug.tags:
                s.bug.lpbug.tags.remove(series_tag)
            if 'block-proposed' in s.bug.lpbug.tags:
                s.bug.lpbug.tags.remove('block-proposed')
        except:
            pass

        cleave(s.__class__.__name__ + '.remove_block_proposed')

    def _security_signoff_verified(s):
        '''
        Check if the security-signoff task has been set to 'Fix Released'. Development
        series tracking bugs do not have this task and should always return True.
        '''
        center(s.__class__.__name__ + '.security_signoff_verified')
        retval = False
        if s.bug.sru_workflow_project:
            try:
                if s.bug.tasks_by_name['security-signoff'].status in ['Fix Released', 'Invalid']:
                    retval = True
                else:
                    cinfo('            security-signoff is neither "Fix Released" nor "Invalid" (%s)' % (s.bug.tasks_by_name['security-signoff'].status), 'yellow')
            except KeyError:
                # security-signoff doesn't exist on this tracking bug.
                #
                retval = True
        else:
            retval = True
        cleave(s.__class__.__name__ + '.security_signoff_verified (%s)' % retval)
        return retval

    def _stakeholder_signoff_verified(s):
        '''
        Check if the stakeholder-signoff task has been set to 'Fix Released'. Development
        series tracking bugs do not have this task and should always return True.
        '''
        center(s.__class__.__name__ + '.stakeholder_signoff_verified')
        retval = False
        if s.bug.sru_workflow_project:
            try:
                if s.bug.tasks_by_name['stakeholder-signoff'].status in ['Fix Released', 'Invalid']:
                    retval = True
                else:
                    cinfo('            stakeholder-signoff is neither "Fix Released" nor "Invalid" (%s)' % (s.bug.tasks_by_name['security-signoff'].status), 'yellow')
            except KeyError:
                # stakeholder-signoff must not exist
                #
                retval = True
        else:
            retval = True
        cleave(s.__class__.__name__ + '.stakeholder_signoff_verified (%s)' % retval)
        return retval

    # _testing_completed
    #
    def _testing_completed(s):
        """
        """
        center(s.__class__.__name__ + '._testing_completed')
        retval = False # For the stub

        while True:
            # If all testing tasks have been set to Fix Released we are ready
            # to release.
            #
            testing_tasks = [
                'automated-testing',
                'regression-testing',
            ]
            if not s.bug.is_development_series:
                testing_tasks.append('certification-testing')
                testing_tasks.append('verification-testing')
            tested = True
            for task in testing_tasks:
                if s.bug.tasks_by_name[task].status not in ['Fix Released', 'Invalid']:
                    cinfo('            %s is neither "Fix Released" nor "Invalid" (%s)' % (task, s.bug.tasks_by_name[task].status), 'yellow')
                    tested = False

            if not tested and 'testing-override' not in s.bug.tags:

                if s.bug.tasks_by_name['promote-to-proposed'] in ['Fix Released']:
                    # Make sure the block-proposed tag is on while testing is still happening.
                    #
                    if s.bug.dev_workflow_project:
                        if 'block-proposed' not in s.bug.tags:
                            s.bug.lpbug.tags.append('block-proposed')
                    else:
                        if 'block-proposed-%s' % s.bug.series not in s.bug.tags:
                            s.bug.lpbug.tags.append('block-proposed-%s' % s.bug.series)
                    break

                break

            retval = True
            break

        cleave(s.__class__.__name__ + '._testing_completed (%s)' % retval)
        return retval

    # master_bug_ready
    #
    def master_bug_ready(s):
        center(s.__class__.__name__ + '.master_bug_ready')
        retval = False

        required_sru_tasks = {
            'prepare-package'            : ['Fix Released'],
            'prepare-package-lbm'        : ['Fix Released', 'Invalid'],
            'prepare-package-meta'       : ['Fix Released', 'Invalid'],
            'prepare-package-ports-meta' : ['Fix Released', 'Invalid'],
            'prepare-package-signed'     : ['Fix Released'],
            'promote-to-proposed'        : ['Confirmed', 'Fix Released'],
            'promote-to-updates'         : ['Confirmed', 'In Progress', 'Fix Released'],
            'promote-to-security'        : ['Confirmed', 'In Progress', 'Fix Released', 'Invalid']
        }

        master = s.bug.master_bug

        if 'testing-override' not in master.tags:
            required_sru_tasks['automated-testing']     = ['Fix Released', 'Invalid']
            required_sru_tasks['regression-testing']    = ['Fix Released', 'Invalid']

            if master.sru_workflow_project:
                required_sru_tasks['certification-testing'] = ['Fix Released', 'Invalid']
                required_sru_tasks['verification-testing']  = ['Fix Released', 'Invalid']

        tasks = required_sru_tasks
        retval = True
        for t in tasks:
            try:
                if master.tasks_by_name[t].status not in tasks[t]:
                    cinfo('master bug task %s is \'%s\' and not one of: %s' % (t, master.tasks_by_name[t].status, str(tasks[t])), 'yellow')
                    retval = False
                    break
            except KeyError:
                cdebug('master bug does not contian the %s task' % t)

        cleave(s.__class__.__name__ + '.master_bug_ready (%s)' % retval)
        return retval

    # master_bug_ready
    #
    def master_bug_ready_for_proposed(s):
        center(s.__class__.__name__ + '.master_bug_ready')
        retval = False

        required_sru_tasks = {
            'promote-to-proposed'        : ['Confirmed', 'Fix Released'],
        }

        master = s.bug.master_bug

        tasks = required_sru_tasks
        retval = True
        for t in tasks:
            try:
                if master.tasks_by_name[t].status not in tasks[t]:
                    cinfo('master bug task %s is \'%s\' and not one of: %s' % (t, master.tasks_by_name[t].status, str(tasks[t])), 'yellow')
                    retval = False
                    break
            except KeyError:
                cdebug('master bug does not contian the %s task' % t)

        cleave(s.__class__.__name__ + '.master_bug_ready (%s)' % retval)
        return retval

# vi: set ts=4 sw=4 expandtab syntax=python
