name = 'shotgunEvents'
version = 'rc.1.4.4'

requires = ['shotgunPythonApi',
            '!pythonStandalone',]

def commands():

    env.PYTHONPATH.append(this.root)
    alias('sgDaemon', 'python {root}/shotgunEvents/src/shotgunEventDaemon.py')
