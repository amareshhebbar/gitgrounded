import json
import tempfile
import time
import uuid
from pathlib import Path
from typing import Any

from gitgrounded import __version__
from gitgrounded.canonical import canonical_bytes, sha256_hex
from gitgrounded.coverage.suite_store import SuiteStore, suite_integrity
from gitgrounded.evidence.bundle import _zip_bytes, build_bundle, ci_environment
from gitgrounded.evidence.merkle import merkle_root
from gitgrounded.evidence.pdf import available as pdf_available
from gitgrounded.evidence.pdf import qr_payload, render_certificate_pdf
from gitgrounded.evidence.sign import build_signer
from gitgrounded.judges.traps import run_traps
from gitgrounded.providers.base import is_offline
from gitgrounded.report.model import RunResult

CERT_FORMAT = "ggb-cert/1"


def render_certificate_html(cert: dict[str, Any]) -> str:
    from gitgrounded.report.html import _css, _template

    return _template("certificate.html.j2").render(c=cert, css=_css())


def _pair_bundle(engine, result: RunResult, suite_files: dict[str, bytes], signer) -> tuple[bytes, dict[str, Any]]:
    from gitgrounded.report.html import render_html

    with tempfile.TemporaryDirectory() as td:
        path = Path(td) / "pair.ggb"
        info = build_bundle(
            result,
            path,
            engine.cfg.model_dump(mode="json"),
            suite_files,
            render_html,
            engine.cfg.evidence.redact,
            engine.cfg.evidence.include_transcripts,
            signer,
        )
        return path.read_bytes(), info


def _slug(name: str) -> str:
    out = "".join(ch if ch.isalnum() else "_" for ch in name)
    return out.strip("_")[:60] or "pair"


def certify(
    engine,
    suite_name: str,
    cases: list,
    pairs: list[tuple[str, RunResult]],
    leaderboard: list[dict[str, Any]],
    out_path: Path,
    sign: str | None = None,
    kind: str = "comparison",
    signer: Any = None,
    issuer: dict[str, Any] | None = None,
) -> dict[str, Any]:
    ccfg = engine.cfg.evidence.certify
    _, suite = engine.cfg.suite(suite_name)
    store = SuiteStore(engine.project, suite_name)
    reasons: list[str] = []
    sealed, why = suite_integrity(store)
    if ccfg.require_sealed_suite and not sealed:
        reasons.append(f"question set is not a sealed AI generated suite: {why}")
    if len(cases) < ccfg.min_cases:
        reasons.append(f"only {len(cases)} cases; at least {ccfg.min_cases} are required")
    rubric_judges, pairwise = engine.build_judges(suite)
    traps = run_traps(
        cases,
        rubric_judges,
        pairwise,
        engine.cfg.providers.generator,
        engine.cache,
        engine.context_text(suite, None),
        ccfg.traps,
        ccfg.trap_threshold,
    )
    if not traps["passed"]:
        reasons.append(f"judge failed trap checks: {traps['correct']}/{traps['total']} below {ccfg.trap_threshold:.0%}")
    if signer is None:
        signer = build_signer(sign or engine.cfg.evidence.sign)
    if signer is None:
        reasons.append("certificate is unsigned; install gitgrounded[sign] and do not use --sign none")
    if is_offline():
        reasons.append("offline mock mode: real models were not used")
    suite_files = {}
    for name in ("current.jsonl", "coverage.json", "mutation.json", "behavior_map.json", "suite.json"):
        p = store.path(name)
        if p.exists():
            suite_files[name] = p.read_bytes()
    files: dict[str, bytes] = {}
    pair_rows = []
    for i, (name, result) in enumerate(pairs):
        data, info = _pair_bundle(engine, result, suite_files, signer)
        rel = f"pairs/{i + 1:02d}_{_slug(name)}.ggb"
        files[rel] = data
        pair_rows.append(
            {
                "name": name,
                "file": rel,
                "verdict": result.verdict,
                "bundle_sha256": sha256_hex(data),
                "merkle_root": info["merkle_root"],
                "run_id": result.run_id,
            }
        )
    meta = store.meta()
    cal_path = engine.project.state_dir / "calibration.json"
    calibration = None
    if cal_path.exists():
        cal = json.loads(cal_path.read_text(encoding="utf-8"))
        calibration = {
            k: cal.get(k) for k in ("labels", "spearman", "cohen_kappa_pass", "pass_agreement", "rubric", "rubric_hash")
        }
    cov = store.read_json("coverage.json") or {}
    judge = engine.cfg.providers.judge
    cert = {
        "format": CERT_FORMAT,
        "id": time.strftime("%Y%m%dT%H%M%SZ", time.gmtime()) + "-" + uuid.uuid4().hex[:8],
        "kind": kind,
        "created_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "tool_version": __version__,
        "project": engine.cfg.project.name,
        "issuer": issuer or {"name": "self-issued", "scope": "self"},
        "certified": not reasons,
        "reasons": reasons,
        "suite": {
            "name": suite_name,
            "version": meta.get("version"),
            "dataset_hash": meta.get("dataset_hash"),
            "sealed_hash": meta.get("sealed_hash"),
            "cases": len(cases),
            "behaviors": meta.get("behaviors"),
            "generator": meta.get("generator"),
            "integrity": why,
        },
        "judge": {"provider": judge.provider, "model": judge.model, "temperature": judge.temperature},
        "panel": [f"{p.provider}:{p.model}" for p in engine.cfg.providers.panel],
        "offline": is_offline(),
        "traps": {k: traps[k] for k in ("total", "correct", "accuracy", "threshold", "passed")},
        "calibration": calibration,
        "coverage": cov.get("summary"),
        "leaderboard": leaderboard,
        "pairs": pair_rows,
        "ci": ci_environment(),
    }
    files["certificate.json"] = canonical_bytes(cert)
    files["certificate.html"] = render_certificate_html(cert).encode("utf-8")
    pdf_info = None
    ccfg = engine.cfg.evidence.certify
    if ccfg.pdf and pdf_available():
        cert_sha = sha256_hex(files["certificate.json"])
        files["certificate.pdf"] = render_certificate_pdf(cert, cert_sha, ccfg.verify_url)
        pdf_info = qr_payload(cert, cert_sha, ccfg.verify_url)
    files["traps.jsonl"] = ("\n".join(json.dumps(i, sort_keys=True) for i in traps["items"]) + "\n").encode("utf-8")
    manifest = {
        "bundle_format": CERT_FORMAT,
        "tool": {"name": "gitgrounded", "version": __version__},
        "run_id": cert["id"],
        "created_at": cert["created_at"],
        "project": cert["project"],
        "suite": suite_name,
        "verdict": "CERTIFIED" if cert["certified"] else "NOT_CERTIFIED",
        "certified": cert["certified"],
        "merkle_root": merkle_root([]),
        "judge": cert["judge"],
        "offline": cert["offline"],
        "ci": cert["ci"],
        "files": {name: sha256_hex(data) for name, data in sorted(files.items())},
    }
    manifest_bytes = canonical_bytes(manifest)
    files["manifest.json"] = manifest_bytes
    if signer is not None:
        sig_files, sig_info = signer.sign(manifest_bytes)
        files.update(sig_files)
    else:
        sig_info = {"type": "none"}
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_bytes(_zip_bytes(files))
    html_path = out_path.with_suffix(".html")
    html_path.write_bytes(files["certificate.html"])
    pdf_path = None
    if "certificate.pdf" in files:
        pdf_path = out_path.with_suffix(".pdf")
        pdf_path.write_bytes(files["certificate.pdf"])
    return {
        "path": str(out_path),
        "html": str(html_path),
        "pdf": str(pdf_path) if pdf_path else None,
        "qr": pdf_info,
        "certified": cert["certified"],
        "reasons": reasons,
        "traps": cert["traps"],
        "signature": sig_info,
        "certificate": cert,
    }
