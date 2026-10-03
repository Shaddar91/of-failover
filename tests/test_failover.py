import pytest

from app.events import Request
from app.failover import Failover, region_of
from tests.conftest import CLUSTER, DESCRIBE_PARAMS, EAST, GLOBAL_ID, WEST, dial_params, endpoint_group, global_cluster


def request(action: str, dry_run: bool = False, target: str | None = None, wait: int = 600) -> Request:
    return Request(action=action, dry_run=dry_run, target_region=target, wait_seconds=wait, reason="test")


def runner(cfg, stubs, clock, budget: float = 600) -> Failover:
    return Failover(cfg, stubs.aws(), budget_seconds=budget, now=clock.now, sleep=clock.sleep)


def test_region_of_reads_the_arn():
    assert region_of(CLUSTER[WEST]) == WEST


def test_status_reports_writer_and_dials(cfg, stubs, clock):
    stubs.rds(WEST).add_response("describe_global_clusters", global_cluster(EAST), DESCRIBE_PARAMS)
    stubs.accelerator().add_response(
        "describe_endpoint_group", endpoint_group(EAST, 100.0), {"EndpointGroupArn": cfg.endpoint_group_arns[EAST]}
    )
    stubs.accelerator().add_response(
        "describe_endpoint_group", endpoint_group(WEST, 0.0), {"EndpointGroupArn": cfg.endpoint_group_arns[WEST]}
    )

    result = runner(cfg, stubs, clock).run(request("status", dry_run=True))

    assert result["writer_region"] == EAST
    assert result["standby_region"] == WEST
    assert result["global_cluster"]["identifier"] == GLOBAL_ID
    assert [member["is_writer"] for member in result["global_cluster"]["members"]] == [True, False]
    assert result["endpoint_groups"][EAST]["traffic_dial_percentage"] == 100.0
    assert result["endpoint_groups"][WEST]["endpoints"][0]["health"] == "HEALTHY"
    assert result["steps"] == []


def test_fence_sets_the_writer_region_dial_to_zero(cfg, stubs, clock):
    stubs.rds(WEST).add_response("describe_global_clusters", global_cluster(EAST), DESCRIBE_PARAMS)
    stubs.accelerator().add_response("update_endpoint_group", endpoint_group(EAST, 0.0), dial_params(EAST, 0.0))

    result = runner(cfg, stubs, clock).run(request("fence"))

    assert result["writer_region"] == EAST
    assert result["steps"][0]["status"] == "done"
    assert result["steps"][0]["params"] == dial_params(EAST, 0.0)


def test_failover_dry_run_only_reads(cfg, stubs, clock):
    stubs.rds(WEST).add_response("describe_global_clusters", global_cluster(EAST), DESCRIBE_PARAMS)

    result = runner(cfg, stubs, clock).run(request("failover", dry_run=True))

    assert result["promoted"] is False
    assert (result["writer_before"], result["writer_after"]) == (EAST, EAST)
    assert [step["status"] for step in result["steps"]] == ["planned"] * 4
    assert [step["call"] for step in result["steps"]] == [
        "globalaccelerator.update_endpoint_group",
        "rds.failover_global_cluster",
        "globalaccelerator.update_endpoint_group",
        "globalaccelerator.update_endpoint_group",
    ]
    assert result["steps"][1]["params"]["AllowDataLoss"] is True
    assert clock.slept == []


def test_failover_fences_promotes_waits_and_opens_the_target(cfg, stubs, clock):
    west = stubs.rds(WEST)
    west.add_response("describe_global_clusters", global_cluster(EAST), DESCRIBE_PARAMS)
    stubs.accelerator().add_response("update_endpoint_group", endpoint_group(EAST, 0.0), dial_params(EAST, 0.0))
    west.add_response(
        "failover_global_cluster",
        {"GlobalCluster": {"GlobalClusterIdentifier": GLOBAL_ID}, "ResponseMetadata": {"HTTPStatusCode": 200}},
        {"GlobalClusterIdentifier": GLOBAL_ID, "TargetDbClusterIdentifier": CLUSTER[WEST], "AllowDataLoss": True},
    )
    west.add_response("describe_global_clusters", global_cluster(EAST), DESCRIBE_PARAMS)
    west.add_response("describe_global_clusters", global_cluster(WEST), DESCRIBE_PARAMS)
    stubs.accelerator().add_response("update_endpoint_group", endpoint_group(EAST, 0.0), dial_params(EAST, 0.0))
    stubs.accelerator().add_response("update_endpoint_group", endpoint_group(WEST, 100.0), dial_params(WEST, 100.0))

    result = runner(cfg, stubs, clock).run(request("failover"))

    assert result["promoted"] is True
    assert (result["writer_before"], result["writer_after"]) == (EAST, WEST)
    assert [step["status"] for step in result["steps"]] == ["done"] * 4
    assert result["steps"][1]["result"] == {"http_status": 200}
    assert clock.slept == [10]


def test_failover_gives_up_when_the_writer_never_moves(cfg, stubs, clock):
    west = stubs.rds(WEST)
    west.add_response("describe_global_clusters", global_cluster(EAST), DESCRIBE_PARAMS)
    stubs.accelerator().add_response("update_endpoint_group", endpoint_group(EAST, 0.0), dial_params(EAST, 0.0))
    west.add_response(
        "failover_global_cluster",
        {"GlobalCluster": {"GlobalClusterIdentifier": GLOBAL_ID}},
        {"GlobalClusterIdentifier": GLOBAL_ID, "TargetDbClusterIdentifier": CLUSTER[WEST], "AllowDataLoss": True},
    )
    for _ in range(3):
        west.add_response("describe_global_clusters", global_cluster(EAST), DESCRIBE_PARAMS)

    result = runner(cfg, stubs, clock, budget=25).run(request("failover", wait=600))

    assert result["promoted"] is False
    assert result["writer_after"] == EAST
    assert [step["call"] for step in result["steps"]] == [
        "globalaccelerator.update_endpoint_group",
        "rds.failover_global_cluster",
    ]
    assert clock.slept == [10, 10]


def test_switchover_runs_in_the_writer_region_without_fencing_first(cfg, stubs, clock):
    west = stubs.rds(WEST)
    west.add_response("describe_global_clusters", global_cluster(EAST), DESCRIBE_PARAMS)
    stubs.rds(EAST).add_response(
        "switchover_global_cluster",
        {"GlobalCluster": {"GlobalClusterIdentifier": GLOBAL_ID}},
        {"GlobalClusterIdentifier": GLOBAL_ID, "TargetDbClusterIdentifier": CLUSTER[WEST]},
    )
    west.add_response("describe_global_clusters", global_cluster(WEST), DESCRIBE_PARAMS)
    stubs.accelerator().add_response("update_endpoint_group", endpoint_group(EAST, 0.0), dial_params(EAST, 0.0))
    stubs.accelerator().add_response("update_endpoint_group", endpoint_group(WEST, 100.0), dial_params(WEST, 100.0))

    result = runner(cfg, stubs, clock).run(request("switchover"))

    assert result["promoted"] is True
    assert [step["call"] for step in result["steps"]] == [
        "rds.switchover_global_cluster",
        "globalaccelerator.update_endpoint_group",
        "globalaccelerator.update_endpoint_group",
    ]
    assert "AllowDataLoss" not in result["steps"][0]["params"]
    assert clock.slept == []


def test_switchover_back_to_the_first_region(cfg, stubs, clock):
    west = stubs.rds(WEST)
    west.add_response("describe_global_clusters", global_cluster(WEST), DESCRIBE_PARAMS)
    west.add_response(
        "switchover_global_cluster",
        {"GlobalCluster": {"GlobalClusterIdentifier": GLOBAL_ID}},
        {"GlobalClusterIdentifier": GLOBAL_ID, "TargetDbClusterIdentifier": CLUSTER[EAST]},
    )
    west.add_response("describe_global_clusters", global_cluster(EAST), DESCRIBE_PARAMS)
    stubs.accelerator().add_response("update_endpoint_group", endpoint_group(WEST, 0.0), dial_params(WEST, 0.0))
    stubs.accelerator().add_response("update_endpoint_group", endpoint_group(EAST, 100.0), dial_params(EAST, 100.0))

    result = runner(cfg, stubs, clock).run(request("switchover", target=EAST))

    assert (result["writer_before"], result["writer_after"], result["promoted"]) == (WEST, EAST, True)


def test_promotion_refuses_the_region_that_already_writes(cfg, stubs, clock):
    stubs.rds(WEST).add_response("describe_global_clusters", global_cluster(EAST), DESCRIBE_PARAMS)

    with pytest.raises(ValueError, match=f"{EAST} already holds the writer"):
        runner(cfg, stubs, clock).run(request("failover", target=EAST))


def test_promotion_refuses_an_unknown_region(cfg, stubs, clock):
    stubs.rds(WEST).add_response("describe_global_clusters", global_cluster(EAST), DESCRIBE_PARAMS)

    with pytest.raises(ValueError, match="eu-central-1 is not a configured region"):
        runner(cfg, stubs, clock).run(request("failover", target="eu-central-1"))


def test_missing_global_cluster_is_reported(cfg, stubs, clock):
    stubs.rds(WEST).add_response("describe_global_clusters", {"GlobalClusters": []}, DESCRIBE_PARAMS)

    with pytest.raises(LookupError, match=f"{GLOBAL_ID} not found"):
        runner(cfg, stubs, clock).run(request("status", dry_run=True))
