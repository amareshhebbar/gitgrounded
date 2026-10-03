import zipfile

import pytest

from gitgrounded.engine import RunOptions


@pytest.mark.parametrize(
    "head,expected",
    [("test/safe-wording-tweak", "PASS"), ("test/drop-citation-rule", "FAIL"), ("test/model-downgrade", "FAIL")],
)
def test_demo_scenarios(engine, head, expected):
    result = engine.run_git("core", "baseline", head, RunOptions())
    assert result.verdict == expected
    assert result.counts["total_cases"] >= 10
    assert result.metrics["score"]["delta"]["n"] == result.counts["total_cases"]


def test_model_downgrade_is_assertion_failure(engine):
    result = engine.run_git("core", "baseline", "test/model-downgrade", RunOptions(generate=False))
    assert result.counts["new_assertion_failures"] > 0


def test_cache_reuse(engine):
    engine.run_git("core", "baseline", "test/safe-wording-tweak", RunOptions(generate=False))
    second = engine.run_git("core", "baseline", "test/safe-wording-tweak", RunOptions(generate=False))
    assert all(t["transcript"]["cached"] for r in second.cases for t in r["head"]["trials"])


def test_bundle_verify_and_tamper(engine, tmp_path):
    from gitgrounded.cli.main import _write_bundle
    from gitgrounded.evidence.verify import verify_bundle

    result = engine.run_git("core", "baseline", "test/drop-citation-rule", RunOptions(generate=False))
    path = tmp_path / "run.ggb"
    info = _write_bundle(engine, result, path, "local")
    assert info["signature"]["type"] == "ed25519"
    ok = verify_bundle(path)
    assert ok.status == "VERIFIED_SELF_SIGNED", ok.checks
    for target in ("records/judgements.jsonl", "summary.json", "report.html", "manifest.json"):
        bad = tmp_path / f"bad-{target.replace('/', '_')}.ggb"
        with zipfile.ZipFile(path) as zin, zipfile.ZipFile(bad, "w") as zout:
            for item in zin.infolist():
                data = zin.read(item)
                if item.filename == target:
                    data = data.replace(b"FAIL", b"PASS", 1) if b"FAIL" in data else data + b" "
                zout.writestr(item, data)
        assert not verify_bundle(bad).status.startswith("VERIFIED"), target


def test_pinned_key_mismatch(engine, tmp_path):
    from gitgrounded.cli.main import _write_bundle
    from gitgrounded.evidence.verify import verify_bundle

    result = engine.run_git("core", "baseline", "test/safe-wording-tweak", RunOptions(generate=False))
    path = tmp_path / "run.ggb"
    _write_bundle(engine, result, path, "local")
    assert verify_bundle(path, public_key="0000000000000000").status == "SIGNATURE_INVALID"


def test_reports_render(engine):
    from gitgrounded.report.html import render_html
    from gitgrounded.report.junit import render_junit
    from gitgrounded.report.markdown import render_markdown

    result = engine.run_git("core", "baseline", "test/drop-citation-rule", RunOptions(generate=False))
    html = render_html(result)
    assert "<!doctype html>" in html and "seed-01" in html
    assert "GitGrounded: **FAIL**" in render_markdown(result)
    assert "<testsuite" in render_junit(result)
