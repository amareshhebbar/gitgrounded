import json
import subprocess
import yaml

from gitgrounded import cache


def _read_git_file(ref, relative_path, repo_dir):
    result = subprocess.run(
        ["git", "show", f"{ref}:{relative_path}"],
        cwd=repo_dir,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        raise FileNotFoundError(f"{relative_path} not found at ref {ref}: {result.stderr.strip()}")
    return result.stdout


def load_version(ref, base_dir, mode):
    prompt_text = _read_git_file(ref, "prompts/triage.txt", base_dir)
    model_yaml = _read_git_file(ref, "config/model.yaml", base_dir)
    model_cfg = yaml.safe_load(model_yaml)[mode]
    return {"ref": ref, "prompt_text": prompt_text, "model_config": model_cfg}


def run_case(app_run_fn, message, version, providers_config):
    cache_key = json.dumps(
        {"prompt": version["prompt_text"], "model": version["model_config"], "msg": message},
        sort_keys=True,
    )
    cached = cache.get("triage_answer", cache_key)
    if cached is not None:
        result = dict(cached)
    else:
        result = app_run_fn(
            message=message,
            prompt_text=version["prompt_text"],
            model_config=version["model_config"],
            providers_config=providers_config,
        )
        cache.set("triage_answer", result, cache_key)

    result["input"] = message
    result["ref"] = version["ref"]
    return result


def run_both(app_run_fn, cases, old_ref, new_ref, base_dir, mode, providers_config):
    old_version = load_version(old_ref, base_dir, mode)
    new_version = load_version(new_ref, base_dir, mode)

    old_results = [run_case(app_run_fn, c["input"], old_version, providers_config) for c in cases]
    new_results = [run_case(app_run_fn, c["input"], new_version, providers_config) for c in cases]

    diff = subprocess.run(
        ["git", "diff", f"{old_ref}..{new_ref}", "--", "prompts/triage.txt", "config/model.yaml"],
        cwd=base_dir,
        capture_output=True,
        text=True,
    ).stdout

    return {
        "old_ref": old_ref,
        "new_ref": new_ref,
        "diff": diff,
        "old_results": old_results,
        "new_results": new_results,
    }