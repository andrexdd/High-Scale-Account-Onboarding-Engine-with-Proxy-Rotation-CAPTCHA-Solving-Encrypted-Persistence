import asyncio
import logging
import random
from typing import Callable, TypeVar, Any, Type, Tuple
from .exceptions import RetryableError, OnboardingError

logger = logging.getLogger(__name__)

T = TypeVar('T')


class RetryConfig:
    def __init__(
        self,
        max_attempts: int = 3,
        initial_delay: float = 1.0,
        max_delay: float = 60.0,
        exponential_base: float = 2.0,
        jitter: bool = True,
        retryable_exceptions: Tuple[Type[Exception], ...] = (RetryableError,),
    ):
        self.max_attempts = max_attempts
        self.initial_delay = initial_delay
        self.max_delay = max_delay
        self.exponential_base = exponential_base
        self.jitter = jitter
        self.retryable_exceptions = retryable_exceptions

    def get_delay(self, attempt: int) -> float:
        delay = self.initial_delay * (self.exponential_base ** attempt)
        delay = min(delay, self.max_delay)
        
        if self.jitter:
            jitter_amount = delay * 0.1
            delay += random.uniform(-jitter_amount, jitter_amount)
        
        return max(0, delay)


async def retry_with_backoff(
    func: Callable[..., Any],
    *args,
    config: RetryConfig = None,
    operation_name: str = "operation",
    **kwargs
) -> Any:
    if config is None:
        config = RetryConfig()
    
    last_exception = None
    
    for attempt in range(config.max_attempts):
        try:
            result = await func(*args, **kwargs)
            if attempt > 0:
                logger.info(f"Retry succeeded for {operation_name} on attempt {attempt + 1}")
            return result
        
        except Exception as exc:
            last_exception = exc
            
            if not isinstance(exc, config.retryable_exceptions):
                logger.error(f"{operation_name} failed with non-retryable error: {exc}")
                raise
            
            if attempt < config.max_attempts - 1:
                delay = config.get_delay(attempt)
                logger.warning(
                    f"{operation_name} failed (attempt {attempt + 1}/{config.max_attempts}): "
                    f"{exc}. Retrying in {delay:.2f}s..."
                )
                await asyncio.sleep(delay)
            else:
                logger.error(
                    f"{operation_name} failed after {config.max_attempts} attempts: {exc}"
                )
    
    raise last_exception


def sync_retry_with_backoff(
    func: Callable[..., T],
    *args,
    config: RetryConfig = None,
    operation_name: str = "operation",
    **kwargs
) -> T:
    if config is None:
        config = RetryConfig()
    
    last_exception = None
    
    for attempt in range(config.max_attempts):
        try:
            result = func(*args, **kwargs)
            if attempt > 0:
                logger.info(f"Retry succeeded for {operation_name} on attempt {attempt + 1}")
            return result
        
        except Exception as exc:
            last_exception = exc
            
            if not isinstance(exc, config.retryable_exceptions):
                logger.error(f"{operation_name} failed with non-retryable error: {exc}")
                raise
            
            if attempt < config.max_attempts - 1:
                delay = config.get_delay(attempt)
                logger.warning(
                    f"{operation_name} failed (attempt {attempt + 1}/{config.max_attempts}): "
                    f"{exc}. Retrying in {delay:.2f}s..."
                )
                import time
                time.sleep(delay)
            else:
                logger.error(
                    f"{operation_name} failed after {config.max_attempts} attempts: {exc}"
                )
    
    raise last_exception
