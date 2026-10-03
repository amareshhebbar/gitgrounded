import importlib
import inspect
import json
import os
import sys
import time
import traceback


def _call(fn, case_input, ctx):
    try:
        params = [
            p
            for p in inspect.signature(fn).parameters.values()
            if p.kind in (p.POSITIONAL_ONLY, p.POSITIONAL_OR_KEYWORD)
        ]
        names = [p.name for p in params]
    except (TypeError, ValueError):
        names = ["input", "ctx"]
    if "message" in names and "prompt_text" in names:
        files = ctx.get("files", {})
        prompt = next((v for k, v in files.items() if k.endswith(".txt")), None)
        msg = case_input if isinstance(case_input, str) else case_input[-1]["content"]
        return fn(message=msg, prompt_text=prompt)
    if len(names) >= 2:
        return fn(case_input, ctx)
    return fn(case_input)


def main() -> None:
    root, entry = sys.argv[1], sys.argv[2]
    real_stdout = sys.stdout
    sys.stdout = sys.stderr
    os.chdir(root)
    if root not in sys.path:
        sys.path.insert(0, root)
    module_name, _, fn_name = entry.partition(":")
    framework = sys.argv[3] if len(sys.argv) > 3 and sys.argv[3] not in ("", "function") else None
    try:
        factory = fn_name.endswith("()")
        fn = getattr(importlib.import_module(module_name), (fn_name[:-2] if factory else fn_name) or "run")
        if factory:
            fn = fn()
        load_error = None
    except Exception:
        fn = None
        load_error = traceback.format_exc()
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        req = json.loads(line)
        start = time.perf_counter()
        if fn is None:
            resp = {"id": req["id"], "ok": False, "error": f"cannot import {entry} from {root}:\n{load_error}"}
        else:
            try:
                if framework:
                    from gitgrounded.targets.frameworks import invoke

                    result = invoke(fn, req["input"], framework, req.get("ctx", {}).get("options", {}))
                else:
                    result = _call(fn, req["input"], req.get("ctx", {}))
                resp = {"id": req["id"], "ok": True, "result": result}
            except Exception:
                resp = {"id": req["id"], "ok": False, "error": traceback.format_exc()[-4000:]}
        resp["latency_ms"] = (time.perf_counter() - start) * 1000
        real_stdout.write(json.dumps(resp, default=str, ensure_ascii=False) + "\n")
        real_stdout.flush()


if __name__ == "__main__":
    main()
