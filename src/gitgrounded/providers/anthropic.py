from gitgrounded.config.schema import ProviderCfg
from gitgrounded.errors import ProviderError
from gitgrounded.providers import env
from gitgrounded.providers.base import BaseProvider, Completion

JSON_SUFFIX = "\n\nRespond with one valid JSON object only. No markdown fences, no preamble."


class AnthropicProvider(BaseProvider):
    name = "anthropic"

    def __init__(self, cfg: ProviderCfg):
        super().__init__(cfg)
        try:
            from anthropic import Anthropic
        except ImportError as e:
            raise ProviderError("anthropic package is required for the anthropic provider") from e
        api_key = env.api_key("anthropic", cfg.api_key_env)
        if not api_key:
            names = " or ".join(env.key_names("anthropic"))
            raise ProviderError(f"{names} is not set; add it to .env or set GITGROUNDED_OFFLINE=1 for mock mode")
        kwargs = {"api_key": api_key, "timeout": cfg.timeout_s, "max_retries": 0}
        base_url = cfg.base_url or env.base_url("anthropic")
        if base_url:
            kwargs["base_url"] = base_url
        self.client = Anthropic(**kwargs)

    def _complete(self, system: str, messages: list[dict[str, str]], json_mode: bool) -> Completion:
        msgs = [dict(m) for m in messages]
        if json_mode and msgs and msgs[-1]["role"] == "user":
            msgs[-1]["content"] = msgs[-1]["content"] + JSON_SUFFIX
        kwargs = {}
        if system:
            kwargs["system"] = system
        resp = self.client.messages.create(
            model=self.cfg.model,
            max_tokens=self.cfg.max_tokens,
            temperature=self.cfg.temperature,
            messages=msgs,
            **kwargs,
        )
        text = "".join(block.text for block in resp.content if getattr(block, "type", "") == "text")
        usage = getattr(resp, "usage", None)
        return Completion(
            text=text,
            model=getattr(resp, "model", None) or self.cfg.model,
            response_id=getattr(resp, "id", None),
            input_tokens=getattr(usage, "input_tokens", 0) or 0,
            output_tokens=getattr(usage, "output_tokens", 0) or 0,
        )
