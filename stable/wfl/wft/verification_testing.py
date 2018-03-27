
from wfl.log                                    import center, cleave, cinfo
from .base                                      import TaskHandler

class VerificationTesting(TaskHandler):
    '''
    A Task Handler for the verification-testing task.
    '''

    # __init__
    #
    def __init__(s, lp, task, bug):
        center(s.__class__.__name__ + '.__init__')
        super(VerificationTesting, s).__init__(lp, task, bug)

        s.jumper['New']          = s._new
        s.jumper['Confirmed']    = s._confirmed

        cleave(s.__class__.__name__ + '.__init__')

    # _new
    #
    def _new(s):
        center(s.__class__.__name__ + '._new')
        retval = False
        if s.bug.ready_for_testing:
            s.task.status = 'Confirmed'
            retval = True
        cleave(s.__class__.__name__ + '._new (%s)' % retval)
        return retval

    # _confirmed
    #
    def _confirmed(s):
        center(s.__class__.__name__ + '._confirmed')
        retval = False
        if s.bug.is_derivative_package:
            master = s.bug.master_bug
            try:
                if s.task.status != master.tasks_by_name['verification-testing'].status:
                    if 'New' != master.tasks_by_name['verification-testing'].status:
                        s.task.status = master.tasks_by_name['verification-testing'].status
                        retval = True
            except KeyError:
                cinfo('    master bug does not contain a verification-testing task', 'yellow')
        cleave(s.__class__.__name__ + '._confirmed (%s)' % retval)
        return retval

# vi: set ts=4 sw=4 expandtab syntax=python
