
from wfl.log                            import center, cleave, cinfo
from .promoter                          import Promoter

class PromoteToSecurity(Promoter):
    '''
    A Task Handler for the promote-to-security task.
    '''

    # __init__
    #
    def __init__(s, lp, task, bug):
        center(s.__class__.__name__ + '.__init__')
        super(Promoter, s).__init__(lp, task, bug)

        s.jumper['New']           = s._ready_for_security
        s.jumper['Confirmed']     = s._verify_promotion
        s.jumper['Triaged']       = s._verify_promotion
        s.jumper['In Progress']   = s._verify_promotion
        s.jumper['Fix Committed'] = s._verify_promotion

        cleave(s.__class__.__name__ + '.__init__')

    # _ready_for_security
    #
    def _ready_for_security(s):
        """
        """
        center(s.__class__.__name__ + '._ready_for_security')
        retval = False # For the stub

        while True:

            # The kernels below are in evaluation.  These only get as far
            # as -proposed and will not be promoted further:
            #
            if s.bug.is_proposed_only:
                s.task.status = 'Invalid'
                s.bug.tasks_by_name['security-signoff'].status = 'Invalid'
                retval = True
                break

            # If the security-signoff task is 'Invalid' then this task should also
            # be 'Invalid'. This task will no longer be processed after that.
            #
            if not s.bug.is_development_series:
                if s.bug.tasks_by_name['security-signoff'].status == 'Invalid':
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

        cleave(s.__class__.__name__ + '._ready_for_security (%s)' % retval)
        return retval

    # _verify_promotion
    #
    def _verify_promotion(s):
        center(s.__class__.__name__ + '._verify_promotion')
        retval = False

        while True:

            if s._block_proposed():
                s._remove_block_proposed()
                cinfo('            Removing block-proposed tag on this tracking bug', 'yellow')

            # Check if packages were copied to the right pocket->component
            #
            if not s.bug.packages_released_to_security:
                break

            cinfo('    All components are now in -proposed', 'magenta')
            s.task.status = 'Fix Released'
            s.task.timestamp('finished')
            s.bug.phase = 'Promoted to security'
            retval = True
            break

        cleave(s.__class__.__name__ + '._verify_promotion')
        return retval

# vi: set ts=4 sw=4 expandtab syntax=python
