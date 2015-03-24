"""
For detailed information please see

http://shotgunsoftware.github.com/shotgunEvents/api.html


Args based shared state
-----------------------

This plugin demoes how three callbacks can share state through the args argument
to registerCallback.

The shared state stores two counters one (sequential) will be incremented
sequentially by each callback and will keep incrementing across event ids.

The second counter (rotating) will be incremented by each successive callback
but will be reset at each new event.


Try me
------

To try the plugin, make sure you copy it into a path mentioned in your .conf's
"paths" ([plugin] section) and change $DEMO_SCRIPT_NAME$ and $DEMO_API_KEY$ for
sane values.
"""


def registerCallbacks(reg):
    """Register all necessary or appropriate callbacks for this plugin."""

    scriptName = '$DEMO_SCRIPT_NAME$'
    scriptKey = '$DEMO_API_KEY$'

    # Prepare the shared state object
    _state = {
        'sequential': -1,
        'rotating': -1,
    }

    # Callbacks are called in registration order. So callbackA will be called
    # before callbackB and callbackC
    reg.registerCallback(scriptName, scriptKey, callbackA, args=_state)
    reg.registerCallback(scriptName, scriptKey, callbackB, args=_state)
    reg.registerCallback(scriptName, scriptKey, callbackC, args=_state)


def callbackA(sg, logger, event, args):
    # We know callbackA will be called first because we registered it first.
    # As the first thing to run on each event, we can reinizialize the rotating
    # counter.
    args['rotating'] = -1

    # Then we pass off to our helper function... because I'm lazy.
    printIds(sg, logger, event, args)


def callbackB(*args):
    # Just an example plugin, remember... Get the ids incremented and logged.
    printIds(*args)


def callbackC(*args):
    # Just an example plugin, remember... Get the ids incremented and logged.
    printIds(*args)


def printIds(sg, logger, event, args):
    # Here we can increment the two counters that are in shared state. Each
    # callback has played with the contents of this shared dictionary.
    args['sequential'] += 1
    args['rotating'] += 1

    # Log the counters so we can actually see something.
    logger.info('Sequential #%d - Rotating #%d', args['sequential'], args['rotating'])
