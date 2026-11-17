import argparse
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import kit
import report


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--results", default=str(HERE / "results"))
    args = ap.parse_args()
    results = Path(args.results)
    problems = kit.check_manifest(results)
    print(f"[1] file hashes: {'ok' if not problems else 'FAIL'}")
    for p in problems[:20]:
        print("    " + p)
    stored = kit.read_json(results / "report" / "results.json")
    fresh = json.loads(json.dumps(report.compute(results)))
    same = json.dumps(stored, sort_keys=True) == json.dumps(fresh, sort_keys=True)
    print(f"[2] every number recomputed from runs/*.json: {'ok' if same else 'FAIL'}")
    root = kit.read_json(results / "manifest.json")["root"]
    page_ok = (results / "report" / "HEADLINE.md").read_text(encoding="utf-8") == report.headline(stored, root)
    print(f"[3] HEADLINE.md matches results.json and manifest root: {'ok' if page_ok else 'FAIL'}")
    ok = not problems and same and page_ok
    print("VERIFIED" if ok else "NOT VERIFIED")
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
