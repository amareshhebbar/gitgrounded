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


def parse_args():
    parser = argparse.ArgumentParser(description="GitGrounded: catch AI regressions from prompt and model changes")
    parser.add_argument("--old", required=True, help="old git ref, e.g. main")
    parser.add_argument("--new", required=True, help="new git ref, e.g. my-change")
    parser.add_argument("--seed-cases", default=os.path.join(BASE_DIR, "data", "seed_cases.json"))
    parser.add_argument("--report", default=os.path.join(BASE_DIR, "report.json"))
    return parser.parse_args()


def main():
    args = parse_args()
    mode = get_mode()
    providers_config = load_yaml(os.path.join(BASE_DIR, "config", "providers.yaml"))

    with open(args.seed_cases) as f:
        seed_cases = json.load(f)

    run_pair = runner.run_both(app_run, seed_cases, args.old, args.new, BASE_DIR, mode, providers_config)

    generated = generate_cases(run_pair["diff"], mode, providers_config)

    old_version = runner.load_version(args.old, BASE_DIR, mode)
    new_version = runner.load_version(args.new, BASE_DIR, mode)

    generated_results_old = [runner.run_case(app_run, c["input"], old_version, providers_config) for c in generated]
    generated_results_new = [runner.run_case(app_run, c["input"], new_version, providers_config) for c in generated]

    policy = load_policy()

    all_old = run_pair["old_results"] + generated_results_old
    all_new = run_pair["new_results"] + generated_results_new

    judged = [
        judge_case(policy, old_r["input"], old_r, new_r, mode, providers_config)
        for old_r, new_r in zip(all_old, all_new)
    ]

    summary, scored_cases = aggregate(judged)
    write_report(summary, scored_cases, generated, run_pair["diff"], args.old, args.new, path=args.report)

    print(f"GitGrounded verdict: {summary['verdict']}")
    print(f"PASS {summary['pass_count']} / WARN {summary['warn_count']} / FAIL {summary['fail_count']} / total {summary['total_cases']}")
    print(f"avg groundedness: {summary['avg_groundedness']}  avg meaning_drift: {summary['avg_meaning_drift']}")
    print(f"report written to {args.report}")

    if summary["verdict"] == "FAIL":
        sys.exit(1)


if __name__ == "__main__":
    main()
