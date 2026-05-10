import asyncio
import json
import logging
import time
from typing import Optional, Tuple
from enum import Enum

import aiohttp
from aiohttp import ClientSession, ClientTimeout

from .exceptions import CaptchaSolverError, CaptchaTimeoutError, CaptchaSubmissionError, RetryableError
from .constants import TimeoutConstants

logger = logging.getLogger(__name__)


class CaptchaProvider(Enum):
    TWO_CAPTCHA = "2captcha"
    ANTI_CAPTCHA = "anti-captcha"


class CaptchaSolver:
    MIN_POLL_INTERVAL = 3
    MAX_POLL_INTERVAL = 10
    BACKOFF_MULTIPLIER = 1.5

    def __init__(
        self,
        api_key: str,
        provider: str = "2captcha",
        timeout: int = TimeoutConstants.CAPTCHA_SUBMIT,
        min_balance: float = 1.0,
    ) -> None:
        self.api_key: str = api_key
        self.provider: str = provider.lower()
        self.timeout: int = timeout
        self.min_balance: float = min_balance

        if self.provider not in {"2captcha", "anti-captcha"}:
            raise ValueError(f"Unsupported captcha provider: {provider}")

        if not api_key or not api_key.strip():
            raise ValueError("API key cannot be empty")

        logger.info(f"CaptchaSolver initialized with provider={self.provider}")

    async def solve(self, site_key: str, page_url: str) -> str:
        if not site_key or not page_url:
            raise ValueError("site_key and page_url are required")

        logger.info(f"Starting captcha solve: provider={self.provider}, site_key={site_key[:8]}...")

        try:
            if self.provider == "2captcha":
                return await self._solve_2captcha(site_key, page_url)
            else:
                return await self._solve_anti_captcha(site_key, page_url)
        except CaptchaSolverError:
            raise
        except asyncio.TimeoutError as exc:
            raise CaptchaTimeoutError(f"Captcha solving timed out after {self.timeout}s") from exc
        except Exception as exc:
            logger.exception(f"Unexpected error during captcha solve: {exc}")
            raise CaptchaSolverError(f"Captcha solve failed: {exc}") from exc

    async def _solve_2captcha(self, site_key: str, page_url: str) -> str:
        submit_url = "http://2captcha.com/in.php"
        payload = {
            "key": self.api_key,
            "method": "userrecaptcha",
            "googlekey": site_key,
            "pageurl": page_url,
            "json": 1,
        }

        try:
            async with aiohttp.ClientSession(timeout=ClientTimeout(total=self.timeout)) as session:
                async with session.post(submit_url, data=payload) as resp:
                    if resp.status != 200:
                        raise CaptchaSubmissionError(f"2captcha API returned status {resp.status}")
                    response = await resp.json()

                    if response.get("status") != 1:
                        error_msg = response.get("error", "Unknown error")
                        if "insufficient" in error_msg.lower():
                            raise CaptchaSolverError(f"Insufficient balance: {error_msg}")
                        raise CaptchaSubmissionError(f"Failed to submit captcha: {error_msg}")

                    captcha_id = response["request"]
                    logger.debug(f"2captcha submission successful, ID: {captcha_id}")
                    
                    return await self._poll_2captcha(session, captcha_id)
        except aiohttp.ClientError as exc:
            logger.error(f"2captcha connection error: {exc}")
            raise RetryableError(f"2captcha connection failed: {exc}") from exc

    async def _poll_2captcha(self, session: ClientSession, captcha_id: str) -> str:
        result_url = "http://2captcha.com/res.php"
        elapsed = 0
        poll_interval = self.MIN_POLL_INTERVAL
        consecutive_not_ready = 0

        while elapsed < self.timeout:
            await asyncio.sleep(poll_interval)
            elapsed += poll_interval

            params = {
                "key": self.api_key,
                "action": "get",
                "id": captcha_id,
                "json": 1,
            }

            try:
                async with session.get(result_url, params=params) as resp:
                    if resp.status != 200:
                        logger.warning(f"2captcha poll returned status {resp.status}")
                        continue

                    response = await resp.json()

                    if response.get("status") == 1:
                        result = response["request"]
                        logger.info(f"Captcha solved: {captcha_id}")
                        return result

                    error_desc = response.get("request", "")
                    if error_desc in {"CAPCHA_NOT_READY", "CAPTCHA_NOT_READY"}:
                        consecutive_not_ready += 1
                        poll_interval = min(
                            self.MAX_POLL_INTERVAL,
                            poll_interval * self.BACKOFF_MULTIPLIER
                        )
                        continue

                    error_code = response.get("error")
                    logger.error(f"2captcha error: {error_code}: {error_desc}")
                    raise CaptchaSolverError(f"Captcha solve error: {error_desc}")

            except aiohttp.ClientError as exc:
                logger.warning(f"2captcha poll network error (attempt {consecutive_not_ready + 1}): {exc}")
                if consecutive_not_ready > 3:
                    raise RetryableError(f"2captcha polling failed: {exc}") from exc
                continue

        raise CaptchaTimeoutError(
            f"Captcha solving timed out after {self.timeout}s (poll_interval={poll_interval:.1f}s)"
        )

    async def _solve_anti_captcha(self, site_key: str, page_url: str) -> str:
        create_task_url = "https://api.anti-captcha.com/createTask"
        task_payload = {
            "clientKey": self.api_key,
            "task": {
                "type": "NoCaptchaTaskProxyless",
                "websiteURL": page_url,
                "websiteKey": site_key,
            },
            "languagePool": "en",
        }

        try:
            async with aiohttp.ClientSession(timeout=ClientTimeout(total=self.timeout)) as session:
                async with session.post(create_task_url, json=task_payload) as resp:
                    if resp.status != 200:
                        raise CaptchaSubmissionError(f"Anti-Captcha API returned status {resp.status}")

                    response = await resp.json()

                    if response.get("errorId") != 0:
                        error_msg = response.get("errorDescription", "Unknown error")
                        if "balance" in error_msg.lower():
                            raise CaptchaSolverError(f"Insufficient balance: {error_msg}")
                        raise CaptchaSubmissionError(f"Anti-Captcha submit failed: {error_msg}")

                    task_id = response["taskId"]
                    logger.debug(f"Anti-Captcha submission successful, task ID: {task_id}")

                    return await self._poll_anti_captcha(session, task_id)
        except aiohttp.ClientError as exc:
            logger.error(f"Anti-Captcha connection error: {exc}")
            raise RetryableError(f"Anti-Captcha connection failed: {exc}") from exc

    async def _poll_anti_captcha(self, session: ClientSession, task_id: int) -> str:
        get_task_url = "https://api.anti-captcha.com/getTaskResult"
        elapsed = 0
        poll_interval = self.MIN_POLL_INTERVAL

        while elapsed < self.timeout:
            await asyncio.sleep(poll_interval)
            elapsed += poll_interval

            payload = {
                "clientKey": self.api_key,
                "taskId": task_id,
            }

            try:
                async with session.post(get_task_url, json=payload) as resp:
                    if resp.status != 200:
                        logger.warning(f"Anti-Captcha poll returned status {resp.status}")
                        continue

                    response = await resp.json()

                    if response.get("errorId") != 0:
                        error_msg = response.get("errorDescription", "Unknown error")
                        logger.error(f"Anti-Captcha polling error: {error_msg}")
                        raise CaptchaSolverError(f"Anti-Captcha polling failed: {error_msg}")

                    status = response.get("status")
                    if status == "ready":
                        result = response["solution"]["gRecaptchaResponse"]
                        logger.info(f"Captcha solved: task_id={task_id}")
                        return result

                    poll_interval = min(
                        self.MAX_POLL_INTERVAL,
                        poll_interval * self.BACKOFF_MULTIPLIER
                    )
                    continue

            except aiohttp.ClientError as exc:
                logger.warning(f"Anti-Captcha poll network error: {exc}")
                raise RetryableError(f"Anti-Captcha polling network error: {exc}") from exc

        raise CaptchaTimeoutError(
            f"Captcha solving timed out after {self.timeout}s"
        )

    async def check_balance(self) -> float:
        if self.provider == "2captcha":
            return await self._check_2captcha_balance()
        else:
            return await self._check_anti_captcha_balance()

    async def _check_2captcha_balance(self) -> float:
        url = "http://2captcha.com/api/user"
        params = {"key": self.api_key, "action": "getbalance", "json": 1}

        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(url, params=params) as resp:
                    response = await resp.json()
                    if response.get("status") == 1:
                        return float(response["request"])
                    raise CaptchaSolverError("Failed to check balance")
        except Exception as exc:
            logger.warning(f"Failed to check 2captcha balance: {exc}")
            return -1.0

    async def _check_anti_captcha_balance(self) -> float:
        url = "https://api.anti-captcha.com/getBalance"
        payload = {"clientKey": self.api_key}

        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(url, json=payload) as resp:
                    response = await resp.json()
                    if response.get("errorId") == 0:
                        return float(response.get("balance", -1))
                    raise CaptchaSolverError("Failed to check balance")
        except Exception as exc:
            logger.warning(f"Failed to check Anti-Captcha balance: {exc}")
            return -1.0

