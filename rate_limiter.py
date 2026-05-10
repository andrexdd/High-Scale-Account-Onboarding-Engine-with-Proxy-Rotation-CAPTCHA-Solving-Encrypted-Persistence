import asyncio
import time
import logging
from dataclasses import dataclass, field
from typing import Dict, Optional
from collections import deque
from enum import Enum

logger = logging.getLogger(__name__)


class RateLimitStrategy(Enum):
    TOKEN_BUCKET = "token_bucket"
    SLIDING_WINDOW = "sliding_window"
    ADAPTIVE = "adaptive"


@dataclass
class RateLimiterConfig:
    requests_per_second: float = 1.0
    burst_size: int = 5
    window_size_seconds: float = 60.0
    strategy: RateLimitStrategy = RateLimitStrategy.TOKEN_BUCKET
    enable_adaptive: bool = True
    min_requests_per_second: float = 0.1
    max_requests_per_second: float = 10.0


class TokenBucketLimiter:
    def __init__(
        self,
        rate: float = 1.0,
        capacity: int = 5,
    ):
        self.rate = rate
        self.capacity = capacity
        self.tokens = float(capacity)
        self.last_update = time.time()
        self._lock = asyncio.Lock()

    async def acquire(self, tokens: int = 1) -> float:
        async with self._lock:
            now = time.time()
            elapsed = now - self.last_update
            self.tokens = min(
                self.capacity,
                self.tokens + elapsed * self.rate
            )
            self.last_update = now

            if self.tokens < tokens:
                sleep_time = (tokens - self.tokens) / self.rate
                return sleep_time

            self.tokens -= tokens
            return 0.0

    async def wait_if_needed(self, tokens: int = 1) -> None:
        sleep_time = await self.acquire(tokens)
        if sleep_time > 0:
            await asyncio.sleep(sleep_time)


class SlidingWindowLimiter:
    def __init__(
        self,
        requests_per_window: int = 60,
        window_size_seconds: float = 60.0,
    ):
        self.requests_per_window = requests_per_window
        self.window_size = window_size_seconds
        self.requests: deque = deque()
        self._lock = asyncio.Lock()

    async def acquire(self) -> float:
        async with self._lock:
            now = time.time()
            window_start = now - self.window_size

            while self.requests and self.requests[0] < window_start:
                self.requests.popleft()

            if len(self.requests) >= self.requests_per_window:
                oldest_request = self.requests[0]
                sleep_time = (oldest_request + self.window_size) - now
                return max(0, sleep_time)

            self.requests.append(now)
            return 0.0

    async def wait_if_needed(self) -> None:
        sleep_time = await self.acquire()
        if sleep_time > 0:
            await asyncio.sleep(sleep_time)


class AdaptiveRateLimiter:
    def __init__(
        self,
        initial_rate: float = 1.0,
        min_rate: float = 0.1,
        max_rate: float = 10.0,
        increase_factor: float = 1.1,
        decrease_factor: float = 0.9,
        adjustment_period: int = 100,
    ):
        self.current_rate = initial_rate
        self.min_rate = min_rate
        self.max_rate = max_rate
        self.increase_factor = increase_factor
        self.decrease_factor = decrease_factor
        self.adjustment_period = adjustment_period
        
        self.request_count = 0
        self.success_count = 0
        self.error_count = 0
        self.last_adjustment_time = time.time()
        
        self.limiter = TokenBucketLimiter(rate=initial_rate, capacity=int(initial_rate * 5))
        self._lock = asyncio.Lock()

    async def acquire(self) -> float:
        return await self.limiter.acquire(1)

    async def wait_if_needed(self) -> None:
        sleep_time = await self.acquire()
        if sleep_time > 0:
            await asyncio.sleep(sleep_time)

    async def record_success(self) -> None:
        async with self._lock:
            self.success_count += 1
            self.request_count += 1
            await self._check_adjustment()

    async def record_error(self) -> None:
        async with self._lock:
            self.error_count += 1
            self.request_count += 1
            await self._check_adjustment()

    async def _check_adjustment(self) -> None:
        if self.request_count < self.adjustment_period:
            return

        success_rate = self.success_count / max(1, self.request_count)

        if success_rate > 0.95:
            new_rate = min(self.max_rate, self.current_rate * self.increase_factor)
            logger.info(f"Success rate {success_rate:.1%}, increasing rate from {self.current_rate:.2f} to {new_rate:.2f}")
            self.current_rate = new_rate
        elif success_rate < 0.80:
            new_rate = max(self.min_rate, self.current_rate * self.decrease_factor)
            logger.info(f"Success rate {success_rate:.1%}, decreasing rate from {self.current_rate:.2f} to {new_rate:.2f}")
            self.current_rate = new_rate

        self.limiter = TokenBucketLimiter(
            rate=self.current_rate,
            capacity=int(self.current_rate * 5)
        )
        self.request_count = 0
        self.success_count = 0
        self.error_count = 0
        self.last_adjustment_time = time.time()


class PerProxyRateLimiter:
    def __init__(
        self,
        requests_per_second: float = 1.0,
        burst_size: int = 5,
    ):
        self.requests_per_second = requests_per_second
        self.burst_size = burst_size
        self.proxy_limiters: Dict[str, TokenBucketLimiter] = {}
        self._lock = asyncio.Lock()

    async def wait_for_proxy(self, proxy_url: str) -> None:
        async with self._lock:
            if proxy_url not in self.proxy_limiters:
                self.proxy_limiters[proxy_url] = TokenBucketLimiter(
                    rate=self.requests_per_second,
                    capacity=self.burst_size,
                )

        limiter = self.proxy_limiters[proxy_url]
        sleep_time = await limiter.acquire(1)
        if sleep_time > 0:
            logger.debug(f"Rate limiting proxy {proxy_url}: sleeping {sleep_time:.2f}s")
            await asyncio.sleep(sleep_time)

    async def get_proxy_stats(self, proxy_url: str) -> Dict:
        if proxy_url not in self.proxy_limiters:
            return {
                "proxy": proxy_url,
                "status": "not_used",
                "tokens": self.burst_size,
                "capacity": self.burst_size,
            }

        limiter = self.proxy_limiters[proxy_url]
        return {
            "proxy": proxy_url,
            "status": "active",
            "tokens": limiter.tokens,
            "capacity": limiter.capacity,
            "rate": limiter.rate,
        }


class GlobalRateLimiter:
    def __init__(
        self,
        config: RateLimiterConfig = None,
    ):
        self.config = config or RateLimiterConfig()
        
        if self.config.strategy == RateLimitStrategy.TOKEN_BUCKET:
            self.limiter = TokenBucketLimiter(
                rate=self.config.requests_per_second,
                capacity=self.config.burst_size,
            )
        elif self.config.strategy == RateLimitStrategy.SLIDING_WINDOW:
            self.limiter = SlidingWindowLimiter(
                requests_per_window=int(self.config.requests_per_second * self.config.window_size_seconds),
                window_size_seconds=self.config.window_size_seconds,
            )
        elif self.config.strategy == RateLimitStrategy.ADAPTIVE:
            self.limiter = AdaptiveRateLimiter(
                initial_rate=self.config.requests_per_second,
                min_rate=self.config.min_requests_per_second,
                max_rate=self.config.max_requests_per_second,
            )
        else:
            raise ValueError(f"Unknown rate limit strategy: {self.config.strategy}")

        self.per_proxy_limiter = PerProxyRateLimiter(
            requests_per_second=self.config.requests_per_second,
            burst_size=self.config.burst_size,
        )

        self.request_count = 0
        self.total_sleep_time = 0.0
        self._lock = asyncio.Lock()

        logger.info(
            f"GlobalRateLimiter initialized: "
            f"strategy={self.config.strategy.value}, "
            f"rate={self.config.requests_per_second}/s, "
            f"burst={self.config.burst_size}"
        )

    async def wait(self, proxy_url: Optional[str] = None) -> None:
        async with self._lock:
            self.request_count += 1

        if proxy_url:
            await self.per_proxy_limiter.wait_for_proxy(proxy_url)

        start_time = time.time()
        await self.limiter.wait_if_needed()
        sleep_time = time.time() - start_time

        if sleep_time > 0:
            async with self._lock:
                self.total_sleep_time += sleep_time
            logger.debug(f"Rate limit wait: {sleep_time:.3f}s")

    async def record_success(self) -> None:
        if isinstance(self.limiter, AdaptiveRateLimiter):
            await self.limiter.record_success()

    async def record_error(self) -> None:
        if isinstance(self.limiter, AdaptiveRateLimiter):
            await self.limiter.record_error()

    async def set_rate(self, rate: float) -> None:
        rate = max(self.config.min_requests_per_second, 
                   min(self.config.max_requests_per_second, rate))
        logger.info(f"Updating global rate limit to {rate}/s")
        
        if isinstance(self.limiter, TokenBucketLimiter):
            async with self.limiter._lock:
                self.limiter.rate = rate
                self.limiter.capacity = int(rate * 5)

    def get_stats(self) -> Dict:
        stats = {
            "strategy": self.config.strategy.value,
            "request_count": self.request_count,
            "total_sleep_time": f"{self.total_sleep_time:.2f}s",
            "avg_sleep_per_request": f"{(self.total_sleep_time / max(1, self.request_count)):.3f}s",
        }

        if isinstance(self.limiter, AdaptiveRateLimiter):
            stats.update({
                "current_rate": f"{self.limiter.current_rate:.2f}/s",
                "min_rate": f"{self.limiter.min_rate:.2f}/s",
                "max_rate": f"{self.limiter.max_rate:.2f}/s",
            })
        elif isinstance(self.limiter, TokenBucketLimiter):
            stats.update({
                "rate": f"{self.limiter.rate:.2f}/s",
                "available_tokens": f"{self.limiter.tokens:.1f}",
                "capacity": self.limiter.capacity,
            })

        return stats

    def log_stats(self) -> None:
        stats = self.get_stats()
        logger.info("=== RATE LIMITER STATS ===")
        for key, value in stats.items():
            logger.info(f"{key}: {value}")
        logger.info("===========================")
