import os
from typing import Any

ALIASES = {
    "claude": "anthropic",
    "anthropic": "anthropic",
    "openai": "openai",
    "groq": "groq",
    "deepseek": "deepseek",
    "ollama": "ollama",
    "custom": "custom",
    "openai_compat": "custom",
    "mock": "mock",
}

ENV_PREFIXES = {
    "anthropic": ["CLAUDE", "ANTHROPIC"],
    "openai": ["OPENAI"],
    "groq": ["GROQ"],
    "deepseek": ["DEEPSEEK"],
    "ollama": ["OLLAMA"],
    "custom": ["CUSTOM"],
    "mock": ["MOCK"],
}

STANDARD_KEYS = {
    "anthropic": "ANTHROPIC_API_KEY",
    "openai": "OPENAI_API_KEY",
    "groq": "GROQ_API_KEY",
    "deepseek": "DEEPSEEK_API_KEY",
}

DEFAULT_MODELS = {
    "anthropic": "claude-sonnet-4-6",
    "openai": "gpt-4.1-mini",
    "groq": "openai/gpt-oss-120b",
    "deepseek": "deepseek-flash",
    "ollama": "qwen2.5:7b",
    "custom": "default",
    "mock": "mock",
}

DEFAULT_BASE_URLS = {
    "groq": "https://api.groq.com/openai/v1",
    "deepseek": "https://api.deepseek.com/v1",
    "ollama": "http://localhost:11434",
}

ROLES = ("generator", "validator", "judge")
KNOWN = ("anthropic", "openai", "groq", "deepseek", "ollama", "custom")


def canonical(provider: str) -> str:
    p = (provider or "").strip().lower()
    if p not in ALIASES:
        raise ValueError(f"unknown provider '{provider}', use one of: claude, openai, groq, deepseek, ollama, custom")
    return ALIASES[p]


def env_field(provider: str, field: str) -> str | None:
    for prefix in ENV_PREFIXES.get(canonical(provider), []):
        value = os.environ.get(f"GITGROUNDED_{prefix}_{field}")
        if value not in (None, ""):
            return value
    return None


def api_key(provider: str, explicit_env: str | None = None) -> str | None:
    p = canonical(provider)
    if explicit_env and os.environ.get(explicit_env):
        return os.environ[explicit_env]
    value = env_field(p, "API_KEY")
    if value:
        return value
    std = STANDARD_KEYS.get(p)
    return os.environ.get(std) if std else None


def key_names(provider: str) -> list[str]:
    p = canonical(provider)
    names = [f"GITGROUNDED_{x}_API_KEY" for x in ENV_PREFIXES.get(p, [])]
    if p in STANDARD_KEYS:
        names.append(STANDARD_KEYS[p])
    return names


def base_url(provider: str) -> str | None:
    p = canonical(provider)
    return env_field(p, "BASE_URL") or DEFAULT_BASE_URLS.get(p)


def default_model(provider: str) -> str:
    p = canonical(provider)
    return env_field(p, "MODEL") or DEFAULT_MODELS.get(p, "default")


def _float(value: str | None) -> float | None:
    try:
        return float(value) if value not in (None, "") else None
    except ValueError:
        return None


def rpm(provider: str) -> float | None:
    return _float(env_field(canonical(provider), "RPM"))


def parse_spec(spec: str, temperature: float | None = None) -> dict[str, Any]:
    spec = (spec or "").strip()
    if not spec:
        raise ValueError("empty model spec")
    provider, _, model = spec.partition(":")
    p = canonical(provider)
    out: dict[str, Any] = {"provider": p, "model": model.strip() or default_model(p)}
    temp = temperature if temperature is not None else _float(env_field(p, "TEMPERATURE"))
    if temp is not None:
        out["temperature"] = temp
    return out


def role_layer() -> dict[str, Any]:
    providers: dict[str, Any] = {}
    for role in ROLES:
        spec = os.environ.get(f"GITGROUNDED_{role.upper()}")
        if spec:
            providers[role] = parse_spec(spec, _float(os.environ.get(f"GITGROUNDED_{role.upper()}_TEMPERATURE")))
    panel = os.environ.get("GITGROUNDED_PANEL")
    if panel:
        providers["panel"] = [parse_spec(s) for s in panel.split(",") if s.strip()]
    layer: dict[str, Any] = {}
    if providers:
        layer["providers"] = providers
    execution: dict[str, Any] = {}
    budget = _float(os.environ.get("GITGROUNDED_BUDGET_USD"))
    if budget is not None:
        execution["budget_usd"] = budget
    conc = os.environ.get("GITGROUNDED_CONCURRENCY")
    if conc and conc.isdigit():
        execution["max_concurrency"] = int(conc)
    trpm = _float(os.environ.get("GITGROUNDED_TARGET_RPM"))
    if trpm:
        execution["requests_per_minute"] = trpm
    mode = os.environ.get("GITGROUNDED_EXEC_MODE")
    if mode in ("threads", "async"):
        execution["mode"] = mode
    if execution:
        layer["execution"] = execution
    return layer


def target_models() -> list[dict[str, Any]]:
    raw = os.environ.get("GITGROUNDED_TARGET_MODELS", "")
    return [parse_spec(s) for s in raw.split(",") if s.strip()]


def split_specs(raw: str) -> list[str]:
    out = []
    for part in raw.split(","):
        part = part.strip()
        if part:
            out.append(part)
    return out


def status() -> list[dict[str, Any]]:
    rows = []
    for p in KNOWN:
        key = api_key(p)
        needs_key = p in STANDARD_KEYS
        rows.append(
            {
                "provider": p,
                "key": "set" if key else ("not needed" if not needs_key else "missing"),
                "base_url": base_url(p),
                "default_model": default_model(p),
                "env": key_names(p),
            }
        )
    return rows
