import json
from typing import Any

import yaml

from gitgrounded.canonical import sha256_hex
from gitgrounded.cases.model import Case
from gitgrounded.errors import ConfigError
from gitgrounded.jsonpath import jsonpath_get
from gitgrounded.providers.base import build_provider
from gitgrounded.sources.variant import Variant
from gitgrounded.targets.base import Target, Transcript, error_transcript


class OpenAIChatTarget(Target):
    kind = "openai_chat"

    def __init__(self, name: str, cfg):
        self.name = name
        self.cfg = cfg

    def describe(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "kind": "openai_chat",
            "system_prompt_file": self.cfg.system_prompt_file,
            "model": self.cfg.model.model,
            "provider": self.cfg.model.provider,
        }

    def supports_mutation(self) -> bool:
        return True

    def system_prompt(self, variant: Variant) -> str:
        if isinstance(variant.overlay.get("system_prompt"), str):
            text = variant.overlay["system_prompt"]
        elif self.cfg.system_prompt_file:
            if self.cfg.system_prompt_file in variant.files:
                text = variant.files[self.cfg.system_prompt_file]
            else:
                p = variant.root / self.cfg.system_prompt_file
                if not p.exists():
                    raise ConfigError(f"system prompt file not found: {p}")
                text = p.read_text(encoding="utf-8")
        else:
            text = self.cfg.system_prompt or ""
        for var, path in self.cfg.template_vars.items():
            value = variant.files.get(path)
            if value is None:
                p = variant.root / path
                value = p.read_text(encoding="utf-8") if p.exists() else ""
            text = text.replace("{{" + var + "}}", value)
        return text

    def model_cfg(self, variant: Variant):
        cfg = self.cfg.model
        if self.cfg.model_file and self.cfg.model_key:
            raw = variant.files.get(self.cfg.model_file)
            if raw is None:
                p = variant.root / self.cfg.model_file
                raw = p.read_text(encoding="utf-8") if p.exists() else None
            if raw is not None:
                value = jsonpath_get(yaml.safe_load(raw) or {}, self.cfg.model_key)
                if isinstance(value, str):
                    cfg = cfg.model_copy(update={"model": value})
                elif isinstance(value, dict):
                    cfg = cfg.model_copy(update=value)
        overlay = variant.overlay.get("model")
        if isinstance(overlay, str):
            cfg = cfg.model_copy(update={"model": overlay})
        elif isinstance(overlay, dict):
            cfg = cfg.model_copy(update=overlay)
        return cfg

    def invoke(self, case: Case, variant: Variant, trial: int) -> Transcript:
        try:
            system = self.system_prompt(variant)
            mcfg = self.model_cfg(variant)
        except Exception as e:
            return error_transcript(case, variant, trial, {}, str(e))
        provider = build_provider(mcfg)
        messages = case.messages()
        request = {
            "model": mcfg.model,
            "provider": mcfg.provider,
            "system_sha256": sha256_hex(system),
            "messages": messages,
        }
        try:
            comp = provider.complete(
                system,
                messages,
                json_mode=self.cfg.json_mode,
                task="target_chat",
                meta={"system": system, "user": case.last_user_message(), "json_mode": self.cfg.json_mode},
            )
        except Exception as e:
            return error_transcript(case, variant, trial, request, f"{type(e).__name__}: {e}")
        output: Any = comp.text
        if self.cfg.json_mode:
            try:
                output = json.loads(comp.text)
            except ValueError:
                output = comp.text
        return Transcript(
            case_id=case.id,
            variant=variant.name,
            trial=trial,
            request=request,
            raw_output=comp.text,
            output=output,
            latency_ms=comp.latency_ms,
            input_tokens=comp.input_tokens,
            output_tokens=comp.output_tokens,
            model=comp.model,
            provider_response_id=comp.response_id,
        )
