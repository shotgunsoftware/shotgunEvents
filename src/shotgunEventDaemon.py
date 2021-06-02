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

from __future__ import print_function

__version__ = "1.0"
__version_info__ = (1, 0)

# Suppress the deprecation warning about imp until we get around to replacing it
import warnings

with warnings.catch_warnings():
    warnings.filterwarnings("ignore", category=DeprecationWarning)
    import imp

import datetime
import logging
import logging.handlers
import os
import pprint
import re
import socket
import sys
import time
import traceback
from six.moves import configparser
import six.moves.cPickle as pickle

from distutils.version import StrictVersion

if sys.platform == "win32":
    import win32serviceutil
    import win32service
    import win32event
    import servicemanager

import daemonizer
import shotgun_api3 as sg
from shotgun_api3.lib.sgtimezone import SgTimezone

try:
    import sentry_sdk
except ImportError:
    sentry_sdk = None


SG_TIMEZONE = SgTimezone()
CURRENT_PYTHON_VERSION = StrictVersion(sys.version.split()[0])
PYTHON_26 = StrictVersion("2.6")
PYTHON_27 = StrictVersion("2.7")

EMAIL_FORMAT_STRING = """Time: %(asctime)s
Logger: %(name)s
Path: %(pathname)s
Function: %(funcName)s
Line: %(lineno)d

%(message)s"""


def _setFilePathOnLogger(logger, path):
    # Remove any previous handler.
    _removeHandlersFromLogger(logger, logging.handlers.TimedRotatingFileHandler)

    # Add the file handler
    handler = logging.handlers.TimedRotatingFileHandler(
        path, "midnight", backupCount=10
    )
    handler.setFormatter(
        logging.Formatter("%(asctime)s - %(name)s - %(levelname)s - %(message)s")
    )
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


def _addMailHandlerToLogger(
    logger,
    smtpServer,
    fromAddr,
    toAddrs,
    emailSubject,
    username=None,
    password=None,
    secure=None,
):
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
        mailHandler = CustomSMTPHandler(
            smtpServer, fromAddr, toAddrs, emailSubject, (username, password), secure
        )
        mailHandler.setLevel(logging.ERROR)
        mailFormatter = logging.Formatter(EMAIL_FORMAT_STRING)
        mailHandler.setFormatter(mailFormatter)

        logger.addHandler(mailHandler)

def _sentry_pre_send(event, hint):
    if 'level' in event['extra']:
        event['level'] = event['extra']['level']
        del(event['extra']['level'])

    sentry_tags = ['plugin_name', 'stop_on_error', 'event_id']
    for _sentry_tag in sentry_tags:
        if _sentry_tag in event['extra']:
            if 'tags' not in event:
                event['tags'] = {}
            event['tags'][_sentry_tag] = event['extra'][_sentry_tag]
            del(event['extra'][_sentry_tag])

    return event


class Config(configparser.SafeConfigParser):
    def __init__(self, path):
        configparser.SafeConfigParser.__init__(self, os.environ)
        self.read(path)

    def getShotgunURL(self):
        return self.get("shotgun", "server")

    def getEngineScriptName(self):
        return self.get("shotgun", "name")

    def getEngineScriptKey(self):
        return self.get("shotgun", "key")

    def getEngineProxyServer(self):
        try:
            proxy_server = self.get("shotgun", "proxy_server").strip()
            if not proxy_server:
                return None
            return proxy_server
        except configparser.NoOptionError:
            return None

    def getEventIdFile(self):
        return self.get("daemon", "eventIdFile")

    def getEnginePIDFile(self):
        return self.get("daemon", "pidFile")

    def getPluginPaths(self):
        return [s.strip() for s in self.get("plugins", "paths").split(",")]

    def getSMTPServer(self):
        return self.get("emails", "server")

    def getSMTPPort(self):
        if self.has_option("emails", "port"):
            return self.getint("emails", "port")
        return 25

    def getFromAddr(self):
        return self.get("emails", "from")

    def getToAddrs(self):
        return [s.strip() for s in self.get("emails", "to").split(",")]

    def getEmailSubject(self):
        return self.get("emails", "subject")

    def getEmailUsername(self):
        if self.has_option("emails", "username"):
            return self.get("emails", "username")
        return None

    def getEmailPassword(self):
        if self.has_option("emails", "password"):
            return self.get("emails", "password")
        return None

    def getSecureSMTP(self):
        if self.has_option("emails", "useTLS"):
            return self.getboolean("emails", "useTLS") or False
        return False

    def getLogMode(self):
        return self.getint("daemon", "logMode")

    def getLogLevel(self):
        return self.getint("daemon", "logging")

    def getMaxEventBatchSize(self):
        if self.has_option("daemon", "max_event_batch_size"):
            return self.getint("daemon", "max_event_batch_size")
        return 500

    def getLogFile(self, filename=None):
        if filename is None:
            if self.has_option("daemon", "logFile"):
                filename = self.get("daemon", "logFile")
            else:
                raise ConfigError("The config file has no logFile option.")

        if self.has_option("daemon", "logPath"):
            path = self.get("daemon", "logPath")

            if not os.path.exists(path):
                os.makedirs(path)
            elif not os.path.isdir(path):
                raise ConfigError(
                    "The logPath value in the config should point to a directory."
                )

            path = os.path.join(path, filename)

        else:
            path = filename

        return path

    def getTimingLogFile(self):
        if (
            not self.has_option("daemon", "timing_log")
            or self.get("daemon", "timing_log") != "on"
        ):
            return None

        return self.getLogFile() + ".timing"

    def getSentryDsn(self):
        if self.has_option('sentry', 'sentry_dsn') and self.get('sentry', 'sentry_dsn'):
            return self.get('sentry', 'sentry_dsn')
        else:
            return None

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

        self.set_sentry_notification()

        # Get config values
        self._pluginCollections = [
            PluginCollection(self, s) for s in self.config.getPluginPaths()
        ]
        self._sg = sg.Shotgun(
            self.config.getShotgunURL(),
            self.config.getEngineScriptName(),
            self.config.getEngineScriptKey(),
            http_proxy=self.config.getEngineProxyServer(),
        )
        self._max_conn_retries = self.config.getint("daemon", "max_conn_retries")
        self._conn_retry_sleep = self.config.getint("daemon", "conn_retry_sleep")
        self._fetch_interval = self.config.getint("daemon", "fetch_interval")
        self._use_session_uuid = self.config.getboolean("shotgun", "use_session_uuid")

        # Setup the loggers for the main engine
        if self.config.getLogMode() == 0:
            # Set the root logger for file output.
            rootLogger = logging.getLogger()
            rootLogger.config = self.config
            _setFilePathOnLogger(rootLogger, self.config.getLogFile())
            print(self.config.getLogFile())

            # Set the engine logger for email output.
            self.log = logging.getLogger("engine")
            self.setEmailsOnLogger(self.log, True)
        else:
            # Set the engine logger for file and email output.
            self.log = logging.getLogger("engine")
            self.log.config = self.config
            _setFilePathOnLogger(self.log, self.config.getLogFile())
            self.setEmailsOnLogger(self.log, True)

        self.log.setLevel(self.config.getLogLevel())

        # Setup the timing log file
        timing_log_filename = self.config.getTimingLogFile()
        if timing_log_filename:
            self.timing_logger = logging.getLogger("timing")
            self.timing_logger.setLevel(self.config.getLogLevel())
            _setFilePathOnLogger(self.timing_logger, timing_log_filename)
        else:
            self.timing_logger = None

        super(Engine, self).__init__()

    def setEmailsOnLogger(self, logger, emails):
        # Configure the logger for email output
        _removeHandlersFromLogger(logger, logging.handlers.SMTPHandler)

        if emails is False:
            return

        smtpServer = self.config.getSMTPServer()
        smtpPort = self.config.getSMTPPort()
        fromAddr = self.config.getFromAddr()
        emailSubject = self.config.getEmailSubject()
        username = self.config.getEmailUsername()
        password = self.config.getEmailPassword()
        if self.config.getSecureSMTP():
            secure = (None, None)
        else:
            secure = None

        if emails is True:
            toAddrs = self.config.getToAddrs()
        elif isinstance(emails, (list, tuple)):
            toAddrs = emails
        else:
            msg = "Argument emails should be True to use the default addresses, False to not send any emails or a list of recipient addresses. Got %s."
            raise ValueError(msg % type(emails))

        _addMailHandlerToLogger(
            logger,
            (smtpServer, smtpPort),
            fromAddr,
            toAddrs,
            emailSubject,
            username,
            password,
            secure,
        )

    def set_sentry_notification(self):
        sentry_dsn = self.config.getSentryDsn()
        if sentry_dsn:
            sentry_sdk.init(dsn=sentry_dsn, ignore_errors=[KeyboardInterrupt], before_send=_sentry_pre_send)
            with sentry_sdk.configure_scope() as scope:
                shotgun_account_name = re.match('.*://(.*).shotgunstudio.com', self.config.getShotgunURL()).group(1)
                scope.set_tag("shotgun_account", shotgun_account_name)
                scope.level = 'fatal'

    def start(self):
        """
        Start the processing of events.

        The last processed id is loaded up from persistent storage on disk and
        the main loop is started.
        """
        # TODO: Take value from config
        socket.setdefaulttimeout(60)

        # Notify which version of shotgun api we are using
        self.log.info("Using SG Python API version %s" % sg.__version__)

        try:
            for collection in self._pluginCollections:
                collection.load()

            self._loadEventIdData()

            self._mainLoop()
        except KeyboardInterrupt:
            self.log.warning("Keyboard interrupt. Cleaning up...")
        except Exception as err:
            msg = "Crash!!!!! Unexpected error (%s) in main loop.\n\n%s"
            self.log.critical(msg, type(err), traceback.format_exc(err))

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
                fh = open(eventIdFile, "rb")
                try:
                    self._eventIdData = pickle.load(fh)

                    # Provide event id info to the plugin collections. Once
                    # they've figured out what to do with it, ask them for their
                    # last processed id.
                    noStateCollections = []
                    for collection in self._pluginCollections:
                        state = self._eventIdData.get(collection.path)
                        if state:
                            collection.setState(state)
                        else:
                            noStateCollections.append(collection)

                    # If we don't have a state it means there's no match
                    # in the id file. First we'll search to see the latest id a
                    # matching plugin name has elsewhere in the id file. We do
                    # this as a fallback in case the plugins directory has been
                    # moved. If there's no match, use the latest event id
                    # in Shotgun.
                    if noStateCollections:
                        maxPluginStates = {}
                        for collection in self._eventIdData.values():
                            for pluginName, pluginState in collection.items():
                                if pluginName in maxPluginStates.keys():
                                    if pluginState[0] > maxPluginStates[pluginName][0]:
                                        maxPluginStates[pluginName] = pluginState
                                else:
                                    maxPluginStates[pluginName] = pluginState

                        lastEventId = self._getLastEventIdFromDatabase()
                        for collection in noStateCollections:
                            state = collection.getState()
                            for pluginName in state.keys():
                                if pluginName in maxPluginStates.keys():
                                    state[pluginName] = maxPluginStates[pluginName]
                                else:
                                    state[pluginName] = lastEventId
                            collection.setState(state)

                except pickle.UnpicklingError:
                    fh.close()

                    # Backwards compatibility:
                    # Reopen the file to try to read an old-style int
                    fh = open(eventIdFile, "rb")
                    line = fh.readline().strip()
                    if line.isdigit():
                        # The _loadEventIdData got an old-style id file containing a single
                        # int which is the last id properly processed.
                        lastEventId = int(line)
                        self.log.debug(
                            "Read last event id (%d) from file.", lastEventId
                        )
                        for collection in self._pluginCollections:
                            collection.setState(lastEventId)
                fh.close()
            except OSError as err:
                raise EventDaemonError(
                    "Could not load event id from file.\n\n%s"
                    % traceback.format_exc(err)
                )
        else:
            # No id file?
            # Get the event data from the database.
            lastEventId = self._getLastEventIdFromDatabase()
            if lastEventId:
                for collection in self._pluginCollections:
                    collection.setState(lastEventId)

            self._saveEventIdData()

    def _getLastEventIdFromDatabase(self):

        conn_attempts = 0
        lastEventId = None
        while lastEventId is None:
            order = [{"column": "id", "direction": "desc"}]
            try:
                result = self._sg.find_one(
                    "EventLogEntry", filters=[], fields=["id"], order=order
                )
            except (sg.ProtocolError, sg.ResponseError, socket.error) as err:
                conn_attempts = self._checkConnectionAttempts(conn_attempts, str(err))
            except Exception as err:
                msg = "Unknown error: %s" % str(err)
                conn_attempts = self._checkConnectionAttempts(conn_attempts, msg)
            else:
                lastEventId = result["id"]
                self.log.info("Last event id (%d) from the SG database.", lastEventId)

        return lastEventId

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
        self.log.debug("Starting the event processing loop.")
        while self._continue:
            # Process events
            events = self._getNewEvents()
            for event in events:
                for collection in self._pluginCollections:
                    collection.process(event)
                self._saveEventIdData()

            # if we're lagging behind Shotgun, we received a full batch of events
            # skip the sleep() call in this case
            if len(events) < self.config.getMaxEventBatchSize():
                time.sleep(self._fetch_interval)

            # Reload plugins
            for collection in self._pluginCollections:
                collection.load()

            # Make sure that newly loaded events have proper state.
            self._loadEventIdData()

        self.log.debug("Shuting down event processing loop.")

    def stop(self):
        self._continue = False

    def _getNewEvents(self):
        """
        Fetch new events from Shotgun.

        @return: Recent events that need to be processed by the engine.
        @rtype: I{list} of Shotgun event dictionaries.
        """
        nextEventId = None
        for newId in [
            coll.getNextUnprocessedEventId() for coll in self._pluginCollections
        ]:
            if newId is not None and (nextEventId is None or newId < nextEventId):
                nextEventId = newId

        if nextEventId is not None:
            filters = [["id", "greater_than", nextEventId - 1]]
            fields = [
                "id",
                "event_type",
                "attribute_name",
                "meta",
                "entity",
                "user",
                "project",
                "session_uuid",
                "created_at",
            ]
            order = [{"column": "id", "direction": "asc"}]

            conn_attempts = 0
            while True:
                try:
                    events = self._sg.find(
                        "EventLogEntry",
                        filters,
                        fields,
                        order,
                        limit=self.config.getMaxEventBatchSize(),
                    )
                    if events:
                        self.log.debug(
                            "Got %d events: %d to %d.",
                            len(events),
                            events[0]["id"],
                            events[-1]["id"],
                        )
                    return events
                except (sg.ProtocolError, sg.ResponseError, socket.error) as err:
                    conn_attempts = self._checkConnectionAttempts(
                        conn_attempts, str(err)
                    )
                except Exception as err:
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

        if eventIdFile is not None:
            for collection in self._pluginCollections:
                self._eventIdData[collection.path] = collection.getState()

            for colPath, state in self._eventIdData.items():
                if state:
                    try:
                        with open(eventIdFile, "wb") as fh:
                            # Use protocol 2 so it can also be loaded in Python 2
                            pickle.dump(self._eventIdData, fh, protocol=2)
                    except OSError as err:
                        self.log.error(
                            "Can not write event id data to %s.\n\n%s",
                            eventIdFile,
                            traceback.format_exc(err),
                        )
                    break
            else:
                self.log.warning("No state was found. Not saving to disk.")

    def _checkConnectionAttempts(self, conn_attempts, msg):
        conn_attempts += 1
        if conn_attempts == self._max_conn_retries:
            self.log.error(
                "Unable to connect to SG (attempt %s of %s): %s",
                conn_attempts,
                self._max_conn_retries,
                msg,
            )
            conn_attempts = 0
            time.sleep(self._conn_retry_sleep)
        else:
            self.log.warning(
                "Unable to connect to SG (attempt %s of %s): %s",
                conn_attempts,
                self._max_conn_retries,
                msg,
            )
        return conn_attempts


class PluginCollection(object):
    """
    A group of plugin files in a location on the disk.
    """

    def __init__(self, engine, path):
        if not os.path.isdir(path):
            raise ValueError("Invalid path: %s" % path)

        self._engine = engine
        self.path = path
        self._plugins = {}
        self._stateData = {}

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

    def getNextUnprocessedEventId(self):
        eId = None
        for plugin in self:
            if not plugin.isActive():
                continue

            newId = plugin.getNextUnprocessedEventId()
            if newId is not None and (eId is None or newId < eId):
                eId = newId
        return eId

    def process(self, event):
        for plugin in self:
            if plugin.isActive():
                plugin.process(event)
            else:
                plugin.logger.debug("Skipping: inactive.")

    def load(self):
        """
        Load plugins from disk.

        General behavior:
        - Loop on all paths.
        - Find all valid .py plugin files.
        - Loop on all plugin files.
        - For any new plugins, load them, otherwise, refresh them.
        """
        newPlugins = {}

        for basename in os.listdir(self.path):
            if not basename.endswith(".py") or basename.startswith("."):
                continue

            if basename in self._plugins:
                newPlugins[basename] = self._plugins[basename]
            else:
                newPlugins[basename] = Plugin(
                    self._engine, os.path.join(self.path, basename)
                )

            newPlugins[basename].load()

        self._plugins = newPlugins

    def __iter__(self):
        for basename in sorted(self._plugins.keys()):
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

        if not os.path.isfile(path):
            raise ValueError("The path to the plugin is not a valid file - %s." % path)

        self._pluginName = os.path.splitext(os.path.split(self._path)[1])[0]
        self._active = True
        self._callbacks = []
        self._mtime = None
        self._lastEventId = None
        self._backlog = {}

        # Setup the plugin's logger
        self.logger = logging.getLogger("plugin." + self.getName())
        self.logger.config = self._engine.config
        self._engine.setEmailsOnLogger(self.logger, True)
        self.logger.setLevel(self._engine.config.getLogLevel())
        if self._engine.config.getLogMode() == 1:
            _setFilePathOnLogger(
                self.logger, self._engine.config.getLogFile("plugin." + self.getName())
            )

    def getName(self):
        return self._pluginName

    def setState(self, state):
        if isinstance(state, int):
            self._lastEventId = state
        elif isinstance(state, tuple):
            self._lastEventId, self._backlog = state
        else:
            raise ValueError("Unknown state type: %s." % type(state))

    def getState(self):
        return (self._lastEventId, self._backlog)

    def getNextUnprocessedEventId(self):
        if self._lastEventId:
            nextId = self._lastEventId + 1
        else:
            nextId = None

        now = datetime.datetime.now()
        for k in list(self._backlog):
            v = self._backlog[k]
            if v < now:
                self.logger.warning("Timeout elapsed on backlog event id %d.", k)
                del self._backlog[k]
            elif nextId is None or k < nextId:
                nextId = k

        return nextId

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

    def load(self):
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
            self._engine.log.info("Loading plugin at %s" % self._path)
        elif self._mtime < mtime:
            self._engine.log.info("Reloading plugin at %s" % self._path)
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
            self.logger.error(
                "Could not load the plugin at %s.\n\n%s",
                self._path,
                traceback.format_exc(),
            )
            return

        regFunc = getattr(plugin, "registerCallbacks", None)
        if callable(regFunc):
            try:
                regFunc(Registrar(self))
            except:
                self._engine.log.critical(
                    "Error running register callback function from plugin at %s.\n\n%s",
                    self._path,
                    traceback.format_exc(),
                )
                self._active = False
        else:
            self._engine.log.critical(
                "Did not find a registerCallbacks function in plugin at %s.", self._path
            )
            self._active = False

    def registerCallback(
        self,
        sgScriptName,
        sgScriptKey,
        callback,
        matchEvents=None,
        args=None,
        stopOnError=True,
    ):
        """
        Register a callback in the plugin.
        """
        global sg
        sgConnection = sg.Shotgun(
            self._engine.config.getShotgunURL(),
            sgScriptName,
            sgScriptKey,
            http_proxy=self._engine.config.getEngineProxyServer(),
        )
        self._callbacks.append(
            Callback(
                callback,
                self,
                self._engine,
                sgConnection,
                matchEvents,
                args,
                stopOnError,
            )
        )

    def process(self, event):
        if event["id"] in self._backlog:
            if self._process(event):
                self.logger.info("Processed id %d from backlog." % event["id"])
                del self._backlog[event["id"]]
                self._updateLastEventId(event)
        elif self._lastEventId is not None and event["id"] <= self._lastEventId:
            msg = "Event %d is too old. Last event processed was (%d)."
            self.logger.debug(msg, event["id"], self._lastEventId)
        else:
            if self._process(event):
                self._updateLastEventId(event)

        return self._active

    def _process(self, event):
        for callback in self:
            if callback.isActive():
                if callback.canProcess(event):
                    msg = "Dispatching event %d to callback %s."
                    self.logger.debug(msg, event["id"], str(callback))
                    if not callback.process(event):
                        # A callback in the plugin failed. Deactivate the whole
                        # plugin.
                        self._active = False
                        break
            else:
                msg = "Skipping inactive callback %s in plugin."
                self.logger.debug(msg, str(callback))

        return self._active

    def _updateLastEventId(self, event):
        BACKLOG_TIMEOUT = (
            5  # time in minutes after which we consider a pending event won't happen
        )
        if self._lastEventId is not None and event["id"] > self._lastEventId + 1:
            event_date = event["created_at"].replace(tzinfo=None)
            if datetime.datetime.now() > (
                event_date + datetime.timedelta(minutes=BACKLOG_TIMEOUT)
            ):
                # the event we've just processed happened more than BACKLOG_TIMEOUT minutes ago so any event
                # with a lower id should have shown up in the EventLog by now if it actually happened
                if event["id"] == self._lastEventId + 2:
                    self.logger.info(
                        "Event %d never happened - ignoring.", self._lastEventId + 1
                    )
                else:
                    self.logger.info(
                        "Events %d-%d never happened - ignoring.",
                        self._lastEventId + 1,
                        event["id"] - 1,
                    )
            else:
                # in this case, we want to add the missing events to the backlog as they could show up in the
                # EventLog within BACKLOG_TIMEOUT minutes, during which we'll keep asking for the same range
                # them to show up until they expire
                expiration = datetime.datetime.now() + datetime.timedelta(
                    minutes=BACKLOG_TIMEOUT
                )
                for skippedId in range(self._lastEventId + 1, event["id"]):
                    self.logger.info("Adding event id %d to backlog.", skippedId)
                    self._backlog[skippedId] = expiration
        self._lastEventId = event["id"]

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

    def __init__(self, plugin):
        """
        Wrap a plugin so it can be passed to a user.
        """
        self._plugin = plugin
        self._allowed = ["logger", "setEmails", "registerCallback"]

    def getLogger(self):
        """
        Get the logger for this plugin.

        @return: The logger configured for this plugin.
        @rtype: L{logging.Logger}
        """
        # TODO: Fix this ugly protected member access
        return self.logger

    def __getattr__(self, name):
        if name in self._allowed:
            return getattr(self._plugin, name)
        raise AttributeError(
            "type object '%s' has no attribute '%s'" % (type(self).__name__, name)
        )


class Callback(object):
    """
    A part of a plugin that can be called to process a Shotgun event.
    """

    def __init__(
        self,
        callback,
        plugin,
        engine,
        shotgun,
        matchEvents=None,
        args=None,
        stopOnError=True,
    ):
        """
        @param callback: The function to run when a Shotgun event occurs.
        @type callback: A function object.
        @param engine: The engine that will dispatch to this callback.
        @type engine: L{Engine}.
        @param shotgun: The Shotgun instance that will be used to communicate
            with your Shotgun server.
        @type shotgun: L{sg.Shotgun}
        @param matchEvents: The event filter to match events against before invoking callback.
        @type matchEvents: dict
        @param args: Any datastructure you would like to be passed to your
            callback function. Defaults to None.
        @type args: Any object.

        @raise TypeError: If the callback is not a callable object.
        """
        if not callable(callback):
            raise TypeError(
                "The callback must be a callable object (function, method or callable class instance)."
            )

        self._name = None
        self._shotgun = shotgun
        self._plugin = plugin
        self._callback = callback
        self._engine = engine
        self._logger = None
        self._matchEvents = matchEvents
        self._args = args
        self._stopOnError = stopOnError
        self._active = True

        # Find a name for this object
        if hasattr(callback, "__name__"):
            self._name = callback.__name__
        elif hasattr(callback, "__class__") and hasattr(callback, "__call__"):
            self._name = "%s_%s" % (callback.__class__.__name__, hex(id(callback)))
        else:
            raise ValueError(
                "registerCallback should be called with a function or a callable object instance as callback argument."
            )

        # TODO: Get rid of this protected member access
        self._logger = logging.getLogger(plugin.logger.name + "." + self._name)
        self._logger.config = self._engine.config

    def canProcess(self, event):
        if not self._matchEvents:
            return True

        if "*" in self._matchEvents:
            eventType = "*"
        else:
            eventType = event["event_type"]
            if eventType not in self._matchEvents:
                return False

        attributes = self._matchEvents[eventType]

        if attributes is None or "*" in attributes:
            return True

        if event["attribute_name"] and event["attribute_name"] in attributes:
            return True

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
            self._shotgun.set_session_uuid(event["session_uuid"])

        if self._engine.timing_logger:
            start_time = datetime.datetime.now(SG_TIMEZONE.local)

        try:
            self._callback(self._shotgun, self._logger, event, self._args)
            error = False
        except:
            error = True

            # Get the local variables of the frame of our plugin
            tb = sys.exc_info()[2]
            stack = []
            while tb:
                stack.append(tb.tb_frame)
                tb = tb.tb_next

            msg = "An error occured processing an event.\n\n%s\n\nLocal variables at outer most frame in plugin:\n\n%s"
            self._logger.critical(
                msg, traceback.format_exc(), pprint.pformat(stack[1].f_locals)
            )

            if sentry_sdk is not None:
                _sen_extra = {'plugin_name': self._plugin.getName(),
                              'event_id': str(event['id']),
                              'stop_on_error': str(self._stopOnError)}
                if self._stopOnError:
                    _sen_extra['level'] = 'error'
                    msg = 'An error occured processing an event.'
                    msg += '\nStopOnError is True, so skipping the plugin from daemon.'
                    msg += '\n\n%s\n\nLocal variables at outer most frame in plugin:\n\n%s'
                else:
                    _sen_extra['level'] = 'warning'
                self._logger.critical(msg, traceback.format_exc(), pprint.pformat(stack[1].f_locals), extra=_sen_extra)
            else:
                self._logger.critical(msg, traceback.format_exc(), pprint.pformat(stack[1].f_locals))

            if self._stopOnError:
                self._active = False

        if self._engine.timing_logger:
            callback_name = self._logger.name.replace("plugin.", "")
            end_time = datetime.datetime.now(SG_TIMEZONE.local)
            duration = self._prettyTimeDeltaFormat(end_time - start_time)
            delay = self._prettyTimeDeltaFormat(start_time - event["created_at"])
            msg_format = "event_id=%d created_at=%s callback=%s start=%s end=%s duration=%s error=%s delay=%s"
            data = [
                event["id"],
                event["created_at"].isoformat(),
                callback_name,
                start_time.isoformat(),
                end_time.isoformat(),
                duration,
                str(error),
                delay,
            ]
            self._engine.timing_logger.info(msg_format, *data)

        return self._active

    def _prettyTimeDeltaFormat(self, time_delta):
        days, remainder = divmod(time_delta.total_seconds(), 86400)
        hours, remainder = divmod(remainder, 3600)
        minutes, seconds = divmod(remainder, 60)
        return "%02d:%02d:%02d:%02d.%06d" % (
            days,
            hours,
            minutes,
            seconds,
            time_delta.microseconds,
        )

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
        logging.ERROR: "ERROR - SG event daemon.",
        logging.CRITICAL: "CRITICAL - SG event daemon.",
    }

    def __init__(
        self, smtpServer, fromAddr, toAddrs, emailSubject, credentials=None, secure=None
    ):
        args = [smtpServer, fromAddr, toAddrs, emailSubject, credentials]
        if credentials:
            # Python 2.7 implemented the secure argument
            if CURRENT_PYTHON_VERSION >= PYTHON_27:
                args.append(secure)
            else:
                self.secure = secure

        logging.handlers.SMTPHandler.__init__(self, *args)

    def getSubject(self, record):
        subject = logging.handlers.SMTPHandler.getSubject(self, record)
        if record.levelno in self.LEVEL_SUBJECTS:
            return subject + " " + self.LEVEL_SUBJECTS[record.levelno]
        return subject

    def emit(self, record):
        """
        Emit a record.

        Format the record and send it to the specified addressees.
        """

        # Mostly copied from Python 2.7 implementation.
        try:
            import smtplib
            from email.utils import formatdate

            port = self.mailport
            if not port:
                port = smtplib.SMTP_PORT
            smtp = smtplib.SMTP(self.mailhost, port)
            msg = self.format(record)
            msg = "From: %s\r\nTo: %s\r\nSubject: %s\r\nDate: %s\r\n\r\n%s" % (
                self.fromaddr,
                ",".join(self.toaddrs),
                self.getSubject(record),
                formatdate(),
                msg,
            )
            if self.username:
                if self.secure is not None:
                    smtp.ehlo()
                    smtp.starttls(*self.secure)
                    smtp.ehlo()
                smtp.login(self.username, self.password)
            smtp.sendmail(self.fromaddr, self.toaddrs, msg)
            smtp.close()
        except (KeyboardInterrupt, SystemExit):
            raise
        except:
            self.handleError(record)


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


if sys.platform == "win32":

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
                (self._svc_name_, ""),
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
        super(LinuxDaemon, self).__init__(
            "shotgunEvent", self._engine.config.getEnginePIDFile()
        )

    def start(self, daemonize=True):
        if not daemonize:
            # Setup the stdout logger
            handler = logging.StreamHandler()
            handler.setFormatter(
                logging.Formatter("%(levelname)s:%(name)s:%(message)s")
            )
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
    """
    if CURRENT_PYTHON_VERSION <= PYTHON_26:
        print(
            "Python 2.5 and older is not supported anymore. Please use Python 2.6 or newer."
        )
        return 3

    action = None
    if len(sys.argv) > 1:
        action = sys.argv[1]

    if sys.platform == "win32" and action != "foreground":
        win32serviceutil.HandleCommandLine(WindowsService)
        return 0

    if action:
        daemon = LinuxDaemon()

        # Find the function to call on the daemon and call it
        func = getattr(daemon, action, None)
        if action[:1] != "_" and func is not None:
            func()
            return 0

        print("Unknown command: %s" % action)

    print("usage: %s start|stop|restart|foreground" % sys.argv[0])
    return 2


def _getConfigPath():
    """
    Get the path of the shotgunEventDaemon configuration file.
    """
    paths = ["/etc", os.path.dirname(__file__)]

    # Get the current path of the daemon script
    scriptPath = sys.argv[0]
    if scriptPath != "" and scriptPath != "-c":
        # Make absolute path and eliminate any symlinks if any.
        scriptPath = os.path.abspath(scriptPath)
        scriptPath = os.path.realpath(scriptPath)

        # Add the script's directory to the paths we'll search for the config.
        paths[:0] = [os.path.dirname(scriptPath)]

    # Search for a config file.
    for path in paths:
        path = os.path.join(path, "shotgunEventDaemon.conf")
        if os.path.exists(path):
            return path

    # No config file was found
    raise EventDaemonError("Config path not found, searched %s" % ", ".join(paths))


if __name__ == "__main__":
    sys.exit(main())
