# Simulates an advanced plugin whose package __init__ imports heavy/Hub-only
# code that fails outside a running Hub (e.g. an uploader/key-lookup). The
# loader must still find the dumper by loading dumper.py directly.
from .this_module_does_not_exist import Boom  # noqa: F401
from .dumper import BrokenDumper  # noqa: F401
