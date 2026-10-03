import os
import random
import threading
import time
from dataclasses import dataclass, field
from typing import Any

from gitgrounded.config.schema import ProviderCfg
from gitgrounded.errors import BudgetExceeded, ProviderError
from gitgrounded.exec.ratelimit import shared


@dataclass
class Completion:
    text: str
    model: str
    response_id: str | None = None
    input_tokens: int = 0
    output_tokens: int = 0
    latency_ms: float = 0.0
    provider: str = ""
    extra: dict[str, Any] = field(default_factory=dict)


def is_offline() -> bool:
    flag = os.environ.get("GITGROUNDED_OFFLINE", "").strip().lower()
    mode = os.environ.get("GITGROUNDED_MODE", "").strip().lower()
    return flag in ("1", "true", "yes") or mode == "test"


class BaseProvider:
    name = "base"

    def __init__(self, cfg: ProviderCfg):
        self.cfg = cfg
        self._sem = threading.BoundedSemaphore(max(1, cfg.max_concurrency))

    def _complete(self, system: str, messages: list[dict[str, str]], json_mode: bool) -> Completion:
        raise NotImplementedError

    def complete(
        self,
        system: str,
        messages: list[dict[str, str]],
        json_mode: bool = False,
        task: str | None = None,
        meta: dict[str, Any] | None = None,
    ) -> Completion:
        attempts = max(1, self.cfg.max_retries)
        last: Exception | None = None
        limiter = shared(f"provider:{self.name}:{self.cfg.base_url or ''}", self.cfg.requests_per_minute)
        for attempt in range(attempts):
            try:
                if limiter:
                    limiter.acquire()
                with self._sem:
                    start = time.perf_counter()
                    result = self._complete(system, messages, json_mode)
                    if not result.latency_ms:
                        result.latency_ms = (time.perf_counter() - start) * 1000
                    result.provider = self.name
                    _record(result)
                    return result
            except ProviderError:
                raise
            except BudgetExceeded:
                raise
            except Exception as e:
                last = e
                if attempt + 1 < attempts:
                    delay = _retry_after(e) or min(30.0, (2**attempt) + random.random())
                    time.sleep(delay)
        raise ProviderError(f"{self.name}/{self.cfg.model} failed after {attempts} attempts: {last}") from last


def _record(result: "Completion") -> None:
    from gitgrounded.providers.usage import USAGE

    USAGE.record(result.model, result.input_tokens, result.output_tokens)
    USAGE.check()


def _retry_after(e: Exception) -> float | None:
    response = getattr(e, "response", None)
    headers = getattr(response, "headers", None)
    if not headers:
        return None
    value = headers.get("retry-after") or headers.get("Retry-After")
    try:
        return min(60.0, float(value)) if value else None
    except (TypeError, ValueError):
        return None


_CACHE: dict[str, BaseProvider] = {}
_LOCK = threading.Lock()


def resolve_cfg(cfg: ProviderCfg) -> ProviderCfg:
    from gitgrounded.providers import env

    provider = env.canonical(cfg.provider)
    update: dict[str, Any] = {"provider": provider}
    if provider != "mock" and cfg.model in ("", "mock", "default"):
        update["model"] = env.default_model(provider)
    if not cfg.base_url and provider in ("ollama", "custom", "deepseek", "groq"):
        update["base_url"] = env.base_url(provider)
    if cfg.requests_per_minute is None and provider != "mock":
        rpm = env.rpm(provider)
        if rpm:
            update["requests_per_minute"] = rpm
    return cfg.model_copy(update=update)


def build_provider(cfg: ProviderCfg) -> BaseProvider:
    cfg = resolve_cfg(cfg)
    effective = cfg if not is_offline() else cfg.model_copy(update={"provider": "mock"})
    key = effective.model_dump_json()
    with _LOCK:
        if key in _CACHE:
            return _CACHE[key]
        if effective.provider == "mock":
            from gitgrounded.providers.mock import MockProvider

            provider: BaseProvider = MockProvider(effective)
        elif effective.provider in ("openai", "groq", "deepseek", "custom"):
            from gitgrounded.providers.openai_compat import OpenAICompatProvider

            provider = OpenAICompatProvider(effective)
        elif effective.provider == "anthropic":
            from gitgrounded.providers.anthropic import AnthropicProvider

            provider = AnthropicProvider(effective)
        elif effective.provider == "ollama":
            from gitgrounded.providers.ollama import OllamaProvider

            provider = OllamaProvider(effective)
        else:
            raise ProviderError(f"unknown provider {effective.provider}")
        _CACHE[key] = provider
        return provider


def reset_provider_cache() -> None:
    with _LOCK:
        _CACHE.clear()
