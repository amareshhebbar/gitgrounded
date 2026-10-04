import asyncio
from pathlib import Path

import pytest

from gitgrounded.cases.model import Case
from gitgrounded.exec import ratelimit
from gitgrounded.exec.executor import Executor
from gitgrounded.exec.ratelimit import RateLimiter
from gitgrounded.sources.variant import Variant
from gitgrounded.store.cache import Cache
from gitgrounded.targets.base import Target, Transcript


class Clock:
    def __init__(self):
        self.t = 0.0
        self.slept = []

    def __call__(self):
        return self.t

    def sleep(self, s):
        self.slept.append(s)
        self.t += s


def test_rate_limiter():
    c = Clock()
    lim = RateLimiter(60, burst=2, clock=c, sleep=c.sleep)
    assert lim.acquire() == 0 and lim.acquire() == 0
    assert lim.acquire() == pytest.approx(1.0)
    c.t += 5
    assert lim.acquire() == 0
    assert asyncio.run(lim.acquire_async()) == 0
    with pytest.raises(ValueError):
        RateLimiter(0)
    ratelimit.reset()
    a = ratelimit.shared("k", 30)
    assert ratelimit.shared("k", 30) is a and ratelimit.shared("k", 60) is not a
    assert ratelimit.shared("k", None) is None


class Echo(Target):
    name = "echo"

    def __init__(self):
        self.calls = 0

    def invoke(self, case, variant, trial):
        self.calls += 1
        return Transcript(
            case_id=case.id, variant=variant.name, trial=trial, request={}, raw_output=case.input, output=case.input
        )


@pytest.mark.parametrize("mode", ["threads", "async"])
def test_executor_modes(tmp_path, mode):
    t = Echo()
    cases = [Case(id=f"c{i}", input=f"q{i}") for i in range(4)]
    v = Variant(name="head", root=Path("."), files={}, content_hash="h")
    seen = []
    ex = Executor(t, Cache(tmp_path), 3, on_progress=lambda d, n: seen.append(d), requests_per_minute=6000, mode=mode)
    out = ex.run(v, cases, trials=2)
    assert len(out) == 8 and out[("c1", 1)].output == "q1" and seen[-1] == 8
    again = ex.run(v, cases, trials=2)
    assert t.calls == 8 and all(tr.cached for tr in again.values())


def test_executor_async_inside_loop(tmp_path):
    t = Echo()
    v = Variant(name="head", root=Path("."), files={}, content_hash="h")
    ex = Executor(t, Cache(tmp_path), 2, use_cache=False, mode="async")

    async def main():
        return ex.run(v, [Case(id="a", input="x")])

    assert asyncio.run(main())[("a", 0)].output == "x"
