#!/usr/bin/env python
#
# Init file for Shotgun event daemon
#
# chkconfig: 345 99 00
# description: Shotgun event daemon
#
### BEGIN INIT INFO
# Provides: shotgunEvent
# Required-Start: $network
# Should-Start: $remote_fs
# Required-Stop: $network
# Should-Stop: $remote_fs
# Default-Start: 2 3 4 5
# Short-Description: Shotgun event daemon
# Description: Shotgun event daemon
### END INIT INFO

"""
For an overview of shotgunEvents, please see raw documentation in the docs
folder or an html compiled version at:

http://shotgunsoftware.github.com/shotgunEvents
"""

__version__ = '0.9'
__version_info__ = (0, 9)

import ConfigParser
import datetime
import imp
import logging
import logging.handlers
import pprint
import socket
import sys
import time
import traceback
import copy
import json
import math
from distutils.version import StrictVersion
from optparse import OptionParser

import os


try:
    import cPickle as pickle
except ImportError:
    import pickle

if sys.platform == 'win32':
    import win32serviceutil
    import win32service
    import win32event
    import servicemanager

import daemonizer
import shotgun_api3 as sg


CURRENT_PYTHON_VERSION = StrictVersion(sys.version.split()[0])
PYTHON_25 = StrictVersion('2.5')
PYTHON_26 = StrictVersion('2.6')
PYTHON_27 = StrictVersion('2.7')

if CURRENT_PYTHON_VERSION > PYTHON_25:
    EMAIL_FORMAT_STRING = """Time: %(asctime)s
Logger: %(name)s
Path: %(pathname)s
Function: %(funcName)s
Line: %(lineno)d

%(message)s"""
else:
    EMAIL_FORMAT_STRING = """Time: %(asctime)s
Logger: %(name)s
Path: %(pathname)s
Line: %(lineno)d

%(message)s"""

ACTIONS = ['start', 'stop', 'restart', 'foreground', 'forceEvents']
CONFIG_DIRECTORIES = ['/etc', os.path.dirname(__file__)]

STAT_TIMINGS = [60]

# Shotgun api does not handle an "in" filter with more than 65536 items,
# but for perf issue, we set it to 1000
MAX_PACKET_SIZE = 1000


def _setFilePathOnLogger(logger, path):
    # Remove any previous handler.
    _removeHandlersFromLogger(logger, logging.handlers.TimedRotatingFileHandler)

    # Add the file handler
    handler = logging.handlers.TimedRotatingFileHandler(path, 'midnight', backupCount=10)
    handler.setFormatter(logging.Formatter("%(asctime)s - %(name)s - %(levelname)s - %(message)s"))
    logger.addHandler(handler)


def _removeHandlersFromLogger(logger, handlerTypes=None):
    """
    Remove all handlers or handlers of a specified type from a logger.

    @param logger: The logger who's handlers should be processed.
    @type logger: A logging.Logger object
    @param handlerTypes: A type of handler or list/tuple of types of handlers
        that should be removed from the logger. If I{None}, all handlers are
        removed.
    @type handlerTypes: L{None}, a logging.Handler subclass or
        I{list}/I{tuple} of logging.Handler subclasses.
    """
    for handler in logger.handlers:
        if handlerTypes is None or isinstance(handler, handlerTypes):
            logger.removeHandler(handler)


def _addMailHandlerToLogger(logger, smtpServer, fromAddr, toAddrs, emailSubject, username=None, password=None, secure=None, use_ssl=None):
    """
    Configure a logger with a handler that sends emails to specified
    addresses.

    The format of the email is defined by L{LogFactory.EMAIL_FORMAT_STRING}.

    @note: Any SMTPHandler already connected to the logger will be removed.

    @param logger: The logger to configure
    @type logger: A logging.Logger instance
    @param toAddrs: The addresses to send the email to.
    @type toAddrs: A list of email addresses that will be passed on to the
        SMTPHandler.
    """
    if smtpServer and fromAddr and toAddrs and emailSubject:
        mailHandler = CustomSMTPHandler(smtpServer, fromAddr, toAddrs, emailSubject, (username, password), secure, use_ssl)
        mailHandler.setLevel(logging.ERROR)
        mailFormatter = logging.Formatter(EMAIL_FORMAT_STRING)
        mailHandler.setFormatter(mailFormatter)

        logger.addHandler(mailHandler)


def resolveEnv(path):
    """
    Resolve environmeent variables in path if possible

    @param path: The path to resolve
    @type path: str
    @return: The resolved path
    @rtype: str
    """
    return os.path.sep.join([folder if (not folder or not folder[0] == '$') else os.environ.get(folder[1:], folder)
                             for folder in path.split(os.path.sep)])

class Config(ConfigParser.ConfigParser):
    def __init__(self, path):
        ConfigParser.ConfigParser.__init__(self)
        self.read(path)

    def getShotgunURL(self):
        return self.get('shotgun', 'server')

    def getEngineScriptName(self):
        return self.get('shotgun', 'name')

    def getEngineScriptKey(self):
        return self.get('shotgun', 'key')

    def getEventIdFile(self):
        return resolveEnv(self.get('daemon', 'eventIdFile'))

    def getEnginePIDFile(self):
        return resolveEnv(self.get('daemon', 'pidFile'))

    def getPluginCommonPath(self):
      if self.has_option('plugins', 'common_path'):
        return resolveEnv(self.get('plugins', 'common_path'))
      return ''

    def getPluginPaths(self):
        return [resolveEnv(s.strip()) for s in self.get('plugins', 'paths').split(',')]

    def getPluginBlacklist(self):
      if self.has_option('plugins', 'blacklist'):
        return [resolveEnv(s.strip()) for s in self.get('plugins', 'blacklist').split(',')]
      return []

    def getPluginWhitelist(self):
      if self.has_option('plugins', 'whitelist'):
        return [resolveEnv(s.strip()) for s in self.get('plugins', 'whitelist').split(',')]
      return []

    def getSMTPServer(self):
        if self.has_option('emails', 'server'):
            return self.get('emails', 'server')
        return None

    def getSMTPPort(self):
        if self.has_option('emails', 'port'):
            return self.getint('emails', 'port')
        return 25

    def getFromAddr(self):
        return self.get('emails', 'from')

    def getToAddrs(self):
        return [s.strip() for s in self.get('emails', 'to').split(',')]

    def getEmailSubject(self):
        return self.get('emails', 'subject')

    def getEmailUsername(self):
        if self.has_option('emails', 'username'):
            return self.get('emails', 'username')
        return None

    def getEmailPassword(self):
        if self.has_option('emails', 'password'):
            return self.get('emails', 'password')
        return None

    def getSecureSMTP(self):
        if self.has_option('emails', 'useTLS'):
            return self.getboolean('emails', 'useTLS') or False
        return False

    def getUseSSL(self):
        if self.has_option('emails', 'useSSL'):
            return self.getboolean('emails', 'useSSL') or False
        return False

    def getLogMode(self):
        return self.getint('daemon', 'logMode')

    def getLogLevel(self):
        return self.getint('daemon', 'logging')

    def getMaxEventBatchSize(self):
        if self.has_option('daemon', 'max_event_batch_size'):
            return self.getint('daemon', 'max_event_batch_size')
        return 500

    def getLogFile(self, filename=None):
        if filename is None:
            if self.has_option('daemon', 'logFile'):
                filename = resolveEnv(self.get('daemon', 'logFile'))
            else:
                raise ConfigError('The config file has no logFile option.')

        if self.has_option('daemon', 'logPath'):
            path = resolveEnv(self.get('daemon', 'logPath'))

            if not os.path.exists(path):
                os.makedirs(path)
            elif not os.path.isdir(path):
                raise ConfigError('The logPath value in the config should point to a directory.')

            path = os.path.join(path, filename)

        else:
            path = filename

        return path

    def getEnableProjectFiltering(self):
        if self.has_option('project', 'enableProjectFiltering'):
            return self.getboolean('project', 'enableProjectFiltering') or False
        return False

    def getProjectNames(self):
        if self.getEnableProjectFiltering():
            if self.has_option('project', 'projectNames'):
                return self.get('project', 'projectNames').split(',')
            else:
                raise ConfigError('Project filtering is enabled but no project'
                                  ' names are defined')
        return None

    def getTreatNonProjectEvents(self):
        if self.getEnableProjectFiltering():
            if self.has_option('project', 'treatNonProjectEvents'):
                return self.getboolean('project', 'treatNonProjectEvents') or False
        return False

    def getBacklogTimeout(self):
        if self.has_option('daemon', 'backlog_timeout'):
            return self.getint('daemon', 'backlog_timeout')
        return 60

    def reprocessOnBacklog(self):
        if self.has_option('daemon', 'reprocess_on_backlog'):
            return self.getboolean('daemon', 'reprocess_on_backlog') or False
        return False

    def getMonitoringRefresh(self):
        if self.has_option('daemon', 'monitoring_refresh'):
            return self.getint('daemon', 'monitoring_refresh')
        return 60

    def getConnRetryMicroSleep(self):
        if self.has_option('daemon', 'conn_retry_microsleep'):
            return self.getint('daemon', 'conn_retry_microsleep')
        return 1

    def getStatTimings(self):
        if self.has_option('daemon', 'stat_timings'):
            timings = self.get('daemon', 'stat_timings').split(',')
            return sorted([int(t) for t in timings], reverse=True)
        # return [3600, 900, 60]  # TODO stat module too heavy to keep 150k event stat infos for ~20 plugins
        # return [300, 60]
        return [60]


class Engine(object):
    """
    The engine holds the main loop of event processing.
    """

    def __init__(self, configPath):
        """
        """
        self._continue = True
        self._eventIdData = {}

        # Read/parse the config
        self.config = Config(configPath)

        # Get config values
        pluginCommonPath = self.config.getPluginCommonPath()
        blacklistedPluginCollection = self.config.getPluginBlacklist()
        whitelistedPluginCollection = self.config.getPluginWhitelist()
        self._pluginCollections = [PluginCollection(self, s, pluginCommonPath, blacklistedPluginCollection, whitelistedPluginCollection) for s in self.config.getPluginPaths()]

        self._sg = sg.Shotgun(
            self.config.getShotgunURL(),
            self.config.getEngineScriptName(),
            self.config.getEngineScriptKey()
        )
        self._max_conn_retries = self.config.getint('daemon', 'max_conn_retries')
        self._conn_retry_sleep = self.config.getint('daemon', 'conn_retry_sleep')
        self._conn_retry_microsleep = self.config.getConnRetryMicroSleep()
        self._fetch_interval = self.config.getint('daemon', 'fetch_interval')
        self._use_session_uuid = self.config.getboolean('shotgun', 'use_session_uuid')

        
        self.enableProjectFiltering = self.config.getEnableProjectFiltering()
        self.projectsToFilter = self.config.getProjectNames()
        self.treatNonProjectEvents = self.config.getTreatNonProjectEvents()

        self._last_monitoring_time = datetime.datetime.now()
        self._fetch_timings = []
        self.stat_timings = self.config.getStatTimings()

        # Setup the logger for the main engine
        if self.config.getLogMode() == 0:
            # Set the root logger for file output.
            rootLogger = logging.getLogger()
            rootLogger.config = self.config
            _setFilePathOnLogger(rootLogger, '%s.%s' % (self.config.getLogFile(), '.stats'))
            print self.config.getLogFile()

            # Set the engine logger for email output.
            self.log = logging.getLogger('engine')
            self.setEmailsOnLogger(self.log, True)
        else:
            # Set the engine logger for file and email output.
            self.log = logging.getLogger('engine')
            self.log.config = self.config
            _setFilePathOnLogger(self.log, self.config.getLogFile())
            self.setEmailsOnLogger(self.log, True)

        self.log.setLevel(self.config.getLogLevel())

        super(Engine, self).__init__()

    def setEmailsOnLogger(self, logger, emails):
        # Configure the logger for email output
        _removeHandlersFromLogger(logger, logging.handlers.SMTPHandler)

        if emails is False:
            return

        smtpServer = self.config.getSMTPServer()
        if not smtpServer:
            return
        smtpPort = self.config.getSMTPPort()
        fromAddr = self.config.getFromAddr()
        emailSubject = self.config.getEmailSubject()
        username = self.config.getEmailUsername()
        password = self.config.getEmailPassword()
        if self.config.getSecureSMTP():
            secure = (None, None)
        else:
            secure = None
        
        if self.config.getUseSSL() :
            use_ssl = True
        else :
            use_ssl= None
    
        if emails is True:
            toAddrs = self.config.getToAddrs()
        elif isinstance(emails, (list, tuple)):
            toAddrs = emails
        else:
            msg = 'Argument emails should be True to use the default addresses, False to not send any emails or a list of recipient addresses. Got %s.'
            raise ValueError(msg % type(emails))

        _addMailHandlerToLogger(logger, (smtpServer, smtpPort), fromAddr, toAddrs, emailSubject, username, password, secure, use_ssl)

    def getCollectionForPath( self, path, autoDiscover=True, ensureExists=True ) :
        """
        Return a plugin collection to handle the given path
        @param path : The path to return a collection for
        @param autoDiscover : Should the collection check for new plugin and load them
        @param ensureExists : Create the collection if it does not exist
        @return: A collection that will handle the path or None.
        @rtype: L{PluginCollection}         
        """
        # Check if we already have a plugin collection covering the directory path
        for pc in self._pluginCollections :
            if pc.path == path :
                return pc
        else :
            if not ensureExists :
                return None
            # Need to create a new plugin collection
            self._pluginCollections.append( PluginCollection(self, path) )
            pc = self._pluginCollections[-1]
            pc._autoDiscover = autoDiscover
            return pc


    def loadPlugin( self, path, autoDiscover=True ) :
        """
        Load the given plugin into the Engine
        @param path : Full path to the plugin Python script
        @param autoDiscover: Wether or not the collection should automatically discover new plugins
        """
        # Check that everything looks right
        if not os.path.isfile(path) :
            raise ValueError( "%s is not a valid file path" % path )
        return self.getPlugin( path, ensureExists=True, autoDiscover=autoDiscover )

    def unloadPlugin( self, path ) :
        """
        Unload the plugin with the given path
        """
        # Get the collection for this path, if any
        ( dir, file ) = os.path.split( path )
        pc = self.getCollectionForPath( dir, ensureExists=False )
        if pc :
            self.log.debug("Unloading %s from %s", file, pc.path )
            pc.unloadPlugin( file )

    def getPlugin( self , path, ensureExists=False, autoDiscover=False ) :
        """
        Return the plugin with the given path if loaded in the Engine
        If ensureExists is True, make sure the plugin is loaded if not already
        @param path : Full path to the wanted plugin
        @param ensureExists : Wether or not the plugin should be loaded if not already
        @param autoDiscover : if a new Collection is created, wheter or not it should automatically check for new scripts
        """
        ( dir, file ) = os.path.split( path )
        pc = self.getCollectionForPath( dir, ensureExists=ensureExists, autoDiscover=autoDiscover )
        p = None
        if pc :
            p = pc.getPlugin( file, ensureExists=ensureExists )
        return p
            
    def start(self):
        """
        Start the processing of events.

        The last processed id is loaded up from persistent storage on disk and
        the main loop is started.
        """
        # TODO: Take value from config
        socket.setdefaulttimeout(60)

        # Notify which version of shotgun api we are using
        self.log.info('Using Shotgun version %s' % sg.__version__)
        try:
            for collection in self._pluginCollections:
                collection.load()

            self._loadEventIdData()

            self._mainLoop()
        except KeyboardInterrupt, err:
            self.log.warning('Keyboard interrupt. Cleaning up...')
        except Exception, err:
            msg = 'Crash!!!!! Unexpected error (%s) in main loop.\n\n%s'
            self.log.critical(msg, type(err), traceback.format_exc(err))

    def _getLastEventId(self):
        conn_attempts = 0
        while True:
            order = [{'column':'id', 'direction':'desc'}]
            try:
                result = self._sg.find_one("EventLogEntry", filters=[], fields=['id'], order=order)
            except (sg.ProtocolError, sg.ResponseError, socket.error), err:
                conn_attempts = self._checkConnectionAttempts(conn_attempts, str(err))
            except Exception, err:
                msg = "Unknown error: %s" % str(err)
                conn_attempts = self._checkConnectionAttempts(conn_attempts, msg)
            else:
                return result['id']

    def _loadEventIdData(self):
        """
        Load the last processed event id from the disk

        If no event has ever been processed or if the eventIdFile has been
        deleted from disk, no id will be recoverable. In this case, we will try
        contacting Shotgun to get the latest event's id and we'll start
        processing from there.
        """
        eventIdFile = self.config.getEventIdFile()

        if eventIdFile and os.path.exists(eventIdFile):
            try:
                fh = open(eventIdFile)
                try:
                    self._eventIdData = pickle.load(fh)

                    # Provide event id info to the plugin collections. Once
                    # they've figured out what to do with it, ask them for their
                    # last processed id.
                    for collection in self._pluginCollections:
                        state = self._eventIdData.get(collection.path)
                        if state:
                            collection.setState(state)
                except pickle.UnpicklingError:
                    fh.close()

                    # Backwards compatibility:
                    # Reopen the file to try to read an old-style int
                    fh = open(eventIdFile)
                    line = fh.readline().strip()
                    if line.isdigit():
                        # The _loadEventIdData got an old-style id file containing a single
                        # int which is the last id properly processed.
                        lastEventId = int(line)
                        self.log.debug('Read last event id (%d) from file.', lastEventId)
                        for collection in self._pluginCollections:
                            collection.setState(lastEventId)
                fh.close()
            except OSError, err:
                raise EventDaemonError('Could not load event id from file.\n\n%s' % traceback.format_exc(err))
        else:
            # No id file?
            # Get the event data from the database.
            lastEventId = self._getLastEventId()
            self.log.info('Last event id (%d) from the Shotgun database.', lastEventId)
            for collection in self._pluginCollections:
                collection.setState(lastEventId)

            self._saveEventIdData()

    def _mainLoop(self):
        """
        Run the event processing loop.

        General behavior:
        - Load plugins from disk - see L{load} method.
        - Get new events from Shotgun
        - Loop through events
        - Loop through each plugin
        - Loop through each callback
        - Send the callback an event
        - Once all callbacks are done in all plugins, save the eventId
        - Go to the next event
        - Once all events are processed, wait for the defined fetch interval time and start over.

        Caveats:
        - If a plugin is deemed "inactive" (an error occured during
          registration), skip it.
        - If a callback is deemed "inactive" (an error occured during callback
          execution), skip it.
        - Each time through the loop, if the pidFile is gone, stop.
        """
        self.log.debug('Starting the event processing loop.')
        while self._continue:

            self._processNewBacklogs()

            # Process events
            newEvents = self._getNewEvents()
            for event in newEvents:
                self.log.debug( "Processing %s", event['id'] )
                for collection in self._pluginCollections:
                    collection.process(event)
                self._saveEventIdData()

            # only sleep if the event list wasn't artificially limited
            if len(newEvents) < self.config.getMaxEventBatchSize():
                time.sleep(self._fetch_interval)

            # Reload plugins
            for collection in self._pluginCollections:
                collection.load()

            # Make sure that newly loaded events have proper state.
            self._loadEventIdData()

            self._handleMonitoring()

        self.log.debug('Shuting down event processing loop.')

    def stop(self):
        self._continue = False

    def _handleMonitoring(self):
        now = datetime.datetime.now()
        if now >= self._last_monitoring_time + datetime.timedelta(seconds=self.config.getMonitoringRefresh()):
            monitoringStartingTime = time.clock()
            self._last_monitoring_time = now

            stats = []
            shouldDelete = True
            for maxTime in self.stat_timings:
                stats.append({
                    'period': maxTime,
                    'stats': self.getStats(maxTime=maxTime, delete=shouldDelete),
                })
                shouldDelete = False

            # bootstrap monitoring with its timing
            stats.append({
                'last_update': str(now),
                'monitoring_time': time.clock()-monitoringStartingTime,
            })

            with open(self.config.getLogFile('stats'), 'w') as f:
                json.dump(stats, f)

    def getStats(self, maxTime=None, delete=False):
        stats = {
            collection.path: collection.getStats(maxTime=maxTime, delete=delete)
            for collection in self._pluginCollections
        }

        newFetchTimings = []
        allTimings = []
        minDate = datetime.datetime.now() - datetime.timedelta(seconds=maxTime)
        for timing in self._fetch_timings:
            if not maxTime or timing['added_at'] >= minDate:
                newFetchTimings.append(timing)
                allTimings.append(timing['timing'])

        if delete:
            self._fetch_timings = newFetchTimings

        stats['fetchTimeDeciles'] = deciles(allTimings)

        return stats

    def _processNewBacklogs(self):
        backlogs = set()
        expired = set()
        newBacklogs = set()
        for collection in self._pluginCollections:
            newBacklogs |= collection.getAndPurgeNewBacklog()
            cBacklogs, cExpired = collection.getBacklogIds()
            backlogs |= cBacklogs
            expired |= cExpired

        if newBacklogs:
            self.log.info('Adding events %s to backlog', newBacklogs)

        if expired:
            self.log.warning('Timeout elapsed on backlog events: %s', list(expired))

        if len(backlogs) == 0:
            return

        self.log.debug("Checking for %d backlog creation", len(backlogs))

        backlogList = list(backlogs)
        backlogEvents = []
        for i in range(0, len(backlogList), MAX_PACKET_SIZE):
            backlogEventsPart = self._fetchEventLogEntries(filters=[['id', 'in', backlogList[i:i+MAX_PACKET_SIZE]]],
                                                           order=[{'column':'id', 'direction':'asc'}])
            backlogEvents.extend(backlogEventsPart)

        # debug: fake drop of an event
        # backlogEvents = filter(lambda ev: ev['id'] != 9830708, backlogEvents)

        if backlogEvents:
            self.log.info('> Found %d backlogs!', len(backlogEvents))

            foundBacklogs = [e['id'] for e in backlogEvents]

            # case 1: we want to reprocess everything
            #   > we reset every plugins state to match
            if self.config.reprocessOnBacklog():
                for collection in self._pluginCollections:
                    for plugin in collection:
                        plugin.log.debug('Rolling back events from %d to %d'
                                             % (plugin._lastEventId, foundBacklogs[0]-1))

                        # remove every found event from the plugin backlog
                        for toremove in set(plugin._backlog.keys()) & foundBacklogs:
                            del(plugin._backlog[toremove])

                        # reset the last event to be the first found backlog
                        plugin._lastEventId = foundBacklogs[0] - 1

            # case 2: we dont want to reprocess events
            #   > we only process backlogs in order: fetch all infos from the events & process them
            else:
                fields = ['id', 'event_type', 'attribute_name', 'meta', 'entity', 'user', 'project', 'description', 'session_uuid', 'created_at']

                backlogList = list(backlogs)
                backlogEvents = []
                for i in range(0, len(backlogList), MAX_PACKET_SIZE):
                    backlogEventsPart = self._fetchEventLogEntries(filters=[['id', 'in', backlogList[i:i+MAX_PACKET_SIZE]]],
                                                                   fields=fields,
                                                                   order=[{'column':'id', 'direction':'asc'}])
                    backlogEvents.extend(backlogEventsPart)

                for collection in self._pluginCollections:
                    for event in backlogEvents:
                        collection.process(event)  # backlog array should be taken care off by the plugin's process

        else:
            self.log.debug('> No backlog created.')

    def _getNewEvents(self):
        """
        Fetch new events from Shotgun.

        @return: Recent events that need to be processed by the engine.
        @rtype: I{list} of Shotgun event dictionaries.
        """
        nextEventId = min([coll.getNextUnprocessedEventId() or -1 for coll in self._pluginCollections if coll.isActive()])

        if nextEventId == -1:  # no active plugin have any event id saved, retrieve it from SG
            nextEventId = self._getLastEventId()
            for collection in self._pluginCollections:
                if collection.isActive():
                    collection.setState(nextEventId)

        filters = [['id', 'greater_than', nextEventId - 1]]
        fields = ['id', 'event_type', 'attribute_name', 'meta', 'entity', 'user', 'project', 'description', 'session_uuid', 'created_at']
        order = [{'column':'id', 'direction':'asc'}]

        self.log.debug("Checking events from %d", nextEventId)

        fetchStartingTime = time.clock()
        nextEvents = self._fetchEventLogEntries(filters, fields, order, limit=self.config.getMaxEventBatchSize())
        self._fetch_timings.append({
            'added_at': datetime.datetime.now(),
            'timing': time.clock()-fetchStartingTime,
        })

        # debug: fake drop of an event
        # nextEvents = filter(lambda ev: ev['id'] != 9830708, nextEvents)

        if nextEvents:
            self.log.debug('> %d events: %d to %d.', len(nextEvents), nextEvents[0]['id'], nextEvents[-1]['id'])
        else:
            self.log.debug('> No events.')

        return nextEvents


    def _fetchEventLogEntries(self, filters, fields=['id'], order=[], limit=0):
        conn_attempts = 0
        while True:
            try:
                return self._sg.find("EventLogEntry", filters, fields, order, limit=limit)
            except (sg.ProtocolError, sg.ResponseError, socket.error), err:
                conn_attempts = self._checkConnectionAttempts(conn_attempts, str(err))
            except IndexError as erro:
                self.log.debug("Event %s doesn't exist yet" % nextEventId)
                return []
            except Exception, err:
                msg = "Unknown error: %s" % str(err)
                conn_attempts = self._checkConnectionAttempts(conn_attempts, msg)

        return []


    def _saveEventIdData(self):
        """
        Save an event Id to persistant storage.

        Next time the engine is started it will try to read the event id from
        this location to know at which event it should start processing.
        """
        eventIdFile = self.config.getEventIdFile()
        tmpEventIdFile = os.path.join(os.path.dirname(eventIdFile), ".%s" % os.path.basename(eventIdFile))

        if eventIdFile is not None:

            idDir = os.path.dirname(eventIdFile)
            if not os.path.isdir(idDir):
                os.makedirs(idDir)

            for collection in self._pluginCollections:
                self._eventIdData[collection.path] = collection.getState()

            for colPath, state in self._eventIdData.items():
                if state:
                    try:
                        fh = open(tmpEventIdFile, 'w')

                        # cleanup timestamp from data for it to be pickled
                        # self._eventIdData is a dict of dict of tuple of dict, hence the following mess
                        cleanData = copy.deepcopy(self._eventIdData)
                        for path, _dict in cleanData.iteritems():
                            for plugin, plugintuple in _dict.iteritems():
                                for item in plugintuple:
                                    if isinstance(item, dict):
                                        for k, v in item.iteritems():
                                            if isinstance(v, datetime.datetime):
                                                item[k] = normalizeSgDatetime(v)

                        pickle.dump(cleanData, fh)
                        fh.close()

                    except OSError, err:
                        self.log.error('Can not write event id data to %s.\n\n%s', tmpEventIdFile, traceback.format_exc(err))

                    else:
                        # file was properly pickled at the temporary location, now override the
                        # last state with this new one
                        os.rename(tmpEventIdFile, eventIdFile)

                    break
            else:
                self.log.warning('No state was found. Not saving to disk.')
                return

    def _checkConnectionAttempts(self, conn_attempts, msg):
        conn_attempts += 1
        if conn_attempts == self._max_conn_retries:
            self.log.error('Unable to connect to Shotgun (attempt %s of %s): %s', conn_attempts, self._max_conn_retries, msg)
            conn_attempts = 0
            time.sleep(self._conn_retry_sleep)
        else:
            self.log.warning('Unable to connect to Shotgun (attempt %s of %s): %s', conn_attempts, self._max_conn_retries, msg)
            time.sleep(self._conn_retry_microsleep)
        return conn_attempts

    def _runSingleEvent( self, eventId ) :
        # Setup the stdout logger
        handler = logging.StreamHandler()
        handler.setFormatter(logging.Formatter("%(levelname)s:%(name)s:%(message)s"))
        logging.getLogger().addHandler(handler)
        # Retrieve the event
        fields = ['id', 'event_type', 'attribute_name', 'meta', 'entity', 'user', 'project', 'session_uuid', 'created_at']
        result = self._sg.find_one("EventLogEntry", filters=[['id', 'is', eventId]], fields=fields )
        if not result :
            raise ValueError("Couldn't find event %d" % eventId)
        for collection in self._pluginCollections:
            collection.load()
        #Process the event
        self.log.info( "Treating event %d", result['id'])
        for collection in self._pluginCollections:
            collection.process( result, forceEvent=True )


class PluginCollection(object):
    """
    A group of plugin files in a location on the disk.
    """
    def __init__(self, engine, path, commonPath='', blacklist=[], whitelist=[]):
        if not os.path.isdir(path):
            raise ValueError('Invalid path: %s' % path)

        self._engine = engine
        self.path = path
        self._autoDiscover = True # Wether or not new plugins should automatically be discovered and loaded
        self._plugins = {}
        self._stateData = {}
        self.commonPath = commonPath
        self.blacklist = blacklist
        self.whitelist = whitelist

    def setState(self, state):
        if isinstance(state, int):
            for plugin in self:
                plugin.setState(state)
                self._stateData[plugin.getName()] = plugin.getState()
        else:
            self._stateData = state
            for plugin in self:
                pluginState = self._stateData.get(plugin.getName())
                if pluginState:
                    plugin.setState(pluginState)

    def getState(self):
        for plugin in self:
            self._stateData[plugin.getName()] = plugin.getState()
        return self._stateData

    def isActive(self):
        for plugin in self:
            if plugin.isActive():
                return True
        return False

    def getNextUnprocessedEventId(self):
        eId = None
        for plugin in self:
            if not plugin.isActive():
                continue

            newId = plugin.getNextUnprocessedEventId()
            if newId is not None and (eId is None or newId < eId):
                eId = newId
        return eId

    def getBacklogIds(self):
        backlogs = set()
        expired = set()
        for plugin in self:
            pBacklogs, pExpired = plugin.getBacklogIds()
            backlogs |= pBacklogs
            expired |= pExpired
        return backlogs, expired

    def getStats(self, maxTime=None, delete=False):
        return {plugin.getName(): plugin.getStats(maxTime=maxTime, delete=delete) for plugin in self}

    def process(self, event, forceEvent=False ):
        for plugin in self:
            if plugin.isActive():
                plugin.logger.debug("Checking event %d", event['id'])
                plugin.process(event, forceEvent)
            else:
                plugin.logger.debug('Skipping: inactive.')

    def getAndPurgeNewBacklog(self):
        newBacklogs = set()
        for plugin in self:
            newBacklogs |= plugin.getAndPurgeNewBacklog()
        return newBacklogs

    def load(self, configPath=None ):
        """
        Load plugins from disk.

        General behavior:
        - Loop on all paths.
        - Find all valid .py plugin files.
        - Loop on all plugin files.
        - For any new plugins, load them, otherwise, refresh them.
        """
        newPlugins = {}
        
        plugins = {}
        listOfPath = [os.path.join(self.path, p) for p in os.listdir(self.path)]
        if os.path.exists(self.commonPath):
            listOfPath = listOfPath + [os.path.join(self.commonPath,p) for p in os.listdir(self.commonPath)]
        for path in listOfPath:
            basename = os.path.basename(path)
            if basename in plugins:
                plugins[basename].append(os.path.dirname(path))
            else:
                plugins[basename] = [os.path.dirname(path)]
        
        for basename,paths in plugins.items():
            if not basename.endswith('.py') or basename.startswith('.'):
                continue 
            if basename[:-3] in self.blacklist:
                continue
            
            if len(paths) > 1 :
                if basename[:-3] in self.whitelist:
                    if os.path.exists(self.commonPath):
                        while self.commonPath in paths:
                            paths.remove(self.commonPath)
                        if paths:
                            newPlugins[basename] = Plugin(self._engine, os.path.join(paths[0], basename))
                    else:
                        newPlugins[basename] = Plugin(self._engine, os.path.join(paths[0], basename))
                else:
                    newPlugins[basename] = Plugin(self._engine, os.path.join(self.commonPath, basename))
            elif basename in self._plugins:
                newPlugins[basename] = self._plugins[basename]
            elif self._autoDiscover :
                newPlugins[basename] = Plugin(self._engine, os.path.join(paths[0], basename))
                
            if basename in newPlugins :
                newPlugins[basename].load()
        
        #TODO : report something when plugins are gone missing
        self._plugins = newPlugins

    def getPlugin( self, file, ensureExists=True ) :
        """
        Return the plugin from this collection.
        If ensureExists is True, ensure it is loaded in this collection.
        @param file : short name of the plugin to retrieve from this collection
        @type file : I{str}
        @param ensureExists : wether or not the plugin should be loaded if not already
        @rtype : L{Plugin} or None
        """
        if file not in self._plugins : # Plugin is not already loaded
            if ensureExists :
                self._plugins[file] = Plugin( self._engine, os.path.join( self.path, file))
                self._plugins[file].load()
            else :
                return None
        return self._plugins[file]

    def unloadPlugin( self, file ) :
        """
        Unload the given plugin
        @param file : short name of the plugin to unload from this collection
        """
        if file in self._plugins :
            self._plugins.pop( file )
    
    def __iter__(self):
        for basename in sorted(self._plugins.keys()):
            if basename in self._plugins : # handle the case where plugins were removed while looping
                yield self._plugins[basename]


class Plugin(object):
    """
    The plugin class represents a file on disk which contains one or more
    callbacks.
    """
    def __init__(self, engine, path):
        """
        @param engine: The engine that instanciated this plugin.
        @type engine: L{Engine}
        @param path: The path of the plugin file to load.
        @type path: I{str}

        @raise ValueError: If the path to the plugin is not a valid file.
        """
        self._engine = engine
        self._path = path
        self._configPath = _getConfigPath()
        if not os.path.isfile(path):
            raise ValueError('The path to the plugin is not a valid file - %s.' % path)

        self._pluginName = os.path.splitext(os.path.split(self._path)[1])[0]
        self._active = True
        self._callbacks = []
        self._mtime = None
        self._lastEventId = None
        self._backlog = {}
        self._newBacklog = set()
        self._eventStats = {}

        # Setup the plugin's logger
        self.logger = logging.getLogger('plugin.' + self.getName())
        self.logger.config = self._engine.config
        self._engine.setEmailsOnLogger(self.logger, True)
        self.logger.setLevel(self._engine.config.getLogLevel())
        if self._engine.config.getLogMode() == 1:
            _setFilePathOnLogger(self.logger, self._engine.config.getLogFile('plugin.' + self.getName()))

    def getName(self):
        return self._pluginName

    def getStats(self, maxTime=None, delete=False):
        callbacks = {}
        ignored = {}  # {reason: count}
        ignoreCount = 0
        backlogCount = 0
        total = 0

        if maxTime:
            minDate = datetime.datetime.now() - datetime.timedelta(seconds=maxTime)

        for eventId in self._eventStats.keys():
            eventStats = self._eventStats[eventId]
            if maxTime and eventStats['added_at'] < minDate:
                if delete:
                    del(self._eventStats[eventId])

            else:
                total += 1

                if eventStats.get('backlog'):
                    backlogCount += 1

                ignoreReason = eventStats.get('ignored')
                if ignoreReason:
                    ignored[ignoreReason] = ignored.get(ignoreReason, 0) + 1
                    ignoreCount += 1

                callbackStats = eventStats.get('callbacks')
                if callbackStats:
                    for c in callbackStats:
                        if c['callback'] not in callbacks:
                            callbacks[c['callback']] = {
                                'ignored': {},
                                'ignoreCount': 0,
                                'totalDispatch': 0,
                                'totalProcess': 0,
                                'handled': 0,
                                'averageDispatch': 0,
                                'averageProcess': 0,
                                'dispatchDeciles': [0 for i in range(0,11)],
                                'processDeciles': [0 for i in range(0,11)],
                                'dispatchList': [],
                                'processList': [],
                            }

                        cStats = callbacks[c['callback']]

                        ignoreReason = c.get('ignored')
                        if ignoreReason:
                            cStats['ignored'][ignoreReason] = cStats['ignored'].get(ignoreReason, 0) + 1
                            cStats['ignoreCount'] += 1

                        if c.get('handled', False):
                            cStats['handled'] += 1
                            cStats['dispatchList'].append(c['dispatch'])
                            cStats['processList'].append(c['process'])
                            cStats['totalDispatch'] += c['dispatch']
                            cStats['totalProcess'] += c['process']

        for c, cdict in callbacks.iteritems():
            if cdict['handled'] > 0:
                cdict['averageDispatch'] = cdict['totalDispatch']/cdict['handled']
                cdict['averageProcess'] = cdict['totalProcess']/cdict['handled']
                cdict['dispatchDeciles'] = deciles(cdict['dispatchList'])
                cdict['processDeciles'] = deciles(cdict['processList'])
                del(cdict['dispatchList'])
                del(cdict['processList'])

        stats = {
            'lastEventId': self._lastEventId,
            'active': self.isActive(),

            'total': total,
            'globalIgnoreCount': ignoreCount,
            'globalIgnored': ignored,
            'callbacks': callbacks,
            'remainingBacklogCount': len(self._backlog),
            'handledBacklogCount': backlogCount,
        }

        return stats

    def setState(self, state):
        if isinstance(state, int):
            self._lastEventId = state
        elif isinstance(state, tuple):
            self._lastEventId, self._backlog = state
        else:
            raise ValueError('Unknown state type: %s.' % type(state))

    def getState(self):
        return (self._lastEventId, self._backlog)

    def getNextUnprocessedEventId(self):
        if self._lastEventId:
            return self._lastEventId + 1
        else:
            return None

    def getBacklogIds(self):
        now = datetime.datetime.now()
        expired = set()
        for k in self._backlog.keys():
            v = self._backlog[k]
            if v < now:
                expired.add(k)
                del(self._backlog[k])

        return set(self._backlog.keys()), expired

    def isActive(self):
        """
        Is the current plugin active. Should it's callbacks be run?

        @return: True if this plugin's callbacks should be run, False otherwise.
        @rtype: I{bool}
        """
        return self._active

    def setEmails(self, *emails):
        """
        Set the email addresses to whom this plugin should send errors.

        @param emails: See L{LogFactory.getLogger}'s emails argument for info.
        @type emails: A I{list}/I{tuple} of email addresses or I{bool}.
        """
        self._engine.setEmailsOnLogger(self.logger, emails)

    def load(self ):
        """
        Load/Reload the plugin and all its callbacks.

        If a plugin has never been loaded it will be loaded normally. If the
        plugin has been loaded before it will be reloaded only if the file has
        been modified on disk. In this event callbacks will all be cleared and
        reloaded.

        General behavior:
        - Try to load the source of the plugin.
        - Try to find a function called registerCallbacks in the file.
        - Try to run the registration function.

        At every step along the way, if any error occurs the whole plugin will
        be deactivated and the function will return.
        """
        # Check file mtime
        mtime = os.path.getmtime(self._path)
        if self._mtime is None:
            self._engine.log.info('Loading plugin at %s' % self._path)
        elif self._mtime < mtime:
            self._engine.log.info('Reloading plugin at %s' % self._path)
        else:
            # The mtime of file is equal or older. We don't need to do anything.
            return

        # Reset values
        self._mtime = mtime
        self._callbacks = []
        self._active = True

        try:
            plugin = imp.load_source(self._pluginName, self._path)
        except:
            self._active = False
            self.logger.error('Could not load the plugin at %s.\n\n%s', self._path, traceback.format_exc())
            return

        regFunc = getattr(plugin, 'registerCallbacks', None)
        if callable(regFunc):
            try:
                regFunc(Registrar(self, configPath = self._configPath ))
            except:
                self._engine.log.critical('Error running register callback function from plugin at %s.\n\n%s', self._path, traceback.format_exc())
                self._active = False
        else:
            self._engine.log.critical('Did not find a registerCallbacks function in plugin at %s.', self._path)
            self._active = False

    def registerCallback(self, sgScriptName, sgScriptKey, callback, matchEvents=None, args=None, stopOnError=True):
        """
        Register a callback in the plugin.
        """
        global sg
        sgConnection = sg.Shotgun(self._engine.config.getShotgunURL(), sgScriptName, sgScriptKey)
        self._callbacks.append(Callback(callback, self, self._engine, sgConnection, matchEvents, args, stopOnError))

    def process(self, event, forceEvent=False):
        self.logger.debug( "Processing %s", event['id'] )

        if forceEvent : # Perform a raw process of the event
            self._process( event )
            return self._active

        # debug: print event with an absurdly large dispatch time
        # if (datetime.datetime.now()-normalizeSgDatetime(event['created_at'])).total_seconds() > 10000:
        #     print 'elapsed: %s' % (datetime.datetime.now()-normalizeSgDatetime(event['created_at'])).total_seconds()
        #     print 'on event: %s' % event
        #     print 'created_at: %s => %s' % (event['created_at'], normalizeSgDatetime(event['created_at']))
        #     print 'now: %s' % datetime.datetime.now()

        # Filtering event by projects
        if self._engine.enableProjectFiltering:
            if event['project'] is None:
                if not self._engine.treatNonProjectEvents:
                    self.logger.debug("Ignoring non project dependent event"
                                      " %s" % event['id'])
                    self._updateLastEventId(event['id'], event['created_at'])
                    self._getOrCreateEventStats(event)['ignored'] = 'non project dependent'
                    return self._active

            elif event['project']['name'] not in self._engine.projectsToFilter:
                self.logger.debug("Ignoring event %s from project"
                                  " %s" % (event['id'],
                                           event['project']['name']))
                self._updateLastEventId(event['id'], event['created_at'])
                self._getOrCreateEventStats(event)['ignored'] = 'non handled project %s' % event['project']['name']
                return self._active

        if event['id'] in self._backlog:
            if self._process(event, backlog=True):
                elapsedTime = datetime.datetime.now()-normalizeSgDatetime(event['created_at'])
                self.logger.info('Processed id %d from backlog - created %d seconds ago'
                                 % (event['id'], elapsedTime.total_seconds()))

                del(self._backlog[event['id']])
                self._updateLastEventId(event['id'], event['created_at'])

        elif self._lastEventId is not None and event['id'] <= self._lastEventId:
            msg = 'Event %d is too old. Last event processed was (%d).'
            self.logger.debug(msg, event['id'], self._lastEventId)
            self._getOrCreateEventStats(event)['ignored'] = 'too old'

        else:
            if self._process(event):
                self._updateLastEventId(event['id'], event['created_at'])

        return self._active

    def _process(self, event, backlog=False):
        for callback in self:
            if callback.isActive():
                now = datetime.datetime.now()
                if callback.canProcess(event):

                    processStartingTime = time.clock()
                    self.logger.debug('Dispatching event %d to callback %s.', event['id'], str(callback))

                    if not callback.process(event):
                        # A callback in the plugin failed. Deactivate the whole
                        # plugin.
                        self._active = False
                        break

                    # TODO hardcoded and ugly
                    # ignore version change viewed_by_current_user, as it sometimes takes days to showup of the events
                    if event.get('attribute_name') == 'viewed_by_current_user':
                        return self._active

                    processTime = time.clock()-processStartingTime
                    dispatchTime = (now-normalizeSgDatetime(event['created_at'])).total_seconds()
                    self.logger.debug('[Stats][%d][%s] total: ~%s s, handling: ~%s s, processing: %s s'
                                      % (event['id'], str(callback),
                                         dispatchTime + processTime,
                                         dispatchTime, processTime))
                    self._getOrCreateEventStats(event, backlog)['callbacks'].append({
                        'handled': True,
                        'callback': str(callback),
                        'dispatch': dispatchTime,
                        'process': processTime,
                    })

                else:
                    if event.get('attribute_name') == 'viewed_by_current_user':
                        return self._active

                    self._getOrCreateEventStats(event, backlog)['callbacks'].append({
                        'callback': str(callback),
                        'ignored': 'event type',
                    })

            else:
                self.logger.debug('Skipping inactive callback %s in plugin.', str(callback))

        return self._active

    def _getOrCreateEventStats(self, event, backlog=False):
        if event['id'] not in self._eventStats:
            self._eventStats[event['id']] = {
                'added_at': datetime.datetime.now(),
                'callbacks': [],
                # 'event': event,
                'backlog': backlog,
            }
        return self._eventStats[event['id']]

    def _updateLastEventId(self, eventId, eventCreationDate):
        if self._lastEventId is not None and eventId > self._lastEventId + 1:
            expiration = eventCreationDate + datetime.timedelta(seconds=self._engine.config.getBacklogTimeout())
            for skippedId in range(self._lastEventId + 1, eventId):
                self._newBacklog.add(skippedId)  # for futur logging
                self._backlog[skippedId] = expiration

        # sometimes the loop rollbacks (SG bug returning some unwanted stuff?)
        # force to never ever go back
        if self._lastEventId is None or eventId > self._lastEventId:
            self._lastEventId = eventId

    def getAndPurgeNewBacklog(self):
        newBacklogs = set(self._newBacklog)
        self._newBacklog = set()
        return newBacklogs

    def __iter__(self):
        """
        A plugin is iterable and will iterate over all its L{Callback} objects.
        """
        return self._callbacks.__iter__()

    def __str__(self):
        """
        Provide the name of the plugin when it is cast as string.

        @return: The name of the plugin.
        @rtype: I{str}
        """
        return self.getName()


class Registrar(object):
    """
    See public API docs in docs folder.
    """
    def __init__(self, plugin, configPath=None):
        """
        Wrap a plugin so it can be passed to a user.
        """
        self._plugin = plugin
        self._allowed = ['logger', 'setEmails', 'registerCallback']
        self._configPath = configPath # Give the plugin the opportunity to read values from the config file

    def getLogger(self):
        """
        Get the logger for this plugin.

        @return: The logger configured for this plugin.
        @rtype: L{logging.Logger}
        """
        # TODO: Fix this ugly protected member access
        return self.logger

    def getConfig( self ):
        """
        Return a config parser for this plugin
        @return: A config parser for this plugin or None
        @rtype: L{ConfigParser.ConfigParser}
        """
        if self._configPath :
            cfg = ConfigParser.ConfigParser()
            cfg.read( self._configPath)
            return cfg
        return None

    def getEngine( self ) :
        """
        Return the engine for this plugin
        @return : The engine for this plugin
        @rtype : L{Engine}
        """
        return self._plugin._engine
    def getName( self ) :
        """
        Return the name of this plugin
        @return: The name of this plugin
        @rtype: I{str}
        """
        return self._plugin.getName()
    
    def __getattr__(self, name):
        if name in self._allowed:
            return getattr(self._plugin, name)
        raise AttributeError("type object '%s' has no attribute '%s'" % (type(self).__name__, name))


class Callback(object):
    """
    A part of a plugin that can be called to process a Shotgun event.
    """

    def __init__(self, callback, plugin, engine, shotgun, matchEvents=None, args=None, stopOnError=True):
        """
        @param callback: The function to run when a Shotgun event occurs.
        @type callback: A function object.
        @param engine: The engine that will dispatch to this callback.
        @type engine: L{Engine}.
        @param shotgun: The Shotgun instance that will be used to communicate
            with your Shotgun server.
        @type shotgun: L{sg.Shotgun}
        @param logger: An object to log messages with.
        @type logger: I{logging.Logger}
        @param matchEvents: The event filter to match events against before invoking callback.
        @type matchEvents: dict
        @param args: Any datastructure you would like to be passed to your
            callback function. Defaults to None.
        @type args: Any object.

        @raise TypeError: If the callback is not a callable object.
        """
        if not callable(callback):
            raise TypeError('The callback must be a callable object (function, method or callable class instance).')

        self._name = None
        self._shotgun = shotgun
        self._callback = callback
        self._engine = engine
        self._logger = None
        self._matchEvents = matchEvents
        self._args = args
        self._stopOnError = stopOnError
        self._active = True

        # Find a name for this object
        if hasattr(callback, '__name__'):
            self._name = callback.__name__
        elif hasattr(callback, '__class__') and hasattr(callback, '__call__'):
            self._name = '%s_%s' % (callback.__class__.__name__, hex(id(callback)))
        else:
            raise ValueError('registerCallback should be called with a function or a callable object instance as callback argument.')

        # TODO: Get rid of this protected member access
        self._logger = logging.getLogger(plugin.logger.name + '.' + self._name)
        self._logger.config = self._engine.config

        self._fullname = plugin.logger.name + '.' + self._name

    def canProcess(self, event):
        if not self._matchEvents:
            return True

        if '*' in self._matchEvents:
            eventType = '*'
        else:
            eventType = event['event_type']
            if eventType not in self._matchEvents:
                self._logger.debug('Rejecting %s not in %s', eventType, self._matchEvents)
                return False

        attributes = self._matchEvents[eventType]

        if attributes is None or '*' in attributes:
            return True

        if event['attribute_name'] and event['attribute_name'] in attributes:
            return True
        self._logger.debug('Rejecting %s not in %s', event['attribute_name'], attributes )
        return False

    def process(self, event):
        """
        Process an event with the callback object supplied on initialization.

        If an error occurs, it will be logged appropriately and the callback
        will be deactivated.

        @param event: The Shotgun event to process.
        @type event: I{dict}
        """
        # set session_uuid for UI updates
        if self._engine._use_session_uuid:
            self._shotgun.set_session_uuid(event['session_uuid'])

        try:
            # retry until we got a none 503 error, or we exceed the max retry count
            try_count = 0
            while True:
                try_count += 1
                try:
                    self._callback(self._shotgun, self._logger, event, self._args)
                    break

                except sg.lib.xmlrpclib.ProtocolError, e:  # 503 error: shotgun is busy, pause & retry
                    if try_count < self._engine._max_conn_retries:
                        self._logger.warning('Unable to connect to Shotgun in callback %s (attempt %s of %s): %s', self._fullname, try_count, self._engine._max_conn_retries, str(e))
                        time.sleep(self._engine._conn_retry_microsleep)
                    else:
                        try_count = 0
                        self._logger.error('Unable to connect to Shotgun in callback %s (attempt %s of %s): %s', self._fullname, try_count, self._engine._max_conn_retries, str(e))
                        time.sleep(self._engine._conn_retry_sleep)

        except Exception as erro:
            # Get the local variables of the frame of our plugin
            tb = sys.exc_info()[2]
            stack = []
            while tb:
                stack.append(tb.tb_frame)
                tb = tb.tb_next

            msg = 'An error occured processing an event : \n%s\n\n%s\n\nLocal variables at outer most frame in plugin:\n\n%s'
            self._logger.critical(msg, str(erro), traceback.format_exc(), pprint.pformat(stack[1].f_locals))
            if self._stopOnError:
                self._active = False

        return self._active

    def isActive(self):
        """
        Check if this callback is active, i.e. if events should be passed to it
        for processing.

        @return: True if this callback should process events, False otherwise.
        @rtype: I{bool}
        """
        return self._active

    def __str__(self):
        """
        The name of the callback.

        @return: The name of the callback
        @rtype: I{str}
        """
        return self._name


class CustomSMTPHandler(logging.handlers.SMTPHandler):
    """
    A custom SMTPHandler subclass that will adapt it's subject depending on the
    error severity.
    """

    LEVEL_SUBJECTS = {
        logging.ERROR: 'ERROR - Shotgun event daemon.',
        logging.CRITICAL: 'CRITICAL - Shotgun event daemon.',
    }

    def __init__(self, smtpServer, fromAddr, toAddrs, emailSubject, credentials=None, secure=None, use_ssl=None):
        args = [smtpServer, fromAddr, toAddrs, emailSubject]
        if credentials:
            # Python 2.6 implemented the credentials argument
            if CURRENT_PYTHON_VERSION >= PYTHON_26:
                args.append(credentials)
            else:
                if isinstance(credentials, tuple):
                    self.username, self.password = credentials
                else:
                    self.username = None

            # Python 2.7 implemented the secure argument

            # Could be wrong here, but I think this is not used at all
            # emit is redefined and open its own connection
            # so the one opened up by the handler is simply ignored ? S.D.
            if CURRENT_PYTHON_VERSION >= PYTHON_27:
                args.append(secure)
            else:
                self.secure = secure
            if use_ssl :
                self.use_ssl = True
            else :
                self.use_ssl = None 
        logging.handlers.SMTPHandler.__init__(self, *args)

    def getSubject(self, record):
        subject = logging.handlers.SMTPHandler.getSubject(self, record)

        hostname = socket.gethostname()
        if hostname:
            subject += '[%s]' % hostname

        if record.levelno in self.LEVEL_SUBJECTS:
            return subject + ' ' + self.LEVEL_SUBJECTS[record.levelno]

        return subject

    def emit(self, record):
        """
        Emit a record.

        Format the record and send it to the specified addressees.
        """
        # If the socket timeout isn't None, in Python 2.4 the socket read
        # following enabling starttls() will hang. The default timeout will
        # be reset to 60 later in 2 locations because Python 2.4 doesn't support
        # except and finally in the same try block.
        if CURRENT_PYTHON_VERSION >= PYTHON_25:
            socket.setdefaulttimeout(None)

        # Mostly copied from Python 2.7 implementation.
        # Using email.Utils instead of email.utils for 2.4 compat.
        try:
            import smtplib
            from email.Utils import formatdate
            port = self.mailport
            if not port:
                port = smtplib.SMTP_PORT
            if self.use_ssl is not None :
                smtp = smtplib.SMTP_SSL(self.mailhost, port)
                smtp.ehlo()
            else :
                smtp = smtplib.SMTP(self.mailhost, port)
            msg = self.format(record)
            msg = "From: %s\r\nTo: %s\r\nSubject: %s\r\nDate: %s\r\n\r\n%s" % (
                            self.fromaddr,
                            ",".join(self.toaddrs),
                            self.getSubject(record),
                            formatdate(), msg)
            if self.username:
                if self.secure is not None and self.use_ssl is None :
                    smtp.ehlo()
                    smtp.starttls(*self.secure)
                    smtp.ehlo()
                smtp.login(self.username, self.password)
            smtp.sendmail(self.fromaddr, self.toaddrs, msg)
            smtp.close()
        except (KeyboardInterrupt, SystemExit):
            socket.setdefaulttimeout(60)
            raise
        except:
            self.handleError(record)

        socket.setdefaulttimeout(60)


class EventDaemonError(Exception):
    """
    Base error for the Shotgun event system.
    """
    pass


class ConfigError(EventDaemonError):
    """
    Used when an error is detected in the config file.
    """
    pass

def percentile(l, percent):
    if not l:
        return None
    k = (len(l)-1)*percent
    f = math.floor(k)
    c = math.ceil(k)
    if f == c:
        return l[int(k)]
    return l[int(f)] * (c-k) + l[int(c)] * (k-f)

def deciles(l):
    l.sort()
    return [percentile(l, i*0.1) for i in range(11)]

def normalizeSgDatetime(datetime):
    if datetime.tzinfo is None:  # already normalized
        return datetime

    norm = datetime.astimezone(sg.sg_timezone.local)
    norm = norm.replace(tzinfo=None)
    return norm

if sys.platform == 'win32':
    class WindowsService(win32serviceutil.ServiceFramework):
        """
        Windows service wrapper
        """
        _svc_name_ = "ShotgunEventDaemon"
        _svc_display_name_ = "Shotgun Event Handler"

        def __init__(self, args):
            win32serviceutil.ServiceFramework.__init__(self, args)
            self.hWaitStop = win32event.CreateEvent(None, 0, 0, None)
            self._engine = Engine(_getConfigPath())

        def SvcStop(self):
            """
            Stop the Windows service.
            """
            self.ReportServiceStatus(win32service.SERVICE_STOP_PENDING)
            win32event.SetEvent(self.hWaitStop)
            self._engine.stop()

        def SvcDoRun(self):
            """
            Start the Windows service.
            """
            servicemanager.LogMsg(
                servicemanager.EVENTLOG_INFORMATION_TYPE,
                servicemanager.PYS_SERVICE_STARTED,
                (self._svc_name_, '')
            )
            self.main()

        def main(self):
            """
            Primary Windows entry point
            """
            self._engine.start()


class LinuxDaemon(daemonizer.Daemon):
    """
    Linux Daemon wrapper or wrapper used for foreground operation on Windows
    """
    def __init__(self):
        self._engine = Engine(_getConfigPath())
        super(LinuxDaemon, self).__init__('shotgunEvent', self._engine.config.getEnginePIDFile())

    def start(self, daemonize=True):
        if not daemonize:
            # Setup the stdout logger
            handler = logging.StreamHandler()
            handler.setFormatter(logging.Formatter("%(levelname)s:%(name)s:%(message)s"))
            logging.getLogger().addHandler(handler)

        super(LinuxDaemon, self).start(daemonize)

    def _run(self):
        """
        Start the engine's main loop
        """
        self._engine.start()

    def _cleanup(self):
        self._engine.stop()


def main():
    """
    Main entry
    """
    usage = "Usage: %prog [options] action\n"
    usage += "Actions:\n"
    usage += "\tstart                         start the event loop (daemon)\n"
    usage += "\tstop                          stop the event loop (daemon)\n"
    usage += "\tforeground                    start the event loop in foreground\n"
    usage += "\tforceEvents eventId [eventId] Force a list of events\n"
    usage += "Options:\n"
    usage += "\t-c --configDirectory          Custom directory to load config file from\n"

    parser = OptionParser(usage=usage)
    parser.add_option("-c", "--configDirectory",
                      metavar='CONFIGDIR',
                      type='string',
                      help='Custom directory to load config file from')

    (options, args) = parser.parse_args()

    if len(args) < 1:
        parser.print_usage()
        return -1

    action = args[0]

    # This solution is not perfect as in _getConfigPath the script path
    # might be added in first position in the list if directories to look at
    # Therefore, if there is a config file within the directory of the script,
    # it will be used.
    if options.configDirectory is not None:
        CONFIG_DIRECTORIES[:0] = [options.configDirectory]

    if action not in ACTIONS:
        parser.print_usage()
        return -2

    # Windows platform
    #
    if sys.platform == 'win32':
        if action not in ['foreground', 'forceEvents']:
            win32serviceutil.HandleCommandLine(WindowsService)
            return 0
        else:
            print("Action %s is not supported on windows." % action)
            return -6

    # Unix-like platform
    #
    daemon = LinuxDaemon()
    if action == 'forceEvents':
        if len(args) < 2:
            print("At least one event id should be passed.\n")
            parser.print_usage()
            return -3

        eventIds = []
        # Check eventIds validity
        for eventId in args[1:]:
            try:
                eventId = int(eventId)
            except ValueError:
                print("EventId %s is not valid. Aborting.\n" % eventId)
                parser.print_usage()
                return -4
            eventIds.append(eventId)
        # Process them
        for eventId in eventIds:
            daemon._engine._runSingleEvent(eventId)
        return 0
    else:
        if len(args) > 1:
            print("Only one command should be passed.\n")
            parser.print_usage()
            return -5

    # Find the function to call on the daemon and call it
    func = getattr(daemon, action, None)
    if func is not None:
        func()
        return 0

def _getConfigPath():
    """
    Get the path of the shotgunEventDaemon configuration file.
    """
    paths = CONFIG_DIRECTORIES

    # Get the current path of the daemon script
    scriptPath = sys.argv[0]
    if scriptPath != '' and scriptPath != '-c':
        # Make absolute path and eliminate any symlinks if any.
        scriptPath = os.path.abspath(scriptPath)
        scriptPath = os.path.realpath(scriptPath)

        # Add the script's directory to the paths we'll search for the config.
        paths[:0] = [os.path.dirname(scriptPath)]

    # Search for a config file.
    for path in paths:
        path = os.path.join(path, 'shotgunEventDaemon.conf')
        if os.path.exists(path):
            return path

    # No config file was found
    raise EventDaemonError('Config path not found, searched %s' % ', '.join(paths))


if __name__ == '__main__':
    sys.exit(main())
