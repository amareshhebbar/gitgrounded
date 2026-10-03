from typing import Any

from pydantic import BaseModel, ConfigDict, Field

SCHEMA_VERSION = "1"


class RunResult(BaseModel):
    model_config = ConfigDict(extra="allow")
    schema_version: str = SCHEMA_VERSION
    run_id: str
    created_at: str
    tool_version: str
    project: str
    suite: str
    mode: str
    target: dict[str, Any]
    base: dict[str, Any] | None = None
    head: dict[str, Any]
    diff: str = ""
    config_hash: str = ""
    dataset_hash: str = ""
    suite_version: str | None = None
    providers: dict[str, Any] = Field(default_factory=dict)
    trials: int = 1
    verdict: str
    gate_trace: list[dict[str, Any]] = Field(default_factory=list)
    counts: dict[str, int] = Field(default_factory=dict)
    metrics: dict[str, Any] = Field(default_factory=dict)
    pairwise: dict[str, Any] = Field(default_factory=dict)
    reliability: dict[str, Any] = Field(default_factory=dict)
    cost: dict[str, Any] = Field(default_factory=dict)
    latency: dict[str, Any] = Field(default_factory=dict)
    behaviors: dict[str, Any] = Field(default_factory=dict)
    coverage: dict[str, Any] | None = None
    cases: list[dict[str, Any]] = Field(default_factory=list)
    generated_cases: list[dict[str, Any]] = Field(default_factory=list)
    usage: dict[str, Any] = Field(default_factory=dict)
    seeds: dict[str, Any] = Field(default_factory=dict)
    evidence: dict[str, Any] | None = None

    def summary(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "run_id": self.run_id,
            "created_at": self.created_at,
            "tool_version": self.tool_version,
            "project": self.project,
            "suite": self.suite,
            "mode": self.mode,
            "verdict": self.verdict,
            "counts": self.counts,
            "metrics": self.metrics,
            "pairwise": self.pairwise,
            "reliability": self.reliability,
            "cost": self.cost,
            "latency": self.latency,
            "gate_trace": self.gate_trace,
            "base": self.base,
            "head": self.head,
            "config_hash": self.config_hash,
            "dataset_hash": self.dataset_hash,
            "suite_version": self.suite_version,
            "coverage": self.coverage,
            "trials": self.trials,
        }
