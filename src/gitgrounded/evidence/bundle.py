import hashlib
import hmac
import io
import json
import os
import platform
import secrets
import zipfile
from pathlib import Path
from typing import Any

from gitgrounded import __version__
from gitgrounded.canonical import canonical_bytes, canonical_str, sha256_hex
from gitgrounded.evidence.merkle import merkle_root
from gitgrounded.jsonpath import jsonpath_get_all
from gitgrounded.report.model import RunResult

BUNDLE_FORMAT = "ggb/1"
RECORD_FILES = [
    "records/cases.jsonl",
    "records/transcripts.jsonl",
    "records/judgements.jsonl",
    "records/assertions.jsonl",
]
ALWAYS_REDACT_HEADERS = {"authorization", "x-api-key", "api-key", "cookie", "proxy-authorization"}
ZIP_DATE = (1980, 1, 1, 0, 0, 0)


class Redactor:
    def __init__(self, paths: list[str]):
        self.paths = paths
        self.salt = secrets.token_bytes(16)
        self.count = 0

    def token(self, value: Any) -> str:
        self.count += 1
        digest = hmac.new(
            self.salt, json.dumps(value, sort_keys=True, default=str).encode(), hashlib.sha256
        ).hexdigest()
        return f"redacted:hmac-sha256:{digest[:32]}"

    def apply(self, record: dict[str, Any]) -> dict[str, Any]:
        rec = json.loads(json.dumps(record, default=str))
        headers = rec.get("request", {}).get("headers") if isinstance(rec.get("request"), dict) else None
        if isinstance(headers, dict):
            for k in list(headers):
                if k.lower() in ALWAYS_REDACT_HEADERS:
                    headers[k] = self.token(headers[k])
        for path in self.paths:
            self._redact_path(rec, path)
        return rec

    def _redact_path(self, rec: dict[str, Any], path: str) -> None:
        if not jsonpath_get_all(rec, path):
            return
        parts = path.lstrip("$").lstrip(".").split(".")
        node: Any = rec
        for p in parts[:-1]:
            if isinstance(node, dict) and p in node:
                node = node[p]
            else:
                return
        last = parts[-1]
        if isinstance(node, dict) and last in node:
            node[last] = self.token(node[last])


def build_records(result: RunResult, redactor: Redactor, include_transcripts: bool = True) -> dict[str, list[str]]:
    out: dict[str, list[str]] = {name: [] for name in RECORD_FILES}
    for r in result.cases:
        cid = r["case"]["id"]
        out["records/cases.jsonl"].append(
            canonical_str(
                {
                    "case_id": cid,
                    "case": r["case"],
                    "status": r["status"],
                    "reasons": r["reasons"],
                    "delta": r["delta"],
                    "pairwise_winner": r["pairwise_winner"],
                }
            )
        )
        for p_i, p in enumerate(r.get("pairwise", [])):
            out["records/judgements.jsonl"].append(
                canonical_str({"case_id": cid, "variant": "pair", "trial": p_i, "judge": "pairwise", **p})
            )
        for side in ("base", "head"):
            v = r.get(side)
            if not v:
                continue
            for t_i, t in enumerate(v["trials"]):
                tr = dict(t["transcript"])
                if not include_transcripts:
                    tr = {k: tr[k] for k in ("case_id", "variant", "trial", "error", "latency_ms", "model") if k in tr}
                    tr["raw_output_sha256"] = sha256_hex(t["transcript"].get("raw_output") or "")
                out["records/transcripts.jsonl"].append(canonical_str({"side": side, **redactor.apply(tr)}))
                for j in t["judges"]:
                    out["records/judgements.jsonl"].append(
                        canonical_str({"case_id": cid, "side": side, "trial": t_i, **j})
                    )
                for a in t["assertions"]:
                    out["records/assertions.jsonl"].append(
                        canonical_str({"case_id": cid, "side": side, "trial": t_i, **a})
                    )
    return out


def record_leaves(records: dict[str, list[str]]) -> list[bytes]:
    leaves: list[bytes] = []
    for name in RECORD_FILES:
        leaves += [line.encode("utf-8") for line in records.get(name, [])]
    return leaves


def leaves_from_files(files: dict[str, bytes]) -> list[bytes]:
    leaves: list[bytes] = []
    for name in RECORD_FILES:
        data = files.get(name, b"")
        leaves += [line for line in data.split(b"\n") if line]
    return leaves


def ci_environment() -> dict[str, Any]:
    keys = [
        "GITHUB_ACTIONS",
        "GITHUB_REPOSITORY",
        "GITHUB_SHA",
        "GITHUB_REF",
        "GITHUB_WORKFLOW_REF",
        "GITHUB_RUN_ID",
        "GITHUB_RUN_ATTEMPT",
        "GITHUB_SERVER_URL",
        "GITLAB_CI",
        "CI_PROJECT_PATH",
        "CI_COMMIT_SHA",
        "CI_PIPELINE_ID",
    ]
    return {k: os.environ[k] for k in keys if os.environ.get(k)}


def _zip_bytes(files: dict[str, bytes]) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", compression=zipfile.ZIP_DEFLATED) as z:
        for name in sorted(files):
            info = zipfile.ZipInfo(name, date_time=ZIP_DATE)
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o644 << 16
            z.writestr(info, files[name])
    return buf.getvalue()


def build_bundle(
    result: RunResult,
    out_path: Path,
    config_resolved: dict[str, Any],
    suite_files: dict[str, bytes],
    report_html_fn,
    redact: list[str],
    include_transcripts: bool,
    signer,
) -> dict[str, Any]:
    redactor = Redactor(redact)
    records = build_records(result, redactor, include_transcripts)
    root = merkle_root(record_leaves(records))
    summary = result.summary()
    summary_bytes = canonical_bytes(summary)
    provenance = {
        "merkle_root": root,
        "summary_sha256": sha256_hex(summary_bytes),
        "bundle_format": BUNDLE_FORMAT,
        "records": {k: len(v) for k, v in records.items()},
    }
    report_html = report_html_fn(result, provenance).encode("utf-8")
    files: dict[str, bytes] = {
        name: ("\n".join(lines) + ("\n" if lines else "")).encode("utf-8") for name, lines in records.items()
    }
    files["summary.json"] = summary_bytes
    files["inputs/config.resolved.json"] = canonical_bytes(config_resolved)
    files["inputs/change.diff"] = (result.diff or "").encode("utf-8")
    for name, data in suite_files.items():
        files[f"inputs/suite/{name}"] = data
    files["merkle.json"] = canonical_bytes(
        {
            "algorithm": "sha256",
            "leaf_prefix": "00",
            "node_prefix": "01",
            "files": RECORD_FILES,
            "root": root,
            "leaves": sum(len(v) for v in records.values()),
        }
    )
    files["report.html"] = report_html
    base = result.base or {}
    head = result.head or {}
    manifest = {
        "bundle_format": BUNDLE_FORMAT,
        "tool": {"name": "gitgrounded", "version": __version__},
        "run_id": result.run_id,
        "created_at": result.created_at,
        "project": result.project,
        "suite": result.suite,
        "suite_version": result.suite_version,
        "mode": result.mode,
        "verdict": result.verdict,
        "counts": result.counts,
        "base": {"name": base.get("name"), "sha": base.get("sha"), "content_hash": base.get("content_hash")}
        if base
        else None,
        "head": {"name": head.get("name"), "sha": head.get("sha"), "content_hash": head.get("content_hash")},
        "config_hash": result.config_hash,
        "dataset_hash": result.dataset_hash,
        "judge": {k: result.providers.get("judge", {}).get(k) for k in ("provider", "model", "temperature")},
        "offline": result.providers.get("offline"),
        "models_used": sorted(result.usage.get("models", {}).keys()),
        "merkle_root": root,
        "summary_sha256": provenance["summary_sha256"],
        "redactions": redactor.count,
        "transcripts_included": include_transcripts,
        "environment": {"python": platform.python_version(), "platform": platform.platform(terse=True)},
        "ci": ci_environment(),
        "files": {name: sha256_hex(data) for name, data in sorted(files.items())},
    }
    manifest_bytes = canonical_bytes(manifest)
    files["manifest.json"] = manifest_bytes
    sig_files, sig_info = signer.sign(manifest_bytes) if signer is not None else ({}, {"type": "none"})
    files.update(sig_files)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_bytes(_zip_bytes(files))
    return {
        "path": str(out_path),
        "merkle_root": root,
        "manifest_sha256": sha256_hex(manifest_bytes),
        "signature": sig_info,
        "files": len(files),
    }
