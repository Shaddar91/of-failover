import pytest

from app import VERSION, config, handler
from tests.conftest import DESCRIBE_PARAMS, EAST, SECRET_ARN, WEST, endpoint_group, global_cluster


class Context:
    def __init__(self, remaining_ms: int) -> None:
        self.remaining_ms = remaining_ms

    def get_remaining_time_in_millis(self) -> int:
        return self.remaining_ms


def test_ping_answers_without_aws(monkeypatch):
    monkeypatch.delenv(config.SECRET_ARN_ENV, raising=False)
    assert handler.lambda_handler({"action": "ping"}) == {"ok": True, "function": "of-failover", "version": VERSION}


def test_budget_keeps_a_margin_under_the_remaining_time():
    assert handler.budget_seconds(Context(60_000)) == 45
    assert handler.budget_seconds(Context(5_000)) == 0
    assert handler.budget_seconds(None) == handler.DEFAULT_BUDGET_SECONDS


def test_alarm_event_runs_the_configured_status(cfg, stubs, monkeypatch):
    monkeypatch.setenv(config.SECRET_ARN_ENV, SECRET_ARN)
    monkeypatch.setattr(handler.clients, "Clients", stubs.aws)
    stubs.expect_secret()
    stubs.rds(WEST).add_response("describe_global_clusters", global_cluster(EAST), DESCRIBE_PARAMS)
    stubs.accelerator().add_response(
        "describe_endpoint_group", endpoint_group(EAST, 100.0), {"EndpointGroupArn": cfg.endpoint_group_arns[EAST]}
    )
    stubs.accelerator().add_response(
        "describe_endpoint_group", endpoint_group(WEST, 0.0), {"EndpointGroupArn": cfg.endpoint_group_arns[WEST]}
    )
    event = {"source": "aws.cloudwatch", "detail": {"alarmName": "edge-east", "state": {"value": "ALARM"}}}

    response = handler.lambda_handler(event, Context(900_000))

    assert response["ok"] is True
    assert (response["action"], response["dry_run"], response["reason"]) == ("status", True, "alarm edge-east ALARM")
    assert response["result"]["writer_region"] == EAST


def test_failures_propagate_after_logging(stubs, monkeypatch):
    monkeypatch.setenv(config.SECRET_ARN_ENV, SECRET_ARN)
    monkeypatch.setattr(handler.clients, "Clients", stubs.aws)
    stubs.expect_secret()
    stubs.rds(WEST).add_response("describe_global_clusters", {"GlobalClusters": []}, DESCRIBE_PARAMS)

    with pytest.raises(LookupError):
        handler.lambda_handler({"action": "status"}, Context(900_000))
