[![Python 2.7 3.7](https://img.shields.io/badge/python-2.7%20%7C%203.7-blue.svg)](https://www.python.org/)
[![Build Status](https://dev.azure.com/shotgun-ecosystem/Toolkit/_apis/build/status/shotgunEvents?branchName=master)](https://dev.azure.com/shotgun-ecosystem/Toolkit/_build/latest?definitionId=89&branchName=master)
[![Code style: black](https://img.shields.io/badge/code%20style-black-000000.svg)](https://github.com/psf/black)
[![Linting](https://img.shields.io/badge/PEP8%20by-Hound%20CI-a873d1.svg)](https://houndci.com)

# Flow Production Tracking Event Framework
This software was originaly developed by [Patrick
Boucher](http://www.patrickboucher.com) with support from [Rodeo
Fx](http://rodeofx.com) and Oblique. It is now part of
[Flow Production Tracking Software](https://www.autodesk.com/products/flow-production-tracking)'s [open source
initiative](https://github.com/shotgunsoftware).

This software is provided under the MIT License that can be found in the LICENSE
file or at the [Open Source Initiative](http://www.opensource.org/licenses/mit-license.php) website.


## Overview

When you want to access the Flow Production Tracking event stream, the preferred way to do so it
to monitor the events table, get any new events, process them and repeat.

A lot of stuff is required for this process to work successfully, stuff that may
not have any direct bearing on the business rules that need to be applied.

The role of the framework is to keep any tedious monitoring tasks out of the
hands of the business logic implementor.

The framework is a daemon process that runs on a server and monitors the Shotgun
event stream. When events are found, the daemon hands the events out to a series
of registered plugins. Each plugin can process the event as it wishes.

The daemon handles:

- Registering plugins from one or more specified paths.
- Deactivate any crashing plugins.
- Reloading plugins when they change on disk.
- Monitoring the Flow Production Tracking event stream.
- Remembering the last processed event id and any backlog.
- Starting from the last processed event id on daemon startup.
- Catching any connection errors.
- Logging information to stdout, file or email as required.
- Creating a connection to Shotgun that will be used by the callback.
- Handing off events to registered callbacks.

A plugin handles:

- Registering any number of callbacks into the framework.
- Processing a single event when one is provided by the framework.


## Advantages of the framework

- Only deal with a single monitoring mechanism for all scripts, not one per
  script.
- Minimize network and database load (only one monitor that supplies event to
  many event processing plugins).


## Documentation

See the [GitHub Wiki](https://github.com/shotgunsoftware/shotgunEvents/wiki).
