"""What an invocation asks for: an event naming an action, or a CloudWatch alarm mapped to the on_alarm action."""

from dataclasses import dataclass

ACTIONS = ("ping", "status", "fence", "failover", "switchover")
ALARM_SOURCE = "aws.cloudwatch"
DEFAULT_WAIT_SECONDS = 600


@dataclass(frozen=True, slots=True)
class Request:
    action: str
    dry_run: bool
    target_region: str | None
    wait_seconds: int
    reason: str


def parse(event: dict | None, on_alarm: str = "status") -> Request:
    event = event or {}
    if event.get("source") == ALARM_SOURCE:
        return _from_alarm(event, on_alarm)
    action = str(event.get("action", "status"))
    if action not in ACTIONS:
        raise ValueError(f"unknown action {action!r}, expected one of {', '.join(ACTIONS)}")
    return Request(
        action=action,
        dry_run=_flag(event.get("dry_run", True)),
        target_region=event.get("target_region") or None,
        wait_seconds=int(event.get("wait_seconds", DEFAULT_WAIT_SECONDS)),
        reason=str(event.get("reason", "manual")),
    )


def _from_alarm(event: dict, on_alarm: str) -> Request:
    detail = event.get("detail") or {}
    state = (detail.get("state") or {}).get("value")
    name = detail.get("alarmName", "unknown")
    action = on_alarm if state == "ALARM" else "status"
    return Request(
        action=action,
        dry_run=action == "status",
        target_region=None,
        wait_seconds=DEFAULT_WAIT_SECONDS,
        reason=f"alarm {name} {state}",
    )


def _flag(value: object) -> bool:
    if isinstance(value, str):
        return value.strip().lower() not in ("false", "0", "no", "")
    return bool(value)
