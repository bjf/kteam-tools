
from wfl.log                                    import center, cleave, cdebug
from .base                                      import TaskHandler

class RegressionTesting(TaskHandler):
    '''
    A Task Handler for the regression-testing task.
    '''

    # __init__
    #
    def __init__(s, lp, task, bug):
        center(s.__class__.__name__ + '.__init__')
        super(RegressionTesting, s).__init__(lp, task, bug)

        s.jumper['New']           = s._new
        s.jumper['Confirmed']     = s._status_check
        s.jumper['In Progress']   = s._status_check
        s.jumper['Incomplete']    = s._status_check
        s.jumper['Fix Committed'] = s._status_check

        cleave(s.__class__.__name__ + '.__init__')

    # _new
    #
    def _new(s):
        center(s.__class__.__name__ + '._new')
        retval = False

        if s.bug.debs.ready_for_testing:
            s.task.status = 'Confirmed'
            retval = True

        cleave(s.__class__.__name__ + '._new (%s)' % retval)
        return retval

    # _status_check
    #
    def _status_check(s):
        center(s.__class__.__name__ + '._status_check')
        retval = False


        # If we have managed to spam the bugs then verification is now in-progress.
        if 'proposed-testing-requested' in s.bug.bprops and s.task.status == 'Confirmed':
            s.task.status = 'In Progress'
            retval = True

        elif 'qa-testing-failed' in s.bug.tags or 'regression-testing-failed' in s.bug.tags:
            cdebug('Regression Testing tagged as FAIL', 'yellow')
            if s.task.status != 'Confirmed' and s.task.status != 'Incomplete':
                msgbody = 'The bug was tagged as qa-testing-failed\n'
                s.bug.add_comment('Regression Testing FAILURE', msgbody)
                s.task.status = 'Incomplete'
                retval = True

        elif 'qa-testing-passed' in s.bug.tags or 'regression-testing-passed' in s.bug.tags:
            cdebug('Regression Testing tagged as PASSED', 'yellow')
            if s.task.status != 'Fix Released':
                s.task.status = 'Fix Released'
                retval = True

        if s.task.status == 'Fix Released':
            pass
        elif s.task.status == 'Incomplete':
            s.task.reason = 'Stalled -- testing FAILED'
        else:
            s.task.reason = 'Ongoing -- testing in progress'

        cleave(s.__class__.__name__ + '._status_check (%s)' % retval)
        return retval

# vi: set ts=4 sw=4 expandtab syntax=python
