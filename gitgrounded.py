import os
import sys
import argparse
import json

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

from gitgrounded.config import load_yaml, get_mode
from gitgrounded import runner
from gitgrounded.generate import generate_cases
from gitgrounded.judge import judge_case
from gitgrounded.report import aggregate, write_report
from app.triage import run as app_run, load_policy


DEMO_SCENARIOS = {
    "safe": "test/safe-wording-tweak",
    "citation": "test/drop-citation-rule",
    "model": "test/model-downgrade",
}


def parse_args():
    parser = argparse.ArgumentParser(description="GitGrounded: catch AI regressions from prompt and model changes")
    parser.add_argument("--old", help="old git ref, e.g. main")
    parser.add_argument("--new", help="new git ref, e.g. my-change")
    parser.add_argument("--demo", choices=DEMO_SCENARIOS.keys(), help="shortcut: baseline vs a named demo branch")
    parser.add_argument("--seed-cases", default=os.path.join(BASE_DIR, "data", "seed_cases.json"))
    parser.add_argument("--report", default=os.path.join(BASE_DIR, "report.json"))
    parser.add_argument("--quick", action="store_true", help="fewer seed and generated cases, for fast local iteration")
    args = parser.parse_args()

    if args.demo:
        args.old = "baseline"
        args.new = DEMO_SCENARIOS[args.demo]
    elif not args.old or not args.new:
        parser.error("either --demo {safe,citation,model} or both --old and --new are required")

    return args


def main():
    args = parse_args()
    mode = get_mode()
    providers_config = load_yaml(os.path.join(BASE_DIR, "config", "providers.yaml"))

    with open(args.seed_cases) as f:
        seed_cases = json.load(f)

    if args.quick:
        seed_cases = seed_cases[:3]

    print(f"comparing {args.old} -> {args.new}")
    print("running seed cases on both versions...")
    run_pair = runner.run_both(app_run, seed_cases, args.old, args.new, BASE_DIR, mode, providers_config)

    print()
    print("=" * 60)
    print(f"detected change ({args.old} -> {args.new}):")
    print("=" * 60)
    if run_pair["diff"].strip():
        print(run_pair["diff"])
    else:
        print("(no diff in prompts/triage.txt or config/model.yaml)")
    print("=" * 60)
    print()

    count_hint = "3 to 5" if args.quick else "15 to 20"
    print(f"asking AI to write {count_hint} test cases targeted at this change...")
    generated = generate_cases(run_pair["diff"], mode, providers_config, count_hint=count_hint)
    print(f"got {len(generated)} generated test cases")

    old_version = runner.load_version(args.old, BASE_DIR, mode)
    new_version = runner.load_version(args.new, BASE_DIR, mode)

    print("running generated cases on both versions...")
    generated_results_old = [runner.run_case(app_run, c["input"], old_version, providers_config) for c in generated]
    generated_results_new = [runner.run_case(app_run, c["input"], new_version, providers_config) for c in generated]

    policy = load_policy()

    all_old = run_pair["old_results"] + generated_results_old
    all_new = run_pair["new_results"] + generated_results_new

    print(f"judging {len(all_old)} old-vs-new answer pairs...")
    judged = [
        judge_case(policy, old_r["input"], old_r, new_r, mode, providers_config)
        for old_r, new_r in zip(all_old, all_new)
    ]

    summary, scored_cases = aggregate(judged)
    write_report(summary, scored_cases, generated, run_pair["diff"], args.old, args.new, path=args.report)

    print()
    print(f"GitGrounded verdict: {summary['verdict']}")
    print(f"PASS {summary['pass_count']} / WARN {summary['warn_count']} / FAIL {summary['fail_count']} / total {summary['total_cases']}")
    print(f"avg groundedness: {summary['avg_groundedness']}  avg meaning_drift: {summary['avg_meaning_drift']}")
    print(f"report written to {args.report}")

    if summary["verdict"] == "FAIL":
        sys.exit(1)


if __name__ == "__main__":
    main()