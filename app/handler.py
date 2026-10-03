"""Lambda entry point: answers ping, else loads the config secret, parses the event and runs the operation."""

from app import VERSION, clients, config, events, failover
from app.log import emit

SAFETY_MARGIN_SECONDS = 15
DEFAULT_BUDGET_SECONDS = 840


def lambda_handler(event: dict | None, context=None) -> dict:
    if (event or {}).get("action") == "ping":
        return {"ok": True, "function": "of-failover", "version": VERSION}
    aws = clients.Clients()
    cfg = config.load(aws.secretsmanager())
    req = events.parse(event, cfg.on_alarm)
    budget = budget_seconds(context)
    emit("request", action=req.action, dry_run=req.dry_run, target_region=req.target_region, reason=req.reason)
    runner = failover.Failover(cfg, aws, budget_seconds=budget)
    try:
        result = runner.run(req)
    except Exception as exc:
        emit("failed", action=req.action, error=f"{type(exc).__name__}: {exc}")
        raise
    emit("done", action=req.action, dry_run=req.dry_run, result=result)
    return {"ok": True, "action": req.action, "dry_run": req.dry_run, "reason": req.reason, "result": result}


def budget_seconds(context) -> float:
    remaining = getattr(context, "get_remaining_time_in_millis", None)
    if remaining is None:
        return DEFAULT_BUDGET_SECONDS
    return max(remaining() / 1000 - SAFETY_MARGIN_SECONDS, 0)
