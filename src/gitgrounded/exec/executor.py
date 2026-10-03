import asyncio
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor

from gitgrounded.cases.model import Case
from gitgrounded.exec.ratelimit import RateLimiter
from gitgrounded.sources.variant import Variant
from gitgrounded.store.cache import Cache
from gitgrounded.targets.base import Target, Transcript


class Executor:
    def __init__(
        self,
        target: Target,
        cache: Cache,
        max_concurrency: int = 8,
        use_cache: bool = True,
        on_progress: Callable[[int, int], None] | None = None,
        requests_per_minute: float | None = None,
        mode: str = "threads",
    ):
        self.target = target
        self.cache = cache
        self.max_concurrency = max(1, max_concurrency)
        self.use_cache = use_cache
        self.on_progress = on_progress
        self.limiter = RateLimiter(requests_per_minute) if requests_per_minute else None
        self.mode = mode

    @classmethod
    def from_config(cls, target: Target, cache: Cache, execution, use_cache: bool = True, **kw) -> "Executor":
        return cls(
            target,
            cache,
            execution.max_concurrency,
            use_cache=use_cache,
            requests_per_minute=execution.requests_per_minute,
            mode=execution.mode,
            **kw,
        )

    def _key(self, variant: Variant, case: Case, trial: int) -> str:
        return self.cache.key(
            "transcript", self.target.describe(), variant.content_hash, variant.overlay, case.hash(), trial
        )

    def _cached(self, variant: Variant, case: Case, trial: int) -> Transcript | None:
        if not self.use_cache:
            return None
        hit = self.cache.get("transcripts", self._key(variant, case, trial))
        if hit is None:
            return None
        tr = Transcript.from_dict(hit)
        tr.variant = variant.name
        tr.cached = True
        return tr

    def _store(self, variant: Variant, case: Case, trial: int, tr: Transcript) -> Transcript:
        if self.use_cache and not tr.error:
            self.cache.set("transcripts", self._key(variant, case, trial), tr.to_dict())
        return tr

    def _one(self, variant: Variant, case: Case, trial: int) -> Transcript:
        hit = self._cached(variant, case, trial)
        if hit is not None:
            return hit
        if self.limiter:
            self.limiter.acquire()
        return self._store(variant, case, trial, self.target.invoke(case, variant, trial))

    async def _one_async(self, sem: asyncio.Semaphore, variant: Variant, case: Case, trial: int) -> Transcript:
        hit = self._cached(variant, case, trial)
        if hit is not None:
            return hit
        async with sem:
            if self.limiter:
                await self.limiter.acquire_async()
            tr = await self.target.ainvoke(case, variant, trial)
        return self._store(variant, case, trial, tr)

    def run(self, variant: Variant, cases: list[Case], trials: int = 1) -> dict[tuple[str, int], Transcript]:
        if self.mode == "async":
            return self._run_async(variant, cases, trials)
        jobs = [(c, t) for c in cases for t in range(trials)]
        out: dict[tuple[str, int], Transcript] = {}
        total = len(jobs)
        done = 0
        with ThreadPoolExecutor(max_workers=self.max_concurrency) as pool:
            futures = {pool.submit(self._one, variant, c, t): (c.id, t) for c, t in jobs}
            for fut, key in futures.items():
                out[key] = fut.result()
                done += 1
                if self.on_progress:
                    self.on_progress(done, total)
        return out

    def _run_async(self, variant: Variant, cases: list[Case], trials: int) -> dict[tuple[str, int], Transcript]:
        jobs = [(c, t) for c in cases for t in range(trials)]
        total = len(jobs)

        async def main() -> dict[tuple[str, int], Transcript]:
            sem = asyncio.Semaphore(self.max_concurrency)
            out: dict[tuple[str, int], Transcript] = {}
            done = 0

            async def job(c: Case, t: int) -> None:
                nonlocal done
                out[(c.id, t)] = await self._one_async(sem, variant, c, t)
                done += 1
                if self.on_progress:
                    self.on_progress(done, total)

            await asyncio.gather(*(job(c, t) for c, t in jobs))
            return out

        try:
            asyncio.get_running_loop()
        except RuntimeError:
            return asyncio.run(main())
        with ThreadPoolExecutor(max_workers=1) as pool:
            return pool.submit(asyncio.run, main()).result()
