name = 'shotgunEvent'
version = '0.1.2'

requires = ['shotgunPythonApi']

def commands():

    env.PYTHONPATH.append(this.root)
    alias('sgDaemon', 'python {root}/src/shotgunEventDaemon.py')
