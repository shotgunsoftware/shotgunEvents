
import re
from os.path import dirname, abspath, join, normpath

from setuptools import setup, find_packages

# Get version from source file
with open(normpath(join(abspath(__file__), '../src/shotgunEventDaemon.py')), 'rU') as f:
    m = re.search(r'\s*__version__ = [\'"]([^\'"]+)[\'"]', f.read())
    version = m.group(1)

setup(
    name='shotgunEvents',
    version=version,
    zip_safe=False,
    package_dir={'': 'src'},
    py_modules=['shotgunEventDaemon', 'daemonizer'],
    entry_points={
        'console_scripts': ['shotgunEventDaemon=shotgunEventDaemon:main'],
    },
)
