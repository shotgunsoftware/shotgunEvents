name = 'shotgunEvents'
version = 'rc.1.4.1'

requires = ['shotgunPythonApi',
            '!pythonStandalone',]

def commands():

    env.PYTHONPATH.append(this.root)
    alias('sgDaemon', 'python {root}/shotgunEvents/src/shotgunEventDaemon.py')
