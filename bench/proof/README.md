# GitGrounded proof bench

This folder measures one thing: can GitGrounded tell a breaking change from a harmless one on a real LLM app?

## Setup

The app is the triage example in `examples/triage`, with 10 more locked cases from `extra_cases.jsonl`. `build_repo.py` makes a git repo with one branch per scenario. Commit dates are fixed, so the branch hashes are the same on every machine.

* 20 breaking changes: dropped citation rule, removed grounding, broken JSON format, renamed fields, wrong enums, policy typos, a truncated policy, refund deflection and more.
* 20 harmless changes: small wording edits that keep the meaning.
* 3 empty commits.

Each branch runs `gitgrounded run --base baseline --head <branch> --suite core`. A breaking change should get FAIL. A harmless change should get PASS.

## Run

```bash
pip install -e ".[sign]"
cp bench/proof/.env.example bench/proof/.env
SMOKE=1 bash bench/proof/run.sh
bash bench/proof/run.sh
python bench/proof/publish.py
```

Finished scenarios are skipped, so you can stop and resume at any time. `MAX=10 bash bench/proof/run.sh` runs 10 of each group to save money.

## Verify

```bash
python -c "from huggingface_hub import snapshot_download as s; s('AmareshHebbar/GitGrounded_Bench', repo_type='dataset', local_dir='bench/proof/results')"
python bench/proof/verify.py
```

Offline mock runs (`GITGROUNDED_OFFLINE=1`) are refused, because they are not real results.
