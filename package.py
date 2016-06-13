name = 'shotgunEvents'
version = '1.1.0'

requires = ['shotgunPythonApi',
            '!pythonStandalone',]

def commands():

    env.PYTHONPATH.append(this.root)
    alias('sgDaemon', 'python {root}/shotgunEvents/src/shotgunEventDaemon.py')
