from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


ProviderName = Literal["anthropic", "claude", "openai", "groq", "deepseek", "custom", "openai_compat", "ollama", "mock"]


class ProviderCfg(Strict):
    provider: ProviderName = "mock"
    model: str = "mock"
    base_url: str | None = None
    api_key_env: str | None = None
    temperature: float = 0.0
    max_tokens: int = 2048
    seed: int | None = None
    max_concurrency: int = 8
    timeout_s: float = 120.0
    max_retries: int = 4
    requests_per_minute: float | None = None


class EmbeddingCfg(Strict):
    provider: Literal["hash", "local", "openai_compat"] = "hash"
    model: str = "sentence-transformers/all-MiniLM-L6-v2"
    base_url: str | None = None
    api_key_env: str | None = None
    dims: int = 512


class ProvidersCfg(Strict):
    judge: ProviderCfg = Field(default_factory=ProviderCfg)
    generator: ProviderCfg = Field(default_factory=ProviderCfg)
    validator: ProviderCfg | None = None
    panel: list[ProviderCfg] = Field(default_factory=list)
    embeddings: EmbeddingCfg = Field(default_factory=EmbeddingCfg)


class PythonTarget(Strict):
    type: Literal["python", "agent", "framework"]
    entry: str
    framework: str = "auto"
    options: dict[str, Any] = Field(default_factory=dict)
    watch: list[str] = Field(default_factory=list)
    timeout_s: float = 300.0
    env: dict[str, str] = Field(default_factory=dict)


class HttpTarget(Strict):
    type: Literal["http"]
    url: str
    method: Literal["POST", "PUT", "GET"] = "POST"
    headers: dict[str, str] = Field(default_factory=dict)
    body: Any = Field(default_factory=lambda: {"message": "{{input}}"})
    output: str | None = None
    context_path: str | None = None
    tool_calls_path: str | None = None
    timeout_s: float = 60.0
    watch: list[str] = Field(default_factory=list)


class OpenAIChatTarget(Strict):
    type: Literal["openai_chat"]
    system_prompt_file: str | None = None
    system_prompt: str | None = None
    template_vars: dict[str, str] = Field(default_factory=dict)
    model: ProviderCfg = Field(default_factory=ProviderCfg)
    model_file: str | None = None
    model_key: str | None = None
    json_mode: bool = False
    watch: list[str] = Field(default_factory=list)


class McpTarget(Strict):
    type: Literal["mcp"]
    transport: Literal["stdio", "http"] = "stdio"
    command: list[str] = Field(default_factory=list)
    url: str | None = None
    env: dict[str, str] = Field(default_factory=dict)
    tools_file: str | None = None
    agent: ProviderCfg | None = None
    watch: list[str] = Field(default_factory=list)
    timeout_s: float = 60.0


class A2ATarget(Strict):
    type: Literal["a2a"]
    url: str
    protocol: Literal["auto", "0.3", "1.0"] = "auto"
    headers: dict[str, str] = Field(default_factory=dict)
    timeout_s: float = 120.0
    watch: list[str] = Field(default_factory=list)


class AdkTarget(Strict):
    type: Literal["adk"]
    base_url: str = "http://127.0.0.1:8000"
    app_name: str
    user_id: str = "gitgrounded"
    headers: dict[str, str] = Field(default_factory=dict)
    timeout_s: float = 180.0
    watch: list[str] = Field(default_factory=list)


TargetCfg = Annotated[
    PythonTarget | HttpTarget | OpenAIChatTarget | McpTarget | A2ATarget | AdkTarget, Field(discriminator="type")
]


class CertifyCfg(Strict):
    trap_threshold: float = 0.9
    traps: int = 4
    min_cases: int = 10
    require_sealed_suite: bool = True
    pdf: bool = True
    verify_url: str | None = None


class AssertionCfg(BaseModel):
    model_config = ConfigDict(extra="allow")
    type: str


class JudgeCfg(Strict):
    type: Literal["rubric", "pairwise"]
    rubric: str = "grounded_answer"
    provider: ProviderCfg | None = None
    swap: bool = True


class GenerateCfg(Strict):
    enabled: bool = True
    count: int = 6
    domain: str = ""


class CoverageSources(Strict):
    system_prompt: str | None = None
    prompts: list[str] = Field(default_factory=list)
    documents: list[str] = Field(default_factory=list)
    tools: list[str] = Field(default_factory=list)
    logs: str | None = None


class MutationCfg(Strict):
    operators: list[str] = Field(
        default_factory=lambda: ["delete_rule", "negate_rule", "weaken_rule", "swap_value", "drop_section"]
    )
    max_mutants: int = 25
    target_file: str | None = None
    model_file: str | None = None
    model_key: str | None = None
    downgrade_to: str | None = None
    repair_rounds: int = 1


class CoverageCfg(Strict):
    sources: CoverageSources = Field(default_factory=CoverageSources)
    dimensions: dict[str, list[str]] = Field(default_factory=dict)
    use_default_dimensions: bool = True
    propose_dimensions: bool = True
    apply_proposed_dimensions: bool = False
    strength: int = 2
    budget_cases: int = 120
    min_cases_per_behavior: int = 3
    oversample: float = 1.5
    mutation_target: float = 0.85
    diversity_lambda: float = 0.7
    mutation: MutationCfg = Field(default_factory=MutationCfg)
    seed: int = 7


class SuiteCfg(Strict):
    target: str
    cases: str | None = None
    assertions: list[AssertionCfg] = Field(default_factory=list)
    judges: list[JudgeCfg] = Field(default_factory=lambda: [JudgeCfg(type="rubric"), JudgeCfg(type="pairwise")])
    trials: int = 1
    context: dict[str, str] = Field(default_factory=dict)
    generate: GenerateCfg = Field(default_factory=GenerateCfg)
    coverage: CoverageCfg | None = None
    primary_metric: str = "score"


class GatesCfg(Strict):
    fail_if: list[str] = Field(default_factory=lambda: ["new_assertion_failures > 0", "fail_cases > 0"])
    warn_if: list[str] = Field(default_factory=lambda: ["warn_cases > 0", "delta.score.mean < -0.5"])


class EvidenceCfg(Strict):
    sign: Literal["auto", "sigstore", "local", "none"] = "auto"
    attest: Literal["github", "none"] = "none"
    include_transcripts: bool = True
    redact: list[str] = Field(default_factory=list)
    certify: CertifyCfg = Field(default_factory=CertifyCfg)


class ExecutionCfg(Strict):
    max_concurrency: int = 8
    mode: Literal["threads", "async"] = "threads"
    requests_per_minute: float | None = None
    budget_usd: float | None = None
    bootstrap_iterations: int = 5000
    seed: int = 1234


class ProjectCfg(Strict):
    name: str = "gitgrounded-project"
    state_dir: str = ".gitgrounded"


class Config(Strict):
    version: Literal[1] = 1
    project: ProjectCfg = Field(default_factory=ProjectCfg)
    providers: ProvidersCfg = Field(default_factory=ProvidersCfg)
    targets: dict[str, TargetCfg] = Field(default_factory=dict)
    suites: dict[str, SuiteCfg] = Field(default_factory=dict)
    coverage: CoverageCfg | None = None
    gates: GatesCfg = Field(default_factory=GatesCfg)
    evidence: EvidenceCfg = Field(default_factory=EvidenceCfg)
    execution: ExecutionCfg = Field(default_factory=ExecutionCfg)
    prices: dict[str, list[float]] = Field(default_factory=dict)

    def suite(self, name: str | None) -> tuple[str, SuiteCfg]:
        from gitgrounded.errors import ConfigError

        if not self.suites:
            raise ConfigError("no suites defined in gitgrounded.yml")
        if name is None:
            name = next(iter(self.suites))
        if name not in self.suites:
            raise ConfigError(f"unknown suite '{name}', available: {', '.join(self.suites)}")
        return name, self.suites[name]

    def target(self, name: str):
        from gitgrounded.errors import ConfigError

        if name not in self.targets:
            raise ConfigError(f"unknown target '{name}', available: {', '.join(self.targets) or 'none'}")
        return self.targets[name]

    def coverage_for(self, suite_name: str) -> CoverageCfg:
        suite = self.suites.get(suite_name)
        if suite and suite.coverage:
            return suite.coverage
        return self.coverage or CoverageCfg()
