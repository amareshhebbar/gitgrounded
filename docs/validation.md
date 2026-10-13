# Validation

GitGrounded's offline mode is a simulation. It proves the plumbing works, not that the verdicts are right with real models. This page defines what is measured with real models and how to reproduce it.

## What is measured

| question | how | pass criterion |
|---|---|---|
| Does it stay quiet when nothing changed? | Compare a ref with itself, repeated | PASS in at least 95 percent of runs |
| Does it stay quiet on a harmless edit? | Wording tweak that does not change behavior | PASS in at least 90 percent of runs |
| Does it catch a real regression? | Dropped citation rule | FAIL in at least 90 percent of runs |
| Does it catch a model downgrade? | Cheaper model swapped in | FAIL in at least 80 percent of runs |
| What does a run cost? | Summed provider spend per run | Reported, no threshold |

## How to reproduce

```bash
export ANTHROPIC_API_KEY=...
python bench/validate.py --reps 10 --budget-usd 2
```

Output is written to `bench/results/validation.md` and `bench/results/validation.json`. Each rate is reported with a Wilson 95 percent interval, so a small number of repetitions is visibly uncertain.

## Status

No real model results are published yet. Until they are, treat verdict accuracy claims as unmeasured. Run the script, read the intervals, and publish the table here with the model names and the date.

## Judge agreement

Use `gitgrounded calibrate` with a human labeled set to measure how often the judge agrees with people, and report the agreement before relying on judge based gates.
