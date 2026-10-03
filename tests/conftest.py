"""Stubbed boto3 clients, a fixed config and a fake clock shared by the tests."""

import json

import boto3
import pytest
from botocore.stub import Stubber

from app.clients import Clients
from app.config import Config

EAST = "us-east-1"
WEST = "us-west-2"
ACCOUNT = "111122223333"
GLOBAL_ID = "prod01-us-aurora-aurora-global"
CLUSTER = {
    EAST: f"arn:aws:rds:{EAST}:{ACCOUNT}:cluster:prod01-us-aurora-aurora-cluster",
    WEST: f"arn:aws:rds:{WEST}:{ACCOUNT}:cluster:prod01-usw2-aurora-aurora-cluster",
}
GROUP = {
    EAST: f"arn:aws:globalaccelerator::{ACCOUNT}:accelerator/a1/listener/l1/endpoint-group/east1",
    WEST: f"arn:aws:globalaccelerator::{ACCOUNT}:accelerator/a1/listener/l1/endpoint-group/west1",
}
SECRET_ARN = f"arn:aws:secretsmanager:{WEST}:{ACCOUNT}:secret:innovate-inc-failover-regional-AbCdEf"
SECRET_VALUE = {
    "global_cluster_identifier": GLOBAL_ID,
    "standby_region": WEST,
    "on_alarm": "status",
    f"cluster_arn.{EAST}": CLUSTER[EAST],
    f"cluster_arn.{WEST}": CLUSTER[WEST],
    f"endpoint_group_arn.{EAST}": GROUP[EAST],
    f"endpoint_group_arn.{WEST}": GROUP[WEST],
}
DESCRIBE_PARAMS = {"GlobalClusterIdentifier": GLOBAL_ID}


def global_cluster(writer: str) -> dict:
    return {
        "GlobalClusters": [
            {
                "GlobalClusterIdentifier": GLOBAL_ID,
                "Status": "available",
                "GlobalClusterMembers": [
                    {
                        "DBClusterArn": CLUSTER[region],
                        "IsWriter": region == writer,
                        "SynchronizationStatus": "connected",
                    }
                    for region in (EAST, WEST)
                ],
            }
        ]
    }


def endpoint_group(region: str, dial: float) -> dict:
    return {
        "EndpointGroup": {
            "EndpointGroupArn": GROUP[region],
            "EndpointGroupRegion": region,
            "TrafficDialPercentage": dial,
            "EndpointDescriptions": [
                {
                    "EndpointId": f"arn:aws:elasticloadbalancing:{region}:{ACCOUNT}:loadbalancer/app/edge/1",
                    "Weight": 100,
                    "HealthState": "HEALTHY",
                }
            ],
        }
    }


def dial_params(region: str, dial: float) -> dict:
    return {"EndpointGroupArn": GROUP[region], "TrafficDialPercentage": dial}


class Clock:
    def __init__(self) -> None:
        self.time = 0.0
        self.slept: list[float] = []

    def now(self) -> float:
        return self.time

    def sleep(self, seconds: float) -> None:
        self.slept.append(seconds)
        self.time += seconds


class Stubs:
    def __init__(self) -> None:
        keys = (("rds", EAST), ("rds", WEST), ("globalaccelerator", WEST), ("secretsmanager", WEST))
        self.clients = {
            key: boto3.client(key[0], region_name=key[1], aws_access_key_id="testing", aws_secret_access_key="testing")
            for key in keys
        }
        self.stubbers = {key: Stubber(client) for key, client in self.clients.items()}

    def __enter__(self) -> "Stubs":
        for stubber in self.stubbers.values():
            stubber.activate()
        return self

    def __exit__(self, *exc) -> None:
        for stubber in self.stubbers.values():
            if exc[0] is None:
                stubber.assert_no_pending_responses()
            stubber.deactivate()

    def rds(self, region: str) -> Stubber:
        return self.stubbers[("rds", region)]

    def accelerator(self) -> Stubber:
        return self.stubbers[("globalaccelerator", WEST)]

    def secrets(self) -> Stubber:
        return self.stubbers[("secretsmanager", WEST)]

    def expect_secret(self, value: dict | None = None) -> None:
        secret = json.dumps(value if value is not None else SECRET_VALUE)
        self.secrets().add_response("get_secret_value", {"SecretString": secret}, {"SecretId": SECRET_ARN})

    def aws(self) -> Clients:
        return Clients(prebuilt=self.clients)


@pytest.fixture
def cfg() -> Config:
    return Config(
        global_cluster_identifier=GLOBAL_ID,
        standby_region=WEST,
        on_alarm="status",
        cluster_arns=dict(CLUSTER),
        endpoint_group_arns=dict(GROUP),
    )


@pytest.fixture
def stubs(monkeypatch):
    monkeypatch.setenv("AWS_REGION", WEST)
    with Stubs() as stubs:
        yield stubs


@pytest.fixture
def clock() -> Clock:
    return Clock()
