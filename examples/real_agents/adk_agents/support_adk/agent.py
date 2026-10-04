import os
import sys
from pathlib import Path

from google.adk.agents import LlmAgent
from google.adk.models.base_llm import BaseLlm
from google.adk.models.llm_response import LlmResponse
from google.genai import types

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
import support  # noqa: E402


def lookup_policy(topic: str) -> str:
    """Return the support policy text for a topic: refund or shipping."""
    return support.lookup_policy(topic)


class ScriptedLlm(BaseLlm):
    model: str = "scripted"

    async def generate_content_async(self, llm_request, stream: bool = False):
        last = llm_request.contents[-1]
        part = last.parts[-1]
        if part.function_response is not None:
            text = str((part.function_response.response or {}).get("result", ""))
            out = types.Part(text=support.answer_from(text))
        else:
            topic = support.topic_of(part.text or "")
            if topic:
                out = types.Part(function_call=types.FunctionCall(name="lookup_policy", args={"topic": topic}))
            else:
                out = types.Part(text=support.answer_from(None))
        yield LlmResponse(
            content=types.Content(role="model", parts=[out]),
            usage_metadata=types.GenerateContentResponseUsageMetadata(prompt_token_count=20, candidates_token_count=8),
        )


root_agent = LlmAgent(
    name="support_adk",
    model=os.environ.get("SUPPORT_ADK_MODEL") or ScriptedLlm(),
    instruction=support.SYSTEM_PROMPT,
    tools=[lookup_policy],
)
