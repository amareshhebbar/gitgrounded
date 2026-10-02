import os
import re
from importlib import resources
from pathlib import Path
from typing import Any

import yaml
from dotenv import load_dotenv
from pydantic import ValidationError

from gitgrounded.config.schema import Config
from gitgrounded.errors import ConfigError

ENV_PATTERN = re.compile(r"\$\{([A-Za-z_][A-Za-z0-9_]*)(?::-([^}]*))?\}")


def load_defaults() -> dict[str, Any]:
    text = resources.files("gitgrounded.config").joinpath("defaults.yaml").read_text(encoding="utf-8")
    return yaml.safe_load(text) or {}


def deep_merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    out = dict(base)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(out.get(key), dict):
            out[key] = deep_merge(out[key], value)
        else:
            out[key] = value
    return out


def expand_env(value: Any, path: str = "", strict: bool = False) -> Any:
    if isinstance(value, str):

        def repl(m: re.Match) -> str:
            name, default = m.group(1), m.group(2)
            if name in os.environ:
                return os.environ[name]
            if default is not None:
                return default
            if strict:
                raise ConfigError(f"{path or 'value'}: environment variable {name} is not set")
            return ""

        return ENV_PATTERN.sub(repl, value)
    if isinstance(value, dict):
        return {k: expand_env(v, f"{path}.{k}" if path else str(k), strict) for k, v in value.items()}
    if isinstance(value, list):
        return [expand_env(v, f"{path}[{i}]", strict) for i, v in enumerate(value)]
    return value


def format_validation_error(err: ValidationError, source: str) -> str:
    lines = [f"invalid config in {source}:"]
    for e in err.errors():
        loc = ".".join(str(p) for p in e["loc"] if not str(p).startswith("function-"))
        lines.append(f"  {loc}: {e['msg']}")
    return "\n".join(lines)


def parse_config(data: dict[str, Any] | None, source: str = "gitgrounded.yml", strict_env: bool = False) -> Config:
    data = data or {}
    if not isinstance(data, dict):
        raise ConfigError(f"{source}: top level must be a mapping")
    from gitgrounded.providers.env import role_layer

    merged = deep_merge(deep_merge(load_defaults(), role_layer()), data)
    merged = expand_env(merged, strict=strict_env)
    try:
        return Config.model_validate(merged)
    except ValidationError as e:
        raise ConfigError(format_validation_error(e, source)) from e


def load_config(path: Path | None, strict_env: bool = False) -> Config:
    load_dotenv(Path.cwd() / ".env", override=False)
    if path is None:
        return parse_config({}, "defaults", strict_env)
    load_dotenv(path.parent / ".env", override=False)
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
    except yaml.YAMLError as e:
        raise ConfigError(f"{path}: YAML parse error: {e}") from e
    except OSError as e:
        raise ConfigError(f"cannot read {path}: {e}") from e
    return parse_config(data, str(path), strict_env)


def config_json_schema() -> dict[str, Any]:
    return Config.model_json_schema()
