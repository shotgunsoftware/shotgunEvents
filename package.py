name = 'shotgunEvent'
version = '1.0.0'

requires = ['shotgunPythonApi']

def commands():

    env.PYTHONPATH.append(this.root)
    alias('sgDaemon', 'python {root}/shotgunEvents/src/shotgunEventDaemon.py')
