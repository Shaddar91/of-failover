"""boto3 clients by service and region; Global Accelerator answers in us-west-2, Secrets Manager locally."""

import os

import boto3
from botocore.config import Config as BotoConfig

ACCELERATOR_REGION = "us-west-2"
RETRIES = BotoConfig(retries={"max_attempts": 5, "mode": "standard"})


class Clients:
    def __init__(self, prebuilt: dict[tuple[str, str], object] | None = None) -> None:
        self._clients: dict[tuple[str, str], object] = dict(prebuilt or {})
        self._session = None

    def rds(self, region: str):
        return self._get("rds", region)

    def accelerator(self):
        return self._get("globalaccelerator", ACCELERATOR_REGION)

    def secretsmanager(self):
        return self._get("secretsmanager", os.environ.get("AWS_REGION", ACCELERATOR_REGION))

    def _get(self, service: str, region: str):
        key = (service, region)
        if key not in self._clients:
            if self._session is None:
                self._session = boto3.Session()
            self._clients[key] = self._session.client(service, region_name=region, config=RETRIES)
        return self._clients[key]
