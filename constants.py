from enum import Enum

class TimeoutConstants:
    BROWSER_LAUNCH = 60000
    PAGE_LOAD = 60000
    FORM_INTERACTION = 30000
    CAPTCHA_SUBMIT = 120
    PROXY_VALIDATION = 5
    HTTP_REQUEST = 20
    BROWSER_CONTEXT_CREATION = 10000


class DelayConstants:
    MIN_FORM_DELAY = 1.0
    MAX_FORM_DELAY = 2.0
    
    MIN_SUBMIT_DELAY = 0.5
    MAX_SUBMIT_DELAY = 1.5
    
    MIN_NAVIGATION_DELAY = 1.0
    MAX_NAVIGATION_DELAY = 3.0
    
    MIN_INTERSECTION_DELAY = 0.2
    MAX_INTERSECTION_DELAY = 0.8
    
    CAPTCHA_POLL_INTERVAL = 5
    PROXY_REFRESH_INTERVAL = 0.1


class ProxyConstants:
    VALIDATION_BATCH_SIZE = 20
    MIN_VALID_RATIO = 0.5
    MAX_FAILURES_BEFORE_REMOVAL = 5
    PROXY_SCRAPE_URL = (
        "https://api.proxyscrape.com/v2/?request=displayproxies&protocol=http"
        "&timeout=10000&country=all&ssl=all&anonymity=all"
    )
    VALIDATION_TEST_URL = "https://www.instagram.com"


class BrowserConstants:
    CHROMIUM_ARGS = [
        "--disable-gpu",
        "--no-sandbox",
        "--disable-web-resources",
        "--disable-sync",
        "--disable-default-apps",
        "--disable-extensions",
    ]
    
    USER_AGENTS = [
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36",
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 13_5) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.4 Safari/605.1.15",
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_1) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.1 Safari/605.1.15",
        "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Firefox/123.0",
        "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Firefox/124.0",
    ]


class SelectorConstants:
    EMAIL_INPUT = 'input[name="emailOrPhone"]'
    FULLNAME_INPUT = 'input[name="fullName"]'
    USERNAME_INPUT = 'input[name="username"]'
    PASSWORD_INPUT = 'input[name="password"]'
    SUBMIT_BUTTON = 'button[type="submit"]'
    
    CAPTCHA_SITEKEY = '[data-sitekey]'
    CAPTCHA_IFRAME_RECAPTCHA = 'iframe[src*="google.com/recaptcha"]'
    CAPTCHA_IFRAME_HCAPTCHA = 'iframe[src*="hcaptcha.com"]'
    CAPTCHA_RESPONSE_TEXTAREA = 'textarea[name="g-recaptcha-response"]'
    CAPTCHA_RESPONSE_INPUT = 'input[name="g-recaptcha-response"]'
    
    CONFIRMATION_BANNER = 'text=Please wait'


class URLConstants:
    INSTAGRAM_SIGNUP = "https://www.instagram.com/accounts/emailsignup/"
    INSTAGRAM_CONFIRM = "https://www.instagram.com/accounts/confirm"
    INSTAGRAM_WELCOME = "https://www.instagram.com/accounts/welcome"


class DatabaseConstants:
    BATCH_INSERT_SIZE = 100
    CONNECTION_TIMEOUT = 30
    TRANSACTION_TIMEOUT = 300


class RetryConstants:
    MAX_BROWSER_ATTEMPTS = 3
    MAX_FORM_ATTEMPTS = 2
    MAX_CAPTCHA_ATTEMPTS = 1
    MAX_PROXY_ATTEMPTS = 3
    
    INITIAL_DELAY = 1.0
    MAX_DELAY = 60.0
    EXPONENTIAL_BASE = 2.0


class ValidationConstants:
    MIN_PASSWORD_LENGTH = 8
    MAX_PASSWORD_LENGTH = 128
    MIN_USERNAME_LENGTH = 3
    MAX_USERNAME_LENGTH = 30
    
    EMAIL_REGEX = r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$'
    
    USERNAME_REGEX = r'^[a-zA-Z0-9._-]{3,30}$'


class ConcurrencyConstants:
    MIN_CONCURRENT_TASKS = 1
    MAX_CONCURRENT_TASKS = 500
    DEFAULT_CONCURRENT_TASKS = 10
    SEMAPHORE_BUFFER = 2
