import requests

from gitgrounded.providers.base import BaseProvider, Completion


class OllamaProvider(BaseProvider):
    name = "ollama"

    def _complete(self, system: str, messages: list[dict[str, str]], json_mode: bool) -> Completion:
        base_url = (self.cfg.base_url or "http://localhost:11434").rstrip("/")
        payload = {
            "model": self.cfg.model,
            "messages": ([{"role": "system", "content": system}] if system else []) + messages,
            "stream": False,
            "think": False,
            "keep_alive": "30m",
            "options": {"temperature": self.cfg.temperature},
        }
        if self.cfg.seed is not None:
            payload["options"]["seed"] = self.cfg.seed
        if json_mode:
            payload["format"] = "json"
        resp = requests.post(f"{base_url}/api/chat", json=payload, timeout=self.cfg.timeout_s)
        resp.raise_for_status()
        data = resp.json()
        return Completion(
            text=data.get("message", {}).get("content", ""),
            model=data.get("model", self.cfg.model),
            response_id=data.get("created_at"),
            input_tokens=data.get("prompt_eval_count", 0) or 0,
            output_tokens=data.get("eval_count", 0) or 0,
        )
