import os
from sys                                import stdout
from subprocess                         import Popen, PIPE, STDOUT
from threading                          import Thread
from time                               import sleep
from sopel.config.types                 import StaticSection, ValidatedAttribute

try:
    from Queue import Queue, Empty
except ImportError:
    from queue import Queue, Empty  # python 3.x

import sopel.module

# ShellTimeoutError
#
class ShellTimeoutError(Exception):
    """
    """
    def __init__(self, cmd, timeout):
        self.__cmd = cmd
        self.__timeout = timeout

    @property
    def cmd(self):
        '''
        The shell command that was being executed when the timeout occured.
        '''
        return self.__cmd

    @property
    def timeout(self):
        '''
        The timeout period that expired.
        '''
        return self.__timeout

# enqueue_output
#
def enqueue_output(out, queue, quiet=False):
    for line in iter(out.readline, b''):
        queue.put(line)
        if not quiet:
            stdout.write(line)
            stdout.flush()
    out.close()

# sh
#
def sh(cmd, timeout=None, ignore_result=False, quiet=False):
    out = []
    p = Popen(cmd, stdout=PIPE, stderr=STDOUT, bufsize=1, shell=True)
    q = Queue()
    t = Thread(target=enqueue_output, args=(p.stdout, q, quiet))
    t.daemon = True # thread dies with the program
    t.start()

    if timeout is not None:
        t.join(timeout)
        if t.is_alive():
            p.terminate()
            raise ShellTimeoutError(cmd, timeout)
    else:
        # If a timeout has not been specified, we still need to wait for
        # the thread to finish, but just don't care how long we wait.
        t.join()

    while p.poll() is None:
        # read line without blocking
        try:
            line = q.get_nowait()
        except Empty:
            pass
        else: # got line
            out.append(line)
        sleep(1)

    while True:
        try:
            line = q.get_nowait()
        except Empty:
            break
        else: # got line
            out.append(line)

    return p.returncode, out

class WFMSection(StaticSection):
    kteam_root = ValidatedAttribute('kteam_root', str, default=None)
    """Root of the kteam-tools directory"""

def configure(config):
    config.define_section('wfm', WFMSection)
    config.admin.configure_setting('kteam_root', 'Full path to the root of kteam-tools')

def setup(bot):
    bot.config.define_section('wfm', WFMSection)

@sopel.module.nickname_commands('help')
def help(bot, trigger):
    '''
    Dump out some info about the commands the bot recognizes.
    '''
    bot.say('Recognized commands:')
    bot.say('    shank [<bugid> <bugid> .. <bugid>]')
    bot.say('        Update one or more tracking bugs.')
    bot.say('    update [<what>]')
    bot.say('        Update one or all of the primary sru reports.')
    bot.say('    retest <bugid> [<bugid> .. <bugid>]')
    bot.say('        Restart testing for one or more tracking bugs.')

@sopel.module.nickname_commands('shank')
def shank_all(bot, trigger):
    '''
    When a user asks the bot to 'shank' or 'shank <bugid>' run the swm utility against the
    indicated bug(s).
    '''
    what = trigger.match.groups()[1]
    if what is None:
        # No bugs were specified so shank them all.
        #
        bot.say(trigger.nick + ', gimme some love boss')

        cmd = 'flock -nx --verbose /tmp/shanky.lck -c "%s/stable/swm" >>%s/logs/shank.log 2>&1' % (bot.config.wfm.kteam_root, os.environ['HOME'])
        (rc, output) = sh(cmd, quiet=True)
        if rc == 0:
            bot.say(trigger.nick + ', ' + 'I shanked them all')
        elif rc == 254:
            cmd = 'pastebinit -f python /tmp/exceptions.log'
            (rc, output) = sh(cmd, quiet=True)
            bot.say(trigger.nick + ', ' + 'That didn\'t go very well: ' + output[0].strip().decode("utf-8"))
    else:
        # A list of bugs were specified on the command line. Shank each of them
        # in order.
        #
        bot.say(trigger.nick + ', roger, roger')
        for bug in what.split():
            if not bug.isdigit():
                bot.say(trigger.nick + ', ' + '%s is not a vaid bug id' % bug)
                continue
            cmd = 'flock -nx --verbose /tmp/shanky.lck -c "%s/stable/swm %s" >>%s/logs/shank.log 2>&1' % (bot.config.wfm.kteam_root, bug, os.environ['HOME'])
            (rc, output) = sh(cmd, quiet=True)
            if rc == 0:
                bot.say(trigger.nick + ', ' + 'bug %s has been shanked' % bug)
            elif rc == 254:
                cmd = 'pastebinit -f python /tmp/exceptions.log'
                (rc, output) = sh(cmd, quiet=True)
                bot.say(trigger.nick + ', ' + 'That didn\'t go very well: ' + output[0].strip().decode("utf-8"))

@sopel.module.nickname_commands('retest')
def retest(bot, trigger):
    '''
    When someone asks the bot to kick off testing again for an existing tracking bug.
    '''
    what = trigger.match.groups()[1]
    if what is None:
        bot.say(trigger.nick + ', ' + 'You must give me the bugid of a tracking bug.')
    else:
        for bug in what.split():
            if not bug.isdigit():
                bot.say(trigger.nick + ', ' + '%s is not a vaid bug id' % bug)
                continue
            cmd = '%s/stable/tbt retest %s' % (bot.config.wfm.kteam_root, bug)
            (rc, output) = sh(cmd, quiet=True)
            if rc == 0:
                bot.say(trigger.nick + ', ' + 'tests for bug %s kicked off' % bug)
            elif rc == 254:
                cmd = 'pastebinit -f python /tmp/exceptions.log'
                (rc, output) = sh(cmd, quiet=True)
                bot.say(trigger.nick + ', ' + 'That didn\'t go very well: ' + output[0].strip())

@sopel.module.nickname_commands('update')
def update(bot, trigger):
    '''
    When someone asks the bot to update various reports.
    '''
    what = trigger.match.groups()[1]
    if what is None:
        what = 'shankbot'
    elif not what.endswith('.html') or ';' in what or ' ' in what:
        bot.say(trigger.nick + ', ' + 'I do not recognise that report.')
        return

    bot.say(trigger.nick + ', ' + 'roger, roger')

    cmd = '(cd /srv/kernel.ubuntu.com/www/sru; flock /tmp/sru-reports.lock make %s)' % (what,)

    (rc, output) = sh(cmd, quiet=True)
    if rc == 0:
        bot.say(trigger.nick + ', ' + 'report %s updated' % (what,))
    elif rc == 254:
        cmd = 'pastebinit -f python /tmp/exceptions.log'
        (rc, output) = sh(cmd, quiet=True)
        bot.say(trigger.nick + ', ' + 'That didn\'t go very well: ' + output[0].strip())
    else:
        bot.say(trigger.nick + ', ' + 'report %s update failed rc=%d' % (what, rc))

# vi:set ts=4 sw=4 expandtab syntax=python:
