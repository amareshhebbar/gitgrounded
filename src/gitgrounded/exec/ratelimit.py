import asyncio
import threading
import time

_LOCK = threading.Lock()
_REGISTRY: dict[str, "RateLimiter"] = {}


class RateLimiter:
    def __init__(self, per_minute: float, burst: int | None = None, clock=time.monotonic, sleep=time.sleep):
        if per_minute <= 0:
            raise ValueError("per_minute must be positive")
        self.rate = per_minute / 60.0
        self.capacity = float(burst if burst is not None else max(1, min(int(per_minute), 10)))
        self.tokens = self.capacity
        self.clock = clock
        self.sleep = sleep
        self.updated = clock()
        self.lock = threading.Lock()

    def _reserve(self) -> float:
        with self.lock:
            now = self.clock()
            self.tokens = min(self.capacity, self.tokens + (now - self.updated) * self.rate)
            self.updated = now
            self.tokens -= 1.0
            if self.tokens >= 0:
                return 0.0
            return -self.tokens / self.rate

    def acquire(self) -> float:
        wait = self._reserve()
        if wait > 0:
            self.sleep(wait)
        return wait

    async def acquire_async(self) -> float:
        wait = self._reserve()
        if wait > 0:
            await asyncio.sleep(wait)
        return wait


def shared(key: str, per_minute: float | None) -> RateLimiter | None:
    if not per_minute:
        return None
    with _LOCK:
        lim = _REGISTRY.get(key)
        if lim is None or abs(lim.rate - per_minute / 60.0) > 1e-9:
            lim = _REGISTRY[key] = RateLimiter(per_minute)
        return lim


def reset() -> None:
    with _LOCK:
        _REGISTRY.clear()
