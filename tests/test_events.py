import pytest

from app import events


def test_empty_event_is_a_dry_status():
    req = events.parse(None)
    assert (req.action, req.dry_run, req.target_region, req.reason) == ("status", True, None, "manual")


def test_explicit_failover_with_dry_run_off():
    req = events.parse({"action": "failover", "dry_run": False, "target_region": "us-west-2", "reason": "drill"})
    assert (req.action, req.dry_run, req.target_region, req.reason) == ("failover", False, "us-west-2", "drill")


@pytest.mark.parametrize("value", ["false", "0", "no", "", False, 0])
def test_dry_run_flag_accepts_false_spellings(value):
    assert events.parse({"action": "fence", "dry_run": value}).dry_run is False


@pytest.mark.parametrize("value", ["true", "yes", "1", True, 1, "anything"])
def test_dry_run_flag_accepts_true_spellings(value):
    assert events.parse({"action": "fence", "dry_run": value}).dry_run is True


def test_unknown_action_is_refused():
    with pytest.raises(ValueError, match="unknown action 'promote'"):
        events.parse({"action": "promote"})


def test_alarm_in_alarm_state_takes_the_configured_action():
    event = {"source": "aws.cloudwatch", "detail": {"alarmName": "edge-east", "state": {"value": "ALARM"}}}
    req = events.parse(event, on_alarm="failover")
    assert (req.action, req.dry_run, req.reason) == ("failover", False, "alarm edge-east ALARM")


def test_alarm_back_to_ok_only_reports():
    event = {"source": "aws.cloudwatch", "detail": {"alarmName": "edge-east", "state": {"value": "OK"}}}
    req = events.parse(event, on_alarm="failover")
    assert (req.action, req.dry_run) == ("status", True)


def test_alarm_with_status_configured_stays_a_dry_status():
    event = {"source": "aws.cloudwatch", "detail": {"alarmName": "edge-east", "state": {"value": "ALARM"}}}
    req = events.parse(event, on_alarm="status")
    assert (req.action, req.dry_run) == ("status", True)
