name = 'shotgunEvents'
version = '1.3.0'

requires = ['shotgunPythonApi',
            '!pythonStandalone',]

# Mikros specific
custom = {
    'description': 'Shotgun event processing framework',
    'doc': 'https://github.com/shotgunsoftware/shotgunEvents/wiki',
    'authors': ['gou', 'jbro', 'angu', 'jbi'],
    'maintainers': ['jbi', 'gou'],
}

def commands():

    env.PYTHONPATH.append(this.root)
    alias('sgDaemon', 'python {root}/shotgunEvents/src/shotgunEventDaemon.py')
