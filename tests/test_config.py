import pytest

from gitgrounded.config.loader import parse_config
from gitgrounded.errors import ConfigError


def test_minimal_config_gets_defaults():
    cfg = parse_config(
        {"targets": {"t": {"type": "python", "entry": "app:run"}}, "suites": {"s": {"target": "t", "cases": "c.jsonl"}}}
    )
    assert cfg.providers.judge.provider == "anthropic"
    assert cfg.suites["s"].trials == 1
    assert [j.type for j in cfg.suites["s"].judges] == ["rubric", "pairwise"]


def test_unknown_field_is_reported_with_path():
    with pytest.raises(ConfigError) as e:
        parse_config({"targets": {"t": {"type": "python", "entry": "a:b", "bogus": 1}}})
    assert "targets.t" in str(e.value)


def test_unknown_target_type():
    with pytest.raises(ConfigError):
        parse_config({"targets": {"t": {"type": "carrier_pigeon"}}})


def test_env_interpolation(monkeypatch):
    monkeypatch.setenv("GG_TOKEN", "secret")
    cfg = parse_config(
        {"targets": {"api": {"type": "http", "url": "http://x", "headers": {"Authorization": "Bearer ${GG_TOKEN}"}}}}
    )
    assert cfg.targets["api"].headers["Authorization"] == "Bearer secret"


def test_env_default():
    cfg = parse_config({"targets": {"api": {"type": "http", "url": "${GG_MISSING_URL:-http://fallback}"}}})
    assert cfg.targets["api"].url == "http://fallback"


def test_strict_env_missing():
    with pytest.raises(ConfigError):
        parse_config({"targets": {"api": {"type": "http", "url": "${GG_DEFINITELY_MISSING}"}}}, strict_env=True)


def test_unknown_suite():
    cfg = parse_config({})
    with pytest.raises(ConfigError):
        cfg.suite("nope")
