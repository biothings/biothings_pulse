"""A minimal advanced-plugin dumper used only by the test-suite discovery/load."""

import os

import biothings.hub.dataload.dumper as dumper
from biothings import config


class WidgetDumper(dumper.LastModifiedHTTPDumper):
    SRC_NAME = "widget"
    SRC_ROOT_FOLDER = os.path.join(config.DATA_ARCHIVE_ROOT, "widget")
    SRC_URLS = ["http://example.com/widget.zip"]
    SCHEDULE = None
    UNCOMPRESS = False
