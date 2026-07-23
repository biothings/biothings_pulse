"""Custom release function for the acme test plugin.

Mirrors the BioThings convention: the function is injected as a dumper method,
so it takes ``self`` (the dumper instance). Returns a constant here so tests
need no network.
"""


def get_release(self):
    return "2024-07-01"
