# Reference benchmark

Measures how many planted regressions an auto generated suite detects compared with the hand written suite of the same example.

```bash
export ANTHROPIC_API_KEY=... GROQ_API_KEY=...
python bench/run.py --example triage --mutants 30
```

Results go to `bench/results/<example>.md` and `.json`. Offline runs (`GITGROUNDED_OFFLINE=1`) only check the plumbing and are labeled as not real. Publish only real model results.
