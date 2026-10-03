import json
import os
import queue
import subprocess
import sys
import threading
import uuid
from pathlib import Path

from gitgrounded.cases.model import Case
from gitgrounded.sources.variant import Variant
from gitgrounded.targets.base import Target, Transcript, error_transcript, transcript_from_result


class _Worker:
    def __init__(self, root: Path, entry: str, env: dict[str, str], framework: str = ""):
        child_env = dict(os.environ)
        child_env.update(env)
        src_dir = str(Path(__file__).resolve().parents[2])
        child_env["PYTHONPATH"] = os.pathsep.join([str(root), src_dir, child_env.get("PYTHONPATH", "")]).rstrip(
            os.pathsep
        )
        child_env["PYTHONIOENCODING"] = "utf-8"
        self.proc = subprocess.Popen(
            [sys.executable, "-m", "gitgrounded.targets._worker", str(root), entry, framework],
            cwd=str(root),
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            env=child_env,
            bufsize=1,
        )
        self.lock = threading.Lock()
        self.out: queue.Queue = queue.Queue()
        self.stderr_tail: list[str] = []
        threading.Thread(target=self._read_stdout, daemon=True).start()
        threading.Thread(target=self._read_stderr, daemon=True).start()

    def _read_stdout(self) -> None:
        for line in self.proc.stdout:
            self.out.put(line)
        self.out.put(None)

    def _read_stderr(self) -> None:
        for line in self.proc.stderr:
            self.stderr_tail.append(line)
            if len(self.stderr_tail) > 50:
                self.stderr_tail.pop(0)

    def call(self, payload: dict, timeout: float) -> dict:
        with self.lock:
            if self.proc.poll() is not None:
                return {"ok": False, "error": "worker exited:\n" + "".join(self.stderr_tail)}
            self.proc.stdin.write(json.dumps(payload, ensure_ascii=False) + "\n")
            self.proc.stdin.flush()
            try:
                line = self.out.get(timeout=timeout)
            except queue.Empty:
                self.proc.kill()
                return {"ok": False, "error": f"timeout after {timeout}s"}
            if line is None:
                return {"ok": False, "error": "worker exited:\n" + "".join(self.stderr_tail)}
            return json.loads(line)

    def close(self) -> None:
        try:
            self.proc.stdin.close()
            self.proc.wait(timeout=5)
        except Exception:
            self.proc.kill()


class PythonTarget(Target):
    kind = "python"

    def __init__(self, name: str, cfg):
        self.name = name
        self.cfg = cfg
        self._workers: dict[str, _Worker] = {}
        self._lock = threading.Lock()

    def describe(self) -> dict:
        return {
            "name": self.name,
            "kind": self.cfg.type,
            "entry": self.cfg.entry,
            "framework": self.cfg.framework if self.cfg.type == "framework" else None,
            "watch": self.cfg.watch,
        }

    def supports_mutation(self) -> bool:
        return True

    def _worker(self, variant: Variant) -> _Worker:
        key = f"{variant.content_hash}:{variant.root}"
        with self._lock:
            w = self._workers.get(key)
            if w is None or w.proc.poll() is not None:
                framework = self.cfg.framework if self.cfg.type == "framework" else ""
                w = _Worker(variant.root, self.cfg.entry, self.cfg.env, framework)
                self._workers[key] = w
            return w

    def invoke(self, case: Case, variant: Variant, trial: int) -> Transcript:
        ctx = {
            "options": self.cfg.options,
            "files": variant.files,
            "variant": variant.name,
            "root": str(variant.root),
            "overlay": variant.overlay,
            "trial": trial,
            "case_id": case.id,
            "context": case.context,
        }
        request = {"input": case.input, "entry": self.cfg.entry}
        resp = self._worker(variant).call({"id": uuid.uuid4().hex, "input": case.input, "ctx": ctx}, self.cfg.timeout_s)
        if not resp.get("ok"):
            return error_transcript(case, variant, trial, request, resp.get("error", "unknown error"))
        return transcript_from_result(case, variant, trial, request, resp.get("result"), resp.get("latency_ms", 0.0))

    def close(self) -> None:
        with self._lock:
            for w in self._workers.values():
                w.close()
            self._workers.clear()
