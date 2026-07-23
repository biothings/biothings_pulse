"""Minimal BioThings Hub *config module* used to satisfy the SDK at import time.

Importing ``biothings.hub`` runs ``_config_for_app()``, which requires a config
module (env ``HUB_CONFIG``) that at minimum defines ``HUB_DB_BACKEND``. We point
that backend at **file-based SQLite** so no MongoDB or running Hub is needed, and
provide the handful of other keys the SQLite hub_db backend + dumper base classes
read (``DATA_SRC_DATABASE``, ``DATA_ARCHIVE_ROOT``, ``LOG_FOLDER``, …).

This module is also injected into ``sys.modules['config']`` by :mod:`bootstrap`,
so advanced plugins that do ``import config`` / ``from config import
DATA_ARCHIVE_ROOT`` resolve against it too.

Values come from ``PULSE_*`` environment variables when set, otherwise from
per-run temp directories. Everything here is scratch state — the check step
downloads nothing.
"""

import os
import tempfile

_ROOT = os.environ.get("PULSE_HUB_ROOT") or os.path.join(
    tempfile.gettempdir(), "biothings_pulse"
)

# --- Hub DB backend: file-based SQLite (no server) -----------------------
HUB_DB_BACKEND = {
    "module": "biothings.utils.sqlite3",
    "sqlite_db_folder": os.path.join(_ROOT, "hubdb"),
}
DATA_HUB_DB_DATABASE = "biothings_hubdb"

# --- Database names the SQLite backend dereferences ----------------------
# The SQLite backend maps these to local files; only the names matter here.
DATA_SRC_DATABASE = "biothings_src"
DATA_TARGET_DATABASE = "biothings_target"
# DATA_SRC_SERVER/PORT are only read by the Mongo backend, but define harmless
# values so nothing raises a ConfigurationError if a code path touches them.
DATA_SRC_SERVER = "localhost"
DATA_SRC_PORT = 27017

# --- Filesystem scratch --------------------------------------------------
DATA_ARCHIVE_ROOT = os.environ.get("PULSE_DATA_ARCHIVE_ROOT") or os.path.join(
    _ROOT, "archive"
)
LOG_FOLDER = os.environ.get("PULSE_LOG_FOLDER") or os.path.join(_ROOT, "logs")

# --- Misc identity -------------------------------------------------------
HUB_NAME = "biothings_pulse"

for _folder in (HUB_DB_BACKEND["sqlite_db_folder"], DATA_ARCHIVE_ROOT, LOG_FOLDER):
    os.makedirs(_folder, exist_ok=True)
