import os
import sys
import argparse
import json
import importlib

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

from gitgrounded.config import load_yaml, get_mode
from gitgrounded import runner
from gitgrounded import compare
from gitgrounded import versions
from gitgrounded.generate import generate_cases
from gitgrounded.judge import judge_case
from gitgrounded.report import aggregate, write_report


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
    parser.add_argument("--rank", nargs="+", help="git mode: --old + several refs, ranked table. endpoint mode: one endpoint/label, ranks its stored version history")
    parser.add_argument("--check", nargs="*", default=None, help="no args: read --gitgrounded-yml and check every registered target. two args: endpoint questions-file. one arg: endpoint (default questions)")
    parser.add_argument("--gitgrounded-yml", default=os.path.join(BASE_DIR, "gitgrounded.yml"), help="targets registry read by bare --check")
    parser.add_argument("--compare", help="external API URL to test live, POST {\"message\": ...} expecting JSON back")
    parser.add_argument("--label", help="name for the API under --compare, used to key its stored version history")
    parser.add_argument("--prompts", help="path to a JSON list of {\"input\": ...} test messages for --compare; defaults to seed-cases")
    parser.add_argument("--app-module", default="app.triage", help="dotted path to a module exposing run(message, prompt_text, model_config, providers_config) -> dict")
    parser.add_argument("--labels", action="store_true", help="list every stored endpoint label and its latest version number")
    parser.add_argument("--del-v", nargs="+", metavar=("LABEL", "VERSION"), help="--del-v LABEL deletes that label's whole history; --del-v LABEL N deletes just version N")
    parser.add_argument("--del-v-all", action="store_true", help="delete ALL stored endpoint version history for every label")
    parser.add_argument("--seed-cases", default=os.path.join(BASE_DIR, "data", "seed_cases.json"))
    parser.add_argument("--report", default=os.path.join(BASE_DIR, "report.json"))
    parser.add_argument("--quick", action="store_true", help="fewer seed and generated cases, for fast local iteration")
    args = parser.parse_args()

    if args.demo:
        args.old = "baseline"
        args.new = DEMO_SCENARIOS[args.demo]
    elif args.labels or args.del_v or args.del_v_all:
        pass
    elif args.check is not None:
        pass
    elif args.rank:
        if not args.old and len(args.rank) != 1:
            parser.error("--rank with multiple values requires --old (git mode); a single value ranks stored history for that endpoint/label")
    elif args.compare:
        if not args.label:
            parser.error("--compare requires --label")
    elif not args.old or not args.new:
        parser.error("either --demo {safe,citation,model}, --check, --old with --rank, --rank <endpoint>, --compare with --label, or both --old and --new are required")

    return args


def run_one(old_ref, new_ref, seed_cases, quick, mode, providers_config, app_run, load_policy, report_path):
    count_hint = "3 to 5" if quick else "15 to 20"

    print(f"comparing {old_ref} -> {new_ref}")
    print("running seed cases on both versions...")
    run_pair = runner.run_both(app_run, seed_cases, old_ref, new_ref, BASE_DIR, mode, providers_config)

    print()
    print("=" * 60)
    print(f"detected change ({old_ref} -> {new_ref}):")
    print("=" * 60)
    if run_pair["diff"].strip():
        print(run_pair["diff"])
    else:
        print("(no diff in prompts/triage.txt or config/model.yaml)")
    print("=" * 60)
    print()

    print(f"asking AI to write {count_hint} test cases targeted at this change...")
    generated = generate_cases(run_pair["diff"], mode, providers_config, count_hint=count_hint)
    print(f"got {len(generated)} generated test cases")

    old_version = runner.load_version(old_ref, BASE_DIR, mode)
    new_version = runner.load_version(new_ref, BASE_DIR, mode)

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
    write_report(summary, scored_cases, generated, run_pair["diff"], old_ref, new_ref, path=report_path)

    print()
    print(f"GitGrounded verdict: {summary['verdict']}")
    print(f"PASS {summary['pass_count']} / WARN {summary['warn_count']} / FAIL {summary['fail_count']} / total {summary['total_cases']}")
    print(f"avg groundedness: {summary['avg_groundedness']}  avg meaning_drift: {summary['avg_meaning_drift']}")
    print(f"report written to {report_path}")
    print()

    return summary


def main():
    args = parse_args()
    mode = get_mode()

    if args.del_v_all:
        count = versions.delete_all(os.path.join(BASE_DIR, ".versions"))
        print(f"deleted {count} label(s)" if count else "no stored versions found, nothing to delete")
        return

    if args.del_v:
        label = versions.safe_label(args.del_v[0])
        version_dir = os.path.join(BASE_DIR, ".versions", label)
        if len(args.del_v) >= 2:
            n = int(args.del_v[1])
            ok = versions.delete_version(version_dir, n)
            print(f"deleted v{n} for '{args.del_v[0]}'" if ok else f"v{n} not found for '{args.del_v[0]}'")
        else:
            count = versions.delete_label(version_dir)
            print(f"deleted {count} version(s) for '{args.del_v[0]}'" if count else f"no stored versions found for '{args.del_v[0]}'")
        return

    if args.labels:
        entries = versions.list_labels(os.path.join(BASE_DIR, ".versions"))
        if not entries:
            print("no stored labels yet")
        else:
            for name, latest in entries:
                print(f"{name:30s} latest: v{latest}")
        return

    providers_config = load_yaml(os.path.join(BASE_DIR, "config", "providers.yaml"))

    if args.check is not None:
        if len(args.check) >= 2:
            targets = [{"name": None, "endpoint": args.check[0], "questions": args.check[1]}]
        elif len(args.check) == 1:
            targets = [{"name": None, "endpoint": args.check[0], "questions": args.seed_cases}]
        else:
            yml_data = load_yaml(args.gitgrounded_yml)
            targets = [
                {"name": name, "endpoint": t["endpoint"], "questions": t["questions"]}
                for name, t in yml_data.get("targets", {}).items()
            ]

        any_fail = False
        for t in targets:
            label = t["name"] or t["endpoint"]
            questions_path = t["questions"] if os.path.isabs(t["questions"]) else os.path.join(BASE_DIR, t["questions"])
            with open(questions_path) as f:
                prompt_cases = json.load(f)
            messages = [c["input"] for c in prompt_cases]
            if args.quick:
                messages = messages[:3]

            print(f"--- checking '{label}' ({t['endpoint']}) ---")
            result = compare.run_compare(t["endpoint"], label, messages, mode, providers_config, BASE_DIR)
            if result["stored_only"]:
                print(f"no previous version — stored baseline as v{result['version']}")
            else:
                print(f"v{result['compared_against_version']} -> v{result['new_version']}: {result['verdict']}  (pass {result['pass_count']} / warn {result['warn_count']} / fail {result['fail_count']})")
                if result["verdict"] == "FAIL":
                    any_fail = True
            print()

        if any_fail:
            sys.exit(1)
        return

    if args.compare:
        prompts_path = args.prompts or args.seed_cases
        with open(prompts_path) as f:
            prompt_cases = json.load(f)
        messages = [c["input"] for c in prompt_cases]
        if args.quick:
            messages = messages[:3]

        result = compare.run_compare(args.compare, args.label, messages, mode, providers_config, BASE_DIR)

        if result["stored_only"]:
            print(f"no previous version found for label '{args.label}'")
            print(f"stored this run as version {result['version']} — run --compare again later to check for drift")
            return

        print(f"comparing live '{args.label}' against stored v{result['compared_against_version']}")
        print(f"stored this run as v{result['new_version']}")
        print()
        for c in result["cases"]:
            print(f"[{c['status']}] {c['input']}")
        print()
        print(f"verdict: {result['verdict']}")
        print(f"PASS {result['pass_count']} / WARN {result['warn_count']} / FAIL {result['fail_count']} / total {result['total']}")

        if result["verdict"] == "FAIL":
            sys.exit(1)
        return

    if args.rank and not args.old:
        result = compare.rank_history(args.rank[0], mode, providers_config, BASE_DIR)
        if "error" in result:
            print(result["error"])
            return
        print(f"version history for '{result['label']}' — {result['total_versions']} versions stored")
        print()
        for t in result["transitions"]:
            if t["fail"] > 0:
                plain = "got worse"
            elif t["warn"] > 0:
                plain = "mixed, worth a look"
            else:
                plain = "held steady or improved"
            print(f"v{t['from']} -> v{t['to']}: {plain}  ({t['pass']} ok / {t['warn']} mixed / {t['fail']} broke, out of {t['total']})")
        print()
        print(f"best version so far: v{result['best_version']}")
        return

    app_mod = importlib.import_module(args.app_module)
    app_run = app_mod.run
    load_policy = getattr(app_mod, "load_policy", lambda: "")

    with open(args.seed_cases) as f:
        seed_cases = json.load(f)

    if args.quick:
        seed_cases = seed_cases[:3]

    if args.rank:
        results = []
        for version in args.rank:
            report_path = os.path.join(BASE_DIR, f"report_{version.replace('/', '_')}.json")
            summary = run_one(args.old, version, seed_cases, args.quick, mode, providers_config, app_run, load_policy, report_path)
            results.append((version, summary))

        results.sort(key=lambda item: item[1]["avg_groundedness"], reverse=True)

        print("=" * 60)
        print(f"RANKING (baseline: {args.old})")
        print("=" * 60)
        for i, (version, summary) in enumerate(results, 1):
            print(f"{i}. {version:35s} {summary['verdict']:5s} groundedness {summary['avg_groundedness']:.2f}  drift {summary['avg_meaning_drift']:.2f}")
        print("=" * 60)
        print(f"best: {results[0][0]}")

        if any(s["verdict"] == "FAIL" for _, s in results):
            sys.exit(1)
    else:
        summary = run_one(args.old, args.new, seed_cases, args.quick, mode, providers_config, app_run, load_policy, args.report)
        if summary["verdict"] == "FAIL":
            sys.exit(1)


if __name__ == "__main__":
    main()