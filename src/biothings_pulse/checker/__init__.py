"""The check engine: load a plugin's dumper and run release detection only."""

from .models import CheckResult
from .runner import check_plugin

__all__ = ["CheckResult", "check_plugin"]
