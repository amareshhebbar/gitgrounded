# Reference benchmark

Measures how many planted regressions an auto generated suite detects compared with the hand written suite of the same example.

```bash
export ANTHROPIC_API_KEY=... GROQ_API_KEY=...
python bench/run.py --example triage --mutants 30
```

Results go to `bench/results/<example>.md` and `.json`. Offline runs (`GITGROUNDED_OFFLINE=1`) only check the plumbing and are labeled as not real. Publish only real model results.

## Validation with real models

Measures the false alarm rate (identical refs and a harmless wording tweak must PASS) and the detection rate (a dropped citation rule and a model downgrade must FAIL), with Wilson 95 percent intervals and total spend.

```bash
export ANTHROPIC_API_KEY=... GROQ_API_KEY=...
python bench/validate.py --reps 10 --budget-usd 2
```

Results go to `bench/results/validation.md` and `.json`. Use `--allow-offline` only to check the plumbing. Publish only real results, and quote the interval, not just the rate.
