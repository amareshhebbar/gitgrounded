from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from gitgrounded.canonical import content_hash

ExpectationKind = Literal["must", "must_not", "should", "refuse", "tool_call", "format"]


class Expectation(BaseModel):
    model_config = ConfigDict(extra="ignore")
    kind: ExpectationKind = "must"
    text: str
    behavior_id: str | None = None
    tool: str | None = None


class Case(BaseModel):
    model_config = ConfigDict(extra="ignore")
    id: str
    input: str | list[dict[str, str]]
    tags: list[str] = Field(default_factory=list)
    behaviors: list[str] = Field(default_factory=list)
    cell: dict[str, str] = Field(default_factory=dict)
    expectations: list[Expectation] = Field(default_factory=list)
    reference: str | None = None
    context: dict[str, Any] = Field(default_factory=dict)
    assertions: list[dict[str, Any]] = Field(default_factory=list)
    origin: Literal["human", "synth", "log", "diff"] = "human"
    reviewed: bool = False
    meta: dict[str, Any] = Field(default_factory=dict)

    def input_text(self) -> str:
        if isinstance(self.input, str):
            return self.input
        return "\n".join(f"{m.get('role', 'user')}: {m.get('content', '')}" for m in self.input)

    def last_user_message(self) -> str:
        if isinstance(self.input, str):
            return self.input
        users = [m.get("content", "") for m in self.input if m.get("role", "user") == "user"]
        return users[-1] if users else ""

    def messages(self) -> list[dict[str, str]]:
        if isinstance(self.input, str):
            return [{"role": "user", "content": self.input}]
        return [{"role": m.get("role", "user"), "content": m.get("content", "")} for m in self.input]

    def hash(self) -> str:
        return content_hash(self.model_dump(mode="json", exclude={"reviewed", "meta"}))


def dataset_hash(cases: list[Case]) -> str:
    return content_hash(sorted(c.hash() for c in cases))
