import asyncio
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional, Dict
from urllib.parse import urlparse
from datetime import datetime, timedelta
import random

import aiohttp
from aiohttp import ClientTimeout, ClientSession

from .exceptions import ProxyError, ProxyExhaustedError, ProxyValidationError, RetryableError
from .constants import ProxyConstants, BrowserConstants
from .validators import ProxyValidator

logger = logging.getLogger(__name__)


@dataclass
class ProxyEntry:
    server: str
    scheme: str = "http"
    username: Optional[str] = None
    password: Optional[str] = None
    fail_count: int = 0
    success_count: int = 0
    last_used: Optional[datetime] = None
    last_failed: Optional[datetime] = None
    consecutive_failures: int = 0
    reputation_score: float = 100.0
    blocked_until: Optional[datetime] = None

    def proxy_url(self) -> str:
        return f"{self.scheme}://{self.server}"

    def playwight_proxy(self) -> dict:
        proxy_config = {
            "server": self.proxy_url(),
        }
        if self.username and self.password:
            proxy_config.update({"username": self.username, "password": self.password})
        return proxy_config

    def aiohttp_args(self) -> dict:
        proxy_args = {"proxy": self.proxy_url()}
        if self.username and self.password:
            from aiohttp import BasicAuth
            proxy_args["proxy_auth"] = BasicAuth(self.username, self.password)
        return proxy_args

    def is_healthy(self, max_failures: int, max_consecutive: int = 3) -> bool:
        if self.blocked_until and datetime.utcnow() < self.blocked_until:
            return False
        if self.fail_count >= max_failures:
            return False
        if self.consecutive_failures >= max_consecutive:
            return False
        return True

    def mark_success(self) -> None:
        self.success_count += 1
        self.consecutive_failures = 0
        self.fail_count = max(0, self.fail_count - 1)
        self.last_used = datetime.utcnow()
        self.reputation_score = min(100.0, self.reputation_score + 5.0)

    def mark_failure(self, block_duration_minutes: int = 5) -> None:
        self.fail_count += 1
        self.consecutive_failures += 1
        self.last_failed = datetime.utcnow()
        self.reputation_score = max(0.0, self.reputation_score - 10.0)
        if self.consecutive_failures >= 3:
            self.blocked_until = datetime.utcnow() + timedelta(minutes=block_duration_minutes)

    def get_quality_score(self) -> float:
        if not self.last_used:
            return self.reputation_score
        age_hours = (datetime.utcnow() - self.last_used).total_seconds() / 3600
        freshness_penalty = min(age_hours * 2, 20.0)
        return max(0.0, self.reputation_score - freshness_penalty)


class ProxyManager:
    def __init__(self, proxies: List[ProxyEntry], max_failures: int = 5) -> None:
        self._proxies: List[ProxyEntry] = proxies
        self._max_failures: int = max_failures
        self._lock: asyncio.Lock = asyncio.Lock()
        self._index: int = 0
        self._validation_check_count: int = 0
        logger.info(f"ProxyManager initialized with {len(proxies)} proxies")

    @classmethod
    async def load_from_file(
        cls,
        path: str,
        max_failures: int = ProxyConstants.MAX_FAILURES_BEFORE_REMOVAL,
        min_valid_ratio: float = ProxyConstants.MIN_VALID_RATIO,
    ) -> "ProxyManager":
        file_path = Path(path)
        proxies = cls._read_proxies_from_file(file_path)

        if not proxies:
            logger.info("Proxy file empty, fetching fresh list")
            proxies = await cls._fetch_and_save_proxies(file_path)

        if proxies:
            valid_count = await cls._validate_proxy_batch(proxies)
            valid_ratio = valid_count / len(proxies) if proxies else 0
            logger.info(f"Proxy validation: {valid_count}/{len(proxies)} valid ({valid_ratio*100:.1f}%)")
            
            if valid_ratio < min_valid_ratio:
                logger.warning(f"Valid ratio {valid_ratio*100:.1f}% < threshold {min_valid_ratio*100:.1f}%. Refreshing...")
                proxies = await cls._fetch_and_save_proxies(file_path)

        if not proxies:
            raise ProxyExhaustedError("No proxies available after validation")

        logger.info(f"Loaded {len(proxies)} proxies from {path}")
        return cls(proxies, max_failures=max_failures)

    @classmethod
    def _read_proxies_from_file(cls, path: Path) -> List[ProxyEntry]:
        proxies: List[ProxyEntry] = []
        if not path.exists():
            return proxies

        try:
            with path.open("r", encoding="utf-8") as f:
                for line_num, raw in enumerate(f, 1):
                    line = raw.strip()
                    if not line or line.startswith("#"):
                        continue
                    try:
                        proxy_data = ProxyValidator.validate_proxy_entry(line)
                        if proxy_data:
                            proxies.append(ProxyEntry(**proxy_data))
                    except ValueError as e:
                        logger.debug(f"Skipping invalid proxy at line {line_num}: {e}")
        except IOError as e:
            logger.error(f"Failed to read proxy file {path}: {e}")
            return []

        return proxies

    @classmethod
    async def _fetch_and_save_proxies(cls, path: Path) -> List[ProxyEntry]:
        proxies = await cls.fetch_proxies_from_source()
        if not proxies:
            logger.warning("No proxies fetched from remote source")
            return []

        path.parent.mkdir(parents=True, exist_ok=True)
        try:
            with path.open("w", encoding="utf-8") as f:
                for proxy in proxies:
                    if proxy.username and proxy.password:
                        f.write(f"{proxy.username}:{proxy.password}@{proxy.server}\n")
                    else:
                        f.write(f"{proxy.server}\n")
            logger.info(f"Saved {len(proxies)} proxies to {path}")
        except IOError as e:
            logger.error(f"Failed to save proxies to {path}: {e}")

        return proxies

    @classmethod
    async def fetch_proxies_from_source(cls, source_url: str = ProxyConstants.PROXY_SCRAPE_URL) -> List[ProxyEntry]:
        proxies: List[ProxyEntry] = []
        try:
            async with aiohttp.ClientSession(timeout=ClientTimeout(total=20)) as session:
                async with session.get(source_url) as response:
                    if response.status != 200:
                        logger.error(f"Proxy source returned status {response.status}")
                        return proxies
                    text = await response.text()
        except Exception as exc:
            logger.exception(f"Failed to fetch proxies from source: {exc}")
            raise RetryableError(f"Proxy fetch failed: {exc}") from exc

        for raw in text.splitlines():
            line = raw.strip()
            if not line or line.startswith("#"):
                continue
            try:
                proxy_data = ProxyValidator.validate_proxy_entry(line)
                if proxy_data:
                    proxies.append(ProxyEntry(**proxy_data))
            except ValueError as e:
                logger.debug(f"Skipping invalid fetched proxy: {e}")

        return proxies

    @classmethod
    async def _validate_proxy_batch(cls, proxies: List[ProxyEntry]) -> int:
        if not proxies:
            return 0

        semaphore: asyncio.Semaphore = asyncio.Semaphore(ProxyConstants.VALIDATION_BATCH_SIZE)
        async with aiohttp.ClientSession(
            timeout=ClientTimeout(total=ProxyConstants.PROXY_VALIDATION_TIMEOUT)
        ) as session:
            tasks = [cls._validate_proxy(session, proxy, semaphore) for proxy in proxies]
            results = await asyncio.gather(*tasks, return_exceptions=True)

        valid_count = sum(1 for result in results if result is True)
        return valid_count

    @classmethod
    async def _validate_proxy(
        cls,
        session: ClientSession,
        proxy: ProxyEntry,
        semaphore: asyncio.Semaphore,
        test_url: str = ProxyConstants.VALIDATION_TEST_URL,
    ) -> bool:
        async with semaphore:
            try:
                proxy_args = proxy.aiohttp_args()
                proxy_args["headers"] = {"User-Agent": cls._random_user_agent()}
                proxy_args["allow_redirects"] = False
                async with session.get(test_url, **proxy_args) as response:
                    is_valid = response.status < 400
                    if is_valid:
                        proxy.reputation_score = 100.0
                    return is_valid
            except asyncio.TimeoutError:
                proxy.reputation_score = max(0.0, proxy.reputation_score - 20.0)
                return False
            except Exception as e:
                logger.debug(f"Proxy validation failed for {proxy.proxy_url()}: {e}")
                proxy.reputation_score = max(0.0, proxy.reputation_score - 15.0)
                return False

    @staticmethod
    def _random_user_agent() -> str:
        return random.choice(BrowserConstants.USER_AGENTS)

    async def get_next_proxy(self) -> ProxyEntry:
        async with self._lock:
            self._validation_check_count += 1
            if self._validation_check_count % 100 == 0:
                await self._cleanup_dead_proxies()

            healthy = [p for p in self._proxies if p.is_healthy(self._max_failures)]
            if not healthy:
                for p in self._proxies:
                    p.fail_count = 0
                    p.consecutive_failures = 0
                    p.blocked_until = None
                healthy = list(self._proxies)
                logger.warning("All proxies unhealthy. Resetting...")

            healthy.sort(key=lambda p: p.get_quality_score(), reverse=True)

            selected = healthy[self._index % len(healthy)]
            self._index += 1

            logger.debug(
                f"Proxy selected: {selected.proxy_url()} "
                f"(score={selected.get_quality_score():.1f}, failures={selected.consecutive_failures})"
            )
            return selected

    def mark_proxy_success(self, proxy: ProxyEntry) -> None:
        proxy.mark_success()
        logger.debug(f"Proxy {proxy.proxy_url()} marked success (score={proxy.reputation_score:.1f})")

    def mark_proxy_failed(self, proxy: ProxyEntry) -> None:
        proxy.mark_failure()
        logger.debug(
            f"Proxy {proxy.proxy_url()} marked failed "
            f"(consecutive={proxy.consecutive_failures}, score={proxy.reputation_score:.1f})"
        )
        if not proxy.is_healthy(self._max_failures):
            logger.warning(f"Proxy {proxy.proxy_url()} marked unhealthy")

    async def _cleanup_dead_proxies(self) -> None:
        dead_proxies = [p for p in self._proxies if not p.is_healthy(self._max_failures)]
        if dead_proxies:
            logger.info(f"Cleaning up {len(dead_proxies)} dead proxies")
            for p in dead_proxies:
                p.fail_count = 0
                p.consecutive_failures = 0
                p.blocked_until = None

    def get_stats(self) -> Dict[str, any]:
        healthy = [p for p in self._proxies if p.is_healthy(self._max_failures)]
        return {
            "total_proxies": len(self._proxies),
            "healthy_proxies": len(healthy),
            "health_ratio": f"{(len(healthy)/len(self._proxies)*100):.1f}%" if self._proxies else "N/A",
            "avg_reputation": f"{(sum(p.reputation_score for p in self._proxies)/len(self._proxies)):.1f}" if self._proxies else "N/A",
            "total_successes": sum(p.success_count for p in self._proxies),
            "total_failures": sum(p.fail_count for p in self._proxies),
        }
