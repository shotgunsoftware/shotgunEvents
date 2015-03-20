"""
For detailed information please see

http://shotgunsoftware.github.com/shotgunEvents/api.html


Object based shared state
-------------------------

This example aims to show that you can store state in callable object instances.

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


class Callback(object):
    def __init__(self, state, rotate=False):
        self.rotate = rotate
        self.state = state

    def __call__(self, sg, logger, event, args):
        if self.rotate:
            self.state['rotating'] = -1

        # Here we can increment the two counters that are in shared state. Each
        # callback has played with the contents of this shared dictionary.
        self.state['sequential'] += 1
        self.state['rotating'] += 1

        # Log the counters so we can actually see something.
        logger.info('Sequential #%d - Rotating #%d', self.state['sequential'], self.state['rotating'])


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
    reg.registerCallback(scriptName, scriptKey, Callback(_state, rotate=True))
    reg.registerCallback(scriptName, scriptKey, Callback(_state))
    reg.registerCallback(scriptName, scriptKey, Callback(_state))
