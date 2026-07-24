"""Result of a single data-source check."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Optional


@dataclass
class CheckResult:
    """Outcome of running the check step for one plugin.

    ``status`` is one of:
      * ``ok``          – release detection succeeded
      * ``error``       – detection ran but failed (network, plugin bug, timeout)
      * ``unsupported`` – the plugin can't be checked (no dumper / docker / etc.)
    """

    status: str
    latest_version: Optional[str] = None
    download_urls: List[str] = field(default_factory=list)
    error: Optional[str] = None
    schedule: Optional[str] = None  # plugin's declared check schedule (cron), if any
