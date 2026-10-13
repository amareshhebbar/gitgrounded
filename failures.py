import argparse, csv, json, os, re, subprocess, sys
from concurrent.futures import ThreadPoolExecutor
import yaml

OUT = "out"


def default_targets(version):
    cfg = yaml.safe_load(open("gitgrounded.yml"))
    names = list((cfg.get("targets") or {}).keys())
    if version:
        return [n for n in names if n.endswith("_" + version)]
    return [n for n in names if not re.search(r"_(v\d|a2a)$", n) and n not in ("support_tools", "concierge")]


def run(target):
    path = f"{OUT}/{target}.json"
    subprocess.run(
        ["gitgrounded", "check", target, "--suite", target, "--json-out", path, "--fail-on", "never", "--format", "json"],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )
    return target, path


def extract(target, path):
    rows = []
    try:
        data = json.load(open(path))
    except Exception as e:
        return [dict(target=target, case="", why="no report: " + str(e), assertion="", question="", answer="")]
    for c in data.get("cases", []):
        head = c.get("head") or {}
        if not head.get("failed") and not c.get("reasons"):
            continue
        if not head.get("failed"):
            continue
        for t in head.get("trials", []):
            tr = t.get("transcript") or {}
            fails = [a for a in t.get("assertions", []) if not a.get("passed")]
            judges = "; ".join(j.get("reason", "") for j in t.get("judges", []) if j.get("score", 1) < 0.5)
            body = (tr.get("request") or {}).get("body") or {}
            out = tr.get("output")
            ans = out.get("answer") if isinstance(out, dict) else out
            if not fails and not tr.get("error"):
                if not judges:
                    continue
            for a in fails or [dict(type="judge", message=judges)]:
                rows.append(dict(
                    target=target,
                    case=c["case"]["id"],
                    why=a.get("type", ""),
                    assertion=(a.get("message") or "")[:300],
                    question=body.get("message", ""),
                    answer=str(ans or tr.get("error") or "")[:400].replace("\n", " "),
                ))
    return rows


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("targets", nargs="*")
    ap.add_argument("--version")
    ap.add_argument("--parse-only", action="store_true")
    ap.add_argument("--jobs", type=int, default=2)
    a = ap.parse_args()
    os.makedirs(OUT, exist_ok=True)
    targets = a.targets or default_targets(a.version)
    if a.parse_only:
        done = [(t, f"{OUT}/{t}.json") for t in targets]
    else:
        with ThreadPoolExecutor(a.jobs) as ex:
            done = list(ex.map(run, targets))
    rows = []
    for t, p in done:
        rows += extract(t, p)
    with open(f"{OUT}/failures.csv", "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["target", "case", "why", "assertion", "question", "answer"])
        w.writeheader()
        w.writerows(rows)
    with open(f"{OUT}/failures.md", "w") as f:
        f.write(f"# Failing cases: {len(rows)}\n\n")
        cur = None
        for r in rows:
            if r["target"] != cur:
                cur = r["target"]
                f.write(f"\n## {cur}\n\n")
            f.write(f"- {r['case']} [{r['why']}] {r['assertion']}\n  Q: {r['question']}\n  A: {r['answer']}\n")
    per = {}
    for r in rows:
        per.setdefault(r["target"], set()).add(r["case"])
    for t, cs in per.items():
        print(f"{t}: {len(cs)} failing")
        print("  rerun: gitgrounded check %s --suite %s --case %s" % (t, t, ",".join(sorted(cs))))
    print(f"total failing rows: {len(rows)}")
    print(f"files: {OUT}/failures.csv {OUT}/failures.md")


main()
