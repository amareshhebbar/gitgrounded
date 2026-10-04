from gitgrounded.coverage.pipeline import CoveragePipeline


def test_synth_and_mutate(engine):
    cfg = engine.cfg.coverage_for("auto")
    cfg.budget_cases = 30
    cfg.mutation.max_mutants = 4
    pipe = CoveragePipeline(engine, "auto")
    found = pipe.discover()
    assert any(b.kind == "knowledge" for b in found["behaviors"])
    assert any(b.implicit for b in found["behaviors"])
    out = pipe.synth()
    assert out["cases"] >= out["behaviors"]
    assert out["coverage"]["behavior_coverage"] == 1.0
    cases = pipe.store.cases()
    assert all(c.behaviors and c.expectations for c in cases)
    mutation = pipe.mutate(repair=False)
    assert mutation["total"] == 4
    assert mutation["killed"] >= 1
    assert pipe.store.path("minimal.jsonl").exists()


def test_incremental_keeps_cases(engine, demo_repo):
    cfg = engine.cfg.coverage_for("auto")
    cfg.budget_cases = 20
    pipe = CoveragePipeline(engine, "auto")
    pipe.synth()
    before = {c.id for c in pipe.store.cases()}
    p = demo_repo / "prompts" / "triage.txt"
    p.write_text(p.read_text().replace("Respond with JSON only.", "Respond with JSON only, never markdown."))
    pipe2 = CoveragePipeline(engine, "auto")
    pipe2.synth()
    after = {c.id for c in pipe2.store.cases()}
    assert len(before & after) > len(before) // 2
