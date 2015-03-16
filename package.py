name = 'shotgunEvent'
version = '0.1.1'

requires = ['shotgunPythonApi', 'shotgunEventPlugins']

def commands():

    env.PYTHONPATH.append(this.root)
    alias('sgDaemon', 'python {root}/src/shotgunEventDaemon.py')
