"""A clean, self-contained dumper whose package __init__ is intentionally broken."""

import os

import biothings.hub.dataload.dumper as dumper
from biothings import config


class BrokenDumper(dumper.LastModifiedHTTPDumper):
    SRC_NAME = "broken"
    SRC_ROOT_FOLDER = os.path.join(config.DATA_ARCHIVE_ROOT, "broken")
    SRC_URLS = ["http://example.com/broken.txt"]
    SCHEDULE = None
