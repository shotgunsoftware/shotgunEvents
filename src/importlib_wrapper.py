# Importlib wrapper for Python 3.11- compatibility.
# This module provides a function to load a source file as a module,
# mimicking the behavior of the `imp.load_source()` function.
# It is intended to be used in environments where the `imp` module is deprecated
# or removed, such as in Python 3.12 and later.
# Taken from https://docs.python.org/3/whatsnew/3.12.html#imp

import importlib.util
import importlib.machinery
from types import ModuleType


def load_source(modname: str, filename: str) -> ModuleType:
    loader = importlib.machinery.SourceFileLoader(modname, filename)
    spec = importlib.util.spec_from_file_location(modname, filename, loader=loader)
    module = importlib.util.module_from_spec(spec)
    # The module is always executed and not cached in sys.modules.
    # Uncomment the following line to cache the module.
    # sys.modules[module.__name__] = module
    loader.exec_module(module)
    return module
