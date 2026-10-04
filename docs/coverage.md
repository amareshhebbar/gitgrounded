# Automatic benchmark synthesis

The problem: a real system prompt covers many topics, rules, formats and refusal boundaries. Writing a test suite by hand that covers all of them, under realistic and adversarial conditions, takes days, and nobody can say which rules were never tested.

GitGrounded treats the prompt as a specification and applies three software testing techniques to it.

## Pipeline

1. **Ingest** (`coverage/ingest.py`). The system prompt, documents and MCP tool lists are split into sentences with stable ids such as `prompts/system.txt#main:4`.
2. **Extract behaviors** (`coverage/extract.py`). A generator model turns sentences into atomic, testable behaviors with a kind, severity, observable success criterion and the source ids they come from. Behaviors that cite no real sentence are dropped. A second pass adds implicit behaviors (out of scope requests, prompt injection, ambiguous requests). Near duplicates are merged by embedding similarity. Behavior ids are hashes of their statement, so they stay stable across runs.
3. **Dimensions** (`coverage/dimensions.py`). Conditions under which inputs vary: style, language, difficulty, adversary type, number of turns. Override or extend them in `coverage.dimensions`.
4. **Plan** (`coverage/planner.py`). For each behavior, a greedy covering array of strength 2 (or 3) over the relevant dimensions guarantees every pair of conditions appears at least once. Budget is allocated by severity. The first cell is always a clean baseline so failures can be attributed to conditions.
5. **Synthesize** (`coverage/synthesize.py`). One call per behavior writes an input for every cell plus expectations (the oracle) derived only from the behavior's source text.
6. **Validate** (`coverage/validate.py`). A second model drops cases whose expectations invent rules, that do not target the behavior, or that are unanswerable.
7. **Diversify** (`coverage/diversity.py`). Shingle Jaccard removes near duplicates, then maximal marginal relevance over embeddings picks the final set per behavior.
8. **Logs** (`coverage/logs.py`, optional). Production messages are redacted, clustered and mapped to behaviors. Clusters without a behavior are reported as untested traffic; behaviors without traffic are reported too.
9. **Mutate** (`coverage/mutate.py`, `gitgrounded mutate`). The prompt is broken on purpose: delete a rule, negate it, weaken it, change a number, drop a section, downgrade the model. Each mutant is run against the suite. Mutation score is the share of mutants the suite detects. Surviving mutants trigger targeted synthesis once; new cases that detect the mutant are added.
10. **Minimize** (`coverage/minimize.py`). Greedy set cover keeps the smallest suite that detects the same mutants with at least the minimum cases per behavior. Run it in CI with `gitgrounded run --minimal`.
11. **Review** (`gitgrounded suite review`). A local page to accept, edit or reject cases with the keyboard. The reviewed share is reported.
12. **Version** (`coverage/suite_store.py`). Every synth writes `.gitgrounded/suites/<name>/versions/vN`. On the next synth only behaviors whose statement or source text changed are regenerated.

## Commands

```bash
gitgrounded discover --suite auto
gitgrounded synth --suite auto
gitgrounded synth --suite auto --full
gitgrounded suite review --suite auto
gitgrounded mutate --suite auto --max-mutants 20
gitgrounded suite coverage --suite auto --open
gitgrounded run --suite auto --base main --minimal
```

## Config

```yaml
suites:
  auto:
    target: app
    coverage:
      sources:
        system_prompt: prompts/system.txt
        documents: [docs/policy.md]
        tools: [tools.json]
        logs: logs/sample.jsonl
      dimensions:
        language: [en, hi]
        style: [terse, angry, typo_heavy, code_mixed_hinglish]
      strength: 2
      budget_cases: 150
      min_cases_per_behavior: 3
      mutation_target: 0.85
      mutation:
        target_file: prompts/system.txt
        model_file: config/model.yaml
        model_key: model
        downgrade_to: gpt-4.1-nano
```

## Files

```
.gitgrounded/suites/auto/
  behavior_map.json
  dimensions.json
  plan.json
  current.jsonl
  minimal.jsonl
  coverage.json
  mutation.json
  dropped.json
  logs.json
  suite.json
  versions/v1 ... vN
```

Commit the suite folder. Runs record the suite version and dataset hash, and evidence bundles include the suite, so a reader can see exactly which questions were asked.
