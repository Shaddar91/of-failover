import pytest

from app import config
from tests.conftest import CLUSTER, EAST, GLOBAL_ID, GROUP, SECRET_ARN, SECRET_VALUE, WEST


def test_parse_groups_arns_by_region():
    cfg = config.parse(SECRET_VALUE)
    assert cfg.global_cluster_identifier == GLOBAL_ID
    assert cfg.standby_region == WEST
    assert cfg.on_alarm == "status"
    assert cfg.cluster_arns == {EAST: CLUSTER[EAST], WEST: CLUSTER[WEST]}
    assert cfg.endpoint_group_arns == {EAST: GROUP[EAST], WEST: GROUP[WEST]}


def test_parse_defaults_on_alarm_to_status():
    raw = {key: value for key, value in SECRET_VALUE.items() if key != "on_alarm"}
    assert config.parse(raw).on_alarm == "status"


def test_parse_names_every_missing_key():
    with pytest.raises(ValueError, match="global_cluster_identifier, standby_region, cluster_arn.<region>"):
        config.parse({f"endpoint_group_arn.{WEST}": GROUP[WEST]})


def test_parse_refuses_a_standby_without_arns():
    raw = {key: value for key, value in SECRET_VALUE.items() if not key.endswith(WEST)}
    with pytest.raises(ValueError, match=f"standby_region {WEST} without"):
        config.parse(raw)


def test_load_reads_the_secret_named_by_the_environment(stubs, monkeypatch):
    monkeypatch.setenv(config.SECRET_ARN_ENV, SECRET_ARN)
    stubs.expect_secret()
    assert config.load(stubs.aws().secretsmanager()).standby_region == WEST


def test_load_without_the_variable_fails_before_any_call(stubs, monkeypatch):
    monkeypatch.delenv(config.SECRET_ARN_ENV, raising=False)
    with pytest.raises(ValueError, match=config.SECRET_ARN_ENV):
        config.load(stubs.aws().secretsmanager())
