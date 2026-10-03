"""What the function may touch, from the config secret: the global database and each region's cluster and dial."""

import json
import os
from dataclasses import dataclass

SECRET_ARN_ENV = "FAILOVER_SECRET_ARN"
CLUSTER_PREFIX = "cluster_arn."
ENDPOINT_GROUP_PREFIX = "endpoint_group_arn."


@dataclass(frozen=True, slots=True)
class Config:
    global_cluster_identifier: str
    standby_region: str
    on_alarm: str
    cluster_arns: dict[str, str]
    endpoint_group_arns: dict[str, str]


def parse(raw: dict[str, str]) -> Config:
    cluster_arns = _by_region(raw, CLUSTER_PREFIX)
    endpoint_group_arns = _by_region(raw, ENDPOINT_GROUP_PREFIX)
    missing = [key for key in ("global_cluster_identifier", "standby_region") if not raw.get(key)]
    if not cluster_arns:
        missing.append(f"{CLUSTER_PREFIX}<region>")
    if not endpoint_group_arns:
        missing.append(f"{ENDPOINT_GROUP_PREFIX}<region>")
    if missing:
        raise ValueError(f"config secret incomplete, missing {', '.join(missing)}")
    standby = raw["standby_region"]
    if standby not in cluster_arns or standby not in endpoint_group_arns:
        raise ValueError(f"config secret names standby_region {standby} without its cluster_arn and endpoint_group_arn")
    return Config(
        global_cluster_identifier=raw["global_cluster_identifier"],
        standby_region=standby,
        on_alarm=raw.get("on_alarm") or "status",
        cluster_arns=cluster_arns,
        endpoint_group_arns=endpoint_group_arns,
    )


def load(secretsmanager, secret_arn: str | None = None) -> Config:
    arn = secret_arn or os.environ.get(SECRET_ARN_ENV)
    if not arn:
        raise ValueError(f"{SECRET_ARN_ENV} is not set")
    value = secretsmanager.get_secret_value(SecretId=arn)["SecretString"]
    return parse(json.loads(value))


def _by_region(raw: dict[str, str], prefix: str) -> dict[str, str]:
    return {key.removeprefix(prefix): value for key, value in raw.items() if key.startswith(prefix) and value}
