"""Operations: status of database and accelerator, fence a region, failover or switchover the writer to a region."""

import time
from collections.abc import Callable
from dataclasses import asdict, dataclass, field

from app.clients import Clients
from app.config import Config
from app.events import Request
from app.log import emit

POLL_SECONDS = 10
FENCED_DIAL = 0.0
OPEN_DIAL = 100.0


@dataclass
class Step:
    call: str
    params: dict
    status: str
    result: dict = field(default_factory=dict)


class Failover:
    def __init__(
        self,
        cfg: Config,
        clients: Clients,
        budget_seconds: float,
        now: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self.cfg = cfg
        self.clients = clients
        self.budget_seconds = budget_seconds
        self.now = now
        self.sleep = sleep

    def run(self, req: Request) -> dict:
        operations = {
            "status": self.status,
            "fence": self.fence,
            "failover": self.failover,
            "switchover": self.switchover,
        }
        result = operations[req.action](req)
        result["steps"] = [asdict(step) for step in result.get("steps", [])]
        return result

    def status(self, req: Request) -> dict:
        cluster = self.global_cluster()
        return {
            "global_cluster": {
                "identifier": cluster["GlobalClusterIdentifier"],
                "status": cluster.get("Status"),
                "members": self.members(cluster),
            },
            "writer_region": self.writer_region(cluster),
            "standby_region": self.cfg.standby_region,
            "endpoint_groups": self.endpoint_groups(),
        }

    def fence(self, req: Request) -> dict:
        writer = self.writer_region(self.global_cluster())
        if writer is None:
            raise LookupError("the global database has no writer to fence")
        return {"writer_region": writer, "steps": [self.set_dial(writer, FENCED_DIAL, req)]}

    def failover(self, req: Request) -> dict:
        return self._promote(req, planned=False)

    def switchover(self, req: Request) -> dict:
        return self._promote(req, planned=True)

    def global_cluster(self) -> dict:
        rds = self.clients.rds(self.cfg.standby_region)
        response = rds.describe_global_clusters(GlobalClusterIdentifier=self.cfg.global_cluster_identifier)
        clusters = response.get("GlobalClusters", [])
        if not clusters:
            raise LookupError(f"global database {self.cfg.global_cluster_identifier} not found")
        return clusters[0]

    def members(self, cluster: dict) -> list[dict]:
        return [
            {
                "arn": member["DBClusterArn"],
                "region": region_of(member["DBClusterArn"]),
                "is_writer": bool(member.get("IsWriter")),
                "synchronization": member.get("SynchronizationStatus"),
            }
            for member in cluster.get("GlobalClusterMembers", [])
        ]

    def writer_region(self, cluster: dict) -> str | None:
        return next((member["region"] for member in self.members(cluster) if member["is_writer"]), None)

    def endpoint_groups(self) -> dict[str, dict]:
        groups = {}
        for region, arn in sorted(self.cfg.endpoint_group_arns.items()):
            group = self.clients.accelerator().describe_endpoint_group(EndpointGroupArn=arn)["EndpointGroup"]
            groups[region] = {
                "traffic_dial_percentage": group.get("TrafficDialPercentage"),
                "endpoints": [
                    {"id": endpoint.get("EndpointId"), "health": endpoint.get("HealthState")}
                    for endpoint in group.get("EndpointDescriptions", [])
                ],
            }
        return groups

    def set_dial(self, region: str, percentage: float, req: Request) -> Step:
        params = {"EndpointGroupArn": self.cfg.endpoint_group_arns[region], "TrafficDialPercentage": percentage}
        accelerator = self.clients.accelerator()
        return self._call("globalaccelerator.update_endpoint_group", params, req, accelerator.update_endpoint_group)

    def _promote(self, req: Request, planned: bool) -> dict:
        writer = self.writer_region(self.global_cluster())
        target = req.target_region or self.cfg.standby_region
        if target not in self.cfg.cluster_arns or target not in self.cfg.endpoint_group_arns:
            raise ValueError(
                f"{target} is not a configured region, expected one of {', '.join(sorted(self.cfg.cluster_arns))}"
            )
        if target == writer:
            raise ValueError(f"{target} already holds the writer, nothing to promote")
        if writer is None:
            raise LookupError("the global database has no writer, promotion would not be a failover")
        steps = []
        params = {
            "GlobalClusterIdentifier": self.cfg.global_cluster_identifier,
            "TargetDbClusterIdentifier": self.cfg.cluster_arns[target],
        }
        if planned:
            rds = self.clients.rds(writer)
            steps.append(self._call("rds.switchover_global_cluster", params, req, rds.switchover_global_cluster))
        else:
            steps.append(self.set_dial(writer, FENCED_DIAL, req))
            params["AllowDataLoss"] = True
            rds = self.clients.rds(target)
            steps.append(self._call("rds.failover_global_cluster", params, req, rds.failover_global_cluster))
        writer_after = writer if req.dry_run else self._wait_for_writer(target, req)
        promoted = writer_after == target
        if promoted or req.dry_run:
            steps.append(self.set_dial(writer, FENCED_DIAL, req))
            steps.append(self.set_dial(target, OPEN_DIAL, req))
        return {
            "target_region": target,
            "writer_before": writer,
            "writer_after": writer_after,
            "promoted": promoted,
            "steps": steps,
        }

    def _wait_for_writer(self, target: str, req: Request) -> str | None:
        deadline = self.now() + min(req.wait_seconds, self.budget_seconds)
        while True:
            writer = self.writer_region(self.global_cluster())
            if writer == target:
                return writer
            if self.now() + POLL_SECONDS > deadline:
                emit("wait_expired", target_region=target, writer_region=writer)
                return writer
            self.sleep(POLL_SECONDS)

    def _call(self, name: str, params: dict, req: Request, call: Callable[..., dict]) -> Step:
        if req.dry_run:
            emit("planned", call=name, params=params)
            return Step(name, params, "planned")
        emit("call", call=name, params=params)
        response = call(**params)
        status = response.get("ResponseMetadata", {}).get("HTTPStatusCode")
        return Step(name, params, "done", {"http_status": status})


def region_of(arn: str) -> str:
    return arn.split(":")[3]
