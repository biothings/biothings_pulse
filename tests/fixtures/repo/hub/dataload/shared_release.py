"""A shared release function referenced by manifests as
``hub.dataload.shared_release:get_release`` (DogPark-style). Reads the manifest
``__metadata__`` exposed on the dumper class."""


def get_release(self):
    return self.__class__.__metadata__.get("version", "unknown")
