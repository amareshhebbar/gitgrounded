from typing import Any

import support
from strands import Agent, tool
from strands.models import Model


@tool
def lookup_policy(topic: str) -> str:
    """Return the support policy text for a topic: refund or shipping."""
    return support.lookup_policy(topic)


class ScriptedModel(Model):
    def __init__(self):
        self.config: dict[str, Any] = {"model_id": "scripted"}

    def update_config(self, **model_config: Any) -> None:
        self.config.update(model_config)

    def get_config(self) -> dict[str, Any]:
        return self.config

    async def structured_output(self, output_model, prompt, system_prompt=None, **kwargs):
        raise NotImplementedError
        yield

    def _decide(self, messages) -> dict[str, Any]:
        last = messages[-1]
        for block in last.get("content", []):
            if "toolResult" in block:
                text = "".join(c.get("text", "") for c in block["toolResult"].get("content", []))
                return {"text": support.answer_from(text)}
        user_text = "".join(b.get("text", "") for b in last.get("content", []))
        topic = support.topic_of(user_text)
        if topic:
            return {"tool": {"toolUseId": "t1", "name": "lookup_policy", "input": {"topic": topic}}}
        return {"text": support.answer_from(None)}

    async def stream(self, messages, tool_specs=None, system_prompt=None, **kwargs):
        import json

        d = self._decide(messages)
        yield {"messageStart": {"role": "assistant"}}
        if "tool" in d:
            t = d["tool"]
            yield {"contentBlockStart": {"start": {"toolUse": {"toolUseId": t["toolUseId"], "name": t["name"]}}}}
            yield {"contentBlockDelta": {"delta": {"toolUse": {"input": json.dumps(t["input"])}}}}
            yield {"contentBlockStop": {}}
            yield {"messageStop": {"stopReason": "tool_use"}}
        else:
            yield {"contentBlockDelta": {"delta": {"text": d["text"]}}}
            yield {"contentBlockStop": {}}
            yield {"messageStop": {"stopReason": "end_turn"}}
        yield {
            "metadata": {
                "usage": {"inputTokens": 20, "outputTokens": 8, "totalTokens": 28},
                "metrics": {"latencyMs": 1},
            }
        }


def build_agent():
    model = support.real_model() or ScriptedModel()
    return Agent(model=model, tools=[lookup_policy], system_prompt=support.SYSTEM_PROMPT, callback_handler=None)
