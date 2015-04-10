#!/usr/bin/env python

# Taken and modified from:
# http://www.jejik.com/articles/2007/02/a_simple_unix_linux_daemon_in_python/

import atexit
import os
import signal
import sys
import time


if (hasattr(os, "devnull")):
    DEVNULL = os.devnull
else:
    DEVNULL = "/dev/null"


class Daemon(object):
    """
    A generic daemon class.
    
    Usage: subclass the Daemon class and override the _run() method
    """
    def __init__(self, serviceName, pidfile, stdin=DEVNULL, stdout=DEVNULL, stderr=DEVNULL):
        super(Daemon, self).__init__()
        
        self._serviceName = serviceName
        self._stdin = stdin
        self._stdout = stdout
        self._stderr = stderr
        self._pidfile = pidfile
    
    def _daemonize(self):
        """
        Do the UNIX double-fork magic, see Stevens' "Advanced
        Programming in the UNIX Environment" for details (ISBN 0201563177)
        http://www.erlenstar.demon.co.uk/unix/faq_2.html#SEC16
        """
        try:
            pid = os.fork()
            if pid > 0:
                # exit first parent
                sys.exit(0)
        except OSError, e:
            sys.stderr.write("fork #1 failed: %d (%s)\n" % (e.errno, e.strerror))
            sys.exit(1)
        
        # decouple from parent environment
        os.chdir("/")
        os.setsid()
        os.umask(0)
        
        # do second fork
        try:
            pid = os.fork()
            if pid > 0:
                # exit from second parent
                sys.exit(0)
        except OSError, e:
            sys.stderr.write("fork #2 failed: %d (%s)\n" % (e.errno, e.strerror))
            sys.exit(1)
        
        # redirect standard file descriptors
        sys.stdout.flush()
        sys.stderr.flush()
        si = file(self._stdin, 'r')
        so = file(self._stdout, 'a+')
        se = file(self._stderr, 'a+', 0)
        os.dup2(si.fileno(), sys.stdin.fileno())
        os.dup2(so.fileno(), sys.stdout.fileno())
        os.dup2(se.fileno(), sys.stderr.fileno())
        
        # write pidfile and subsys file
        pid = str(os.getpid())
        file(self._pidfile,'w+').write("%s\n" % pid)
        if os.path.exists('/var/lock/subsys'):
            try:
                fh = open(os.path.join('/var/lock/subsys', self._serviceName), 'w')
                fh.close()
            except IOError:
                print("Couldn't write to /var/lock/subsys")
    
    def _delpid(self):
        if os.path.exists(self._pidfile):
            os.remove(self._pidfile)
        
        subsysPath = os.path.join('/var/lock/subsys', self._serviceName)
        if os.path.exists(subsysPath):
            os.remove(subsysPath)
        
        self._cleanup()
    
    def start(self, daemonize=True):
        """
        Start the daemon
        """
        # Check for a pidfile to see if the daemon already runs
        try:
            pf = file(self._pidfile,'r')
            pid = int(pf.read().strip())
            pf.close()
        except IOError as erro:
            # pid file doesn't exist yet
            pid = None
        
        if pid:
            message = "pidfile %s already exist. Daemon already running?\n"
            sys.stderr.write(message % self._pidfile)
            sys.exit(1)
        
        # Start the daemon
        if daemonize:
            self._daemonize()
        
        # Cleanup handling
        def termHandler(signum, frame):
            self._delpid()
        signal.signal(signal.SIGTERM, termHandler)
        atexit.register(self._delpid)
        
        # Run the daemon
        self._run()
    
    def stop(self):
        """
        Stop the daemon
        """
        # Get the pid from the pidfile
        try:
            pf = file(self._pidfile,'r')
            pid = int(pf.read().strip())
            pf.close()
        except IOError:
            pid = None
        
        if not pid:
            message = "pidfile %s does not exist. Daemon not running?\n"
            sys.stderr.write(message % self._pidfile)
            return # not an error in a restart
        
        # Try killing the daemon process
        try:
            while 1:
                os.kill(pid, signal.SIGTERM)
                time.sleep(0.1)
        except OSError, err:
            err = str(err)
            if err.find("No such process") > 0:
                if os.path.exists(self._pidfile):
                    os.remove(self._pidfile)
            else:
                print str(err)
                sys.exit(1)
    
    def foreground(self):
        self.start(daemonize=False)
    
    def restart(self, daemonize=True):
        """
        Restart the daemon
        """
        self.stop()
        self.start(daemonize)
    
    def _run(self):
        """
        You should override this method when you subclass Daemon. It will be
        called after the process has been daemonized by start() or restart().
        """
        raise NotImplementedError('You must implement the method in your class.')
    
    def _cleanup(self):
        """
        You should override this method when you subclass Daemon. It will be
        called when the daemon exits.
        """
        raise NotImplementedError('You must implement the method in your class.')
