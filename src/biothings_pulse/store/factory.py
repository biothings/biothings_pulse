"""Construct the configured state store backend."""

from __future__ import annotations

from ..config import Settings
from .base import StateStore


def make_store(settings: Settings) -> StateStore:
    backend = settings.store_backend.lower()
    if backend == "sqlite":
        from .sqlite_store import SQLiteStateStore

        return SQLiteStateStore(settings.sqlite_path)
    if backend == "dynamodb":
        from .dynamo_store import DynamoDBStateStore

        return DynamoDBStateStore(
            table_name=settings.dynamodb_table,
            region_name=settings.aws_region,
            endpoint_url=settings.dynamodb_endpoint_url,
        )
    raise ValueError(f"Unknown store backend: {settings.store_backend!r}")
