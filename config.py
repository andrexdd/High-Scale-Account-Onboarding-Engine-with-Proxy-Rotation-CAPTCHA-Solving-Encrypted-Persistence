import os
import logging
from pathlib import Path
from .validators import ConfigValidator
from .constants import ConcurrencyConstants, TimeoutConstants, ProxyConstants
from .exceptions import ConfigurationError

logger = logging.getLogger(__name__)

BASE_DIR = Path(__file__).resolve().parent.parent
PROXIES_FILE = BASE_DIR / "proxies.txt"
DATABASE_FILE = BASE_DIR / "onboarding_results.db"
ENCRYPTION_KEY_FILE = BASE_DIR / ".encryption_key"
LOGS_DIR = BASE_DIR / "logs"

LOGS_DIR.mkdir(exist_ok=True, parents=True)

def _load_config():
    config = {
        "captcha_provider": os.getenv("CAPTCHA_PROVIDER", "sandbox").lower(),
        "captcha_api_key": os.getenv("CAPTCHA_API_KEY", "").strip(),
        "onboarding_target_url": os.getenv(
            "ONBOARDING_TARGET_URL", "https://www.instagram.com/accounts/emailsignup/"
        ),
        "site_verify_url": os.getenv("SITE_VERIFY_URL", "https://www.instagram.com"),
        "max_concurrent_tasks": int(os.getenv("MAX_CONCURRENT_TASKS", "10")),
        "total_simulation_jobs": int(os.getenv("TOTAL_SIMULATION_JOBS", "10")),
        "use_proxy": os.getenv("USE_PROXY", "True").lower() == "true",
        "request_timeout_seconds": int(os.getenv("REQUEST_TIMEOUT_SECONDS", "60")),
        "proxy_max_failures": int(os.getenv("PROXY_MAX_FAILURES", "5")),
        "proxy_min_valid_ratio": float(os.getenv("PROXY_MIN_VALID_RATIO", "0.5")),
        "headless": os.getenv("HEADLESS", "False").lower() == "true",
        "enable_metrics": os.getenv("ENABLE_METRICS", "True").lower() == "true",
        "log_level": os.getenv("LOG_LEVEL", "INFO").upper(),
    }
    
    try:
        config["max_concurrent_tasks"] = ConfigValidator.validate_concurrent_tasks(
            config["max_concurrent_tasks"]
        )
        config["total_simulation_jobs"] = ConfigValidator.validate_int(
            config["total_simulation_jobs"],
            "TOTAL_SIMULATION_JOBS",
            min_val=1,
            max_val=100000
        )
        config["request_timeout_seconds"] = ConfigValidator.validate_int(
            config["request_timeout_seconds"],
            "REQUEST_TIMEOUT_SECONDS",
            min_val=10,
            max_val=600
        )
        config["proxy_max_failures"] = ConfigValidator.validate_int(
            config["proxy_max_failures"],
            "PROXY_MAX_FAILURES",
            min_val=1,
            max_val=100
        )
        config["proxy_min_valid_ratio"] = ConfigValidator.validate_float(
            config["proxy_min_valid_ratio"],
            "PROXY_MIN_VALID_RATIO",
            min_val=0.0,
            max_val=1.0
        )
    except ConfigurationError as e:
        logger.error(f"Configuration validation error: {e}")
        raise
    
    if config["captcha_provider"] not in {"2captcha", "anti-captcha", "sandbox"}:
        raise ConfigurationError(
            f"Invalid CAPTCHA_PROVIDER: {config['captcha_provider']}. "
            "Must be one of: 2captcha, anti-captcha, sandbox"
        )
    
    return config

_config = _load_config()

CAPTCHA_PROVIDER = _config["captcha_provider"]
CAPTCHA_API_KEY = _config["captcha_api_key"]
ONBOARDING_TARGET_URL = _config["onboarding_target_url"]
SITE_VERIFY_URL = _config["site_verify_url"]
MAX_CONCURRENT_TASKS = _config["max_concurrent_tasks"]
TOTAL_SIMULATION_JOBS = _config["total_simulation_jobs"]
USE_PROXY = _config["use_proxy"]
REQUEST_TIMEOUT_SECONDS = _config["request_timeout_seconds"]
PROXY_MAX_FAILURES = _config["proxy_max_failures"]
PROXY_MIN_VALID_RATIO = _config["proxy_min_valid_ratio"]
HEADLESS = _config["headless"]
ENABLE_METRICS = _config["enable_metrics"]
LOG_LEVEL = _config["log_level"]

DEFAULT_FERNET_KEY = os.getenv("FERNET_KEY", None)

if DEFAULT_FERNET_KEY is None:
    if ENCRYPTION_KEY_FILE.exists():
        DEFAULT_FERNET_KEY = ENCRYPTION_KEY_FILE.read_text().strip()
    else:
        DEFAULT_FERNET_KEY = ""

logger.info(
    "Configuration loaded: "
    f"max_concurrent={MAX_CONCURRENT_TASKS}, "
    f"total_jobs={TOTAL_SIMULATION_JOBS}, "
    f"use_proxy={USE_PROXY}, "
    f"captcha_provider={CAPTCHA_PROVIDER}"
)
