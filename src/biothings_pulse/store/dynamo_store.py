"""DynamoDB-backed state store for AWS deployments.

Table schema (created by Terraform, or via :meth:`ensure_table` for local
dynamodb-local): partition key ``repo`` (S), sort key ``plugin`` (S), plus a
``doc`` string attribute holding the JSON-serialised :class:`SourceState`.
"""

from __future__ import annotations

from typing import List, Optional

from .base import SourceState, StateStore


class DynamoDBStateStore(StateStore):
    def __init__(
        self,
        table_name: str,
        region_name: str = "us-west-2",
        endpoint_url: Optional[str] = None,
    ):
        import boto3  # imported lazily so local dev needn't install boto3

        self._table_name = table_name
        self._ddb = boto3.resource(
            "dynamodb", region_name=region_name, endpoint_url=endpoint_url
        )
        self._table = self._ddb.Table(table_name)

    def get(self, repo: str, plugin: str) -> Optional[SourceState]:
        resp = self._table.get_item(Key={"repo": repo, "plugin": plugin})
        item = resp.get("Item")
        if not item:
            return None
        return SourceState.model_validate_json(item["doc"])

    def put(self, state: SourceState) -> None:
        self._table.put_item(
            Item={
                "repo": state.repo,
                "plugin": state.plugin,
                "doc": state.model_dump_json(),
            }
        )

    def list_all(self) -> List[SourceState]:
        states: List[SourceState] = []
        kwargs: dict = {}
        while True:
            resp = self._table.scan(**kwargs)
            for item in resp.get("Items", []):
                states.append(SourceState.model_validate_json(item["doc"]))
            last = resp.get("LastEvaluatedKey")
            if not last:
                break
            kwargs["ExclusiveStartKey"] = last
        return states

    def ensure_table(self) -> None:
        """Create the table if missing (handy for dynamodb-local / tests)."""
        existing = [t.name for t in self._ddb.tables.all()]
        if self._table_name in existing:
            return
        table = self._ddb.create_table(
            TableName=self._table_name,
            KeySchema=[
                {"AttributeName": "repo", "KeyType": "HASH"},
                {"AttributeName": "plugin", "KeyType": "RANGE"},
            ],
            AttributeDefinitions=[
                {"AttributeName": "repo", "AttributeType": "S"},
                {"AttributeName": "plugin", "AttributeType": "S"},
            ],
            BillingMode="PAY_PER_REQUEST",
        )
        table.wait_until_exists()
        self._table = table
