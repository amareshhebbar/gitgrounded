import json
import re
from typing import Any, TypeVar

from pydantic import BaseModel, ValidationError

from gitgrounded.errors import ProviderError
from gitgrounded.providers.base import BaseProvider, Completion

T = TypeVar("T", bound=BaseModel)

FENCE = re.compile(r"^```(?:json)?\s*|\s*```$", re.M)


def extract_json(text: str) -> Any:
    cleaned = FENCE.sub("", (text or "").strip()).strip()
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        pass
    for open_ch, close_ch in (("{", "}"), ("[", "]")):
        start = cleaned.find(open_ch)
        end = cleaned.rfind(close_ch)
        if start != -1 and end > start:
            try:
                return json.loads(cleaned[start : end + 1])
            except json.JSONDecodeError:
                continue
    raise ValueError("response is not valid JSON")


def complete_json(
    provider: BaseProvider,
    system: str,
    user: str,
    task: str,
    meta: dict[str, Any] | None = None,
    schema: type[T] | None = None,
    repairs: int = 2,
) -> tuple[Any, Completion]:
    messages = [{"role": "user", "content": user}]
    last_error: Exception | None = None
    for _ in range(repairs + 1):
        completion = provider.complete(system, messages, json_mode=True, task=task, meta=meta)
        try:
            data = extract_json(completion.text)
            if schema is not None:
                data = schema.model_validate(data)
            return data, completion
        except (ValueError, ValidationError) as e:
            last_error = e
            messages = [
                {"role": "user", "content": user},
                {"role": "assistant", "content": completion.text[:4000]},
                {
                    "role": "user",
                    "content": f"That response was invalid: {str(e)[:500]}. Return only the corrected JSON object.",
                },
            ]
    raise ProviderError(f"{task}: model never returned valid JSON: {last_error}")
