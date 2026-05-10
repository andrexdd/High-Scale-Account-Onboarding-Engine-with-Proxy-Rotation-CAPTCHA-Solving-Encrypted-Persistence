import asyncio
import logging
import os
import sys

if sys.platform == 'win32':
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

from high_scale_onboarding import (
    CaptchaSolver, OnboardingEngine, PersistenceStore, ProxyManager,
    MetricsCollector, LOGS_DIR
)
from high_scale_onboarding.config import (
    DATABASE_FILE, ENCRYPTION_KEY_FILE, MAX_CONCURRENT_TASKS, PROXIES_FILE,
    TOTAL_SIMULATION_JOBS, CAPTCHA_API_KEY, CAPTCHA_PROVIDER, LOG_LEVEL, ENABLE_METRICS
)
from high_scale_onboarding.rate_limiter import GlobalRateLimiter, RateLimiterConfig, RateLimitStrategy

log_file = LOGS_DIR / f"onboarding_{int(__import__('time').time())}.log"

logging.basicConfig(
    level=getattr(logging, LOG_LEVEL),
    format="%(asctime)s [%(levelname)-8s] %(name)-20s %(message)s",
    handlers=[
        logging.FileHandler(log_file),
        logging.StreamHandler(sys.stdout),
    ],
)

logger = logging.getLogger(__name__)


def ensure_encryption_key() -> bytes:
    if ENCRYPTION_KEY_FILE.exists():
        return ENCRYPTION_KEY_FILE.read_bytes().strip()

    key = PersistenceStore.generate_key()
    ENCRYPTION_KEY_FILE.write_bytes(key)
    logger.info(f"Generated new encryption key: {ENCRYPTION_KEY_FILE}")
    return key


async def main() -> None:
    logger.info("=" * 70)
    logger.info("Starting onboarding engine")
    logger.info("=" * 70)
    logger.info(f"Configuration:")
    logger.info(f"  - Max concurrent tasks: {MAX_CONCURRENT_TASKS}")
    logger.info(f"  - Total jobs: {TOTAL_SIMULATION_JOBS}")
    logger.info(f"  - Captcha provider: {CAPTCHA_PROVIDER}")
    logger.info(f"  - Database: {DATABASE_FILE}")
    logger.info(f"  - Enable metrics: {ENABLE_METRICS}")
    logger.info("=" * 70)

    try:
        encryption_key = ensure_encryption_key()
        
        logger.info("Loading proxy manager...")
        proxy_manager = await ProxyManager.load_from_file(str(PROXIES_FILE), max_failures=5)
        proxy_stats = proxy_manager.get_stats()
        logger.info(f"Proxy stats: {proxy_stats}")

        logger.info(f"Initializing captcha solver: {CAPTCHA_PROVIDER}")
        captcha_solver = CaptchaSolver(api_key=CAPTCHA_API_KEY, provider=CAPTCHA_PROVIDER)

        logger.info("Initializing rate limiter...")
        rate_limiter = GlobalRateLimiter(
            RateLimiterConfig(
                requests_per_second=0.5,
                burst_size=3,
                strategy=RateLimitStrategy.TOKEN_BUCKET,
                enable_adaptive=True,
            )
        )

        logger.info("Initializing persistence store...")
        persistence = PersistenceStore.from_config(str(DATABASE_FILE), encryption_key.decode())

        metrics_collector = MetricsCollector() if ENABLE_METRICS else None

        logger.info("Creating onboarding engine...")
        engine = OnboardingEngine(
            proxy_manager=proxy_manager,
            captcha_solver=captcha_solver,
            persistence=persistence,
            metrics_collector=metrics_collector,
            rate_limiter=rate_limiter,
            max_concurrent=MAX_CONCURRENT_TASKS,
        )

        logger.info("Starting batch processing...")
        await engine.run(TOTAL_SIMULATION_JOBS)

        logger.info("Loading saved records...")
        records = persistence.load_records(limit=10)
        logger.info(f"Total records saved: {persistence.get_total_records()}")
        logger.info(f"Latest {len(records)} records:")
        for record in records:
            logger.info(f"  - {record['user_id']} ({record['created_at']})")

        rate_limiter.log_stats()
        persistence.close()
        logger.info("=" * 70)
        logger.info("Batch processing completed successfully")
        logger.info("=" * 70)

    except KeyboardInterrupt:
        logger.warning("Process interrupted by user")
        sys.exit(0)
    except Exception as exc:
        logger.exception(f"Fatal error: {exc}")
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())
