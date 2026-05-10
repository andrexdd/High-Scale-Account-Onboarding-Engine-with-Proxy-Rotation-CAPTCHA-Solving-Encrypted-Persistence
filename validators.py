import re
import logging
from typing import List, Dict, Any
from pathlib import Path
from .constants import ValidationConstants, ConcurrencyConstants
from .exceptions import ConfigurationError

logger = logging.getLogger(__name__)


class ConfigValidator:
    @staticmethod
    def validate_string(value: str, name: str, min_len: int = 0, max_len: int = None) -> str:
        if not isinstance(value, str):
            raise ConfigurationError(f"{name} must be a string, got {type(value)}")
        if len(value) < min_len:
            raise ConfigurationError(f"{name} must be at least {min_len} characters")
        if max_len and len(value) > max_len:
            raise ConfigurationError(f"{name} must be at most {max_len} characters")
        return value

    @staticmethod
    def validate_int(value: int, name: str, min_val: int = None, max_val: int = None) -> int:
        if not isinstance(value, int):
            raise ConfigurationError(f"{name} must be an integer, got {type(value)}")
        if min_val is not None and value < min_val:
            raise ConfigurationError(f"{name} must be at least {min_val}")
        if max_val is not None and value > max_val:
            raise ConfigurationError(f"{name} must be at most {max_val}")
        return value

    @staticmethod
    def validate_float(value: float, name: str, min_val: float = None, max_val: float = None) -> float:
        if not isinstance(value, (int, float)):
            raise ConfigurationError(f"{name} must be a float, got {type(value)}")
        if min_val is not None and value < min_val:
            raise ConfigurationError(f"{name} must be at least {min_val}")
        if max_val is not None and value > max_val:
            raise ConfigurationError(f"{name} must be at most {max_val}")
        return float(value)

    @staticmethod
    def validate_path(value: str, name: str, must_exist: bool = False) -> Path:
        path = Path(value)
        if must_exist and not path.exists():
            raise ConfigurationError(f"{name} path does not exist: {path}")
        return path

    @staticmethod
    def validate_concurrent_tasks(value: int) -> int:
        return ConfigValidator.validate_int(
            value,
            "MAX_CONCURRENT_TASKS",
            min_val=ConcurrencyConstants.MIN_CONCURRENT_TASKS,
            max_val=ConcurrencyConstants.MAX_CONCURRENT_TASKS,
        )


class CredentialValidator:
    @staticmethod
    def validate_email(email: str) -> str:
        email = email.strip()
        if not re.match(ValidationConstants.EMAIL_REGEX, email):
            raise ValueError(f"Invalid email format: {email}")
        if len(email) > 254:
            raise ValueError(f"Email too long: {len(email)} > 254")
        return email

    @staticmethod
    def validate_username(username: str) -> str:
        username = username.strip()
        if not re.match(ValidationConstants.USERNAME_REGEX, username):
            raise ValueError(
                f"Invalid username: {username}. Must be 3-30 alphanumeric characters, dots, underscores, hyphens"
            )
        return username

    @staticmethod
    def validate_password(password: str) -> str:
        password = password.strip()
        if len(password) < ValidationConstants.MIN_PASSWORD_LENGTH:
            raise ValueError(
                f"Password too short: {len(password)} < {ValidationConstants.MIN_PASSWORD_LENGTH}"
            )
        if len(password) > ValidationConstants.MAX_PASSWORD_LENGTH:
            raise ValueError(
                f"Password too long: {len(password)} > {ValidationConstants.MAX_PASSWORD_LENGTH}"
            )
        return password

    @staticmethod
    def validate_full_name(name: str) -> str:
        name = name.strip()
        if len(name) < 2:
            raise ValueError("Full name must be at least 2 characters")
        if len(name) > 150:
            raise ValueError("Full name must be at most 150 characters")
        if not re.match(r'^[a-zA-Z\s\'\-]+$', name):
            raise ValueError("Full name contains invalid characters")
        return name

    @staticmethod
    def validate_credentials(
        email: str,
        username: str,
        password: str,
        full_name: str,
    ) -> Dict[str, str]:
        return {
            "email": CredentialValidator.validate_email(email),
            "username": CredentialValidator.validate_username(username),
            "password": CredentialValidator.validate_password(password),
            "full_name": CredentialValidator.validate_full_name(full_name),
        }


class ProxyValidator:
    @staticmethod
    def validate_proxy_entry(proxy_str: str) -> Dict[str, Any]:
        proxy_str = proxy_str.strip()
        if not proxy_str or proxy_str.startswith("#"):
            return None
        
        result = {
            "server": None,
            "scheme": "http",
            "username": None,
            "password": None,
        }
        
        if "@" in proxy_str:
            auth_part, server_part = proxy_str.rsplit("@", 1)
            if ":" in auth_part:
                result["username"], result["password"] = auth_part.split(":", 1)
            else:
                result["username"] = auth_part
        else:
            server_part = proxy_str
        
        if "://" in server_part:
            scheme, server_part = server_part.split("://", 1)
            result["scheme"] = scheme
        
        if ":" not in server_part:
            raise ValueError(f"Invalid proxy format (missing port): {proxy_str}")
        
        host, port = server_part.rsplit(":", 1)
        try:
            port_int = int(port)
            if not (1 <= port_int <= 65535):
                raise ValueError(f"Invalid port number: {port}")
        except ValueError as e:
            raise ValueError(f"Invalid port: {port}") from e
        
        result["server"] = server_part
        
        return result


class DatabaseValidator:
    @staticmethod
    def validate_encryption_key(key: str) -> str:
        if not key:
            raise ConfigurationError("Encryption key cannot be empty")
        if len(key) < 32:
            raise ConfigurationError("Encryption key too short")
        return key

    @staticmethod
    def validate_db_path(path: Path) -> Path:
        if not path.parent.exists():
            path.parent.mkdir(parents=True, exist_ok=True)
        return path
