"""
Token-bucket rate limiter for pacing outbound Azure OpenAI calls.

Azure enforces a hard Requests-Per-Minute (and Tokens-Per-Minute) quota per
deployment. Firing a burst of concurrent requests at it just gets most of
them rejected with 429s (see: 9/50 succeeded in the first load test). This
limiter instead paces calls to stay under the configured RPM, so requests
queue briefly server-side rather than round-tripping to Azure and failing.

It intentionally does NOT wait forever: if the queue would take longer than
`max_wait_seconds`, `acquire()` gives up and the caller should fail fast with
a "please retry" response instead of holding an HTTP connection open for
minutes under sustained overload.
"""

import asyncio
import time


class LocallyRateLimited(Exception):
    """Raised when a call would have to wait too long for a rate-limiter slot.
    Distinguished from Azure's own RateLimitError: this means our own pacer
    decided not to wait further, not that Azure itself rejected a request."""


class AsyncRateLimiter:
    def __init__(self, rate_per_minute: int, max_wait_seconds: float = 20.0):
        self.rate_per_minute = rate_per_minute
        self.max_wait_seconds = max_wait_seconds
        self._tokens = float(rate_per_minute)
        self._updated = time.monotonic()
        self._lock = asyncio.Lock()

    async def acquire(self):
        start = time.monotonic()
        while True:
            async with self._lock:
                now = time.monotonic()
                elapsed = now - self._updated
                self._updated = now
                self._tokens = min(
                    self.rate_per_minute, self._tokens + elapsed * (self.rate_per_minute / 60.0)
                )
                if self._tokens >= 1:
                    self._tokens -= 1
                    return

            if time.monotonic() - start >= self.max_wait_seconds:
                raise LocallyRateLimited(
                    f"Waited {time.monotonic() - start:.1f}s for a rate-limit slot "
                    f"(limit: {self.rate_per_minute}/min) without one becoming free; "
                    f"exceeded max_wait_seconds={self.max_wait_seconds}."
                )
            await asyncio.sleep(min(1.0, self.max_wait_seconds))  # recheck periodically