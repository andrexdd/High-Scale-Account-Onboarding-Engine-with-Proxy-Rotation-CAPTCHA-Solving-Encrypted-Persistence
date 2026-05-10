import asyncio
import logging
import random
import string
import time
from dataclasses import dataclass
from typing import Any, Dict, Optional, Tuple
from datetime import datetime

from playwright.async_api import async_playwright, Browser, BrowserContext, Page, TimeoutError as PlaywrightTimeoutError

from .config import (
    ONBOARDING_TARGET_URL, REQUEST_TIMEOUT_SECONDS, MAX_CONCURRENT_TASKS, USE_PROXY, HEADLESS
)
from .captcha_solver import CaptchaSolver
from .persistence import PersistenceStore
from .proxy_manager import ProxyManager, ProxyEntry
from .metrics import MetricsCollector, JobStatus
from .constants import (
    TimeoutConstants, DelayConstants, BrowserConstants, SelectorConstants, URLConstants,
    RetryConstants, ValidationConstants
)
from .exceptions import (
    BrowserError, BrowserLaunchError, NavigationError, FormInteractionError,
    RetryableError
)
from .retry import RetryConfig, retry_with_backoff
from .validators import CredentialValidator
from .rate_limiter import GlobalRateLimiter, RateLimiterConfig, RateLimitStrategy

logger = logging.getLogger(__name__)


@dataclass
class OnboardingResult:
    user_id: str
    email: str
    session_token: str
    cookies: Dict[str, str]
    extra: Dict[str, Any]


class OnboardingEngine:
    def __init__(
        self,
        proxy_manager: ProxyManager,
        captcha_solver: CaptchaSolver,
        persistence: PersistenceStore,
        metrics_collector: MetricsCollector = None,
        rate_limiter: GlobalRateLimiter = None,
        target_url: str = ONBOARDING_TARGET_URL,
        max_concurrent: int = MAX_CONCURRENT_TASKS,
        request_timeout: int = REQUEST_TIMEOUT_SECONDS,
    ) -> None:
        self.proxy_manager = proxy_manager
        self.captcha_solver = captcha_solver
        self.persistence = persistence
        self.metrics = metrics_collector or MetricsCollector()
        self.rate_limiter = rate_limiter or GlobalRateLimiter(
            RateLimiterConfig(
                requests_per_second=1.0,
                burst_size=5,
                strategy=RateLimitStrategy.TOKEN_BUCKET,
            )
        )
        self.target_url = target_url
        self.max_concurrent = max_concurrent
        self.request_timeout = request_timeout
        self._startup_time = time.time()

        logger.info(
            f"OnboardingEngine initialized: "
            f"max_concurrent={max_concurrent}, "
            f"target_url={target_url}, "
            f"timeout={request_timeout}s"
        )

    async def run(self, total_jobs: int) -> None:
        logger.info(f"Starting batch of {total_jobs} jobs")
        self.metrics.process_metrics.total_jobs = total_jobs
        
        semaphore = asyncio.Semaphore(self.max_concurrent)
        
        try:
            async with asyncio.TaskGroup() as tg:
                for job_index in range(total_jobs):
                    await semaphore.acquire()
                    tg.create_task(self._run_one(job_index, semaphore))
        except Exception as exc:
            logger.error(f"Task group error: {exc}")
        finally:
            self.metrics.log_process_summary()
            logger.info("Batch processing completed")

    async def _run_one(self, job_index: int, semaphore: asyncio.Semaphore) -> None:
        self.metrics.start_job(job_index)
        try:
            await self._process_job(job_index)
            self.metrics.mark_job_success(job_index)
        except Exception as exc:
            self.metrics.mark_job_failed(job_index, str(exc))
            logger.error(f"Job {job_index} failed: {exc}", exc_info=False)
        finally:
            semaphore.release()

    async def _process_job(self, job_index: int) -> None:
        proxy_entry = None
        browser = None

        try:
            credentials = self._build_user_credentials(job_index)
            
            if USE_PROXY:
                proxy_entry = await self.proxy_manager.get_next_proxy()
                if proxy_entry:
                    self.metrics.record_proxy_used(job_index, proxy_entry.proxy_url())

            start_time = time.time()
            browser_config = self._get_browser_config(proxy_entry)

            await self.rate_limiter.wait(proxy_entry.proxy_url() if proxy_entry else None)

            async with async_playwright() as playwright:
                browser_start = time.time()
                browser = await self._launch_browser_with_retry(playwright, browser_config)
                self.metrics.record_timing(job_index, "browser_launch_time", time.time() - browser_start)

                context = await browser.new_context(
                    user_agent=self._random_user_agent(),
                    locale="en-US",
                    timezone_id="America/New_York",
                    geolocation={"latitude": 40.7128, "longitude": -74.0060},
                    permissions=["geolocation"],
                )

                page = await context.new_page()
                await self._apply_stealth_measures(page)

                page_load_start = time.time()
                await self._navigate_to_signup(page)
                self.metrics.record_timing(job_index, "page_load_time", time.time() - page_load_start)

                form_start = time.time()
                await self._fill_form(page, credentials)
                self.metrics.record_timing(job_index, "form_fill_time", time.time() - form_start)

                await self._handle_captcha_if_present(page, job_index)

                if not await self._verify_signup_success(page, context):
                    raise RuntimeError("Signup verification failed")

                cookies = await self._collect_cookies(context)
                result = OnboardingResult(
                    user_id=credentials["username"],
                    email=credentials["email"],
                    session_token=cookies.get("sessionid", ""),
                    cookies=cookies,
                    extra={
                        "page_url": page.url,
                        "created_at": datetime.utcnow().isoformat(),
                    }
                )

                self.persistence.save_record(result.user_id, result.__dict__)
                if proxy_entry:
                    self.proxy_manager.mark_proxy_success(proxy_entry)

                await self.rate_limiter.record_success()
                logger.info(f"Job {job_index} completed successfully: {result.user_id}")

        except RetryableError as exc:
            if proxy_entry:
                self.proxy_manager.mark_proxy_failed(proxy_entry)
                self.metrics.record_proxy_failure(job_index)
            await self.rate_limiter.record_error()
            raise
        except Exception as exc:
            if proxy_entry:
                self.proxy_manager.mark_proxy_failed(proxy_entry)
            await self.rate_limiter.record_error()
            raise
        finally:
            if browser:
                try:
                    await browser.close()
                except Exception as e:
                    logger.warning(f"Error closing browser for job {job_index}: {e}")

    def _get_browser_config(self, proxy: Optional[ProxyEntry]) -> Dict[str, Any]:
        config = {
            "headless": HEADLESS,
            "args": BrowserConstants.CHROMIUM_ARGS,
        }
        if proxy:
            config["proxy"] = proxy.playwight_proxy()
        return config

    async def _launch_browser_with_retry(self, playwright, config: Dict) -> Browser:
        retry_config = RetryConfig(
            max_attempts=RetryConstants.MAX_BROWSER_ATTEMPTS,
            initial_delay=1.0,
            max_delay=10.0,
            retryable_exceptions=(BrowserLaunchError, RetryableError),
        )

        async def launch():
            try:
                return await asyncio.wait_for(
                    playwright.chromium.launch(**config),
                    timeout=TimeoutConstants.BROWSER_LAUNCH / 1000,
                )
            except asyncio.TimeoutError as exc:
                raise BrowserLaunchError(f"Browser launch timeout") from exc
            except Exception as exc:
                raise BrowserLaunchError(f"Browser launch failed: {exc}") from exc

        return await retry_with_backoff(
            launch,
            config=retry_config,
            operation_name="browser_launch",
        )

    async def _navigate_to_signup(self, page: Page) -> None:
        retry_config = RetryConfig(
            max_attempts=RetryConstants.MAX_BROWSER_ATTEMPTS,
            retryable_exceptions=(NavigationError, RetryableError),
        )

        async def navigate():
            try:
                response = await page.goto(
                    self.target_url,
                    timeout=TimeoutConstants.PAGE_LOAD,
                    wait_until="domcontentloaded",
                )
                if not response or response.status >= 400:
                    raise NavigationError(f"Navigation returned status {response.status if response else 'unknown'}")
                
                await page.wait_for_selector(
                    SelectorConstants.EMAIL_INPUT,
                    timeout=TimeoutConstants.FORM_INTERACTION,
                )
                return True
            except PlaywrightTimeoutError as exc:
                raise NavigationError(f"Form selector timeout") from exc
            except Exception as exc:
                raise NavigationError(f"Navigation failed: {exc}") from exc

        await retry_with_backoff(
            navigate,
            config=retry_config,
            operation_name="navigate_signup_page",
        )

    async def _fill_form(self, page: Page, credentials: Dict[str, str]) -> None:
        delays = DelayConstants()
        
        try:
            await page.fill(
                SelectorConstants.EMAIL_INPUT,
                credentials["email"],
                timeout=TimeoutConstants.FORM_INTERACTION,
            )
            await self._human_delay(delays.MIN_FORM_DELAY, delays.MAX_FORM_DELAY)

            await page.fill(
                SelectorConstants.FULLNAME_INPUT,
                credentials["full_name"],
                timeout=TimeoutConstants.FORM_INTERACTION,
            )
            await self._human_delay(delays.MIN_FORM_DELAY, delays.MAX_FORM_DELAY)

            await page.fill(
                SelectorConstants.USERNAME_INPUT,
                credentials["username"],
                timeout=TimeoutConstants.FORM_INTERACTION,
            )
            await self._human_delay(delays.MIN_FORM_DELAY, delays.MAX_FORM_DELAY)

            await page.fill(
                SelectorConstants.PASSWORD_INPUT,
                credentials["password"],
                timeout=TimeoutConstants.FORM_INTERACTION,
            )
            await self._human_delay(delays.MIN_INTERSECTION_DELAY, delays.MAX_INTERSECTION_DELAY)

            await page.click(
                SelectorConstants.SUBMIT_BUTTON,
                timeout=TimeoutConstants.FORM_INTERACTION,
            )
            await asyncio.sleep(2.0)

        except Exception as exc:
            raise FormInteractionError(f"Form filling failed: {exc}") from exc

    async def _handle_captcha_if_present(self, page: Page, job_index: int) -> None:
        try:
            await page.wait_for_timeout(1000)
            
            site_key = await self._extract_captcha_site_key(page)
            if not site_key:
                logger.debug(f"Job {job_index}: No captcha detected")
                return

            self.metrics.record_captcha_solve(job_index)
            logger.info(f"Job {job_index}: Captcha detected")

            captcha_start = time.time()
            try:
                token = await asyncio.wait_for(
                    self.captcha_solver.solve(site_key, page.url),
                    timeout=TimeoutConstants.CAPTCHA_SUBMIT,
                )
                self.metrics.record_timing(job_index, "captcha_solve_time", time.time() - captcha_start)

                await self._inject_captcha_token(page, token)
                await self._human_delay(0.5, 1.5)

                await page.click(
                    SelectorConstants.SUBMIT_BUTTON,
                    timeout=TimeoutConstants.FORM_INTERACTION,
                )
                await asyncio.sleep(2.0)

            except asyncio.TimeoutError as exc:
                raise RetryableError(f"Captcha solve timeout") from exc
        except Exception as exc:
            logger.warning(f"Job {job_index}: Captcha handling failed: {exc}")

    async def _extract_captcha_site_key(self, page: Page) -> Optional[str]:
        selectors = [
            SelectorConstants.CAPTCHA_SITEKEY,
            SelectorConstants.CAPTCHA_IFRAME_RECAPTCHA,
            SelectorConstants.CAPTCHA_IFRAME_HCAPTCHA,
        ]

        for selector in selectors:
            try:
                element = page.locator(selector)
                count = await element.count()
                
                if count > 0:
                    if selector == SelectorConstants.CAPTCHA_SITEKEY:
                        site_key = await element.first.get_attribute("data-sitekey")
                        if site_key:
                            return site_key
                    else:
                        src = await element.first.get_attribute("src")
                        if src and "k=" in src:
                            for part in src.split("&"):
                                if part.startswith("k="):
                                    return part.split("=", 1)[1]
            except Exception:
                continue

        return None

    async def _inject_captcha_token(self, page: Page, token: str) -> None:
        script = """
        (token) => {
            const textarea = document.querySelector('textarea[name="g-recaptcha-response"]');
            if (textarea) textarea.value = token;
            
            const input = document.querySelector('input[name="g-recaptcha-response"]');
            if (input) input.value = token;
            
            window.__gRecaptchaResponse = token;
            window.grecaptcha && window.grecaptcha.callback && window.grecaptcha.callback(token);
            
            const event = new Event('change', { bubbles: true });
            textarea && textarea.dispatchEvent(event);
            input && input.dispatchEvent(event);
        }
        """
        try:
            await page.evaluate(script, token)
        except Exception as exc:
            logger.warning(f"Captcha token injection failed: {exc}")

    async def _verify_signup_success(self, page: Page, context: BrowserContext) -> bool:
        cookies = await self._collect_cookies(context)
        
        if cookies.get("sessionid"):
            return True

        current_url = page.url
        success_urls = [URLConstants.INSTAGRAM_CONFIRM, URLConstants.INSTAGRAM_WELCOME]
        for success_url in success_urls:
            if success_url in current_url:
                return True

        try:
            confirmation = await page.locator(SelectorConstants.CONFIRMATION_BANNER).count()
            if confirmation > 0:
                return True
        except Exception:
            pass

        return False

    def _build_user_credentials(self, job_index: int) -> Dict[str, str]:
        email = f"user{job_index}_{self._random_string(8)}@example.com"
        username = f"usr_{job_index}_{self._random_string(6)}"
        password = self._generate_password()
        full_name = f"User {job_index} Name"

        try:
            return CredentialValidator.validate_credentials(email, username, password, full_name)
        except ValueError as exc:
            logger.error(f"Credential validation failed: {exc}")
            raise

    def _generate_password(self, length: int = 16) -> str:
        chars = list(string.ascii_letters + string.digits + "!@#$%^&*")
        random.shuffle(chars)
        password = ''.join(random.choice(chars) for _ in range(length))
        return password

    async def _collect_cookies(self, context: BrowserContext) -> Dict[str, str]:
        try:
            cookies = await context.cookies()
            return {cookie["name"]: cookie["value"] for cookie in cookies}
        except Exception as exc:
            logger.warning(f"Cookie collection failed: {exc}")
            return {}

    async def _apply_stealth_measures(self, page: Page) -> None:
        stealth_script = """
        Object.defineProperty(navigator, 'webdriver', {
            get: () => false,
        });
        
        Object.defineProperty(navigator, 'plugins', {
            get: () => [
                {name: 'Chrome PDF Plugin', description: 'Portable Document Format'},
                {name: 'Chrome PDF Viewer', description: 'Portable Document Format'},
                {name: 'Native Client Executable', description: 'Native Client Executable'},
            ],
        });
        
        window.chrome = {
            runtime: {},
        };
        """
        try:
            await page.add_init_script(stealth_script)
        except Exception as exc:
            logger.warning(f"Stealth measures application failed: {exc}")

    @staticmethod
    def _random_user_agent() -> str:
        return random.choice(BrowserConstants.USER_AGENTS)

    def _random_string(self, length: int = 12) -> str:
        return "".join(random.choices(string.ascii_lowercase + string.digits, k=length))

    @staticmethod
    async def _human_delay(min_delay: float = 0.5, max_delay: float = 1.5) -> None:
        delay = random.uniform(min_delay, max_delay)
        await asyncio.sleep(delay)
