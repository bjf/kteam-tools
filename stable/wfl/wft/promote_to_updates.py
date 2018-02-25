
from wfl.log                            import center, cleave, cinfo
from .promoter                          import Promoter

class PromoteToUpdates(Promoter):
    '''
    A Task Handler for the propose-to-proposed task.
    '''

    # __init__
    #
    def __init__(s, lp, task, bug):
        center(s.__class__.__name__ + '.__init__')
        super(PromoteToUpdates, s).__init__(lp, task, bug)

        s.jumper['New']           = s._ready_for_updates
        s.jumper['Confirmed']     = s._verify_promotion
        s.jumper['Triaged']       = s._verify_promotion
        s.jumper['In Progress']   = s._verify_promotion
        s.jumper['Fix Committed'] = s._verify_promotion
        s.jumper['Fix Released']  = s._complete
        s.jumper['Invalid']       = s._complete

        cleave(s.__class__.__name__ + '.__init__')

    # _ready_for_updates
    #
    def _ready_for_updates(s):
        """
        """
        center(s.__class__.__name__ + '._ready_for_updates')
        retval = False

        while True:

            # The kernels below are in evaluation.  These only get as far
            # as -proposed and will not be promoted further:
            #
            if s.bug.is_proposed_only:
                s.task.status = 'Invalid'
                retval = True
                break

            if s.bug.is_derivative_package:
                if not s.master_bug_ready():
                    break

            if not s._security_signoff_verified():
                break

            if not s._stakeholder_signoff_verified():
                break

            if not s._testing_completed():
                break

            if s._kernel_block():
                cinfo('            A kernel-block tag exists on this tracking bug', 'yellow')
                break

            s.task.status = 'Confirmed'
            retval = True
            break

        cleave(s.__class__.__name__ + '._ready_for_updates (%s)' % retval)
        return retval

    # _verify_promotion
    #
    def _verify_promotion(s):
        center(s.__class__.__name__ + '._verify_promotion')
        retval = False

        while True:

            # Check if packages were copied to the right pocket->component
            #
            if s._block_proposed():
                s._remove_block_proposed()
                cinfo('            Removing block-proposed tag on this tracking bug', 'yellow')

            if not s.bug.packages_released:
                cinfo('            packages have not been released', 'yellow')
                break

            cinfo('    All components are now in -updates', 'magenta')
            s.task.status = 'Fix Released'
            s.task.timestamp('finished')
            s.bug.phase = 'Promoted to updates'
            retval = True
            break

        cleave(s.__class__.__name__ + '._verify_promotion (%s)' % retval)
        return retval

    # _complete
    #
    def _complete(s):
        """
        """
        center(s.__class__.__name__ + '._complete')
        retval = False

        while True:
            # Check that the promote-to-updates status matches -updates pocket.
            promote_to_updates = s.bug.tasks_by_name['promote-to-updates']
            #if promote_to_updates.status not in ['Invalid', 'Fix Released']:
            #    break
            if promote_to_updates.status == 'Invalid' and s.bug.packages_released:
                cinfo('            packages have been released, but the task is set to "Invalid"', 'yellow')
                break
            elif promote_to_updates.status == 'Fix Released' and not s.bug.packages_released:
                cinfo('            packages have not been released, but the task is set to "Fix Released"', 'yellow')
                break

            # Since this is the one place where the master, project task is set Fix Released it needs to
            # do more than just look at the promote-to-updates. It needs to also look at promote-to-security,
            # confirm the testing is complete and that security signoff is completed.

            # Confirm we have completed all testing.
            if not s._testing_completed():
                break

            # Confirm we have a valid security signoff.
            if not s._security_signoff_verified():
                break

            if not s.bug.is_development_series:
                # Check that the promote-to-security status matches -security pocket.
                promote_to_security = s.bug.tasks_by_name['promote-to-security']
                if promote_to_security.status not in ['Invalid', 'Fix Released']:
                    cinfo('            promote-to-security is neither "Fix Released" nor "Invalid" (%s)' % (s.bug.tasks_by_name['promote-to-security'].status), 'yellow')
                    break
                if promote_to_security.status == 'Invalid' and s.bug.packages_released_to_security:
                    cinfo('            packages have been released to security, but the task is set to "Invalid"', 'yellow')
                    break
                elif promote_to_security.status == 'Fix Released' and not s.bug.packages_released_to_security:
                    cinfo('            packages have not been released to security, but the task is set to "Fix Released"', 'yellow')
                    break

                # Check that the promote-to-security status matches that of the security-signoff.
                security_signoff = s.bug.tasks_by_name['security-signoff']
                if promote_to_security.status != security_signoff.status:
                    cinfo('            package promote-to-security status (%s) does not match security-signoff status (%s)' % (promote_to_security.status, security_signoff.status), 'yellow')
                    break

                # Check that all snap tasks are either "Invalid" or "Fix Released"
                snap_done = True
                for taskname in s.bug.tasks_by_name:
                    if taskname.startswith('snap-') and s.bug.tasks_by_name[taskname].status not in ['Invalid', 'Fix Released']:
                        cinfo('            %s is neither "Fix Released" nor "Invalid" (%s)' % (taskname, s.bug.tasks_by_name[taskname].status), 'yellow')
                        snap_done = False
                if not snap_done:
                    break

            # All is completed so we can finally close out this workflow bug.
            s.bug.tasks_by_name[s.bug.workflow_project].status = 'Fix Released'
            if promote_to_updates.status == 'Invalid':
                msgbody = 'All tasks have been completed and the bug is being set to Fix Released\n'
                s.bug.add_comment('Workflow done!', msgbody)
            else:
                s.bug.phase = 'Released'
                msgbody = 'The package has been published and the bug is being set to Fix Released\n'
                s.bug.add_comment('Package Released!', msgbody)
            break

        cleave(s.__class__.__name__ + '._complete (%s)' % retval)
        return retval

# vi: set ts=4 sw=4 expandtab syntax=python
