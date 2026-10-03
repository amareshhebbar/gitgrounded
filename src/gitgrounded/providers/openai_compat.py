from gitgrounded.config.schema import ProviderCfg
from gitgrounded.errors import ProviderError
from gitgrounded.providers import env
from gitgrounded.providers.base import BaseProvider, Completion


class OpenAICompatProvider(BaseProvider):
    name = "openai_compat"

    def __init__(self, cfg: ProviderCfg):
        super().__init__(cfg)
        self.name = cfg.provider
        try:
            from openai import OpenAI
        except ImportError as e:
            raise ProviderError("openai package is required for openai compatible providers") from e
        key = env.api_key(cfg.provider, cfg.api_key_env)
        if not key and cfg.provider in env.STANDARD_KEYS:
            names = " or ".join(env.key_names(cfg.provider))
            raise ProviderError(f"{names} is not set; add it to .env or set GITGROUNDED_OFFLINE=1 for mock mode")
        base_url = cfg.base_url or env.base_url(cfg.provider)
        api_key = key
        self.client = OpenAI(api_key=api_key or "not-needed", base_url=base_url, timeout=cfg.timeout_s, max_retries=0)

    def _complete(self, system: str, messages: list[dict[str, str]], json_mode: bool) -> Completion:
        kwargs = {}
        if json_mode:
            kwargs["response_format"] = {"type": "json_object"}
        if self.cfg.seed is not None:
            kwargs["seed"] = self.cfg.seed
        payload = ([{"role": "system", "content": system}] if system else []) + messages
        resp = self.client.chat.completions.create(
            model=self.cfg.model,
            messages=payload,
            temperature=self.cfg.temperature,
            max_tokens=self.cfg.max_tokens,
            **kwargs,
        )
        usage = getattr(resp, "usage", None)
        return Completion(
            text=resp.choices[0].message.content or "",
            model=getattr(resp, "model", None) or self.cfg.model,
            response_id=getattr(resp, "id", None),
            input_tokens=getattr(usage, "prompt_tokens", 0) or 0,
            output_tokens=getattr(usage, "completion_tokens", 0) or 0,
        )
