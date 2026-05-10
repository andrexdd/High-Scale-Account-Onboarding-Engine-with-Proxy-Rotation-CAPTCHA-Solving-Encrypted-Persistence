class OnboardingError(Exception):
    pass


class ProxyError(OnboardingError):
    pass


class ProxyExhaustedError(ProxyError):
    pass


class ProxyValidationError(ProxyError):
    pass


class CaptchaError(OnboardingError):
    pass


class CaptchaSolverError(CaptchaError):
    pass


class CaptchaTimeoutError(CaptchaError):
    pass


class CaptchaSubmissionError(CaptchaError):
    pass


class PersistenceError(OnboardingError):
    pass


class EncryptionError(PersistenceError):
    pass


class DatabaseError(PersistenceError):
    pass


class BrowserError(OnboardingError):
    pass


class BrowserLaunchError(BrowserError):
    pass


class NavigationError(BrowserError):
    pass


class FormInteractionError(BrowserError):
    pass


class ConfigurationError(OnboardingError):
    pass


class RetryableError(OnboardingError):
    pass
