name = 'shotgunEvent'
version = '0.1.1'

requires = ['shotgunPythonApi', 'shotgunEventPlugins']

def commands():

    import os
    env.PYTHONPATH.append(this.root)
    env.SG_DAEMON_ROOT = this.root

    alias('sgDaemon', 'python {root}/src/shotgunEventDaemon.py')
    # To be able to have a relative path in config
    os.chdir(this.root)
